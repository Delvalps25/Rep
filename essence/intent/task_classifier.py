import enum as _enum
from essence.core.hardware import HardwareProfile
from essence.core.providers import REGISTRY

class RequestComplexity(_enum.Enum):
    TRIVIAL  = 0
    SIMPLE   = 1
    MODERATE = 2
    COMPLEX  = 3
    EXPERT   = 4

def _classify_complexity(text: str, tool: str = "none") -> RequestComplexity:
    t = text.lower()
    n = len(text.split())
    if any(k in t for k in ("research", "implement", "architect", "design system",
                             "refactor", "analyze dataset", "train", "finetune",
                             "multi-step", "long-term", "strategy")):
        return RequestComplexity.EXPERT
    if (n > 80 or any(k in t for k in ("plan", "steps to", "how do i", "compare",
                                        "explain in detail", "code that", "write a"))):
        return RequestComplexity.COMPLEX
    if tool in ("run_analysis", "train_model", "finetune", "vision_task"):
        return RequestComplexity.COMPLEX
    if tool in ("python_exec", "shell", "web_search"):
        return RequestComplexity.MODERATE
    if n > 30 or any(k in t for k in ("summarize", "describe", "list", "find")):
        return RequestComplexity.MODERATE
    if n <= 8:
        return RequestComplexity.TRIVIAL
    return RequestComplexity.SIMPLE

def route_model_for_complexity(hw: HardwareProfile,
                                complexity: RequestComplexity) -> str:
    _tier_map = {
        RequestComplexity.TRIVIAL:  0,
        RequestComplexity.SIMPLE:   0,
        RequestComplexity.MODERATE: 1,
        RequestComplexity.COMPLEX:  2,
        RequestComplexity.EXPERT:   3,
    }
    min_tier = _tier_map[complexity]
    effective_tier = min(min_tier, hw.tier)
    budget = hw.effective_gb * 0.85
    candidates = sorted(
        [m for m in REGISTRY
         if m.min_tier <= effective_tier
         and m.vram_q4_gb <= budget
         and not m.requires_vlm],
        key=lambda m: (m.pinch, m.active_b), reverse=True,
    )
    if not candidates:
        return hw.model
    if complexity in (RequestComplexity.TRIVIAL, RequestComplexity.SIMPLE):
        tier_candidates = [m for m in candidates if m.min_tier == 0]
        if tier_candidates:
            return sorted(tier_candidates, key=lambda m: m.vram_q4_gb)[0].ollama_tag
    return candidates[0].ollama_tag
