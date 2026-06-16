from __future__ import annotations
import hashlib
import threading
import asyncio
from typing import Any, Callable, list
from uais_core.events import log
from uais_core.infra.fast_json import _fast_dumps

class ToolRegistry:
    def __init__(self) -> None:
        self._handlers:  dict[str, Callable[[dict], str]] = {}
        self._schemas:   list[dict]                       = []
        self._inflight:  dict[str, tuple[threading.Event, list]] = {}
        self._dedup_lock = threading.Lock()
        self._ainflight: dict[str, tuple[asyncio.Event, list]]   = {}
        self._adedup_lock = asyncio.Lock()

    def _call_key(self, name: str, args: dict) -> str:
        try:
            args_sig = _fast_dumps(args, sort_keys=True, default=str)
        except Exception:
            args_sig = str(args)
        return hashlib.sha256(f"{name}:{args_sig}".encode()).hexdigest()[:24]

    def call(self, name: str, args: dict) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            return f"[unknown tool: {name}]"
        key = self._call_key(name, args)
        with self._dedup_lock:
            if key in self._inflight:
                evt, holder = self._inflight[key]
                is_leader   = False
            else:
                evt    = threading.Event()
                holder = []
                self._inflight[key] = (evt, holder)
                is_leader = True
        if not is_leader:
            evt.wait(timeout=120)
            return holder[0] if holder else f"[dedup_timeout: {name}]"
        try:
            result = handler(args)
        except Exception as e:
            result = f"[tool_error: {e}]"
        finally:
            with self._dedup_lock:
                holder.append(result)
                evt.set()
                self._inflight.pop(key, None)
        return result

    async def acall(self, name: str, args: dict) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            return f"[unknown tool: {name}]"

        _ahandler = getattr(handler, "ahandler", None)

        key = self._call_key(name, args)
        async with self._adedup_lock:
            if key in self._ainflight:
                evt, holder = self._ainflight[key]
                is_leader   = False
            else:
                evt    = asyncio.Event()
                holder = []
                self._ainflight[key] = (evt, holder)
                is_leader = True

        if not is_leader:
            try:
                await asyncio.wait_for(evt.wait(), timeout=120)
                return holder[0] if holder else f"[dedup_timeout: {name}]"
            except asyncio.TimeoutError:
                return f"[dedup_timeout: {name}]"

        try:
            if _ahandler:
                result = await _ahandler(args)
            elif asyncio.iscoroutinefunction(handler):
                result = await handler(args)
            else:
                loop   = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, handler, args)
        except Exception as e:
            result = f"[tool_error: {e}]"
        finally:
            async with self._adedup_lock:
                holder.append(result)
                evt.set()
                self._ainflight.pop(key, None)
        return result

    def register(self, schema: dict, handler: Callable[[dict], str]) -> None:
        name = schema["function"]["name"]
        self._handlers[name] = handler
        self._schemas = [s for s in self._schemas
                         if s["function"]["name"] != name]
        self._schemas.append(schema)
        log.debug("tool_registered", extra={"name": name})

    def get_handler(self, name: str) -> Callable[[dict], str] | None:
        return self._handlers.get(name)

    def get_tools(self) -> list[dict]:
        return list(self._schemas)

    def names(self) -> list[str]:
        return list(self._handlers.keys())

    def unregister(self, name: str) -> None:
        self._handlers.pop(name, None)
        self._schemas = [s for s in self._schemas
                         if s["function"]["name"] != name]

TOOL_REGISTRY = ToolRegistry()

