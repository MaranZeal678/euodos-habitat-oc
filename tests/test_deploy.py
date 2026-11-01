"""A fresh checkout is what Render (or any CI) builds from, so everything the running product reads must be committed,
addressed relative to the repo, and present in the Docker build context."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from keystone import config
from keystone.agents import memory
from keystone.agents.specs import SPECS
from keystone.models import registry

ROOT = config.ROOT
needs_git = pytest.mark.skipif(not (shutil.which("git") and (ROOT / ".git").exists()), reason="not a git checkout")


def tracked(path):
    out = subprocess.run(["git", "ls-files", "--", str(path)], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return bool(out.strip())


@pytest.mark.parametrize("name", ["parking_cnn", "market_gap"])
def test_champion_models_load_from_any_checkout(name):
    c = registry.champion(name)
    assert c is not None
    assert not Path(c["path"]).is_absolute(), f"{name} champion path is machine-specific: {c['path']}"
    assert registry.model_file(c).exists()


@needs_git
@pytest.mark.parametrize("name", ["parking_cnn", "market_gap"])
def test_champion_models_are_committed(name):
    assert tracked(registry.champion(name)["path"])


@needs_git
def test_every_dockerfile_copy_source_is_committed():
    copies = re.findall(r"^COPY\s+(.+?)\s+\S+$", (ROOT / "Dockerfile").read_text(), flags=re.MULTILINE)
    sources = [s for line in copies for s in line.split()]
    assert sources
    for s in sources:
        assert tracked(s), f"Dockerfile copies {s}, which is not in git, so a build from the repo fails"


@needs_git
def test_dockerignore_keeps_what_the_image_needs():
    ignored = [l.strip() for l in (ROOT / ".dockerignore").read_text().splitlines() if l.strip() and not l.startswith("#")]
    for needed in ("keystone", "data/processed", "artifacts/registry.json", "artifacts/improve_log.json"):
        assert not any(needed == i or needed.startswith(i.rstrip("/") + "/") for i in ignored), needed


@needs_git
@pytest.mark.parametrize("path", ["artifacts/registry.json", "artifacts/improve_log.json",
                                  "keystone/app/static/demo/reference_run.json", "keystone/app/static/demo/portfolio.json",
                                  "keystone/app/static/demo/keystone_demo_720p.mp4"])
def test_demo_evidence_is_committed(path):
    assert tracked(path), f"{path} would be missing on a fresh deploy"


def test_fresh_state_starts_from_promoted_playbooks():
    # the isolated state dir is empty, like a new deploy: agents must use the gate-approved playbooks, not v0
    promoted = 0
    for agent in SPECS:
        champ = registry.champion(f"playbook:{agent}")
        if champ:
            promoted += 1
            assert memory.playbook(agent)["text"] == champ["path"]
    assert promoted >= 1
