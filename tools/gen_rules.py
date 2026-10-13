"""Generates rules/*.json (the cleaning catalog). Run:  python tools/gen_rules.py

Browsers share one shape, so they are built from tables here. The JSON it writes is the source of truth at
runtime; edit this script (not the JSON) for built-in rules, or add your own JSON next to the user data.

What is deliberately NOT here:
  * registry-based items (typed URLs, MRU lists, ...)   -> no registry cleaner, by design
  * Firefox history                                      -> places.sqlite also holds your bookmarks
  * Windows event logs, Defender / EDR / management data -> protected by the Safety Guard
  * workplace apps (Teams, Outlook, Slack, Zoom, OneDrive) -> corporate software is left alone
"""
import json
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules")
LA, RA = "%LOCALAPPDATA%", "%APPDATA%"
rules = []


def add(id, category, label, tab, paths, risk="safe", include=None, recursive=None, closed=None, admin=False,
        age=0, note="", action=None, dir_name=None, quarantine=None, prune=False):
    r = {"id": id, "category": category, "label": label, "tab": tab, "risk": risk, "paths": paths}
    if include:
        r["include"] = include
    if recursive is not None:
        r["recursive"] = recursive
    if closed:
        r["requires_closed"] = closed
    if admin:
        r["requires_admin"] = True
    if age:
        r["min_age_days"] = age
    if note:
        r["note"] = note
    if action:
        r["action"] = action
    if dir_name:
        r["dir_name"] = dir_name
    if quarantine is not None:
        r["quarantine"] = quarantine
    if prune:
        r["prune_empty"] = True
    rules.append(r)


NOTES = {
    "cache": "Temporary web files the browser rebuilds as you browse. Pages may load a little slower the first time afterwards.",
    "cookies": "Signs you out of websites and resets site preferences. Removed files go to quarantine, so you can restore them.",
    "history": "Clears the visited-pages list and top-site thumbnails. Bookmarks are not touched. Restorable from quarantine.",
    "session": "Forgets the tabs from your last session, so 'restore previous tabs' will have nothing to bring back.",
    "forms": "Removes saved autofill entries (names, addresses, cards saved in the browser). Restorable from quarantine.",
    "logins": "Removes passwords saved in this browser, so you must sign in again. Restorable from quarantine. "
              "Passwords synced to an account can return on the next sync.",
}

# ---- Chromium-family browsers -------------------------------------------------------------------------------
CHROMIUM = [
    # id prefix, group, tab, exe, profile roots, cache roots
    ("edge", "Edge Browser", "windows", "msedge.exe",
     [f"{LA}\\Microsoft\\Edge\\User Data\\*"], [f"{LA}\\Microsoft\\Edge\\User Data\\*"]),
    ("chrome", "Chrome Browser", "apps", "chrome.exe",
     [f"{LA}\\Google\\Chrome\\User Data\\*"], [f"{LA}\\Google\\Chrome\\User Data\\*"]),
    ("brave", "Brave Browser", "apps", "brave.exe",
     [f"{LA}\\BraveSoftware\\Brave-Browser\\User Data\\*"], [f"{LA}\\BraveSoftware\\Brave-Browser\\User Data\\*"]),
    ("vivaldi", "Vivaldi Browser", "apps", "vivaldi.exe",
     [f"{LA}\\Vivaldi\\User Data\\*"], [f"{LA}\\Vivaldi\\User Data\\*"]),
    ("opera", "Opera Browser", "apps", "opera.exe",
     [f"{RA}\\Opera Software\\Opera Stable", f"{RA}\\Opera Software\\Opera Stable\\Default"],
     [f"{LA}\\Opera Software\\Opera Stable", f"{LA}\\Opera Software\\Opera Stable\\Default"]),
]
for pre, group, tab, exe, prof, cache in CHROMIUM:
    sub = lambda roots, *tails: [r + ("\\" + t if t else "") for r in roots for t in tails]
    add(f"{pre}_cache", group, "Page & asset cache", tab, sub(cache, "Cache", "Code Cache", "GPUCache",
        "Service Worker\\CacheStorage"), closed=[exe], note=NOTES["cache"], quarantine=False)
    add(f"{pre}_cookies", group, "Cookies & site data", tab, sub(prof, "", "Network"), "review",
        ["Cookies", "Cookies-journal"], False, [exe], note=NOTES["cookies"])
    add(f"{pre}_history", group, "Browsing trail", tab, sub(prof, ""), "review",
        ["History", "History-journal", "Visited Links", "Top Sites", "Top Sites-journal", "Favicons",
         "Favicons-journal"], False, [exe], note=NOTES["history"])
    add(f"{pre}_session", group, "Last-session tabs", tab, sub(prof, "", "Sessions"), "review",
        ["Current Session", "Current Tabs", "Last Session", "Last Tabs", "Session_*", "Tabs_*"], False, [exe],
        note=NOTES["session"])
    add(f"{pre}_forms", group, "Autofill profiles", tab, sub(prof, ""), "advanced",
        ["Web Data", "Web Data-journal"], False, [exe], note=NOTES["forms"])
    add(f"{pre}_logins", group, "Stored sign-ins", tab, sub(prof, ""), "advanced",
        ["Login Data", "Login Data-journal", "Login Data For Account", "Login Data For Account-journal"], False,
        [exe], note=NOTES["logins"])