BUILTIN_TOOLS: list[dict] = [
    {"type": "function", "function": {
        "name": "shell",
        "description": "Run a sandboxed shell command; returns stdout+stderr. "
                       "Use for file ops, git, system queries, package installs.",
        "parameters": {"type": "object", "required": ["command"],
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 15}}}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file from the workspace.",
        "parameters": {"type": "object", "required": ["path"],
            "properties": {
                "path":     {"type": "string"},
                "encoding": {"type": "string", "default": "utf-8"}}}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write content to a file (creates or overwrites).",
        "parameters": {"type": "object", "required": ["path", "content"],
            "properties": {
                "path":    {"type": "string"},
                "content": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "python_exec",
        "description": "Execute a Python snippet in a sandboxed subprocess.",
        "parameters": {"type": "object", "required": ["code"],
            "properties": {
                "code":    {"type": "string"},
                "timeout": {"type": "integer", "default": 10}}}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web via DuckDuckGo (no API key required).",
        "parameters": {"type": "object", "required": ["query"],
            "properties": {
                "query":       {"type": "string"},
                "max_results": {"type": "integer", "default": 5}}}}},
    {"type": "function", "function": {
        "name": "heartbeat_add",
        "description": "Schedule a recurring background task.",
        "parameters": {"type": "object",
            "required": ["name", "message", "schedule"],
            "properties": {
                "name":     {"type": "string",
                             "description": "Unique task identifier"},
                "message":  {"type": "string",
                             "description": "Task prompt to run on schedule"},
                "schedule": {"type": "string",
                             "description": "Interval: '30m', '1h', '1d'; "
                                            "or cron: 'cron:0 9 * * *'"}}}}},
    {"type": "function", "function": {
        "name": "analyze_image",
        "description": "Analyze an image with a vision-language model. "
                       "Requires hw.tier >= 1 and VRAM >= 4 GB. "
                       "Returns a text description or answer to the question.",
        "parameters": {"type": "object", "required": ["path", "question"],
            "properties": {
                "path":     {"type": "string",
                             "description": "Absolute or workspace-relative image path"},
                "question": {"type": "string",
                             "description": "Question to ask about the image"}}}}},
    {"type": "function", "function": {
        "name": "build_skill",
        "description": "Auto-build a new skill: scaffold a SKILL.md in workspace/skills/ "
                       "with the agent writing the instructions. The skill is sandboxed "
                       "to its declared capability list on first run.",
        "parameters": {"type": "object", "required": ["description"],
            "properties": {
                "description": {"type": "string",
                                "description": "Natural-language description of "
                                               "what the skill should do"}}}}},
    {"type": "function", "function": {
        "name": "ingest",
        "description": "Ingest a file, directory, or URL into the RAG memory store. "
                       "Supports PDF, DOCX, HTML, CSV, Markdown, plain text. "
                       "After ingestion, agent memory search retrieves relevant passages.",
        "parameters": {"type": "object", "required": ["path_or_url"],
            "properties": {
                "path_or_url": {"type": "string",
                                "description": "File path, directory path, or https:// URL"}}}}},
    {"type": "function", "function": {
        "name": "run_analysis",
        "description": "Run data analysis or ML on a dataset file (CSV/parquet/JSON/Excel). "
                       "Tasks: eda, cluster, classify, regress, forecast, anomaly, "
                       "ab_test, sentiment, risk, churn, feature_importance. "
                       "Saves plots to workspace/plots/. Returns JSON metrics.",
        "parameters": {"type": "object", "required": ["dataset_path", "task"],
            "properties": {
                "dataset_path": {"type": "string"},
                "task": {"type": "string",
                         "enum": ["eda","cluster","classify","regress","forecast",
                                  "anomaly","ab_test","sentiment","risk","churn",
                                  "feature_importance","correlation","segmentation"]},
                "target_col": {"type": "string", "default": ""},
                "config": {"type": "object",
                           "description": "Task-specific options e.g. "
                           "{algorithm, n_clusters, periods, group_col, hpo, confidence}"}}}}},
    {"type": "function", "function": {
        "name": "train_model",
        "description": "End-to-end ML model training on a CSV dataset. "
                       "model_type: auto|sklearn_rf|sklearn_gbm|sklearn_lr|pytorch_mlp. "
                       "Set config.hpo=true for Optuna hyperparameter optimisation. "
                       "Saves model artifact to workspace/models/<run_id>/.",
        "parameters": {"type": "object", "required": ["dataset_path", "target_col"],
            "properties": {
                "dataset_path": {"type": "string"},
                "target_col":   {"type": "string"},
                "model_type":   {"type": "string", "default": "auto"},
                "config":       {"type": "object"}}}}},
    {"type": "function", "function": {
        "name": "finetune",
        "description": "Fine-tune an LLM (Llama3, Qwen2.5, Mistral, Phi, Gemma2) on "
                       "a local JSONL dataset using unsloth (fastest) or PEFT LoRA. "
                       "Dataset: JSONL with {prompt, response} or Alpaca {instruction, input, output}. "
                       "Requires T2+ hardware (≥12 GB VRAM).",
        "parameters": {"type": "object", "required": ["base_model", "dataset_path"],
            "properties": {
                "base_model":   {"type": "string",
                                 "description": "HF model ID e.g. unsloth/llama-3-8b-bnb-4bit"},
                "dataset_path": {"type": "string"},
                "output_dir":   {"type": "string", "default": ""},
                "config":       {"type": "object",
                                 "description": "{epochs, lr, batch_size, lora_r, max_seq_len}"}}}}},
    {"type": "function", "function": {
        "name": "vision_task",
        "description": "Computer vision on an image file. "
                       "task: classify (ResNet/ViT), detect (YOLOv8), "
                       "ocr (tesseract/PaddleOCR), segment (SAM, T3 only). "
                       "Tiered: T0=OCR only, T1=detect+classify, T2=full, T3=segment.",
        "parameters": {"type": "object", "required": ["path", "task"],
            "properties": {
                "path":  {"type": "string"},
                "task":  {"type": "string",
                          "enum": ["classify", "detect", "ocr", "segment"]},
                "model": {"type": "string", "default": "auto"}}}}},
    {"type": "function", "function": {
        "name": "speech",
        "description": "Speech and audio tasks. "
                       "task=transcribe: STT via faster-whisper (CPU-friendly). "
                       "task=translate: transcribe + translate to English. "
                       "task=tts: text-to-speech via kokoro-onnx (pass text as audio_path). "
                       "task=classify: audio feature extraction.",
        "parameters": {"type": "object", "required": ["audio_path"],
            "properties": {
                "audio_path": {"type": "string",
                               "description": "Audio file path, or text string when task=tts"},
                "task":     {"type": "string",
                             "enum": ["transcribe","translate","tts","classify"],
                             "default": "transcribe"},
                "language": {"type": "string", "default": "en"}}}}},
    {"type": "function", "function": {
        "name": "browser_open",
        "description": "Navigate to a URL and return the page's main text content. "
                       "Uses Playwright headless Chromium with full JS rendering. "
                       "Falls back to urllib for plain HTML if Playwright not installed. "
                       "Opens a persistent BrowserSession — subsequent browser_click, "
                       "browser_fill, browser_extract calls operate on the same page.",
        "parameters": {"type": "object", "required": ["url"],
            "properties": {
                "url":        {"type": "string", "description": "Full URL to open"},
                "timeout_ms": {"type": "integer", "default": 15000,
                               "description": "Navigation timeout in milliseconds"}}}}},
    {"type": "function", "function": {
        "name": "browser_screenshot",
        "description": "Take a screenshot of the current browser page and return the PNG file path. "
                       "Call browser_open first. Pair with analyze_image for VLM visual reasoning. "
                       "Requires: pip install playwright && playwright install chromium",
        "parameters": {"type": "object", "required": [],
            "properties": {
                "selector": {"type": "string",
                             "description": "CSS selector for element screenshot (optional)"}}}}},
    {"type": "function", "function": {
        "name": "browser_click",
        "description": "Click an element on the current browser page by CSS selector. "
                       "Call browser_open first to establish a session.",
        "parameters": {"type": "object", "required": ["selector"],
            "properties": {
                "selector":   {"type": "string", "description": "CSS selector of element to click"},
                "timeout_ms": {"type": "integer", "default": 5000}}}}},
    {"type": "function", "function": {
        "name": "browser_fill",
        "description": "Fill an input field on the current browser page by CSS selector. "
                       "Call browser_open first to establish a session.",
        "parameters": {"type": "object", "required": ["selector", "value"],
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of input to fill"},
                "value":    {"type": "string", "description": "Text value to enter"}}}}},
    {"type": "function", "function": {
        "name": "browser_extract",
        "description": "Extract inner text from elements matching a CSS selector on the current page. "
                       "Call browser_open first to establish a session.",
        "parameters": {"type": "object", "required": ["selector"],
            "properties": {
                "selector": {"type": "string",
                             "description": "CSS selector — e.g. 'h1', '.product-price', 'table'",
                             "default": "body"}}}}},
    {"type": "function", "function": {
        "name": "computer_screenshot",
        "description": "Take a screenshot of the entire desktop. Returns PNG file path. "
                       "Requires UAIS_COMPUTER_USE=1 and pip install pyautogui pillow. "
                       "Pair with analyze_image for VLM-powered GUI reasoning.",
        "parameters": {"type": "object", "required": [], "properties": {}}}},
    {"type": "function", "function": {
        "name": "computer_click",
        "description": "Click at screen coordinates (x, y). Requires UAIS_COMPUTER_USE=1.",
        "parameters": {"type": "object", "required": ["x", "y"],
            "properties": {
                "x":      {"type": "integer", "description": "Screen x coordinate"},
                "y":      {"type": "integer", "description": "Screen y coordinate"},
                "button": {"type": "string", "enum": ["left","right","middle"],
                           "default": "left"}}}}},
    {"type": "function", "function": {
        "name": "computer_type",
        "description": "Type text at the current cursor position. Requires UAIS_COMPUTER_USE=1.",
        "parameters": {"type": "object", "required": ["text"],
            "properties": {
                "text":     {"type": "string", "description": "Text to type"},
                "interval": {"type": "number", "default": 0.02,
                             "description": "Delay between keystrokes in seconds"}}}}},
    {"type": "function", "function": {
        "name": "voice_transcribe",
        "description": "Transcribe an audio file to text using faster-whisper (offline STT). "
                       "Accepts .wav, .mp3, .ogg, .flac files.",
        "parameters": {"type": "object", "required": ["audio_path"],
            "properties": {
                "audio_path": {"type": "string", "description": "Path to audio file"}}}}},
    {"type": "function", "function": {
        "name": "voice_speak",
        "description": "Synthesise speech from text using kokoro-onnx TTS (offline). "
                       "Plays through default audio device.",
        "parameters": {"type": "object", "required": ["text"],
            "properties": {
                "text": {"type": "string", "description": "Text to speak aloud"}}}}},
    {"type": "function", "function": {
        "name": "read_skill",
        "description": "Read the full SKILL.md instructions for a named skill. "
                       "Call this when the skills index shows a relevant skill and "
                       "you need its complete instructions before using it.",
        "parameters": {"type": "object", "required": ["skill_name"],
            "properties": {
                "skill_name": {"type": "string",
                               "description": "Exact skill name from the Available Skills index"}}}}},
    {"type": "function", "function": {
        "name": "skill_write",
        "description": "Create a new skill from scratch and hot-reload it into the active "
                       "tool registry. Use when you cannot satisfy a request with existing "
                       "tools and a reusable capability would help. Writes SKILL.md + "
                       "optional tool.py, installs requirements, validates, and activates.",
        "parameters": {"type": "object",
            "required": ["skill_name", "description", "skill_md"],
            "properties": {
                "skill_name": {"type": "string",
                               "description": "Short slug, e.g. 'pdf-summariser' (no spaces)"},
                "description": {"type": "string",
                                "description": "One-sentence description shown in the skills index"},
                "skill_md": {"type": "string",
                             "description": "Full SKILL.md content (instructions for this skill)"},
                "tool_py": {"type": "string",
                            "description": "Optional Python tool implementation code"},
                "requirements": {"type": "string",
                                 "description": "Optional newline-separated pip requirements"}}}}},
]
