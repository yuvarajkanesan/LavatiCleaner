"""Thin Windows helpers (all degrade gracefully on other platforms)."""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000
IS_WINDOWS = sys.platform == "win32"


def _system_exe(name: str) -> str:
    """Absolute path of a System32 tool, so a planted copy earlier on PATH is never run."""
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", name)


def is_admin() -> bool:
    if not IS_WINDOWS:
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def running_processes() -> set[str]:
    """Lower-case image names of running processes."""
    if not IS_WINDOWS:
        return set()
    try:
        out = subprocess.run(
            [_system_exe("tasklist.exe"), "/fo", "csv", "/nh"], capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, timeout=15,
        ).stdout
    except Exception:
        return set()
    names = set()
    for line in out.splitlines():
        if line.startswith('"'):
            names.add(line.split('","')[0].strip('"').lower())
    return names


class _RBInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("i64Size", ctypes.c_int64), ("i64NumItems", ctypes.c_int64)]


def recycle_bin_info() -> tuple[int, int]:
    """(bytes, items) across all drives."""
    if not IS_WINDOWS:
        return 0, 0
    info = _RBInfo()
    info.cbSize = ctypes.sizeof(_RBInfo)
    try:
        if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
            return int(info.i64Size), int(info.i64NumItems)
    except Exception:
        pass
    return 0, 0


def empty_recycle_bin() -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "Recycle Bin is only available on Windows"
    flags = 0x1 | 0x2 | 0x4  # no confirmation, no progress UI, no sound
    try:
        rc = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags) & 0xFFFFFFFF
    except Exception as e:  # pragma: no cover
        return False, str(e)
    # S_OK, or E_UNEXPECTED (0x8000FFFF) which Windows returns when the bin is already empty
    if rc in (0, 0x8000FFFF):
        return True, ""
    return False, f"Windows error 0x{rc:08X}"


def show_in_explorer(path: str) -> None:
    if IS_WINDOWS:
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)], creationflags=CREATE_NO_WINDOW)
        except OSError:
            pass


def open_folder(path: str) -> None:
    if IS_WINDOWS:
        try:
            os.startfile(path)  # noqa: S606
        except OSError:
            pass


_EXE_NAME = re.compile(r"^[\w.\-]{1,64}\.exe$", re.I)


def close_process(exe: str) -> bool:
    """Ask a program to close politely (no /F). Only plain .exe names are accepted."""
    if not IS_WINDOWS or not _EXE_NAME.match(exe or ""):
        return False
    try:
        subprocess.run([_system_exe("taskkill.exe"), "/IM", exe], capture_output=True,
                       creationflags=CREATE_NO_WINDOW, timeout=20)
        return True
    except Exception:
        return False


# Image names of common corporate security / management agents (used only to *detect* a managed PC).
KNOWN_AGENTS = {
    "csfalconservice.exe", "csfalconcontainer.exe", "sentinelagent.exe", "sentinelservicehost.exe",
    "cbdefense.exe", "repmgr.exe", "cylancesvc.exe", "savservice.exe", "mcshield.exe", "masvc.exe",
    "ccsvchst.exe", "smc.exe", "tmbmsrv.exe", "ntrtscan.exe", "cyserver.exe", "zsatray.exe", "zsaservice.exe",
    "vpnagent.exe", "taniumclient.exe", "splunkd.exe", "ccmexec.exe", "mssense.exe", "sensecncproxy.exe",
    "osqueryd.exe", "sysmon.exe", "sysmon64.exe", "elastic-agent.exe", "winlogbeat.exe", "nxlog.exe",
    "filebeat.exe", "qualysagent.exe", "besclient.exe", "netskopeclient.exe", "agentexecutor.exe",
    "forticlient.exe", "pangpa.exe", "pangps.exe",
}


_BUILTIN_PROVIDERS = {"Local Authority", "Cloud Authority", "Deploy Authority"}


def _reg_read(root, path, name):
    import winreg
    with winreg.OpenKey(root, path) as k:
        return winreg.QueryValueEx(k, name)[0]


def managed_info(running=None) -> dict:
    """Does this PC look managed by an organisation? Reads only; never changes anything."""
    info = {"domain": False, "mdm": False, "aad": False, "agents": [], "policy_lock": False}
    if IS_WINDOWS:
        try:
            buf, typ = ctypes.c_wchar_p(), ctypes.c_int()
            if ctypes.windll.netapi32.NetGetJoinInformation(None, ctypes.byref(buf), ctypes.byref(typ)) == 0:
                info["domain"] = typ.value == 3          # NetSetupDomainName
                ctypes.windll.netapi32.NetApiBufferFree(buf)
        except Exception:
            pass
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Enrollments") as k:
                for i in range(winreg.QueryInfoKey(k)[0]):
                    try:
                        with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sk:
                            prov = winreg.QueryValueEx(sk, "ProviderID")[0]
                            if prov and prov not in _BUILTIN_PROVIDERS:     # Windows' own placeholders
                                info["mdm"] = True
                    except OSError:
                        continue
        except OSError:
            pass
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Control\CloudDomainJoin\JoinInfo") as k:
                info["aad"] = winreg.QueryInfoKey(k)[0] > 0
        except OSError:
            pass
        try:
            import winreg
            info["policy_lock"] = bool(_reg_read(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\LavatiCleaner",
                                                 "ProtectManagedPC"))
        except OSError:
            pass
    if running:
        info["agents"] = sorted(KNOWN_AGENTS & set(running))
    info["managed"] = info["domain"] or info["mdm"] or info["aad"] or bool(info["agents"]) or info["policy_lock"]
    return info


def open_file(path: str) -> None:
    """Open a bundled document with the default viewer (only files that exist)."""
    if IS_WINDOWS and os.path.isfile(path):
        os.startfile(path)  # noqa: S606 - fixed, app-bundled file names only
