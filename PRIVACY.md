# Privacy

Lavati Cleaner works entirely on your PC.

- **No network access.** The app makes no network connections: no telemetry, no analytics, no update
  check, no crash upload.
- **What is stored, and where** (all under your own account, `%LOCALAPPDATA%\LavatiCleaner`):
  - `history.db`: a record of each scan/clean run (time, counts, sizes, skipped file paths and reasons) and
    your settings.
  - `Quarantine\`: files you chose to remove that were not plain rebuildable caches, kept for the number of
    days you set (default 7), then deleted.
  - `app.log`: a small, size-capped log of events and errors. It does not contain file contents.
- **Uninstall** offers to delete all of the above.
- **Elevation.** The app never asks for administrator rights by itself.
