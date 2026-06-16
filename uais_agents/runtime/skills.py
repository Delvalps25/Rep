from __future__ import annotations
import threading
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable, list
from uais_core.events import log
from uais_agents.runtime.tools import TOOL_REGISTRY, BUILTIN_TOOLS

class SkillCycleError(RuntimeError): pass
_skill_call_stack = threading.local()

def _tool_use_skill(args: dict, *, _registry: Any = None) -> str:
    skill_name = str(args.get("skill_name", "")).strip()
    task       = str(args.get("task", "")).strip()
    if not skill_name or not task: return "[use_skill error: skill_name and task required]"
    stack: list[str] = getattr(_skill_call_stack, "stack", [])
    if skill_name in stack:
        cycle_path = " → ".join(stack + [skill_name])
        log.warning("skill_cycle_detected", extra={"cycle": cycle_path})
        return f"[use_skill error: cycle detected ({cycle_path})]"
    reg = _registry or TOOL_REGISTRY
    handler = reg.get_handler(skill_name)
    if handler is None: return f"[use_skill error: skill '{skill_name}' not found]"
    if not hasattr(_skill_call_stack, "stack"): _skill_call_stack.stack = []
    _skill_call_stack.stack.append(skill_name)
    try:
        result = handler({"task": task, "prompt": task})
        return str(result)
    except Exception as _e:
        return f"[use_skill error: {_e}]"
    finally: _skill_call_stack.stack.pop()

def load_skills(workspace: Path) -> dict[str, str]:
    skills: dict[str, str] = {}
    skills_dir = workspace / "skills"
    if not skills_dir.exists(): return skills
    for skill_path in skills_dir.glob("*/SKILL.md"):
        try: skills[skill_path.parent.name] = skill_path.read_text(encoding="utf-8")
        except Exception: pass
    return skills

def load_skills_index(workspace: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    skills_dir = workspace / "skills"
    if not skills_dir.exists(): return index
    for skill_path in skills_dir.glob("*/SKILL.md"):
        name = skill_path.parent.name
        try:
            md = skill_path.read_text(encoding="utf-8")
            desc = next((l.strip() for l in md.splitlines() if l.strip() and not l.startswith(("#", "---"))), name)
            index[name] = desc[:120]
        except Exception: index[name] = name
    return index

def read_skill_content(workspace: Path, skill_name: str) -> str:
    skill_path = workspace / "skills" / skill_name / "SKILL.md"
    if not skill_path.exists(): return f"[skill '{skill_name}' not found]"
    try: return skill_path.read_text(encoding="utf-8")
    except Exception as e: return f"[error reading skill: {e}]"

def skills_summary(skills: dict[str, str]) -> str:
    if not skills: return ""
    lines = ["[Available Skills — use read_skill tool to load full instructions]"]
    for name, content in skills.items():
        if "\n" in content:
            desc = next((l.strip() for l in content.splitlines() if l.strip() and not l.startswith(("#", "---"))), name)
        else: desc = content
        lines.append(f"  • {name}: {desc[:100]}")
    return "\n".join(lines)
