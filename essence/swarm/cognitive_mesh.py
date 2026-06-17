from __future__ import annotations
import os
import json
import re
import time
import asyncio
import dataclasses as _dc
from typing import Any, List as list
from essence.core.events import log

_TOT_BRANCHES = int(os.environ.get("UAIS_TOT_BRANCHES", "3"))
_TOT_ENABLED  = os.environ.get("UAIS_TOT_ENABLED", "0") == "1"

_PLAN_SYS = (
    "You are a precise task planner. Break the user's request into numbered steps. "
    "Output ONLY a JSON array (no markdown, no prose): "
    '[{"step":1,"action":"...","tool":"shell|read_file|write_file|'
    'python_exec|web_search|heartbeat_add|none","args":{}}]. '
    "No other text."
)

@_dc.dataclass
class ThoughtBranch:
    branch_id:   int
    plan:        list[dict]
    score:       float = 0.0
    rationale:   str   = ""
    tokens_used: int   = 0

class TreeOfThought:
    SCORE_THRESHOLD = 0.4

    def __init__(self, provider: Any, model: str, n_branches: int = 0):
        self._prov = provider; self._model = model
        self._branches = n_branches or _TOT_BRANCHES

    def expand(self, goal: str, context: str = "", plan_sys: str = "") -> list[ThoughtBranch]:
        branches: list[ThoughtBranch] = []
        sys_prompt = plan_sys or _PLAN_SYS
        for i in range(self._branches):
            diversity = "" if i == 0 else f" Branch {i+1}/{self._branches} — use a DIFFERENT approach."
            messages = [{"role": "system", "content": sys_prompt + diversity},
                        {"role": "user", "content": goal}]
            if context:
                messages.insert(1, {"role": "system", "content": context})
            try:
                raw = "".join(self._prov.complete(messages, model=self._model, stream=True, thinking=True))
                plan = self._parse_plan(raw)
                branches.append(ThoughtBranch(branch_id=i, plan=plan, tokens_used=len(raw) // 4))
            except Exception as _e:
                log.debug("tot_expand_error", extra={"branch": i, "error": str(_e)[:80]})
        return branches or [ThoughtBranch(branch_id=0, plan=[])]

    async def aexpand(self, goal: str, context: str = "", plan_sys: str = "") -> list[ThoughtBranch]:
        sys_prompt = plan_sys or _PLAN_SYS
        async def _ex_one(i):
            diversity = "" if i == 0 else f" Branch {i+1}/{self._branches} — use a DIFFERENT approach."
            messages = [{"role": "system", "content": sys_prompt + diversity},
                        {"role": "user", "content": goal}]
            if context:
                messages.insert(1, {"role": "system", "content": context})
            try:
                _toks = []
                async for tok in self._prov.acomplete(messages, model=self._model, stream=True, thinking=True):
                    _toks.append(tok)
                raw = "".join(_toks)
                plan = self._parse_plan(raw)
                return ThoughtBranch(branch_id=i, plan=plan, tokens_used=len(raw) // 4)
            except Exception:
                return ThoughtBranch(branch_id=i, plan=[])

        tasks = [asyncio.create_task(_ex_one(i)) for i in range(self._branches)]
        branches = await asyncio.gather(*tasks)
        return list(branches)

    def score(self, branches: list[ThoughtBranch], goal: str, genesis: Any = None, arch_id: str = "") -> list[ThoughtBranch]:
        judge_sys = ('Rate this plan 0.0-1.0. Consider completeness, efficiency, safety. '
                     'Respond ONLY with JSON: {"score": 0.0-1.0, "rationale": "..."}')
        for branch in branches:
            if not branch.plan:
                branch.score = 0.0; continue
            plan_text = json.dumps(branch.plan, indent=2)[:2000]
            user_msg = "Goal: " + goal + "\nPlan:\n" + plan_text
            messages = [{"role": "system", "content": judge_sys},
                        {"role": "user", "content": user_msg}]
            try:
                raw = "".join(self._prov.complete(messages, model=self._model, stream=True, thinking=False))
                m = re.search(r'"score"\s*:\s*([\d.]+)', raw)
                llm_score = float(m.group(1)) if m else 0.5
                m2 = re.search(r'"rationale"\s*:\s*"([^"]*)"', raw)
                branch.rationale = m2.group(1) if m2 else ""
                genesis_score = 0.5
                if genesis and arch_id:
                    genesis_score = 0.8
                branch.score = 0.7 * llm_score + 0.3 * genesis_score
            except Exception:
                branch.score = 0.5
        return branches

    async def ascore(self, branches: list[ThoughtBranch], goal: str, genesis: Any = None, arch_id: str = "") -> list[ThoughtBranch]:
        judge_sys = ('Rate this plan 0.0-1.0. Consider completeness, efficiency, safety. '
                     'Respond ONLY with JSON: {"score": 0.0-1.0, "rationale": "..."}')
        async def _sc_one(branch):
            if not branch.plan:
                branch.score = 0.0; return branch
            plan_text = json.dumps(branch.plan, indent=2)[:2000]
            user_msg = "Goal: " + goal + "\nPlan:\n" + plan_text
            messages = [{"role": "system", "content": judge_sys},
                        {"role": "user", "content": user_msg}]
            try:
                _toks = []
                async for tok in self._prov.acomplete(messages, model=self._model, stream=True, thinking=False):
                    _toks.append(tok)
                raw = "".join(_toks)
                m = re.search(r'"score"\s*:\s*([\d.]+)', raw)
                llm_score = float(m.group(1)) if m else 0.5
                m2 = re.search(r'"rationale"\s*:\s*"([^"]*)"', raw)
                branch.rationale = m2.group(1) if m2 else ""
                genesis_score = 0.5
                if genesis and arch_id:
                    genesis_score = 0.8
                branch.score = 0.7 * llm_score + 0.3 * genesis_score
            except Exception:
                branch.score = 0.5
            return branch
        tasks = [asyncio.create_task(_sc_one(b)) for b in branches]
        await asyncio.gather(*tasks)
        return branches

    def prune(self, branches: list[ThoughtBranch]) -> list[ThoughtBranch]:
        surviving = [b for b in branches if b.score >= self.SCORE_THRESHOLD]
        return surviving or [max(branches, key=lambda b: b.score)]

    def select(self, branches: list[ThoughtBranch]) -> ThoughtBranch:
        return max(branches, key=lambda b: b.score)

    def reason(self, goal: str, context: str = "", plan_sys: str = "", genesis: Any = None, arch_id: str = "") -> tuple[list[dict], ThoughtBranch]:
        if not _TOT_ENABLED or self._branches <= 1:
            branches = self.expand(goal, context, plan_sys)
            b = branches[0] if branches else ThoughtBranch(0, []); b.score = 1.0
            return b.plan, b
        branches = self.expand(goal, context, plan_sys)
        branches = self.score(branches, goal, genesis=genesis, arch_id=arch_id)
        branches = self.prune(branches)
        winner = self.select(branches)
        log.info("tot_selected", extra={"branches": len(branches), "winner": winner.branch_id, "score": winner.score})
        return winner.plan, winner

    async def areason(self, goal: str, context: str = "", plan_sys: str = "", genesis: Any = None, arch_id: str = "") -> tuple[list[dict], ThoughtBranch]:
        if not _TOT_ENABLED or self._branches <= 1:
            branches = await self.aexpand(goal, context, plan_sys)
            b = branches[0] if branches else ThoughtBranch(0, []); b.score = 1.0
            return b.plan, b
        branches = await self.aexpand(goal, context, plan_sys)
        branches = await self.ascore(branches, goal, genesis=genesis, arch_id=arch_id)
        branches = self.prune(branches)
        winner = self.select(branches)
        return winner.plan, winner

    @staticmethod
    def _parse_plan(raw: str) -> list[dict]:
        m = re.search(r'\[\s*\{.*\}\s*\]', raw, re.DOTALL)
        if m:
            try: return json.loads(m.group(0))
            except json.JSONDecodeError: pass
        return []
