from __future__ import annotations
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from uais_core.events import log

class BrowserSession:
    SESSION_TTL = 300

    def __init__(self, session_id: str = "") -> None:
        self._session_id  = session_id or secrets.token_hex(6)
        self._browser: Any = None
        self._page:    Any = None
        self._last_used: float = time.time()
        self._lock = threading.RLock()

    def _ensure_open(self) -> bool:
        if self._browser is not None and self._page is not None:
            self._last_used = time.time()
            return True
        try:
            from playwright.sync_api import sync_playwright
            self._pw_ctx   = sync_playwright()
            pw             = self._pw_ctx.__enter__()
            self._browser  = pw.chromium.launch(headless=True)
            self._page     = self._browser.new_page(
                viewport={"width": 1280, "height": 900})
            self._last_used = time.time()
            return True
        except ImportError:
            return False
        except Exception as e:
            log.debug("browser_session_open_error", extra={"error": str(e)[:80]})
            try:
                if self._browser:
                    self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._page    = None
            return False

    def close(self) -> None:
        with self._lock:
            try:
                if self._browser:
                    self._browser.close()
            except Exception:
                pass
            try:
                if hasattr(self, "_pw_ctx"):
                    self._pw_ctx.__exit__(None, None, None)
            except Exception:
                pass
            self._browser = None
            self._page    = None

    @property
    def is_expired(self) -> bool:
        return time.time() - self._last_used > self.SESSION_TTL

    def open(self, url: str, timeout_ms: int = 15000) -> str:
        with self._lock:
            if not self._ensure_open():
                return "[BrowserSession] Playwright not available — pip install playwright && playwright install chromium"
            try:
                self._page.goto(url, timeout=timeout_ms,
                                wait_until="domcontentloaded")
                self._page.wait_for_load_state("networkidle", timeout=timeout_ms)
                text = self._page.evaluate(
                    "() => document.body ? document.body.innerText : ''")
                return (text or "")[:8000].strip()
            except Exception as e:
                return f"[BrowserSession.open error: {e}]"

    def click(self, selector: str, timeout_ms: int = 5000) -> str:
        with self._lock:
            if not self._ensure_open():
                return "[BrowserSession] not open"
            try:
                self._page.click(selector, timeout=timeout_ms)
                return f"[BrowserSession] clicked: {selector}"
            except Exception as e:
                return f"[BrowserSession.click error: {e}]"

    def fill(self, selector: str, value: str,
             timeout_ms: int = 5000) -> str:
        with self._lock:
            if not self._ensure_open():
                return "[BrowserSession] not open"
            try:
                self._page.fill(selector, value, timeout=timeout_ms)
                return f"[BrowserSession] filled {selector}"
            except Exception as e:
                return f"[BrowserSession.fill error: {e}]"

    def extract(self, selector: str) -> str:
        with self._lock:
            if not self._ensure_open():
                return "[BrowserSession] not open"
            try:
                elements = self._page.query_selector_all(selector)
                texts    = [el.inner_text() for el in elements if el]
                return "\n".join(texts).strip() or "[no elements matched]"
            except Exception as e:
                return f"[BrowserSession.extract error: {e}]"

    def screenshot(self, out_dir: Path | None = None,
                   selector: str = "") -> str:
        with self._lock:
            if not self._ensure_open():
                return "[BrowserSession] not open"
            try:
                import tempfile
                save_dir = out_dir or Path(tempfile.gettempdir())
                out_path = save_dir / f"uais_browser_{int(time.time())}.png"
                if selector:
                    el = self._page.query_selector(selector)
                    (el or self._page).screenshot(path=str(out_path))
                else:
                    self._page.screenshot(path=str(out_path), full_page=False)
                return str(out_path)
            except Exception as e:
                return f"[BrowserSession.screenshot error: {e}]"

    def current_url(self) -> str:
        with self._lock:
            if self._page is None:
                return ""
            try:
                return self._page.url
            except Exception:
                return ""

_browser_sessions: dict[str, BrowserSession] = {}
_browser_sessions_lock = threading.Lock()

def get_browser_session(session_id: str) -> BrowserSession:
    with _browser_sessions_lock:
        sess = _browser_sessions.get(session_id)
        if sess is None or sess.is_expired:
            if sess is not None:
                try:
                    sess.close()
                except Exception:
                    pass
            sess = BrowserSession(session_id)
            _browser_sessions[session_id] = sess
        return sess

def close_browser_session(session_id: str) -> None:
    with _browser_sessions_lock:
        sess = _browser_sessions.pop(session_id, None)
    if sess:
        sess.close()
