# Lavati Cleaner

A safe, transparent Windows cleaner. It finds temporary files, browser and developer caches, crash dumps,
duplicates and large forgotten files, shows exactly what it found, and removes only what you approve.

- **Scan, plan, preview, execute, report.** Nothing is deleted blindly; the first clean is a dry run.
- **Reversible.** Anything that is not a rebuildable cache goes to a quarantine you can restore from.
- **Careful on work PCs.** Security/management software, Windows event and tracing logs, and system folders
  are never touched. Managed PCs get extra locks. See [SECURITY.md](SECURITY.md).
- **Private.** No network access, no telemetry. See [PRIVACY.md](PRIVACY.md).
- **No registry cleaner**, on purpose.
- Light and dark themes. Rules are plain JSON in [`rules/`](rules).

## Run from source
Python 3.11+ on Windows, standard library only:

    python main.py
    python -m unittest discover -s tests

## Build the installer
`build.bat` runs the tests, builds with PyInstaller and, if [Inno Setup 6](https://jrsoftware.org/isdl.php)
is installed, produces `dist\LavatiCleaner-Setup.exe`. To sign it, set `SIGN_CERT_SHA1` (see
`tools/sign.ps1`).

## Safety note
Cleaning tools can delete files you care about. Review the preview, keep backups of valuable data, and read
[SECURITY.md](SECURITY.md) for exactly what is protected.

## License
[MIT](LICENSE.txt). Third-party components: [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt).