# ---- Firefox (no history item: places.sqlite also contains bookmarks) --------------------------------------
FF_R, FF_C = f"{RA}\\Mozilla\\Firefox\\Profiles\\*", f"{LA}\\Mozilla\\Firefox\\Profiles\\*"
G = "Firefox Browser"
add("firefox_cache", G, "Page & asset cache", "apps", [f"{FF_C}\\cache2", f"{FF_C}\\startupCache", f"{FF_C}\\thumbnails"],
    closed=["firefox.exe"], note=NOTES["cache"], quarantine=False)
add("firefox_cookies", G, "Cookies & site data", "apps", [FF_R], "review",
    ["cookies.sqlite", "cookies.sqlite-wal", "cookies.sqlite-shm"], False, ["firefox.exe"], note=NOTES["cookies"])
add("firefox_session", G, "Last-session tabs", "apps", [FF_R, f"{FF_R}\\sessionstore-backups"], "review",
    ["sessionstore.jsonlz4", "recovery.jsonlz4", "recovery.baklz4", "previous.jsonlz4", "upgrade.jsonlz4-*"], False,
    ["firefox.exe"], note=NOTES["session"])
add("firefox_forms", G, "Autofill profiles", "apps", [FF_R], "advanced",
    ["formhistory.sqlite", "formhistory.sqlite-wal", "formhistory.sqlite-shm"], False, ["firefox.exe"],
    note=NOTES["forms"])
add("firefox_logins", G, "Stored sign-ins", "apps", [FF_R], "advanced", ["logins.json", "key4.db", "logins-backup.json"],
    False, ["firefox.exe"], note=NOTES["logins"])

# ---- Windows tab: classic web engine -----------------------------------------------------------------------
G = "Classic Web Engine"
add("legacy_cache", G, "Legacy web cache", "windows", [f"{LA}\\Microsoft\\Windows\\INetCache"],
    note="Cache used by Internet Explorer mode and embedded web views. Rebuilt on demand.", quarantine=False)
add("legacy_cookies", G, "Legacy cookies", "windows", [f"{LA}\\Microsoft\\Windows\\INetCookies"], "review",
    note=NOTES["cookies"])
add("legacy_history", G, "Legacy visit list", "windows", [f"{LA}\\Microsoft\\Windows\\History"], "review",
    note=NOTES["history"])

# ---- Windows tab: File Explorer traces ---------------------------------------------------------------------
G = "File Explorer Traces"
add("recent_docs", G, "Recently opened shortcuts", "windows", [f"{RA}\\Microsoft\\Windows\\Recent"], include=["*.lnk"],
    recursive=False, note="The shortcuts behind Recent files lists. Your documents themselves are not touched.",
    quarantine=False)
add("jump_lists", G, "Taskbar jump lists", "windows",
    [f"{RA}\\Microsoft\\Windows\\Recent\\AutomaticDestinations", f"{RA}\\Microsoft\\Windows\\Recent\\CustomDestinations"],
    include=["*.automaticDestinations-ms", "*.customDestinations-ms"], recursive=False,
    note="Recent and pinned items shown when you right-click a taskbar icon. Pinned items are forgotten too.",
    quarantine=False)
add("thumbnails", G, "Thumbnail & icon cache", "windows", [f"{LA}\\Microsoft\\Windows\\Explorer"],
    include=["thumbcache_*.db", "iconcache_*.db"], recursive=False,
    note="Picture previews and icons Explorer rebuilds when needed.", quarantine=False)

# ---- Windows tab: housekeeping -----------------------------------------------------------------------------
G = "Windows Housekeeping"
add("recycle_bin", G, "Recycle Bin", "windows", [], action="recycle_bin",
    note="Empties the Recycle Bin on every drive. Its files cannot be restored afterwards.")
add("user_temp", G, "Personal temp files", "windows", ["%TEMP%"], age=1, quarantine=False, prune=True,
    note="Leftovers programs create in your temp folder. Files from the last day are left alone.")
add("windows_temp", G, "System temp files", "windows", ["%SystemRoot%\\Temp"], age=1, quarantine=False, prune=True,
    note="Files you cannot delete without administrator rights are skipped, never forced.")
