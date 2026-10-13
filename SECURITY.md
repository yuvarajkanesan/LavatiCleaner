# Security model

## What the app will never touch
Enforced by one gate (`lavaticleaner/core/safety.py`) that every delete passes, whatever rule or tool
produced it:

- Windows event and tracing logs (`.evtx`, `.evt`, `.etl`), and the System32, SysWOW64 and WinSxS trees.
- Corporate security, monitoring and device-management software and their data/logs: EDR/antivirus agents,
  VPN/ZTNA clients, Intune, SCCM/ConfigMgr, Splunk, Sysmon, Defender, and similar (see `PROTECTED_TOKENS`).
- Drive roots, your profile folder, Program Files, ProgramData, and your Documents/Desktop/Pictures
  (finders may list files there, but nothing there is ever pre-selected).
- Anything reached through a junction or symlink: links are never followed, and the real path is re-checked
  immediately before each delete.
- Files in use by another program (skipped, never force-closed).

## Managed (corporate) PCs
If the PC is domain-joined, cloud-joined, MDM-enrolled or runs known security agents, Windows servicing,
diagnostic, log and crash-dump rules are switched off ("Managed"). Administrators can enforce this and add
protected locations:

- Registry (HKLM), `SOFTWARE\Policies\LavatiCleaner`:
  - `ProtectManagedPC` (DWORD, 1): users cannot turn the managed-PC protection off.
  - `ProtectedPaths` (REG_MULTI_SZ): extra folders that are never touched.
- `protected.json` in `%LOCALAPPDATA%\LavatiCleaner` or `%ProgramData%\LavatiCleaner`:
  `{"paths": ["D:\\CorpData"], "tokens": ["acmeagent"]}`

## Reversibility
Plan, preview and confirm before anything runs. The first clean is a dry run. Review-level items and files
found by the finders go to a per-user quarantine and can be restored. The quarantine manifest is treated as
untrusted: IDs are validated and restores never land in system or protected folders, behind links, or on
network paths, and never overwrite existing files.

## Other hardening
- No network, no registry cleaner, no self-elevation, no code or rules downloaded at runtime.
- External tools (`tasklist`, `taskkill`) are called by absolute System32 path.
- User rule files can only point inside folders the guard accepts; overly broad roots are refused.

## Reporting a vulnerability
Please email the publisher (see the installer / About details) rather than opening a public issue.
