"""Safety Guard: the only gate in front of the executor.

Rule items must live inside a root declared by their own rule. Analyzer items (duplicates, large
files, ...) must live inside a folder the user chose to scan and outside hard-blocked system
locations. Junction/symlink escapes are rejected by comparing real paths.

Independent of the rule, these are NEVER touched (on any machine, with any rule):
  * Windows event and tracing logs (.evtx / .evt / .etl) and the System32 / WinSxS trees
  * corporate security, monitoring and device-management software and the data/logs they keep
    (EDR, antivirus, VPN/ZTNA agents, Intune, SCCM, Splunk, Sysmon, ...)
  * anything the administrator or user adds to protected.json or the LavatiCleaner group policy key
"""
from __future__ import annotations

import json
import os
import re
import string

ANALYZER_PREFIX = "analyzer:"
PROTECTED_WHY = "Protected: security, audit or management data"

# Rules that touch Windows servicing, diagnostics or crash/log data that IT teams rely on. They are
# switched off (shown as "Managed") on a PC that looks managed by an organisation.
MANAGED_LOCKED_RULES = {"windows_temp", "windows_update", "delivery_optimization", "prefetch", "old_logs",
                        "wer", "crash_dumps", "memory_dumps", "chkdsk_frag", "font_cache", "dns_cache"}

# Matched as substrings of the lower-cased path.
PROTECTED_TOKENS = (
    "crowdstrike", "csagent", "sentinelone", "sentinelagent", "carbonblack", "carbon black", "cbdefense",
    "cylance", "sophos", "symantec", "mcafee", "trellix", "trendmicro", "trend micro", "kaspersky",
    "bitdefender", "paloalto", "palo alto", "cortex xdr", "cisco", "anyconnect",
    "zscaler", "forcepoint", "netskope", "tanium", "splunk", "nessus", "tenable", "qualys", "rapid7",
    "osquery", "sysmon", "elastic-agent", "winlogbeat", "filebeat", "nxlog", "intunemanagementextension",
    "microsoft intune", "microsoft endpoint", "windows defender", "mdatp", "mssense", "bigfix", "ivanti",
    "manageengine", "lansweeper", "airwatch", "workspace one", "citrix", "forescout", "proofpoint",
    "mimecast", "digital guardian", "digitalguardian", "okta", "duo security", "beyondtrust", "cyberark",
    "crowdstrike falcon", "globalprotect", "fortinet", "forticlient", "check point",
    "pulse secure", "ivanti secure", "endpoint security",
)
PROTECTED_COMPONENTS = {"ccm", "ccmcache", "ccmsetup", "winevt", "logfiles", "winsxs", "system32", "syswow64"}
PROTECTED_SUFFIXES = (".evtx", ".evt", ".etl")
_TOKEN_RE = re.compile("|".join(re.escape(t) for t in sorted(PROTECTED_TOKENS, key=len, reverse=True)))


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def _env(name):
    v = os.environ.get(name)
    return _norm(v) if v else None


def hard_block_paths() -> list[str]:
    vals = [_env("SystemRoot"), _env("ProgramFiles"), _env("ProgramFiles(x86)"), _env("ProgramW6432")]
    return sorted({v for v in vals if v})


def protected_user_folders() -> list[str]:
    """Analyzers may *list* files here but must never auto-select them."""
    from .paths import known_folder
    home = os.path.expanduser("~")
    out = {_norm(known_folder(n)) for n in ("Documents", "Desktop", "Pictures")}
    bases = [home]
    one = os.environ.get("OneDrive")
    if one:
        bases.append(one)
    for b in bases:
        for n in ("Documents", "Desktop", "Pictures"):
            out.add(_norm(os.path.join(b, n)))
    return sorted(out)


def forbidden_exact() -> set[str]:
    s = set()
    for letter in string.ascii_uppercase:
        s.add(_norm(f"{letter}:\\"))
    for v in ("USERPROFILE", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData",
              "LOCALAPPDATA", "APPDATA", "SystemDrive"):
        e = _env(v)
        if e:
            s.add(e)
    s.add(_norm(os.path.expanduser("~")))
    s.update(protected_user_folders())
    return s


def protected_prefixes() -> list[str]:
    root, pd = os.environ.get("SystemRoot"), os.environ.get("ProgramData")
    out = []
    if root:
        out += [os.path.join(root, p) for p in ("System32", "SysWOW64", "WinSxS", "CCM", "ccmcache", "ccmsetup")]
    if pd:
        out += [os.path.join(pd, "Microsoft", p) for p in
                ("Windows Defender", "Windows Defender Advanced Threat Protection", "IntuneManagementExtension",
                 "Windows Security Health")]
    return [_norm(p) for p in out]


