import re
import json
from typing import Any
from dataclasses import dataclass

@dataclass
class VerificationResult:
    claim:       str
    verdict:     str    # "verified" | "unverified" | "contradicted"
    confidence:  float  # 0.0–1.0
    evidence:    str    # quote from tool result or "no evidence"

class VerifierLayer:
    """
    Factuality verifier — cross-references LLM claims against tool results.

    Usage:
        vl = VerifierLayer(provider, cheapest_model)
        results = vl.verify(response_text, tool_results_context)
        annotated = vl.annotate(response_text, results)
    """

    # Patterns that signal a factual claim worth checking
    _CLAIM_PATTERNS = [
        re.compile(r'\b\d{4,}\b'),                   # numbers ≥ 4 digits
        re.compile(r'https?://\S+'),                  # URLs
        re.compile(r'[A-Za-z0-9_./-]+\.(py|json|txt|csv|md|yaml|toml)\b'),  # filenames
        re.compile(r'\b(?:always|never|all|none|every|no)\b', re.I),         # absolutes
        re.compile(r'\b(?:error|fail|success|complete|done|finish)\b', re.I),# outcomes
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
        """Extract and verify factual claims in response against tool_context."""
        if not self.enabled or not self._provider:
            return []
        if not self._has_claims(response):
            return []

        # Extract claims using the LLM (one cheap call)
        try:
            extract_prompt = (
                f"Extract up to {max_claims} specific verifiable factual claims "
                f"(numbers, filenames, outcomes, URLs) from this text. "
                f"Output ONLY a JSON array of strings. No prose.\n\n"
                f"Text:\n{response[:1500]}"
            )
            # Placeholder for actual LLM call
            # claims = self._provider.generate(extract_prompt, model=self._model)
            claims = [] # Mocked for now
        except Exception:
            return []

        results = []
        # Logic to call verifier for each claim would go here
        return results

    def annotate(self, text: str, results: list[VerificationResult]) -> str:
        """Annotate text with verification marks."""
        for r in results:
            mark = "✅" if r.verdict == "verified" else "❌" if r.verdict == "contradicted" else "❓"
            text = text.replace(r.claim, f"{r.claim} [{mark}]")
        return text
