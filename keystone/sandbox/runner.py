"""Sandboxed Python execution for agents.

Agents write analysis code (sensitivity sweeps, custom portfolio cuts); it runs here, never in the host process.
Layers, following Anthropic's sandboxing guidance (filesystem + network isolation, enforced by the OS):
  - macOS seatbelt profile via sandbox-exec (Linux: bubblewrap): no network, writes only to a per-run temp dir,
    and reads only from an allowlist (interpreter, system libraries, the project's code/data, the work dir), so
    agent code cannot read credentials elsewhere on the host
  - isolated interpreter (-I), scrubbed environment (no API keys), CPU/file-size rlimits, wall-clock timeout
  - code is AST-screened for obviously dangerous calls before it runs, and every run is audit-logged
Production would swap this for Anthropic's code execution tool or a Firecracker/gVisor microVM; the interface stays.
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from keystone.config import ARTIFACTS, ROOT

AUDIT = ARTIFACTS / "sandbox_audit.jsonl"
BLOCKED_CALLS = {"system", "popen", "fork", "execv", "execve", "spawnv", "rmtree", "remove", "unlink", "kill"}
BLOCKED_MODULES = {"socket", "subprocess", "ctypes", "multiprocessing", "requests", "urllib", "http", "shutil"}

# Read allowlist: everything else on the host (home directory, ~/.config, ~/.ssh, .env files) is unreadable.
SYSTEM_READ = ["/System", "/usr", "/bin", "/Library/Frameworks", "/Library/Apple", "/private/etc", "/private/var/db/timezone",
               "/opt/homebrew/lib", "/opt/homebrew/opt", "/dev"]


def _read_roots(workdir):
    venv_or_prefix = os.path.realpath(sys.prefix)
    base = os.path.realpath(sys.base_prefix)
    project = [str(ROOT / d) for d in ("keystone", "data", "artifacts")]
    return sorted({*SYSTEM_READ, venv_or_prefix, base, *project, os.path.realpath(workdir)})


SEATBELT = """(version 1)
(deny default)
(allow process-exec process-fork)
(allow file-read-metadata)
(allow file-read* {read_rules})
(allow file-write* (subpath "{workdir}") (literal "/dev/null"))
(allow sysctl-read)
(allow mach-lookup)
(allow ipc-posix-shm)
(allow signal (target self))
(deny network*)
"""


def screen(code):
    """Cheap static screen; the OS sandbox is the real boundary."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for n in names:
                if n.split(".")[0] in BLOCKED_MODULES:
                    return f"import of '{n}' is not allowed in the sandbox"
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in BLOCKED_CALLS or name in ("eval", "exec", "__import__", "compile"):
                return f"call to '{name}' is not allowed in the sandbox"
    return None


def run_python(code, timeout=90, agent="unknown"):
    t0 = time.time()
    problem = screen(code)
    if problem:
        result = {"ok": False, "stdout": "", "stderr": problem, "blocked": True, "sandbox": "static-screen"}
        _audit(agent, code, result, t0)
        return result
    workdir = tempfile.mkdtemp(prefix="keystone_sbx_")
    script = os.path.join(workdir, "main.py")
    with open(script, "w") as f:
        f.write(code)
    env = {"PATH": "/usr/bin:/bin", "HOME": workdir, "TMPDIR": workdir, "MPLCONFIGDIR": workdir, "MPLBACKEND": "Agg", "PYTHONPATH": str(ROOT),
           "OMP_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    roots = _read_roots(workdir)
    py = [sys.executable, "-I", "-c",
          # rlimits are set inside the child (preexec_fn is unsafe in the threaded MCP server)
          ("import resource, sys; resource.setrlimit(resource.RLIMIT_CPU, (60, 60)); "
           "resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 2**20, 50 * 2**20)); "
           f"sys.path.insert(0, {str(ROOT)!r}); exec(compile(open({script!r}).read(), 'main.py', 'exec'))")]
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        rules = " ".join(f'(subpath "{r}")' for r in roots) + f' (literal "{ROOT}") (literal "/")'
        cmd = ["sandbox-exec", "-p", SEATBELT.format(workdir=os.path.realpath(workdir), read_rules=rules)] + py
        kind = "seatbelt"
    elif shutil.which("bwrap"):
        # Linux: an empty root with only the allowlisted trees bound read-only (lib dirs added when present)
        binds = []
        for r in [*roots, "/lib", "/lib64", "/etc"]:
            if os.path.exists(r) and r != os.path.realpath(workdir):
                binds += ["--ro-bind", r, r]
        cmd = ["bwrap", *binds, "--bind", workdir, workdir, "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
               "--unshare-all", "--die-with-parent", "--chdir", workdir] + py
        kind = "bubblewrap"
    else:
        result = {"ok": False, "stdout": "", "stderr": "no OS sandbox available on this host; refusing to run", "sandbox": None}
        _audit(agent, code, result, t0)
        return result
    try:
        p = subprocess.run(cmd, check=False, cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout)
        result = {"ok": p.returncode == 0, "stdout": p.stdout[-20_000:], "stderr": p.stderr[-5_000:],
                  "returncode": p.returncode, "sandbox": kind}
        if not result["ok"] and not result["stderr"]:
            result["stderr"] = f"exit code {p.returncode}"
    except subprocess.TimeoutExpired:
        result = {"ok": False, "stdout": "", "stderr": f"timeout after {timeout}s", "sandbox": kind}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    _audit(agent, code, result, t0)
    return result


def _audit(agent, code, result, t0):
    with open(AUDIT, "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "agent": agent, "secs": round(time.time() - t0, 2),
                            "ok": result["ok"], "sandbox": result.get("sandbox"), "code": code[:4000],
                            "stderr": result["stderr"][:500]}) + "\n")
