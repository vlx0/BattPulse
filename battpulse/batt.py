"""Battery via GetSystemPowerStatus + optional WMI wear."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import subprocess
from dataclasses import dataclass

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
UNKNOWN = 0xFFFFFFFF
NO_BATTERY = 128


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wt.DWORD),
        ("BatteryFullLifeTime", wt.DWORD),
    ]


@dataclass
class BattExtra:
    wear_pct: float | None
    name: str
    designed_mwh: int | None
    full_mwh: int | None
    remain_mwh: int | None
    voltage_mv: int | None

    @property
    def max_pct(self) -> float | None:
        if not self.designed_mwh or not self.full_mwh:
            return None
        return max(0.0, min(100.0, 100.0 * self.full_mwh / self.designed_mwh))

    def mah(self, mwh: int | None) -> int | None:
        if not mwh or not self.voltage_mv:
            return None
        return max(1, round(mwh * 1000 / self.voltage_mv))


@dataclass
class BattSnap:
    present: bool
    on_ac: bool | None
    charging: bool
    percent: int | None
    secs_left: int | None
    wear_pct: float | None
    name: str


def snap_from_win32(ac_raw: int, flag: int, pct: int, life: int) -> BattSnap:
    ac = {0: False, 1: True}.get(ac_raw)
    unknown = flag == 255
    # 255 is "couldn't read", not "no battery". 255 & 128 is a false positive.
    no_batt = (not unknown) and bool(flag & NO_BATTERY)
    charging = (not unknown) and (not no_batt) and bool(flag & 8)
    return BattSnap(
        present=not no_batt,
        on_ac=ac,
        charging=charging,
        percent=None if no_batt or pct > 100 else pct,
        secs_left=None if no_batt or life == UNKNOWN else max(0, life),
        wear_pct=None,
        name="",
    )


def sample() -> BattSnap | None:
    st = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return None
    return snap_from_win32(
        int(st.ACLineStatus),
        int(st.BatteryFlag),
        int(st.BatteryLifePercent),
        int(st.BatteryLifeTime),
    )


def _int(data: dict, key: str) -> int | None:
    try:
        n = int(data.get(key) or 0)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def extra() -> BattExtra:
    empty = BattExtra(None, "", None, None, None, None)
    script = (
        "$s = Get-CimInstance -Namespace root/wmi -ClassName BatteryStaticData "
        "-ErrorAction SilentlyContinue | Select-Object -First 1;"
        "$f = Get-CimInstance -Namespace root/wmi -ClassName BatteryFullChargedCapacity "
        "-ErrorAction SilentlyContinue | Select-Object -First 1;"
        "$b = Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus "
        "-ErrorAction SilentlyContinue | Select-Object -First 1;"
        "$n = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue | Select-Object -First 1;"
        "[pscustomobject]@{"
        "Designed=$s.DesignedCapacity; Full=$f.FullChargedCapacity; "
        "Remain=$b.RemainingCapacity; Volt=$b.Voltage; DesignVolt=$n.DesignVoltage; "
        "Name=$n.Name; Device=$n.DeviceID"
        "} | ConvertTo-Json -Compress"
    )
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            timeout=8,
            creationflags=CREATE_NO_WINDOW,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return empty
    if not raw:
        return empty
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return empty
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return empty
    name = str(data.get("Name") or data.get("Device") or "").strip()
    designed = _int(data, "Designed")
    full = _int(data, "Full")
    remain = _int(data, "Remain")
    volt = _int(data, "Volt") or _int(data, "DesignVolt")
    wear = None
    if designed and full:
        wear = max(0.0, min(100.0, 100.0 * (1.0 - full / designed)))
    return BattExtra(wear, name, designed, full, remain, volt)
