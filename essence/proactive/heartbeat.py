from __future__ import annotations
import json
import os
import re
import threading
import time
import dataclasses as _dc
from pathlib import Path
from typing import Any, Callable, list
from essence.config import BaseModel, ConfigDict, log
from essence.swarm.specialist import AgentRole
from essence.vault.secrets import _workspace_root

class HeartbeatJob(BaseModel):
    model_config = ConfigDict(frozen=False)
    name:     str
    message:  str
    schedule: str
    last_run: float = 0.0
    enabled:  bool  = True

def _parse_interval(s: str) -> float | None:
    s = s.strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(s|m|h|d)", s.lower())
    if m:
        v, u = float(m.group(1)), m.group(2)
        return v * {"s": 1, "m": 60, "h": 3600, "d": 86400}[u]
    expr = re.sub(r"^cron:", "", s, flags=re.I).strip()
    if len(expr.split()) == 5:
        try:
            from croniter import croniter as _croniter
            import datetime as _dt
            now = _dt.datetime.now()
            it  = _croniter(expr, now)
            next_dt = it.get_next(_dt.datetime)
            return max(0.0, (next_dt - now).total_seconds())
        except ImportError: pass
        except Exception as _ce:
            log.debug("cron_parse_error", extra={"expr": expr, "error": str(_ce)[:80]})

        cm = re.fullmatch(r"(\d+)\s+(\d+)\s+\*\s+\*\s+\*", expr)
        if cm:
            import time as _time
            cron_min, cron_hour = int(cm.group(1)), int(cm.group(2))
            now_st     = _time.localtime()
            target_sod = cron_hour * 3600 + cron_min * 60
            now_sod    = now_st.tm_hour * 3600 + now_st.tm_min * 60 + now_st.tm_sec
            diff = target_sod - now_sod
            if diff <= 0: diff += 86400
            return float(diff)
        log.warning("cron_unsupported_expression", extra={"expr": expr})
    return None

