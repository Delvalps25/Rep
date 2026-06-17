import json
from typing import Any

try:
    import orjson as _orjson
    _ORJSON = True

    def _fast_dumps(obj: Any, **kw) -> str:
        """orjson.dumps → str (stdlib json.dumps compat)."""
        opts = _orjson.OPT_NON_STR_KEYS
        if kw.get("indent") == 2:
            opts |= _orjson.OPT_INDENT_2
        if kw.get("sort_keys"):
            opts |= _orjson.OPT_SORT_KEYS
        return _orjson.dumps(obj, default=kw.get("default"), option=opts).decode()

    def _fast_loads(s: "str | bytes") -> Any:
        return _orjson.loads(s)

except ImportError:
    _ORJSON = False
    _fast_dumps = json.dumps
    _fast_loads = json.loads
