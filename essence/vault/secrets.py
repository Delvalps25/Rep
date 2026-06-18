import os
import json
import base64
import struct
import hashlib
import secrets
import threading
import sys
import zlib as _zlib
from pathlib import Path
from typing import Any, Dict, Optional
from essence.config import log

_COMPRESS_MAGIC = b"UAISCZ1\x00"

def compress_bundle(data: bytes) -> bytes:
    compressed = _zlib.compress(data, level=6)
    if len(compressed) < len(data):
        return _COMPRESS_MAGIC + compressed
    return data

def decompress_bundle(data: bytes) -> bytes:
    if data[:8] == _COMPRESS_MAGIC:
        return _zlib.decompress(data[8:])
    return data

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _AESGCM = True
except ImportError:
    _AESGCM = False

class SecretsVault:
    _ITER     = 260_000
    _SALT_LEN = 32
    _KEY_LEN  = 32

    def __init__(self, vault_path: Path) -> None:
        self._path  = vault_path
        self._data: Dict[str, str] = {}
        self._key:  Optional[bytes] = None
        self._lock  = threading.RLock()

    @staticmethod
    def _derive(password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt,
            SecretsVault._ITER, dklen=SecretsVault._KEY_LEN)

    def unlock(self, password: str | None = None) -> bool:
        with self._lock:
            if self._key is not None:
                return True
            if password is None:
                if sys.stdin.isatty():
                    import getpass
                    password = getpass.getpass("  UAIS Vault master password: ").strip()
                else:
                    password = os.environ.get("UAIS_VAULT_PASSWORD", "")
            if not password:
                return False

            salt = secrets.token_bytes(self._SALT_LEN)
            self._key = self._derive(password, salt)
            return True

    def get(self, name: str, default: str = "") -> str:
        with self._lock:
            return self._data.get(name, default)

    def set(self, name: str, value: str) -> None:
        with self._lock:
            self._data[name] = value

    def resolve(self, name: str, default: str = "") -> str:
        val = self.get(name, "")
        return val or os.environ.get(name, default)
