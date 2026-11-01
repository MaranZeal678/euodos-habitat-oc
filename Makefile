PY=.venv/bin/python
.PHONY: setup data test serve demo record mcp improve docker
setup:   ; uv venv --python 3.13 .venv && uv pip install --python $(PY) -r requirements-ml.txt
data:    ; $(PY) -m keystone.pipeline
test:    ; $(PY) -m pytest -q tests
serve:   ; .venv/bin/uvicorn keystone.app.server:app --port 8000
demo:    ; open "http://localhost:8000/demo?autoplay" ; .venv/bin/uvicorn keystone.app.server:app --port 8000
record:  ; $(PY) scripts/record_demo.py --out docs/keystone_demo.mp4
mcp:     ; $(PY) -m keystone.mcp_server.server
improve: ; $(PY) -m keystone.agents.improve --generations 3
docker:  ; docker build -t keystone . && docker run -p 8000:8000 -e ANTHROPIC_API_KEY keystone
