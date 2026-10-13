"""LavatiCleaner entry point."""
import ctypes
import logging
import logging.handlers
import os
import sys

if __name__ == "__main__" and not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lavaticleaner.core.paths import data_dir  # noqa: E402


def selftest() -> int:
    """Used by build.bat on the packaged exe: proves bundled data, Tk, SQLite and hashing all work."""
    import hashlib
    import tempfile
    os.environ["LAVATI_DATA_DIR"] = tempfile.mkdtemp()
    hashlib.blake2b(b"x").hexdigest()
    from lavaticleaner.core.analyzers import find_duplicates
    from lavaticleaner.core.paths import rules_dir
    from lavaticleaner.core.rules import load_rules
    rules, errors = load_rules(rules_dir())
    assert rules and not errors, errors
    d = tempfile.mkdtemp()
    for n in ("a", "b"):
        with open(os.path.join(d, n), "wb") as fh:
            fh.write(b"z" * 4096)
    assert len(find_duplicates([d], 1024)) == 1
    from lavaticleaner.ui.app import App
    app = App()
    app.update()
    app.destroy()
    return 0


def main() -> None:
    if "--selftest" in sys.argv:
        try:
            sys.exit(selftest())
        except Exception:
            sys.exit(1)
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
