"""Voyager-style skill library: sandbox code that ran successfully, stored for reuse by later agent runs."""
import json
import re
import time

from keystone.config import ARTIFACTS

DIR = ARTIFACTS / "skills"
DIR.mkdir(exist_ok=True)
INDEX = DIR / "index.json"


def index():
    return json.loads(INDEX.read_text()) if INDEX.exists() else {}


def save(name, code, description=""):
    name = re.sub(r"[^a-z0-9_]", "_", name.lower())[:60]
    idx = index()
    (DIR / f"{name}.py").write_text(code)
    entry = idx.get(name, {"uses": 0, "created": time.strftime("%Y-%m-%d %H:%M")})
    entry.update({"description": description, "updated": time.strftime("%Y-%m-%d %H:%M"), "lines": code.count("\n") + 1})
    idx[name] = entry
    INDEX.write_text(json.dumps(idx, indent=2))
    return name


def get(name):
    idx = index()
    if name not in idx:
        return {"error": f"unknown skill {name}", "available": list(idx)}
    idx[name]["uses"] += 1
    INDEX.write_text(json.dumps(idx, indent=2))
    return {"name": name, **idx[name], "code": (DIR / f"{name}.py").read_text()}
