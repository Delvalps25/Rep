import os
import time
from pathlib import Path
from essence.core.events import log

def _computer_use_available() -> bool:
    if os.environ.get("UAIS_COMPUTER_USE", "0") != "1":
        return False
    try:
        import pyautogui
        return True
    except ImportError:
        return False

def _tool_computer_screenshot(out_dir: Path | None = None) -> str:
    if not _computer_use_available():
        return "[computer_screenshot] disabled — set UAIS_COMPUTER_USE=1 and pip install pyautogui pillow"
    try:
        import pyautogui, tempfile
        save_dir = out_dir or Path(tempfile.gettempdir())
        out_path = save_dir / f"uais_desktop_{int(time.time())}.png"
        img = pyautogui.screenshot()
        img.save(str(out_path))
        return str(out_path)
    except Exception as e:
        return f"[computer_screenshot error: {e}]"

def _tool_computer_click(x: int, y: int, button: str = "left") -> str:
    if not _computer_use_available():
        return "[computer_click] disabled — set UAIS_COMPUTER_USE=1"
    try:
        import pyautogui
        pyautogui.click(x, y, button=button)
        log.info("computer_click", extra={"x": x, "y": y, "button": button})
        return f"[computer_click] clicked ({x},{y}) with {button} button"
    except Exception as e:
        return f"[computer_click error: {e}]"

def _tool_computer_type(text: str, interval: float = 0.02) -> str:
    if not _computer_use_available():
        return "[computer_type] disabled — set UAIS_COMPUTER_USE=1"
    try:
        import pyautogui
        try:
            import pyperclip
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            log.info("computer_type_clipboard",
                     extra={"chars": len(text)})
            return f"[computer_type] pasted {len(text)} chars via clipboard"
        except ImportError:
            pass

        pyautogui.write(text, interval=interval)
        log.info("computer_type_write", extra={"chars": len(text)})
        return (f"[computer_type] typed {len(text)} chars via write(). "
                "Install pyperclip for full Unicode support: pip install pyperclip")
    except Exception as e:
        return f"[computer_type error: {e}]"