class HeartbeatScheduler:
    HEARTBEAT_OK = "[HEARTBEAT_OK]"

    def __init__(self, workspace: Path, run_fn: Callable[[str], str]) -> None:
        self._ws   = workspace
        self._run  = run_fn
        self._path = workspace / "heartbeat.json"
        self._jobs: list[HeartbeatJob] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sleep_agent_ref: Any = None
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._jobs = [HeartbeatJob(**j)
                              for j in json.loads(self._path.read_text(encoding="utf-8"))]
            except Exception: self._jobs = []

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps([j.model_dump() for j in self._jobs], indent=2),
            encoding="utf-8")
        tmp.replace(self._path)

    def add(self, name: str, message: str, schedule: str) -> None:
        with self._lock:
            self._jobs = [j for j in self._jobs if j.name != name]
            self._jobs.append(HeartbeatJob(name=name, message=message, schedule=schedule))
            self._save()

    def remove(self, name: str) -> bool:
        with self._lock:
            before = len(self._jobs)
            self._jobs = [j for j in self._jobs if j.name != name]
            self._save()
            return len(self._jobs) < before

    def list_jobs(self) -> list[HeartbeatJob]:
        with self._lock:
            return list(self._jobs)

    def start(self) -> None:
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        from essence.vault.secrets import load_ws_file
        while not self._stop.is_set():
            now = time.time()
            hb_content = load_ws_file(self._ws, "HEARTBEAT.md")
            if hb_content.strip():
                has_active = any(line.strip() and not line.strip().startswith(("#", "<!--", "-->", "//")) and not line.strip() == "---" for line in hb_content.splitlines())
                if has_active and (now - self.get("__hb_last", 0)) >= 1800:
                    self.set("__hb_last", now)
                    try:
                        result = self._run(hb_content)
                        if result and not result.startswith(self.HEARTBEAT_OK):
                            self._log('__heartbeat__', result)
                        log.info('heartbeat_tick', extra={'suppressed': result.startswith(self.HEARTBEAT_OK) if result else True})
                    except Exception as exc:
                        log.error('heartbeat_error', extra={'error': str(exc)})

            with self._lock:
                snapshot = list(self._jobs)
            for job in snapshot:
                if not job.enabled: continue
                interval = _parse_interval(job.schedule)
                if interval and (now - job.last_run) >= interval:
                    with self._lock:
                        job.last_run = now
                        self._save()
                    try:
                        result = self._run(job.message)
                        if result and not result.startswith(self.HEARTBEAT_OK):
                            self._log(job.name, result)
                    except Exception as _exc:
                        log.debug('heartbeat_job_error', extra={'job': job.name, 'error': str(_exc)})

            agent = self._sleep_agent_ref
            if agent is not None:
                idle_mins = int(os.environ.get("UAIS_SLEEP_IDLE_MINS", "30"))
                last_chat = getattr(agent, "_last_chat_ts", 0)
                last_sleep = self.get("__sleep_last", 0)
                idle_secs = now - last_chat
                if (idle_secs >= idle_mins * 60 and (now - last_sleep) >= idle_mins * 60):
                    self.set("__sleep_last", now)
                    try: self._run_sleep_consolidation(agent)
                    except Exception as _se: log.debug("sleep_consolidation_error", extra={"error": str(_se)[:120]})
            self._stop.wait(timeout=30)

    def attach_sleep_agent(self, agent: Any) -> None:
        self._sleep_agent_ref = agent

    def _run_sleep_consolidation(self, agent: Any) -> None:
        mem = agent.memory
        pool = getattr(agent, "_specialist_pool", {})
        specialist = pool.get(AgentRole.SLEEPTIME_CONSOLIDATOR)
        if specialist is None: return

        with mem._kv_lock:
            kv_facts = [f"{k}: {str(v)[:200]}" for k, v in mem._kv.items()]
        episodes = mem.recent_episodes(20)
        ep_texts = [ep["text"][:200] for ep in episodes]
        mem_dump = ("=== Semantic KV facts ===\n" + "\n".join(kv_facts[:50]) + "\n\n=== Recent episodes ===\n" + "\n".join(ep_texts[:20]))
        if not mem_dump.strip(): return

        raw = specialist.run(mem_dump)
        try:
            clean = re.sub(r"```[a-zA-Z]*", "", raw).strip()
            result = json.loads(clean)
            retain = result.get("retain", [])
            if retain and isinstance(retain, list):
                with mem._kv_lock:
                    mem._kv = {f"fact_{i}": f for i, f in enumerate(retain[:100]) if isinstance(f, str)}
                mem._save_kv()
                for fact in retain[:100]:
                    mem._backend.store(fact, {"layer": "semantic", "type": "sleep_reorganised"})
            profile_updates = result.get("profile", {})
            if profile_updates and isinstance(profile_updates, dict):
                mem.update_profile(profile_updates)
            sss = getattr(agent, "_semantic_state", None)
            triples = result.get("triples", [])
            if sss is not None and triples and isinstance(triples, list):
                sss_imported = 0
                for t in triples[:50]:
                    if not isinstance(t, dict): continue
                    try:
                        sss.assert_fact(
                            entity    = str(t.get("entity",    "user")),
                            relation  = str(t.get("relation",  "note")),
                            attribute = str(t.get("attribute", "fact")),
                            value     = str(t.get("value",     ""))[:300],
                            confidence= float(t.get("confidence", 0.8)),
                            source    = "sleep_consolidation")
                        sss_imported += 1
                    except Exception: pass
                log.debug("sleep_consolidation_sss_imported", extra={"triples": sss_imported})
            log.info("sleep_consolidation_done", extra={"facts_retained": len(retain)})
        except Exception as _pe:
            log.debug("sleep_consolidation_parse_error", extra={"error": str(_pe)[:80]})

    def _log(self, name: str, result: str) -> None:
        log_dir = self._ws / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"heartbeat_{name}.jsonl"
        record   = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": result[:1000]})
        with open(log_file, "a", encoding="utf-8") as f: f.write(record + "\n")

    def get(self, key: str, default: float = 0.0) -> float:
        ks = self._ws / "heartbeat_state.json"
        if ks.exists():
            try: return json.loads(ks.read_text(encoding="utf-8")).get(key, default)
            except Exception: pass
        return default

    def set(self, key: str, value: float) -> None:
        ks = self._ws / "heartbeat_state.json"
        data: dict = {}
        if ks.exists():
            try: data = json.loads(ks.read_text(encoding="utf-8"))
            except Exception: pass
        data[key] = value
        tmp = ks.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(ks)
