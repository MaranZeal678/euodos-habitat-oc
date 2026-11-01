"""Sandboxed Python execution for agents.

Agents write analysis code (sensitivity sweeps, custom portfolio cuts); it runs here, never in the host process.
Layers, following Anthropic's sandboxing guidance (filesystem + network isolation, enforced by the OS):
  - macOS seatbelt profile via sandbox-exec (Linux: bubblewrap): no network, writes only to a per-run temp dir,
    and reads only from an allowlist (interpreter, system libraries, the project's code/data, the work dir), so
    agent code cannot read credentials elsewhere on the host, nor the product's runtime state (runs, skills, audit)
  - no new processes: seatbelt denies fork and allows exec of the interpreter only (Linux: private pid namespace);
    the whole process session is killed when the run ends
  - output is streamed with a byte cap, so a program that prints gigabytes cannot exhaust the server's memory
  - isolated interpreter (-I), scrubbed environment (no API keys), CPU/file-size rlimits, wall-clock timeout
  - code is AST-screened for obviously dangerous calls before it runs, and every run is audit-logged
Production would swap this for Anthropic's code execution tool or a Firecracker/gVisor microVM; the interface stays.
"""
import ast
import contextlib
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from keystone.config import ROOT, STATE

AUDIT = STATE / "sandbox_audit.jsonl"
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


MAX_OUTPUT = 2 * 2**20  # bytes of stdout+stderr kept; past this the run is killed
STATE_PRIVATE = ["runs", "skills", "memory", "sandbox_audit.jsonl"]  # never readable by agent code

SEATBELT = """(version 1)
(deny default)
(allow process-exec {exec_rules})
(allow file-read-metadata)
(allow file-read* {read_rules})
(deny file-read* {deny_rules})
(allow file-write* (subpath "{workdir}") (literal "/dev/null"))
(allow sysctl-read)
(allow ipc-posix-shm)
(allow signal (target self))
(deny network*)
"""


def _private_state():
    return [str((STATE / p).resolve()) for p in STATE_PRIVATE]


def _collect(p, timeout):
    """Read stdout/stderr as they arrive, keeping at most MAX_OUTPUT bytes; kill the run past the cap or deadline."""
    out, err, total, deadline = bytearray(), bytearray(), 0, time.monotonic() + timeout
    sel = selectors.DefaultSelector()
    assert p.stdout and p.stderr
    sel.register(p.stdout.fileno(), selectors.EVENT_READ, out)
    sel.register(p.stderr.fileno(), selectors.EVENT_READ, err)
    reason = None
    while sel.get_map():
        left = deadline - time.monotonic()
        if left <= 0:
            reason = f"timeout after {timeout}s"
            break
        for key, _ in sel.select(min(left, 1.0)):
            chunk = os.read(key.fd, 65536)
            if not chunk:
                sel.unregister(key.fd)
                continue
            total += len(chunk)
            key.data.extend(chunk)
            del key.data[:-MAX_OUTPUT]  # keep the tail
        if total > MAX_OUTPUT * 4:
            reason = f"output over {MAX_OUTPUT * 4 // 2**20} MB; run stopped"
            break
    sel.close()
    return out.decode(errors="replace"), err.decode(errors="replace"), reason


def _kill_session(p):
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(p.pid, signal.SIGKILL)
    p.wait()


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
    private = _private_state()
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        rules = " ".join(f'(subpath "{r}")' for r in roots) + f' (literal "{ROOT}") (literal "/")'
        exe = " ".join(f'(literal "{e}")' for e in {sys.executable, os.path.realpath(sys.executable)})
        deny = " ".join(f'(subpath "{d}")' for d in private)
        cmd = ["sandbox-exec", "-p", SEATBELT.format(workdir=os.path.realpath(workdir), read_rules=rules, exec_rules=exe,
                                                     deny_rules=deny)] + py
        kind = "seatbelt"
    elif shutil.which("bwrap"):
        # Linux: an empty root with only the allowlisted trees bound read-only (lib dirs added when present)
        binds = []
        for r in [*roots, "/lib", "/lib64", "/etc"]:
            if os.path.exists(r) and r != os.path.realpath(workdir):
                binds += ["--ro-bind", r, r]
        for d in private:  # runtime state under a bound root is masked with an empty tmpfs
            if any(d == r or d.startswith(r.rstrip("/") + "/") for r in roots) and os.path.isdir(d):
                binds += ["--tmpfs", d]
        # /tmp is mounted before the work dir: the work dir usually lives under /tmp on Linux, and a later tmpfs would hide it
        cmd = ["bwrap", *binds, "--tmpfs", "/tmp", "--bind", workdir, workdir, "--proc", "/proc", "--dev", "/dev",
               "--unshare-all", "--die-with-parent", "--new-session", "--chdir", workdir] + py
        kind = "bubblewrap"
    else:
        result = {"ok": False, "stdout": "", "stderr": "no OS sandbox available on this host; refusing to run", "sandbox": None}
        _audit(agent, code, result, t0)
        return result
    p = subprocess.Popen(cmd, cwd=workdir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True)  # own session, so one killpg ends everything
    try:
        out, err, stopped = _collect(p, timeout)
    finally:
        _kill_session(p)
        shutil.rmtree(workdir, ignore_errors=True)
    ok = stopped is None and p.returncode == 0
    result = {"ok": ok, "stdout": out[-20_000:], "stderr": (stopped or err[-5_000:] or ("" if ok else f"exit code {p.returncode}")),
              "returncode": p.returncode, "sandbox": kind}
    _audit(agent, code, result, t0)
    return result


def _audit(agent, code, result, t0):
    with open(AUDIT, "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "agent": agent, "secs": round(time.time() - t0, 2),
                            "ok": result["ok"], "sandbox": result.get("sandbox"), "code": code[:4000],
                            "stderr": result["stderr"][:500]}) + "\n")
