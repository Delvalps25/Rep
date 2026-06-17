from __future__ import annotations
import os
import threading
from pathlib import Path
from typing import Any
from essence.core.events import log

class VoicePipeline:
    def __init__(self) -> None:
        self._whisper_model_size = os.environ.get("UAIS_VOICE_MODEL", "base")
        self._lang     = os.environ.get("UAIS_VOICE_LANG",  "en")
        self._tts_voice = os.environ.get("UAIS_TTS_VOICE", "af_heart")
        self._device   = os.environ.get("UAIS_VOICE_DEVICE", "cpu")
        self._stt: Any = None
        self._tts: Any = None

    def _load_stt(self) -> bool:
        if self._stt is not None:
            return True
        try:
            from faster_whisper import WhisperModel
            self._stt = WhisperModel(
                self._whisper_model_size,
                device=self._device,
                compute_type="int8" if self._device == "cpu" else "float16",
            )
            return True
        except ImportError:
            log.debug("whisper_not_installed",
                      extra={"detail": "pip install faster-whisper"})
            return False
        except Exception as e:
            log.warning("whisper_load_error", extra={"error": str(e)[:80]})
            return False

    def transcribe(self, audio_path: str | Path, language: str = "") -> str:
        if not self._load_stt():
            return ""
        lang = language or self._lang
        try:
            segments, _ = self._stt.transcribe(
                str(audio_path), language=lang,
                beam_size=5, best_of=5,
                vad_filter=True,
            )
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:
            return f"[transcribe error: {e}]"

    def transcribe_bytes(self, audio_bytes: bytes,
                         suffix: str = ".wav", language: str = "") -> str:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        try:
            return self.transcribe(tmp, language)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def _load_tts(self) -> bool:
        if self._tts is not None:
            return True
        try:
            from kokoro_onnx import Kokoro
            _model_name  = "kokoro-v0_19.onnx"
            _voices_name = "voices.bin"
            _search_dirs = [
                Path(os.environ.get("UAIS_WORKSPACE",
                                    str(Path.home() / ".uais"))) / "models",
                Path.cwd(),
            ]
            _model_path  = next(
                (d / _model_name  for d in _search_dirs if (d / _model_name).exists()),
                Path(_model_name))
            _voices_path = next(
                (d / _voices_name for d in _search_dirs if (d / _voices_name).exists()),
                Path(_voices_name))
            self._tts = Kokoro(str(_model_path), str(_voices_path))
            return True
        except ImportError:
            return False
        except Exception as e:
            log.debug("tts_load_error", extra={"error": str(e)[:80]})
            return False

    def speak(self, text: str, output_path: str | Path | None = None) -> bool:
        if not text.strip():
            return True

        if self._load_tts():
            try:
                import numpy as np
                samples, sample_rate = self._tts.create(
                    text, voice=self._tts_voice, speed=1.0, lang=self._lang)
                if output_path:
                    import soundfile as sf
                    sf.write(str(output_path), samples, sample_rate)
                else:
                    import sounddevice as sd
                    sd.play(samples, sample_rate)
                    sd.wait()
                return True
            except Exception as e:
                log.debug("tts_kokoro_error", extra={"error": str(e)[:80]})

        try:
            import pyttsx3
            engine = pyttsx3.init()
            if output_path:
                engine.save_to_file(text, str(output_path))
                engine.runAndWait()
            else:
                engine.say(text)
                engine.runAndWait()
            return True
        except Exception:
            pass

        log.debug("tts_unavailable",
                  extra={"detail": "install faster-whisper kokoro-onnx sounddevice"})
        return False

    @property
    def available(self) -> bool:
        return self._load_stt()

_voice_pipeline: VoicePipeline | None = None
_voice_pipeline_lock = threading.Lock()

def get_voice_pipeline() -> VoicePipeline:
    global _voice_pipeline
    if _voice_pipeline is not None:
        return _voice_pipeline
    with _voice_pipeline_lock:
        if _voice_pipeline is None:
            _voice_pipeline = VoicePipeline()
    return _voice_pipeline
