"""Machine facts for model suggestions (standard library only)."""

from __future__ import annotations

import ctypes
import os
import sys

HEADROOM = 4 * 1024**3  # OS, browser and Proposal Studio itself


def total_ram_bytes() -> int | None:
    """Physical memory in bytes, or None if it can't be read."""
    try:
        if sys.platform == "win32":

            class MemoryStatus(ctypes.Structure):
                _fields_ = [  # noqa: RUF012 - ctypes layout
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
                return int(status.ullTotalPhys)
            return None
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def model_budget(ram: int | None) -> int | None:
    """Bytes a model may use: total RAM minus headroom (None if RAM is unknown)."""
    return None if ram is None else max(ram - HEADROOM, 0)
