import os
import platform
import shutil
import json
import subprocess
from typing import Any, List
from pydantic import BaseModel, Field, ConfigDict, field_validator
from essence.config import log

class HardwareProfile(BaseModel):
    os_name:    str       # Linux | Darwin | Windows
    arch:       str       # x86_64 | arm64 | aarch64
    cpu_cores:  int       = Field(default=1)
    ram_gb:     float     = Field(default=4.0)
    gpu_vendor: str       # nvidia | amd | apple | intel | none
    vram_gb:    float     = Field(default=0.0)  # 0 = no discrete GPU
    has_cuda:   bool      = False
    has_metal:  bool      = False  # Apple Silicon
    has_rocm:   bool      = False
    has_vulkan: bool      = False
    tier:       int       = 0    # 0–3
    tier_label: str       = 'T0·IoT'
    backend:    str       = 'ollama'
    model:      str       = 'qwen3:0.6b'

    @field_validator('vram_gb', mode='before')
    @classmethod
    def _clamp_vram(cls, v: Any) -> float:
        return max(0.0, float(v))

    @field_validator('cpu_cores', mode='before')
    @classmethod
    def _clamp_cores(cls, v: Any) -> int:
        return max(1, int(v))

    @field_validator('ram_gb', mode='before')
    @classmethod
    def _clamp_ram(cls, v: Any) -> float:
        return max(0.5, float(v))

    @property
    def effective_gb(self) -> float:
        """Heuristic for available model memory."""
        if self.gpu_vendor == "apple": return self.ram_gb * 0.75
        if self.vram_gb > 0: return self.vram_gb
        return self.ram_gb * 0.5

def _sh(cmd: List[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8")
    except Exception:
        return ""

def _ram_gb() -> float:
    try:
        s = platform.system()
        if s == "Darwin":
            return int(_sh(["sysctl", "-n", "hw.memsize"])) / 1e9
        if s == "Linux":
            for line in open("/proc/meminfo"):
                if line.startswith("MemTotal"):
                    return int(line.split()[1]) / 1e6
    except Exception: pass
    return 4.0

def probe_hardware() -> HardwareProfile:
    os_name = platform.system()
    arch    = platform.machine().lower()
    cores   = os.cpu_count() or 1
    ram     = _ram_gb()

    profile = HardwareProfile(
        os_name=os_name, arch=arch, cpu_cores=cores, ram_gb=ram,
        gpu_vendor="none"
    )

    # Tier classification logic simplified for brevity
    if ram >= 32:
        profile.tier = 3
        profile.tier_label = "T3·Cluster"
    elif ram >= 16:
        profile.tier = 2
        profile.tier_label = "T2·Pro"
    elif ram >= 8:
        profile.tier = 1
        profile.tier_label = "T1·Desktop"
    else:
        profile.tier = 0
        profile.tier_label = "T0·IoT"

    return profile
