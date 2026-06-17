from __future__ import annotations
import json, os, time, uuid
from pathlib import Path
from typing import Any, Optional
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from pydantic import BaseModel, ConfigDict
from contextlib import asynccontextmanager

try:
    import tomllib
except ImportError:
    try: import tomli as tomllib
    except ImportError: tomllib = None

_WS = Path(os.environ.get("UAIS_WORKSPACE", str(Path(__file__).resolve().parent.parent)))
_CFG_PATH = _WS / "config.toml"
_CONFIG_OVERLAY: dict = {}

def _cfg_base() -> dict:
    if tomllib and _CFG_PATH.exists():
        with open(_CFG_PATH, "rb") as f:
            return tomllib.load(f)
    return {}

def _cfg() -> dict:
    base = _cfg_base()
    base.update(_CONFIG_OVERLAY)
    return base

def _model() -> str:
    return os.environ.get("UAIS_MODEL", _cfg().get("inference", {}).get("model", "qwen3:4b"))

def _ollama() -> str:
    return os.environ.get(
        "OLLAMA_HOST",
        os.environ.get("UAIS_OLLAMA_HOST",
                       _cfg().get("inference", {}).get("ollama_url", "http://localhost:11434"))
    )

@asynccontextmanager
async def lifespan(a: FastAPI):
    a.state.start_ts = time.time()
    a.state.sessions: dict = {}
    yield

app = FastAPI(title="UAIS", version="29.0.0", lifespan=lifespan)

_INDEX = _WS / "server" / "index.html"

@app.get("/", response_class=HTMLResponse)
async def root():
    if _INDEX.exists():
        html = _INDEX.read_text(encoding="utf-8")
    else:
        html = "<html><head><title>UAIS</title></head><body><h1>UAIS v29.0</h1></body></html>"
    return html

@app.get("/healthz")
async def healthz(req: Request):
    uptime = round(time.time() - req.app.state.start_ts, 1)
    return {"status": "ok", "uptime": uptime}