def _policy_values() -> list[str]:
    """Paths an administrator protects through HKLM\\SOFTWARE\\Policies\\LavatiCleaner\\ProtectedPaths."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\LavatiCleaner") as k:
            val, typ = winreg.QueryValueEx(k, "ProtectedPaths")
            return [v for v in (val if typ == winreg.REG_MULTI_SZ else [val]) if isinstance(v, str)]
    except Exception:
        return []


def load_extra_protected(*json_paths) -> tuple[list[str], list[str]]:
    """(paths, tokens) from protected.json files + group policy. Bad files are ignored, never fatal."""
    paths, tokens = [], []
    for jp in json_paths:
        try:
            with open(jp, encoding="utf-8") as fh:
                d = json.load(fh)
            paths += [str(p) for p in d.get("paths", [])]
            tokens += [str(t).lower() for t in d.get("tokens", []) if str(t).strip()]
        except (OSError, ValueError, AttributeError):
            continue
    paths += _policy_values()
    return [_norm(os.path.expandvars(p)) for p in paths if p.strip() and "%" not in os.path.expandvars(p)], tokens


class SafetyGuard:
    def __init__(self, extra_json_paths=()):
        self._roots: dict[str, list[tuple[str, str]]] = {}   # id -> [(lexical, real)]
        self._real_parent_cache: dict[str, str] = {}
        self._forbidden = forbidden_exact()
        self._hard_block = hard_block_paths()
        self._prefixes = protected_prefixes()
        extra_paths, extra_tokens = load_extra_protected(*extra_json_paths)
        self._extra_prefixes = extra_paths
        self._extra_re = re.compile("|".join(re.escape(t) for t in extra_tokens)) if extra_tokens else None
        self.protected = protected_user_folders()

    # -- configuration -------------------------------------------------
    def register(self, key: str, roots, strict: bool = True) -> list[str]:
        """Register allowed roots for a rule / analyzer. Returns roots refused as too broad.

        Rules are strict: a root may not be a protected location itself nor contain one (so "C:\\Users"
        is refused). Analyzers pass strict=False: the user picks the folder and individual items are
        still checked.
        """
        ok, refused = [], []
        for r in roots:
            n = _norm(r)
            if strict and (n in self._forbidden or self._contains_forbidden(n) or self.protected_reason(n)):
                refused.append(r)
                continue
            ok.append((n, os.path.normcase(os.path.realpath(r))))
        self._roots[key] = ok
        return refused

    def _contains_forbidden(self, n: str) -> bool:
        return any(f != n and _under(f, n) for f in self._forbidden) or any(_under(p, n) for p in self._prefixes)

    def is_protected(self, path: str) -> bool:
        n = _norm(path)
        return any(_under(n, p) for p in self.protected)

    def protected_reason(self, n: str) -> str:
        """Non-empty when `n` (already normalised) must never be touched."""
        if n.endswith(PROTECTED_SUFFIXES):
            return PROTECTED_WHY
        if any(_under(n, p) for p in self._prefixes) or any(_under(n, p) for p in self._extra_prefixes):
            return PROTECTED_WHY
        if not PROTECTED_COMPONENTS.isdisjoint(n.split(os.sep)):
            return PROTECTED_WHY
        if _TOKEN_RE.search(n) or (self._extra_re and self._extra_re.search(n)):
            return PROTECTED_WHY
        return ""

    # -- the gate ------------------------------------------------------
    def check(self, path: str, key: str, fresh: bool = False) -> tuple[bool, str]:
        """fresh=True re-resolves the parent folder instead of trusting the cache (used right before a
        real delete, so a link swapped in after the scan is noticed)."""
        n = _norm(path)
        if n in self._forbidden:
            return False, "Protected location"
        why = self.protected_reason(n)
        if why:
            return False, why
        roots = self._roots.get(key)
        if not roots:
            return False, "No allowed root registered"
        if key.startswith(ANALYZER_PREFIX) and any(_under(n, b) for b in self._hard_block):
            return False, "System location (blocked)"
        if not any(_under(n, lex) for lex, _ in roots):
            return False, "Outside the allowed folders"
        if any(n == lex for lex, _ in roots):
            return True, ""        # the root itself is an explicit file target (e.g. MEMORY.DMP)
        parent = os.path.dirname(n)
        real = None if fresh else self._real_parent_cache.get(parent)
        if real is None:
            real = os.path.normcase(os.path.realpath(parent))
            self._real_parent_cache[parent] = real
        if not any(_under(real, rr) for _, rr in roots):
            return False, "Path resolves outside the allowed folders (link)"
        why = self.protected_reason(real + os.sep)
        if why:
            return False, why
        return True, ""

    def filter_items(self, key: str, items) -> tuple[list, int]:
        """Drop items the guard would refuse, so the plan the user sees is the plan that runs."""
        keep, dropped = [], 0
        for it in items:
            if it.path.startswith("::") or self.check(it.path, key)[0]:
                keep.append(it)
            else:
                dropped += 1
        return keep, dropped
