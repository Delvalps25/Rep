from __future__ import annotations
from typing import Any

class CognitiveReflector:
    def __init__(self, provider: Any, model: str, critic_sys: str = ""):
        self.provider = provider
        self.model = model
        self.critic_sys = critic_sys or "You are a critical reviewer. Find flaws in the plan/output."

    def reflect(self, task: str, plan_or_output: Any,
                context: str = "") -> tuple[bool, str]:
        critique_prompt = f"Task: {task}\nTarget: {plan_or_output}\nContext: {context}\nProvide a critique."
        critique = self._call_llm(self.critic_sys, critique_prompt)
        should_replan = "REPLAN" in critique.upper() or "ERROR" in critique.upper()
        return should_replan, critique

    async def areflect(self, task: str, plan_or_output: Any,
                      context: str = "") -> tuple[bool, str]:
        critique_prompt = f"Task: {task}\nTarget: {plan_or_output}\nContext: {context}\nProvide a critique."
        critique = await self._acall_llm(self.critic_sys, critique_prompt)
        should_replan = "REPLAN" in critique.upper() or "ERROR" in critique.upper()
        return should_replan, critique

    def _call_llm(self, sys: str, user: str) -> str:
        out = ""
        for tok in self.provider.complete(
            [{"role": "system", "content": sys},
             {"role": "user", "content": user}],
            model=self.model, stream=False
        ):
            out += tok
        return out.strip()

    async def _acall_llm(self, sys: str, user: str) -> str:
        out = ""
        async for tok in self.provider.acomplete(
            [{"role": "system", "content": sys},
             {"role": "user", "content": user}],
            model=self.model, stream=False
        ):
            out += tok
        return out.strip()
