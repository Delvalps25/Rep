import time
import json
import urllib.request
import urllib.error
import subprocess
import shutil
import os
import threading
import asyncio
from typing import Any, List, Dict, Optional, Iterator, AsyncIterator, Protocol
from pydantic import BaseModel, Field, ConfigDict
from essence.core.events import log

class InferenceProvider(Protocol):
    NAME: str
    def alive(self) -> bool: ...
    def complete(self, messages: List[Dict], **kwargs) -> Iterator[str]: ...
    async def acomplete(self, messages: List[Dict], **kwargs) -> AsyncIterator[str]: ...

class BackendError(RuntimeError): ...

def _json_post(url: str, payload: dict, timeout: int = 180) -> Iterator[bytes]:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            while chunk := r.readline():
                yield chunk
    except urllib.error.URLError as e:
        raise BackendError(f"POST {url}: {e}") from e

async def _ajson_post(url: str, payload: dict, timeout: int = 180) -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    gen = _json_post(url, payload, timeout)
    while True:
        try:
            chunk = await loop.run_in_executor(None, next, gen)
            yield chunk
        except StopIteration:
            break

class ModelSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    id:           str
    ollama_tag:   str
    hf_slug:      str
    family:       str
    total_b:      float
    active_b:     float
    vram_q4_gb:   float
    ctx_k:        int
    min_tier:     int
    thinking:     bool
    moe:          bool
    pinch:        float
    note:         str
    requires_vlm: bool = False

REGISTRY: List[ModelSpec] = [
    ModelSpec(id="qwen3-0.6b",  ollama_tag="qwen3:0.6b",  hf_slug="Qwen/Qwen3-0.6B-GGUF",
              family="Qwen3",  total_b=0.6,  active_b=0.6, vram_q4_gb=0.5,
              ctx_k=32,  min_tier=0, thinking=True,  moe=False, pinch=0.0,
              note="SBC / 2 GB devices. Thinking mode enabled."),
]

class OllamaBackend:
    NAME = "ollama"
    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host
        self._chat = f"{host}/api/chat"
    def alive(self) -> bool:
        try:
            urllib.request.urlopen(f"{self.host}/api/tags", timeout=2)
            return True
        except: return False
    def complete(self, messages: List[Dict], **kwargs) -> Iterator[str]:
        payload = {"model": kwargs.get("model"), "messages": messages, "stream": kwargs.get("stream", True)}
        for raw in _json_post(self._chat, payload):
            try:
                chunk = json.loads(raw.decode())
                if tok := chunk.get("message", {}).get("content", ""): yield tok
                if chunk.get("done"): break
            except: continue
    async def acomplete(self, messages: List[Dict], **kwargs) -> AsyncIterator[str]:
        payload = {"model": kwargs.get("model"), "messages": messages, "stream": kwargs.get("stream", True)}
        async for raw in _ajson_post(self._chat, payload):
            try:
                chunk = json.loads(raw.decode())
                if tok := chunk.get("message", {}).get("content", ""): yield tok
                if chunk.get("done"): break
            except: continue

class ProviderChain:
    def __init__(self, providers: List[InferenceProvider]):
        self.providers = providers
    def complete(self, *a, **kw) -> Iterator[str]:
        for p in self.providers:
            if p.alive():
                try:
                    yield from p.complete(*a, **kw)
                    return
                except: continue
        raise BackendError("All providers failed")
    async def acomplete(self, *a, **kw) -> AsyncIterator[str]:
        for p in self.providers:
            if p.alive():
                try:
                    async for tok in p.acomplete(*a, **kw):
                        yield tok
                    return
                except: continue
        raise BackendError("All providers failed async")
