"""Drive listing and optimisation through Windows' own storage optimizer (defrag.exe).

Design rules:
  * SSDs are never defragmented. For them the optimizer's /O mode sends TRIM (retrim) instead.
  * Only fixed local drives are offered. Nothing here touches files or the registry.
  * defrag.exe needs administrator rights; the caller checks that first (this app never self-elevates).
  * defrag reports many failures as text with an error code (0x8900....) while still exiting 0, so the
    output is inspected, not just the exit code.
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import string
import subprocess
import threading
from ctypes import wintypes
from dataclasses import dataclass

CREATE_NO_WINDOW = 0x08000000
IS_WINDOWS = os.name == "nt"

KNOWN_ERRORS = {
    "0x89000024": "Administrator rights are required.",
    "0x89000008": "This drive cannot be optimized (for example it is locked, read-only or not NTFS/ReFS).",
    "0x89000010": "The drive is busy or being used by another optimization.",
    "0x8900002a": "The drive is locked (BitLocker) or unavailable.",
}


@dataclass
class Drive:
    letter: str
    label: str
    fs: str
    total: int
    free: int
    kind: str          # "ssd" | "hdd" | "unknown"

    @property
    def used(self) -> int:
        return self.total - self.free

    @property
    def can_defrag(self) -> bool:
        return self.kind == "hdd"


class _Query(ctypes.Structure):
    _fields_ = [("PropertyId", ctypes.c_int), ("QueryType", ctypes.c_int), ("Extra", ctypes.c_ubyte * 1)]


class _SeekPenalty(ctypes.Structure):
    _fields_ = [("Version", wintypes.DWORD), ("Size", wintypes.DWORD), ("IncursSeekPenalty", ctypes.c_ubyte)]


def drive_kind(letter: str) -> str:
    """'ssd' when the drive reports no seek penalty, 'hdd' when it does, 'unknown' if it cannot be asked.
    Works without administrator rights (the volume is opened with no access, only to query a property)."""
    if not IS_WINDOWS or len(letter) != 1:
        return "unknown"
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        h = k32.CreateFileW(f"\\\\.\\{letter.upper()}:", 0, 3, None, 3, 0, None)
        if h in (None, wintypes.HANDLE(-1).value):
            return "unknown"
        try:
            q = _Query(7, 0)                     # StorageDeviceSeekPenaltyProperty, standard query
            out, got = _SeekPenalty(), wintypes.DWORD()
            ok = k32.DeviceIoControl(h, 0x2D1400, ctypes.byref(q), ctypes.sizeof(q), ctypes.byref(out),
                                     ctypes.sizeof(out), ctypes.byref(got), None)
            if not ok:
                return "unknown"
            return "hdd" if out.IncursSeekPenalty else "ssd"
        finally:
            k32.CloseHandle(h)
    except Exception:
        return "unknown"


def list_drives() -> list[Drive]:
    """Fixed local drives only (no network, removable or optical drives)."""
    if not IS_WINDOWS:
        return []
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = f"{letter}:\\"
        if k32.GetDriveTypeW(root) != 3:         # DRIVE_FIXED
            continue
        label, fs = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
        if not k32.GetVolumeInformationW(root, label, 261, None, None, None, fs, 261):
            continue                              # not ready / locked
        try:
            du = shutil.disk_usage(root)
        except OSError:
            continue
        out.append(Drive(letter, label.value, fs.value, du.total, du.free, drive_kind(letter)))
    return out


def defrag_exe() -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "defrag.exe")


def parse_fragmentation(text: str):
    """Percent fragmented from an analysis report, or None if the (possibly localised) text has no match."""
    m = re.search(r"(?i)total fragmented space\s*=\s*(\d+)\s*%", text) or re.search(r"(?i)(\d+)\s*%\s*fragmented", text)
    return int(m.group(1)) if m else None


def find_error(text: str) -> str:
    """'' when the output shows no failure, otherwise a readable reason."""
    m = re.search(r"\((0x8[0-9a-fA-F]{7})\)", text)
    if not m:
        return ""
    code = m.group(1).lower()
    return KNOWN_ERRORS.get(code, f"The storage optimizer reported error {code}.")


def run_defrag(letter: str, mode: str, on_line=None, cancel: threading.Event | None = None, exe: str | None = None,
               extra_args=None) -> tuple[bool, str, str]:
    """mode: 'analyze' or 'optimize'. Returns (ok, error_reason, full_output).

    optimize uses /O: Windows picks the right action for the media (defragment a hard disk, retrim an SSD).
    `exe` / `extra_args` exist so tests can substitute a harmless program."""
    letter = letter.upper()
    if not re.fullmatch(r"[A-Z]", letter):
        return False, "Invalid drive letter.", ""
    if exe is None:
        args = [defrag_exe(), f"{letter}:"] + (["/A", "/V"] if mode == "analyze" else ["/O", "/U"])
    else:
        args = [exe] + list(extra_args or [])
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="oem"
                            if IS_WINDOWS else "utf-8", errors="replace", creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0)
    stop = threading.Event()

    def watcher():
        while not stop.is_set():
            if cancel is not None and cancel.is_set():
                # kill the whole tree: a child process would otherwise keep the output pipe open
                kill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
                try:
                    subprocess.run([kill, "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                                   creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0, timeout=15)
                except Exception:
                    proc.kill()
                return
            stop.wait(0.2)
    t = threading.Thread(target=watcher, daemon=True)
    t.start()
    lines = []
    try:
        for line in proc.stdout:
            lines.append(line)
            if on_line:
                on_line(line)
        proc.wait()
    finally:
        stop.set()
        proc.stdout.close()
    text = "".join(lines)
    if cancel is not None and cancel.is_set():
        return False, "Cancelled.", text
    err = find_error(text)
    if err:
        return False, err, text
    if proc.returncode not in (0, None):
        return False, f"The storage optimizer exited with code {proc.returncode}.", text
    return True, "", text
