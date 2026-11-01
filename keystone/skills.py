"""Voyager-style skill library: sandbox code that ran successfully, stored for reuse by later agent runs."""
import json
import os
import re
import threading
import time

from keystone.config import STATE

DIR = STATE / "skills"
DIR.mkdir(exist_ok=True)
INDEX = DIR / "index.json"
_lock = threading.Lock()  # concurrent missions share the index: read-modify-write under one lock, replace atomically


def _write(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def index():
    return json.loads(INDEX.read_text()) if INDEX.exists() else {}


def save(name, code, description=""):
    """Add a verified skill. An existing skill is never replaced by different code (agents run skills by name, so a
    silent overwrite would change what every later run executes); returns None in that case."""
    name = re.sub(r"[^a-z0-9_]", "_", name.lower())[:60]
    with _lock:
        idx = index()
        if name in idx and (DIR / f"{name}.py").exists() and (DIR / f"{name}.py").read_text() != code:
            return None
        _write(DIR / f"{name}.py", code)
        entry = idx.get(name, {"uses": 0, "created": time.strftime("%Y-%m-%d %H:%M")})
        entry.update({"description": description, "updated": time.strftime("%Y-%m-%d %H:%M"), "lines": code.count("\n") + 1})
        idx[name] = entry
        _write(INDEX, json.dumps(idx, indent=2))
    return name


def get(name):
    with _lock:
        idx = index()
        if name not in idx:
            return {"error": f"unknown skill {name}", "available": list(idx)}
        idx[name]["uses"] += 1
        _write(INDEX, json.dumps(idx, indent=2))
    return {"name": name, **idx[name], "code": (DIR / f"{name}.py").read_text()}