add("clipboard", G, "Clipboard contents", "windows", [], action="clipboard",
    note="Clears whatever you last copied. Handy after copying a password.")
add("dns_cache", G, "Name-lookup cache", "windows", [], action="flush_dns",
    note="Flushes the DNS resolver cache. Needs administrator rights on some PCs.")
add("crash_dumps", G, "Application crash dumps", "windows", [f"{LA}\\CrashDumps"], quarantine=False,
    note="Diagnostic snapshots Windows saved when apps crashed.")
add("memory_dumps", G, "System memory dumps", "windows", ["%SystemRoot%\\Minidump", "%SystemRoot%\\MEMORY.DMP"],
    admin=True, quarantine=False, note="Large blue-screen snapshots. Keep them if you are chasing a crash.")
add("wer", G, "Error report archive", "windows",
    [f"{LA}\\Microsoft\\Windows\\WER", "%ProgramData%\\Microsoft\\Windows\\WER"], quarantine=False,
    note="Queued and archived Windows Error Reporting data.")
add("old_logs", G, "Servicing logs", "windows", ["%SystemRoot%\\Logs\\CBS", "%SystemRoot%\\Logs\\DISM"],
    include=["*.log", "*.cab"], age=30, admin=True, quarantine=False, note="Old Windows servicing logs.")
add("chkdsk_frag", G, "Disk-check fragments", "windows", ["%SystemDrive%\\found.*"], include=["*.chk"], admin=True,
    quarantine=False, note="File fragments chkdsk recovered (FILE0000.CHK). Check them before deleting if you lost data.")
add("store_cache", G, "Microsoft Store cache", "windows",
    [f"{LA}\\Packages\\Microsoft.WindowsStore_8wekyb3d8bbwe\\LocalCache"], quarantine=False,
    note="Downloaded store listings and images.")
add("shader_cache", G, "Graphics shader caches", "windows",
    [f"{LA}\\D3DSCache", f"{LA}\\NVIDIA\\DXCache", f"{LA}\\NVIDIA\\GLCache", f"{LA}\\AMD\\DxCache"], quarantine=False,
    note="Compiled GPU shaders. Games rebuild them, which can cause brief stutter on the next launch.")
add("font_cache", G, "Font cache", "windows", ["%SystemRoot%\\ServiceProfiles\\LocalService\\AppData\\Local\\FontCache"],
    include=["*.dat"], admin=True, recursive=False, quarantine=False, note="Windows rebuilds the font cache at next start.")

# ---- Windows tab: deep clean -------------------------------------------------------------------------------
G = "Deep Clean"
add("windows_update", G, "Update download cache", "windows", ["%SystemRoot%\\SoftwareDistribution\\Download"], "review",
    admin=True, quarantine=False, note="Windows re-downloads updates if needed. Do not clean while an update is pending.")
add("delivery_optimization", G, "Delivery Optimization cache", "windows",
    ["%SystemRoot%\\ServiceProfiles\\NetworkService\\AppData\\Local\\Microsoft\\Windows\\DeliveryOptimization\\Cache"],
    "review", admin=True, quarantine=False, note="Update pieces kept to share with other PCs. Rebuilt on demand.")
add("prefetch", G, "Launch-speed hints", "windows", ["%SystemRoot%\\Prefetch"], "review", ["*.pf"], False, admin=True,
    quarantine=False, note="Windows rebuilds these; the first launch of each app may be slightly slower.")

# ---- Applications tab --------------------------------------------------------------------------------------
G = "Office & Documents"
add("office_cache", G, "Office document cache", "apps", [f"{LA}\\Microsoft\\Office\\16.0\\OfficeFileCache"], quarantine=False,
    closed=["winword.exe", "excel.exe", "powerpnt.exe"], note="Temporary copies Office keeps of cloud documents.")
add("office_recent", G, "Office recent-file shortcuts", "apps", [f"{RA}\\Microsoft\\Office\\Recent"], include=["*.lnk"],
    recursive=False, quarantine=False, note="The shortcuts behind Office's recent lists. Your documents are not touched.")

G = "Media & Creative"
add("spotify_cache", G, "Streaming-music cache", "apps", [f"{LA}\\Spotify\\Data", f"{LA}\\Spotify\\Storage"],
    closed=["spotify.exe"], quarantine=False, note="Songs Spotify cached for offline-like playback. Downloads you made are kept in other files.")
add("vlc_art", G, "Player artwork cache", "apps", [f"{RA}\\vlc\\art"], quarantine=False, note="Album art VLC downloaded.")
add("adobe_media", G, "Adobe media cache", "apps",
    [f"{RA}\\Adobe\\Common\\Media Cache Files", f"{RA}\\Adobe\\Common\\Media Cache", f"{RA}\\Adobe\\Common\\Peak Files"],
    quarantine=False, note="Previews and conformed audio Premiere and After Effects rebuild.")

