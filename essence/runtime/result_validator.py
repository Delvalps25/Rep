from __future__ import annotations
import re
import json
import asyncio
import dataclasses as _dc
from typing import Any, List as list
from essence.core.events import log

@_dc.dataclass
class VerificationResult:
    claim:       str
    verdict:     str
    confidence:  float
    evidence:    str

class VerifierLayer:
    _CLAIM_PATTERNS = [
        re.compile(r'\b\d{4,}\b'),
        re.compile(r'https?://\S+'),
        re.compile(r'[A-Za-z0-9_./-]+\.(py|json|txt|csv|md|yaml|toml)\b'),
        re.compile(r'\b(?:always|never|all|none|every|no)\b', re.I),
        re.compile(r'\b(?:error|fail|success|complete|done|finish)\b', re.I),
    ]

    _VERIFY_SYS = (
        "You are a factuality verifier. Given a claim and context, respond ONLY with "
        'JSON: {"verdict": "verified"|"unverified"|"contradicted", '
        '"confidence": 0.0-1.0, "evidence": "brief quote or none"}. No other text.'
    )

    def __init__(self, provider: Any | None = None,
                 model: str = "", enabled: bool = True) -> None:
        self._provider = provider
        self._model    = model
        self.enabled   = enabled

    def _has_claims(self, text: str) -> bool:
        return any(p.search(text) for p in self._CLAIM_PATTERNS)

    def verify(self, response: str, tool_context: str,
               max_claims: int = 5, spine: Any = None) -> list[VerificationResult]:
        if not self.enabled or not self._provider:
            return []
        if not self._has_claims(response):
            return []

        try:
            extract_prompt = (
                f"Extract up to {max_claims} specific verifiable factual claims "
                f"(numbers, filenames, outcomes, URLs) from this text. "
                f"Output ONLY a JSON array of strings. No prose.\n\nText:\n{response[:1500]}"
            )
            raw = ""
            for tok in self._provider.complete(
                [{"role": "user", "content": extract_prompt}],
                model=self._model, stream=False, thinking=False
            ):
                raw += tok
            clean = re.sub(r"```[a-zA-Z]*", "", raw).strip()
            claims: list[str] = json.loads(clean)
            if not isinstance(claims, list):
                return []
        except Exception:
            return []

        results: list[VerificationResult] = []
        ctx_snip = tool_context[:2000]
        prism_ctx = ""
        if spine and hasattr(spine, 'active_findings') and spine.active_findings:
            prism_ctx = "\n\nPRISM Analytical Findings:\n" + "\n".join(
                f"- {f.title}: {f.description}" for f in spine.active_findings[:5]
            )

        for claim in claims[:max_claims]:
            try:
                prompt = (f"Claim: {claim}\n\nContext (tool results):\n{ctx_snip}{prism_ctx}")
                raw_v  = ""
                for tok in self._provider.complete(
                    [{"role": "user", "content": prompt}],
                    model=self._model, stream=False, thinking=False,
                    tools=None
                ):
                    raw_v += tok
                d = json.loads(re.sub(r"```[a-zA-Z]*", "", raw_v).strip())
                results.append(VerificationResult(
                    claim=claim,
                    verdict=d.get("verdict", "unverified"),
                    confidence=float(d.get("confidence", 0.5)),
                    evidence=str(d.get("evidence", ""))[:200],
                ))
            except Exception:
                results.append(VerificationResult(
                    claim=claim, verdict="unverified",
                    confidence=0.5, evidence="parse error"))
        return results

    async def aversion(self, response: str, tool_context: str,
                       max_claims: int = 5, spine: Any = None) -> list[VerificationResult]:
        if not self.enabled or not self._provider:
            return []
        if not self._has_claims(response):
            return []

        try:
            extract_prompt = (
                f"Extract up to {max_claims} specific verifiable factual claims "
                f"(numbers, filenames, outcomes, URLs) from this text. "
                f"Output ONLY a JSON array of strings. No prose.\n\nText:\n{response[:1500]}"
            )
            raw = ""
            async for tok in self._provider.acomplete(
                [{"role": "user", "content": extract_prompt}],
                model=self._model, stream=False, thinking=False
            ):
                raw += tok
            clean = re.sub(r"```[a-zA-Z]*", "", raw).strip()
            claims: list[str] = json.loads(clean)
            if not isinstance(claims, list): return []
        except Exception:
            return []

        results: list[VerificationResult] = []
        ctx_snip = tool_context[:2000]
        prism_ctx = ""
        if spine and hasattr(spine, 'active_findings') and spine.active_findings:
            prism_ctx = "\n\nPRISM Analytical Findings:\n" + "\n".join(
                f"- {f.title}: {f.description}" for f in spine.active_findings[:5]
            )

        async def _v_one(claim):
            try:
                prompt = (f"Claim: {claim}\n\nContext (tool results):\n{ctx_snip}{prism_ctx}")
                raw_v  = ""
                async for tok in self._provider.acomplete(
                    [{"role": "user", "content": prompt}],
                    model=self._model, stream=False, thinking=False,
                    tools=None
                ):
                    raw_v += tok
                d = json.loads(re.sub(r"```[a-zA-Z]*", "", raw_v).strip())
                return VerificationResult(
                    claim=claim,
                    verdict=d.get("verdict", "unverified"),
                    confidence=float(d.get("confidence", 0.5)),
                    evidence=str(d.get("evidence", ""))[:200],
                )
            except Exception:
                return VerificationResult(
                    claim=claim, verdict="unverified",
                    confidence=0.5, evidence="parse error")

        tasks = [asyncio.create_task(_v_one(c)) for c in claims[:max_claims]]
        results = await asyncio.gather(*tasks)
        return list(results)

    def annotate(self, response: str,
                 results: list[VerificationResult]) -> str:
        if not results:
            return response
        low = [r for r in results if r.verdict in ("unverified", "contradicted")]
        if not low:
            return response
        footer = "\n\n---\n⚠ **Verification flags** (auto-checked against tool results):\n"
        for r in low:
            icon = "✗" if r.verdict == "contradicted" else "?"
            footer += f"  {icon} [{r.confidence:.0%}] {r.claim[:80]}"
            if r.evidence and r.evidence != "no evidence":
                footer += f" — {r.evidence[:60]}"
            footer += "\n"
        return response + footer
