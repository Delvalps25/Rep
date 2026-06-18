import os
import platform
import subprocess
import shutil
from pathlib import Path
from typing import Any, List, Dict, Optional

class SeccompSandbox:
    @staticmethod
    def available() -> bool:
        if platform.system() != "Linux": return False
        return True

    @staticmethod
    def run(argv: List[str], cwd: str, timeout: int):
        return subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=timeout, cwd=cwd)

class ContainerSandbox:
    def __init__(self, session_id: str, workspace: Path):
        self._sid = session_id
        self._ws = workspace
        self._runtime = self._detect_runtime()

    @staticmethod
    def _detect_runtime() -> Optional[str]:
        for rt in ["docker", "podman"]:
            if shutil.which(rt): return rt
        return None

    def available(self) -> bool:
        return self._runtime is not None
