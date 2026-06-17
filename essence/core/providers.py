import time
from typing import Any, List, Dict, Optional, Iterator, AsyncIterator
from pydantic import BaseModel, Field, ConfigDict
from essence.core.events import log

class ModelSpec(BaseModel):
    """Immutable Pydantic v2 model for a registry entry."""
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
    ModelSpec(id="qwen3-4b",    ollama_tag="qwen3:4b",    hf_slug="Qwen/Qwen3-4B-GGUF",
              family="Qwen3",  total_b=4.0,  active_b=4.0, vram_q4_gb=3.2,
              ctx_k=128, min_tier=1, thinking=True,  moe=False, pinch=0.0,
              note="Best everyday model for 6 GB VRAM / 8 GB RAM."),
]

class ProviderChain:
    """
    primary → fallback_1 → fallback_2 → cloud.
    """
    def __init__(self, providers: List):
        self.providers = providers

    def complete(self, *a, **kw) -> Iterator[str]:
        for provider in self.providers:
            if not hasattr(provider, "alive") or provider.alive():
                try:
                    yield from provider.complete(*a, **kw)
                    return
                except Exception as e:
                    log.warning("provider_failed", extra={"error": str(e)})
        raise RuntimeError("All providers failed")

    async def acomplete(self, *a, **kw) -> AsyncIterator[str]:
        for provider in self.providers:
            if not hasattr(provider, "alive") or provider.alive():
                try:
                    async for tok in provider.acomplete(*a, **kw):
                        yield tok
                    return
                except Exception as e:
                    log.warning("provider_failed_async", extra={"error": str(e)})
        raise RuntimeError("All providers failed async")
