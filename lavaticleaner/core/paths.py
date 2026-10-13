"""Filesystem locations used by the app."""
from __future__ import annotations

import os
import sys

from .. import APP_NAME


def app_root() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rules_dir() -> str:
    return os.path.join(app_root(), "rules")


def data_dir() -> str:
    base = os.environ.get("LAVATI_DATA_DIR")
    if not base:
        base = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP_NAME)
    os.makedirs(base, exist_ok=True)
    return base


def user_rules_dir() -> str:
    return os.path.join(data_dir(), "rules")


def quarantine_dir() -> str:
    """Per-user on purpose: a folder shared between accounts (e.g. ProgramData) would let another local
    user tamper with a manifest and steer where restored files land."""
    override = os.environ.get("LAVATI_QUARANTINE_DIR")
    path = override or os.path.join(data_dir(), "Quarantine")
    os.makedirs(path, exist_ok=True)
    return path


_KNOWN = {
    "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "Pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "Videos": "18989B1D-99B5-42FB-8BA3-6E8F5CAF8F5F",
}


def known_folder(name: str) -> str:
    """Real location of a user folder (it may be redirected to OneDrive or another drive)."""
    home = os.path.expanduser("~")
    fallback = os.path.join(home, name)
    if os.name != "nt" or name not in _KNOWN:
        return fallback
    try:
        import ctypes
        import uuid
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

        u = uuid.UUID(_KNOWN[name])
        g = GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        ptr = ctypes.c_wchar_p()
        fn = ctypes.windll.shell32.SHGetKnownFolderPath
        fn.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        if fn(ctypes.byref(g), 0, None, ctypes.byref(ptr)) == 0 and ptr.value:
            path = ptr.value
            ctypes.windll.ole32.CoTaskMemFree(ptr)
            return path
    except Exception:
        pass
    return fallback


def user_folders() -> list[str]:
    """Default folders searched by the duplicate / large-file analyzers."""
    out = []
    for n in ("Downloads", "Documents", "Desktop", "Pictures", "Videos"):
        p = known_folder(n)
        if os.path.isdir(p) and p not in out:
            out.append(p)
    return out
