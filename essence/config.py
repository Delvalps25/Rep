import os
import dataclasses as _dc
from pathlib import Path
from typing import Any, Optional
import logging

UAIS_VERSION = "29.0.0"
TEAM_ID = os.environ.get("UAIS_TEAM_ID", "local")
COST_BUDGET = int(os.environ.get("UAIS_COST_BUDGET", "0"))
SOP_DIR = os.environ.get("UAIS_SOP_DIR", "")
DRIFT_WEBHOOK = os.environ.get("UAIS_DRIFT_WEBHOOK", "")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Structured Logging Setup
def _setup_logging():
    _log = logging.getLogger('uais')
    if _log.handlers:
        return _log
    _log.setLevel(logging.DEBUG if os.environ.get('UAIS_DEBUG') else logging.INFO)
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter('%(asctime)s [%(levelname)s] uais: %(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
    _handler.setFormatter(_formatter)
    _log.addHandler(_handler)
    return _log

log = _setup_logging()

@_dc.dataclass
class UAISConfig:
    model:        str   = _dc.field(default_factory=lambda: os.environ.get("UAIS_MODEL", ""))
    backend:      str   = _dc.field(default_factory=lambda: os.environ.get("UAIS_BACKEND", ""))
    role:         str   = _dc.field(default_factory=lambda: os.environ.get("UAIS_ROLE", "standalone"))
    rl_chat:      int   = _dc.field(default_factory=lambda: int(os.environ.get("UAIS_RL_CHAT", "60")))
    rl_shell:     int   = _dc.field(default_factory=lambda: int(os.environ.get("UAIS_RL_SHELL", "20")))
    rl_agent:     int   = _dc.field(default_factory=lambda: int(os.environ.get("UAIS_RL_AGENT", "10")))
    api_token:    str   = _dc.field(default_factory=lambda: os.environ.get("UAIS_API_TOKEN", ""))
    auth_disabled: bool = _dc.field(default_factory=lambda: os.environ.get("UAIS_AUTH_DISABLED", "0") == "1")
    team_id:      str   = _dc.field(default_factory=lambda: os.environ.get("UAIS_TEAM_ID", "local"))
    scache:       bool  = _dc.field(default_factory=lambda: os.environ.get("UAIS_SCACHE", "0") == "1")
    scache_thresh: float= _dc.field(default_factory=lambda: float(os.environ.get("UAIS_SCACHE_THRESH", "0.97")))
    metrics:      bool  = _dc.field(default_factory=lambda: os.environ.get("UAIS_METRICS", "0") == "1")
    audit:        bool  = _dc.field(default_factory=lambda: os.environ.get("UAIS_AUDIT", "0") == "1")
    otel_endpoint: str  = _dc.field(default_factory=lambda: os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""))
    valkey_url:   str   = _dc.field(default_factory=lambda: os.environ.get("UAIS_VALKEY_URL", ""))
    nats_url:     str   = _dc.field(default_factory=lambda: os.environ.get("UAIS_NATS_URL", ""))
    alive_ttl:    float = _dc.field(default_factory=lambda: float(os.environ.get("UAIS_ALIVE_TTL", "10")))
    plugins:      bool  = _dc.field(default_factory=lambda: os.environ.get("UAIS_PLUGINS", "0") == "1")
    auto_resume:  bool  = _dc.field(default_factory=lambda: os.environ.get("UAIS_AUTO_RESUME", "0") == "1")
    guided:       bool  = _dc.field(default_factory=lambda: os.environ.get("UAIS_GUIDED", "0") == "1")
    cost_budget:  int   = _dc.field(default_factory=lambda: int(os.environ.get("UAIS_COST_BUDGET", "0")))

    @classmethod
    def load(cls, workspace: Path) -> "UAISConfig":
        return cls()


import enum as _enum

class SystemRole(_enum.Enum):
    STANDALONE    = "standalone"
    ORCHESTRATOR  = "orchestrator"
    WORKER        = "worker"
    ROUTER        = "router"

def get_system_role() -> SystemRole:
    raw = os.environ.get("UAIS_ROLE", "standalone").lower().strip()
    _alias = {"master": "orchestrator", "slave": "worker", "intermediary": "router"}
    raw = _alias.get(raw, raw)
    try: return SystemRole(raw)
    except ValueError: return SystemRole.STANDALONE
