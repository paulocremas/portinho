"""Download do YouTube com novas tentativas automáticas quando o YouTube recusa.

Ordem: jeito padrão (o yt-dlp já combina vários "clientes" do YouTube; forçar um só piora)
-> cookies do navegador do usuário, só se o YouTube pedir "confirme que você não é um robô"
ou login -> formato único, só se juntar vídeo+áudio falhar. Cada tentativa vai para o registro.
"""
import os

from . import audio
from .log import YdlLogger, log

BROWSERS = ("firefox", "edge", "chrome", "brave", "chromium", "opera", "vivaldi")
NEEDS_LOGIN = ("not a bot", "sign in", "confirm your age", "inappropriate", "cookies")


def base_opts(fmt, outtmpl, hook, out_dir):
    opts = {
        "format": fmt,
        "outtmpl": os.path.join(out_dir, outtmpl),
        "ffmpeg_location": audio.ffmpeg_exe(),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "logger": YdlLogger(),
        "progress_hooks": [hook],
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
    }
    deno = os.path.join(audio.resource_dir(), "deno.exe" if os.name == "nt" else "deno")
    if os.path.exists(deno):
        opts["js_runtimes"] = {"deno": {"path": deno}}
    return opts


# se juntar falhar: formato clássico 18, ou arquivo único, ou H.264+AAC (junta em MP4 sem recodificar)
FALLBACK_FORMAT = "18/b/bv*[vcodec^=avc1]+ba[ext=m4a]"
MERGE_FAILED = ("postprocessing", "conversion failed", "merg", "ffmpeg")


def _attempts(fmt):
    yield "padrão", {}, fmt, None
    for b in BROWSERS:
        yield f"cookies do {b}", {"cookiesfrombrowser": (b,)}, fmt, "login"
    yield "formato único", {}, FALLBACK_FORMAT, "merge"


def fetch(url, fmt, outtmpl, hook, out_dir, merge=None, attempt_cb=None):
    """Baixa e retorna (info, caminho). Levanta RuntimeError com mensagem amigável."""
    import yt_dlp
    errors = []
    login_needed = merge_failed = False
    for name, extra, f, only_if in _attempts(fmt):
        if only_if == "login" and not login_needed:
            continue          # só usa o navegador se o YouTube pediu login/robô
        if only_if == "merge" and not merge_failed:
            continue
        opts = base_opts(f, outtmpl, hook, out_dir)
        if merge:
            opts["merge_output_format"] = merge
        opts.update(extra)
        log.info("download: tentativa '%s' (%s) %s", name, f, url)
        if attempt_cb and errors:
            attempt_cb(name)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if "entries" in info:
                    info = next(e for e in info["entries"] if e)
                reqs = info.get("requested_downloads") or []
                path = reqs[0]["filepath"] if reqs else ydl.prepare_filename(info)
            if not os.path.exists(path):
                raise RuntimeError(f"arquivo não apareceu: {path}")
            log.info("download: ok com '%s': %s", name, path)
            return info, path
        except Exception as e:
            msg = str(e).replace("\x1b[0;31m", "").replace("\x1b[0m", "")
            log.warning("download: '%s' falhou: %s", name, msg)
            errors.append(msg)
            low = msg.lower()
            if any(k in low for k in NEEDS_LOGIN):
                login_needed = True
            if any(k in low for k in MERGE_FAILED):
                merge_failed = True
                login_needed = login_needed and "cookies" in name
            if any(k in low for k in ("private video", "video unavailable", "removed", "is not a valid url",
                                      "unsupported url", "does not exist")):
                break         # não adianta tentar de novo
    raise RuntimeError(friendly(errors))


def friendly(errors):
    last = errors[-1] if errors else "erro desconhecido"
    low = " ".join(errors).lower()
    if "private video" in low:
        head = "Esse vídeo é privado."
    elif "video unavailable" in low or "removed" in low or "does not exist" in low:
        head = "Esse vídeo não está disponível (foi removido ou bloqueado no seu país)."
    elif "unsupported url" in low or "is not a valid url" in low:
        head = "Esse link não parece ser de um vídeo do YouTube."
    elif any(k in low for k in NEEDS_LOGIN):
        head = ("O YouTube pediu para confirmar que você não é um robô (ou pediu login).\n"
                "Abra o YouTube no Firefox ou no Edge, entre na sua conta, feche o navegador e tente de novo "
                "— o Portinho usa esse login só para baixar.")
    elif any(k in low for k in ("getaddrinfo", "timed out", "network", "connection", "urlopen error")):
        head = "Sem conexão com o YouTube. Confira a internet e tente de novo."
    else:
        head = "O YouTube recusou o download."
    return f"{head}\n\nDetalhe técnico: {last[:400]}"
