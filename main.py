"""LavatiCleaner entry point."""
import ctypes
import logging
import logging.handlers
import os
import sys

if __name__ == "__main__" and not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lavaticleaner.core.paths import data_dir  # noqa: E402


def main() -> None:
    # Local, size-capped log. It records events (scan/clean results, errors), not file contents,
    # and nothing is ever sent anywhere: the app makes no network connections.
    handler = logging.handlers.RotatingFileHandler(os.path.join(data_dir(), "app.log"), maxBytes=512 * 1024,
                                                   backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    from lavaticleaner.ui.app import App
    App().mainloop()


if __name__ == "__main__":
    main()
