"""Live draw: battery pack rate and/or NVIDIA GPU. No pip."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class PowerSnap:
    watts: float | None
    source: str


def gpu_watts() -> float | None:
    smi = shutil.which("nvidia-smi")
    if not smi:
        cand = (
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                         "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe")
        )
        smi = cand if os.path.isfile(cand) else None
    if not smi:
        return None
    try:
        raw = subprocess.check_output(
            [smi, "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
            text=True,
            timeout=4,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    total = 0.0
    n = 0
    for line in raw.splitlines():
        s = line.strip().replace("[N/A]", "").replace("N/A", "")
        if not s:
            continue
        try:
            total += float(s)
            n += 1
        except ValueError:
            continue
    return total if n else None


def pack_watts() -> float | None:
    script = (
        "$b = Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus "
        "-ErrorAction SilentlyContinue | Select-Object -First 1;"
        "if (-not $b) { '{}' ; exit 0 }; "
        "[pscustomobject]@{Charge=$b.ChargeRate; Discharge=$b.DischargeRate} | "
        "ConvertTo-Json -Compress"
    )
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            timeout=4,
            creationflags=CREATE_NO_WINDOW,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return pack_from_data(data)


def pack_from_data(data: object) -> float | None:
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return None

    def _mw(key: str) -> int | None:
        if key not in data or data[key] is None:
            return None
        try:
            n = int(data[key])
        except (TypeError, ValueError):
            return None
        return n if n >= 0 else None

    discharge = _mw("Discharge")
    charge = _mw("Charge")
    if discharge is None and charge is None:
        return None
    if discharge and discharge > 0:
        return discharge / 1000.0
    if charge and charge > 0:
        return charge / 1000.0
    return 0.0


def sample_power(has_battery: bool) -> PowerSnap:
    if has_battery:
        pack = pack_watts()
        if pack is not None:
            return PowerSnap(pack, "battery")
    gpu = gpu_watts()
    if gpu is not None:
        return PowerSnap(gpu, "gpu")
    return PowerSnap(None, "")