G = "Chat & Social"
add("discord_cache", G, "Chat app cache", "apps",
    [f"{RA}\\discord\\Cache", f"{RA}\\discord\\Code Cache", f"{RA}\\discord\\GPUCache"], closed=["discord.exe"],
    quarantine=False, note="Images and scripts Discord rebuilds.")
add("telegram_cache", G, "Messenger media cache", "apps",
    [f"{RA}\\Telegram Desktop\\tdata\\user_data\\cache", f"{RA}\\Telegram Desktop\\tdata\\user_data\\media_cache"],
    closed=["telegram.exe"], quarantine=False, note="Downloaded media Telegram can fetch again.")

G = "Gaming Platforms"
add("steam_web", G, "Store & overlay cache", "apps", [f"{LA}\\Steam\\htmlcache"], closed=["steam.exe", "steamwebhelper.exe"],
    quarantine=False, note="Web content shown inside Steam. Rebuilt on launch.")
add("epic_web", G, "Launcher web cache", "apps", [f"{LA}\\EpicGamesLauncher\\Saved\\webcache*", f"{LA}\\EpicGamesLauncher\\Saved\\Logs"],
    closed=["epicgameslauncher.exe"], quarantine=False, note="Web content and logs of the Epic launcher.")

G = "Developer Tools"
add("npm_cache", G, "npm package cache", "apps", [f"{LA}\\npm-cache", f"{RA}\\npm-cache"], "review", quarantine=False,
    note="Packages are re-downloaded when needed.")
add("pip_cache", G, "pip wheel cache", "apps", [f"{LA}\\pip\\Cache"], "review", quarantine=False,
    note="Python packages are re-downloaded when needed.")
add("nuget_cache", G, "NuGet HTTP cache", "apps", [f"{LA}\\NuGet\\v3-cache", f"{LA}\\NuGet\\plugins-cache"], "review",
    quarantine=False)
add("gradle_cache", G, "Gradle caches", "apps", ["%USERPROFILE%\\.gradle\\caches"], "review", closed=["java.exe"],
    quarantine=False, note="Dependencies are re-downloaded on the next build.")
add("maven_repo", G, "Maven local repository", "apps", ["%USERPROFILE%\\.m2\\repository"], "review", quarantine=False,
    note="Dependencies are re-downloaded on the next build.")
add("android_build_cache", G, "Android build cache", "apps",
    ["%USERPROFILE%\\.android\\build-cache", "%USERPROFILE%\\.android\\cache"], "review", quarantine=False)
add("vscode_cache", G, "Code editor caches", "apps",
    [f"{RA}\\Code\\Cache", f"{RA}\\Code\\CachedData", f"{RA}\\Code\\Code Cache", f"{RA}\\Code\\GPUCache"],
    closed=["code.exe"], quarantine=False, note="VS Code rebuilds these. Settings and extensions are untouched.")
add("jetbrains_cache", G, "JetBrains IDE caches", "apps", [f"{LA}\\JetBrains\\*\\caches"], "review", quarantine=False,
    closed=["idea64.exe", "pycharm64.exe", "webstorm64.exe", "rider64.exe"],
    note="Indexes the IDE rebuilds; the next start re-indexes your projects and can take a while.")
add("vs_cache", G, "Visual Studio component cache", "apps", [f"{LA}\\Microsoft\\VisualStudio\\*\\ComponentModelCache"],
    closed=["devenv.exe"], quarantine=False, note="Rebuilt the next time Visual Studio starts.")
add("pycache", G, "Python bytecode caches", "apps",
    ["%USERPROFILE%\\source", "%USERPROFILE%\\projects", "%USERPROFILE%\\dev", "%USERPROFILE%\\code",
     "%USERPROFILE%\\Documents\\GitHub"], include=["*.pyc", "*.pyo"], dir_name="__pycache__", quarantine=False,
    note="Compiled Python files created next to your code.")

G = "Utilities & Installers"
add("old_installers", G, "Old installers in Downloads", "apps", ["%USERPROFILE%\\Downloads"], "review",
    ["*.exe", "*.msi", "*.msix", "*.iso"], False, age=60,
    note="Setup files older than 60 days. Moved to quarantine, so you can restore them for 7 days.")


def write():
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)), "duplicate rule ids"
    for f in os.listdir(OUT):
        if f.endswith(".json"):
            os.remove(os.path.join(OUT, f))
    parts = {"windows.json": [r for r in rules if r["tab"] == "windows"],
             "applications.json": [r for r in rules if r["tab"] == "apps"]}
    for name, rs in parts.items():
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
            json.dump({"rules": rs}, fh, indent=1)
            fh.write("\n")
    print(f"{len(rules)} rules in {len({r['category'] for r in rules})} groups")


if __name__ == "__main__":
    write()
