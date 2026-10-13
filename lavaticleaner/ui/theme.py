"""Dark theme: colours, bundled fonts, ttk styling and formatting helpers."""
from __future__ import annotations

import ctypes
import glob
import os
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ..core.paths import app_root

# Palettes. apply() copies one into this module's globals, so widgets read theme.CARD etc. at build time.
DARK = dict(
    BG="#0b0d10", CONTENT="#14161b", SIDEBAR="#0f1114", CARD="#1b1e24", CARD_HI="#22262d", BORDER="#2a2e36",
    TRACK="#262a31", TEXT="#eceef1", MUTED="#8d94a1", FAINT="#5f6672",
    AMBER="#f5a31f", AMBER_HI="#ffb73d", AMBER_DIM="#3a2f17", AMBER_OFF="#6b5120", AMBER_OFF_FG="#a8925f",
    GREEN="#34d399", GREEN_BG="#143129", OK_BG="#1d3b33", RED="#f87171", RED_BG="#3d2124", RED_BORDER="#6b2f33",
    WARN_BG="#2a2213", WARN_BORDER="#5a4a22", BLUE="#6ba6ff", INK="#1a1305", TITLEBAR_DARK=True,
)
LIGHT = dict(
    BG="#e9e7e0", CONTENT="#f6f5f1", SIDEBAR="#eeede7", CARD="#ffffff", CARD_HI="#f0efe9", BORDER="#dcdad1",
    TRACK="#e3e1d8", TEXT="#1d1e21", MUTED="#656b77", FAINT="#9a9fa8",
    AMBER="#cf7f00", AMBER_HI="#e58f10", AMBER_DIM="#fbeccb", AMBER_OFF="#efd9a8", AMBER_OFF_FG="#a58a4e",
    GREEN="#12805a", GREEN_BG="#d9f2e6", OK_BG="#d9f2e6", RED="#c23b3b", RED_BG="#fbe1e1", RED_BORDER="#e8b4b4",
    WARN_BG="#fdf3dc", WARN_BORDER="#ecd29a", BLUE="#2f78e0", INK="#1a1305", TITLEBAR_DARK=False,
)
MODE = "dark"


def system_mode() -> str:
    """'light' or 'dark' following the Windows app setting."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
    except Exception:
        return "dark"


def apply(mode: str) -> str:
    """mode: 'system' | 'light' | 'dark'. Returns the palette actually used."""
    global MODE, RISK_FG, RISK_BG
    eff = system_mode() if mode == "system" else ("light" if mode == "light" else "dark")
    globals().update(LIGHT if eff == "light" else DARK)
    MODE = eff
    RISK_FG = {"safe": GREEN, "review": AMBER, "advanced": RED}
    RISK_BG = {"safe": GREEN_BG, "review": AMBER_DIM, "advanced": RED_BG}
    return eff


RISK_LABEL = {"safe": "Safe", "review": "Review", "advanced": "Advanced"}
SEGMENTS = ["#6ba6ff", "#34d399", "#b69cf7", "#f5b942", "#ff8a7a", "#7fd6e0", "#c8d65a", "#e58fc2"]

_UI, _MONO = "Segoe UI", "Consolas"
apply("dark")


def load_fonts() -> None:
    """Register the bundled IBM Plex Sans / JetBrains Mono for this process (Windows only)."""
    if os.name != "nt":
        return
    add = ctypes.windll.gdi32.AddFontResourceExW
    for f in glob.glob(os.path.join(app_root(), "fonts", "*.ttf")):
        add(f, 0x10, 0)          # FR_PRIVATE


def init_fonts(root) -> None:
    global _UI, _MONO
    fams = set(tkfont.families(root))
    _UI = next((f for f in ("IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI") if f in fams), "TkDefaultFont")
    _MONO = next((f for f in ("JetBrains Mono", "Cascadia Mono", "Consolas") if f in fams), "TkFixedFont")


def F(size=10, bold=False):
    return (_UI, size, "bold") if bold else (_UI, size)


def M(size=10, bold=False):
    return (_MONO, size, "bold") if bold else (_MONO, size)


ICONS = "Segoe MDL2 Assets"


def icon(size=14):
    return (ICONS, size)


def dark_titlebar(win) -> None:
    """Ask Windows for a dark caption bar (Win10 1809+ / Win11). Silently ignored elsewhere."""
    if os.name != "nt":
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1 if TITLEBAR_DARK else 0)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4)
    except Exception:
        pass


def fmt_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(n)} B"
            if unit in ("GB", "TB"):
                return f"{n:.2f} {unit}"
            return f"{n:.0f} {unit}" if n >= 100 else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


def size_parts(n: float) -> tuple[str, str]:
    s = fmt_size(n)
    num, unit = s.rsplit(" ", 1)
    return num, unit


def fmt_time(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def fmt_date(ts: float) -> str:
    return time.strftime("%d %b %Y", time.localtime(ts)).lstrip("0")


def fmt_count(n: int) -> str:
    return f"{n:,}"


def setup_style(root) -> None:
    root.configure(bg=BG)
    root.option_add("*TCombobox*Listbox.background", CARD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", AMBER_DIM)
    root.option_add("*TCombobox*Listbox.selectForeground", AMBER)
    root.option_add("*TCombobox*Listbox.font", F(10))
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", font=F(10), background=CONTENT, foreground=TEXT, bordercolor=BORDER)
    s.configure("TFrame", background=CONTENT)
    s.configure("TLabel", background=CONTENT, foreground=TEXT)
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=30,
                borderwidth=0, font=F(10))
    s.configure("Treeview.Heading", background=CARD_HI, foreground=MUTED, font=F(9, True), relief="flat",
                borderwidth=0, padding=(8, 6))
    s.map("Treeview.Heading", background=[("active", CARD_HI)])
    s.map("Treeview", background=[("selected", AMBER_DIM)], foreground=[("selected", TEXT)])
    s.configure("TCombobox", fieldbackground=CARD, background=CARD_HI, foreground=TEXT, arrowcolor=MUTED,
                bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD, padding=6)
    s.map("TCombobox", fieldbackground=[("readonly", CARD)], foreground=[("readonly", TEXT)],
          background=[("active", CARD_HI)])
    s.configure("TSpinbox", fieldbackground=CARD, background=CARD_HI, foreground=TEXT, arrowcolor=MUTED,
                bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD, padding=4)
    s.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    s.configure("Vertical.TScrollbar", width=8, background=TRACK, troughcolor=CARD, bordercolor=CARD,
                lightcolor=TRACK, darkcolor=TRACK, relief="flat", borderwidth=0)
    s.map("Vertical.TScrollbar", background=[("active", FAINT)], lightcolor=[("active", FAINT)],
          darkcolor=[("active", FAINT)])
    s.configure("TProgressbar", troughcolor=TRACK, background=AMBER, bordercolor=TRACK,
                lightcolor=AMBER, darkcolor=AMBER, thickness=8)
    s.configure("TCheckbutton", background=CONTENT, foreground=TEXT, indicatorcolor=CARD,
                focuscolor=CONTENT)
    s.map("TCheckbutton", indicatorcolor=[("selected", AMBER)], background=[("active", CONTENT)])


def label(parent, text="", size=10, bold=False, fg=None, mono=False, bg=None, **kw):
    bg = bg or parent.cget("bg")
    fg = fg or TEXT          # read at call time so a theme switch takes effect
    return tk.Label(parent, text=text, font=M(size, bold) if mono else F(size, bold), fg=fg, bg=bg,
                    bd=0, highlightthickness=0, **kw)
