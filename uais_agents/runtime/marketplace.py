import os
import json
import urllib.request
import textwrap
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from uais_core.events import log

class SkillInfo:
    """Metadata for a skill in the marketplace registry."""
    def __init__(self, name: str, description: str = "", version: str = "",
                 author: str = "", url: str = "", sha256: str = "",
                 installed: bool = False, local_path: str = "") -> None:
        self.name        = name
        self.description = description
        self.version     = version
        self.author      = author
        self.url         = url
        self.sha256      = sha256
        self.installed   = installed
        self.local_path  = local_path
    def __repr__(self) -> str:
        return f"SkillInfo(name={self.name!r}, version={self.version!r})"

class SkillMarketplace:
    """
    Local skill installer with optional remote registry.
    """
    SKILL_REGISTRY_URL = os.environ.get("UAIS_SKILL_REGISTRY", "https://api.github.com/repos/uais-project/skill-hub/contents/registry.json")

    def __init__(self, workspace: Path, agent: Any = None) -> None:
        self._ws    = workspace
        self._agent = agent

    def fetch_registry(self) -> List[SkillInfo]:
        try:
            resp = json.loads(
                urllib.request.urlopen(self.SKILL_REGISTRY_URL, timeout=8)
                .read().decode("utf-8", errors="replace"))
            return [SkillInfo(**item) for item in resp.get("skills", [])]
        except Exception as e:
            log.debug("skill_registry_fetch_error", extra={"error": str(e)})
            return []

    def list_installed(self) -> List[SkillInfo]:
        skills_dir = self._ws / "skills"
        if not skills_dir.exists():
            return []
        result = []
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir(): continue
            skill_md = d / "SKILL.md"
            if not skill_md.exists(): continue
            try:
                content = skill_md.read_text(encoding="utf-8")
                desc = next((l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")), d.name)
                result.append(SkillInfo(name=d.name, description=desc[:120], version="local", author="local", installed=True))
            except Exception: pass
        return result

    def scaffold_new_skill(self, name: str) -> Path:
        skill_dir = self._ws / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            skill_md.write_text(textwrap.dedent(f"""                # {name}
                ## Description
                ## When to use
                ## Steps
                ## Tools used
                ## Examples
            """), encoding="utf-8")
        return skill_dir
