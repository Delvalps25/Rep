import threading
import importlib.util as _ilu
import ast as _ast
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Set
from essence.config import log

class PluginLoader:
    _BLOCKED_IMPORTS = frozenset({
        "subprocess", "socket", "ctypes", "pty", "fcntl", "multiprocessing",
        "os.system", "shutil", "signal", "resource", "mmap", "cffi", "_thread",
    })

    def __init__(self, plugin_dir: Path, poll_interval: float = 30.0) -> None:
        self._dir      = plugin_dir
        self._interval = poll_interval
        self._mtimes:  Dict[str, float] = {}
        self._stop     = threading.Event()
        self._thread:  Optional[threading.Thread] = None

    def _ast_check(self, path: Path) -> Tuple[bool, str]:
        try:
            tree = _ast.parse(path.read_text(encoding="utf-8"))
        except Exception as e:
            return False, f"syntax error: {e}"
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.Import, _ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, _ast.Import) else [node.module or ""]
                for name in names:
                    root = (name or "").split(".")[0]
                    if root in self._BLOCKED_IMPORTS:
                        return False, f"forbidden import: {name}"
        return True, "ok"

    def _load_file(self, path: Path) -> None:
        safe, reason = self._ast_check(path)
        if not safe:
            log.warning("plugin_blocked", extra={"file": path.name, "reason": reason})
            return
        spec = _ilu.spec_from_file_location(f"essence_plugin_{path.stem}", path)
        if spec and spec.loader:
            module = _ilu.module_from_spec(spec)
            spec.loader.exec_module(module)
            log.info("plugin_loaded", extra={"file": path.name})
