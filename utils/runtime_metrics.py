"""Small, dependency-free process telemetry helpers.

The production container is Linux, so ``/proc/self/statm`` gives current RSS
without importing a monitoring SDK.  Platform fallbacks keep local development
and tests useful while ensuring telemetry can never expose configuration.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any


logger = logging.getLogger(__name__)


def process_rss_mb() -> float | None:
    """Return current process resident memory in MiB when available."""
    try:
        with open("/proc/self/statm", encoding="ascii") as statm:
            resident_pages = int(statm.read().split()[1])
        return round(resident_pages * os.sysconf("SC_PAGE_SIZE") / 1048576, 1)
    except (FileNotFoundError, AttributeError, IndexError, OSError, ValueError):
        pass

    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class _MemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = _MemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            get_current_process = ctypes.windll.kernel32.GetCurrentProcess
            get_current_process.restype = wintypes.HANDLE
            get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
            get_process_memory_info.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(_MemoryCounters),
                wintypes.DWORD,
            ]
            handle = get_current_process()
            ok = get_process_memory_info(
                handle, ctypes.byref(counters), counters.cb
            )
            if ok:
                return round(counters.WorkingSetSize / 1048576, 1)
        except (AttributeError, OSError, ValueError):
            pass

    try:
        import resource

        maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1048576 if sys.platform == "darwin" else 1024
        return round(maximum_rss / divisor, 1)
    except (ImportError, OSError, ValueError):
        return None


def log_runtime_memory(event: str, *, level: int = logging.INFO, **context: Any) -> None:
    """Emit safe process-memory telemetry with controlled caller context."""
    payload = {"event": event, "rss_mb": process_rss_mb(), **context}
    logger.log(level, "runtime_memory %s", json.dumps(payload, default=str, sort_keys=True))
