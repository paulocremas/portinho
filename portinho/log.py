"""Registro em arquivo (para diagnosticar problemas no computador do usuário)."""
import logging
import logging.handlers
import os
import sys


def log_dir():
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    d = os.path.join(base, "Portinho")
    os.makedirs(d, exist_ok=True)
    return d


LOG_PATH = os.path.join(log_dir(), "portinho.log")
log = logging.getLogger("portinho")
if not log.handlers:
    log.setLevel(logging.DEBUG)
    try:
        h = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=2_000_000, backupCount=1, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    except OSError:
        log.addHandler(logging.NullHandler())


def tail(n=40):
    try:
        with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return ""


class YdlLogger:
    """Manda as mensagens do yt-dlp para o registro."""

    def debug(self, msg):
        if not msg.startswith("[download]"):
            log.debug("yt-dlp: %s", msg)

    def info(self, msg):
        log.info("yt-dlp: %s", msg)

    def warning(self, msg):
        log.warning("yt-dlp: %s", msg)

    def error(self, msg):
        log.error("yt-dlp: %s", msg)


def install_excepthook():
    def hook(t, v, tb):
        log.error("erro não tratado", exc_info=(t, v, tb))
        sys.__excepthook__(t, v, tb)
    sys.excepthook = hook
