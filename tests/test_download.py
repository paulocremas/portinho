"""Novas tentativas do download quando o YouTube recusa (simulado) + download real."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import yt_dlp  # noqa: E402

from portinho import download  # noqa: E402
from portinho import download as dlmod  # noqa: E402
from portinho.log import LOG_PATH, tail  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("  OK   " if cond else "  FALHA") + f" {name}" + (f"  ({detail})" if detail else ""), flush=True)
    if not cond:
        fails.append(name)


Real = yt_dlp.YoutubeDL
seen = []


def fake(fail_when):
    class F(Real):
        def extract_info(self, url, download=True, **k):
            p = self.params
            tag = ("cookies:" + p["cookiesfrombrowser"][0]) if p.get("cookiesfrombrowser") else \
                ("client:" + p["extractor_args"]["youtube"]["player_client"][0]) if p.get("extractor_args") else \
                ("fmt:b" if p["format"] == dlmod.FALLBACK_FORMAT else "padrão")
            seen.append(tag)
            err = fail_when(tag)
            if err:
                raise yt_dlp.utils.DownloadError(err)
            # sucesso simulado: baixa de verdade, mas sem ler cookies reais do navegador
            self.params.pop("cookiesfrombrowser", None)
            self.cookiejar.clear()
            return super().extract_info(url, download=download, **k)
    return F


T = tempfile.mkdtemp()
URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
BOT = "ERROR: [youtube] x: Sign in to confirm you're not a bot. Use --cookies-from-browser"

print("\n[download real, sem simular erro]")
info, path = download.fetch(URL, "ba/b", "%(id)s.a.%(ext)s", lambda d: None, T)
check("baixa de primeira", os.path.exists(path), os.path.basename(path))

print("\n[YouTube pede 'não sou robô': usa o login do navegador]")
seen.clear()
yt_dlp.YoutubeDL = fake(lambda t: BOT if not t.startswith("cookies:edge") else None)
try:
    info, path = download.fetch(URL, "ba/b", "%(id)s.c.%(ext)s", lambda d: None, T)
    ok = True
except RuntimeError:
    ok = False
check("tenta firefox e depois edge, e baixa", ok and seen[-2:] == ["cookies:firefox", "cookies:edge"], seen)

print("\n[nada funciona: mensagem clara]")
seen.clear()
yt_dlp.YoutubeDL = fake(lambda t: BOT)
try:
    download.fetch(URL, "ba/b", "%(id)s.d.%(ext)s", lambda d: None, T)
    msg = ""
except RuntimeError as e:
    msg = str(e)
check("explica o que fazer (login no navegador)", "não é um robô" in msg and "Firefox" in msg, msg[:90])
check("tentou o padrão e todos os navegadores", seen == ["padrão"] + [f"cookies:{b}" for b in download.BROWSERS], len(seen))
check("tudo registrado no log", "cookies do vivaldi" in tail(80) and os.path.exists(LOG_PATH), LOG_PATH)

print("\n[vídeo privado: não insiste]")
seen.clear()
yt_dlp.YoutubeDL = fake(lambda t: "ERROR: [youtube] x: Private video. Sign in if you've been granted access")
try:
    download.fetch(URL, "ba/b", "%(id)s.e.%(ext)s", lambda d: None, T)
except RuntimeError as e:
    msg = str(e)
check("para na hora e diz que é privado", len(seen) == 1 and msg.startswith("Esse vídeo é privado"), seen)

print("\n[juntar vídeo+áudio falha: tenta formato único]")
seen.clear()
yt_dlp.YoutubeDL = fake(lambda t: None if t == "fmt:b" else "ERROR: Postprocessing: Conversion failed!")
download_b = "b"
info, path = download.fetch(URL, "bv*+ba", "%(id)s.f.%(ext)s", lambda d: None, T, merge="mkv")
check("formato único resolveu", seen[-1] == "fmt:b" and os.path.exists(path), seen)
yt_dlp.YoutubeDL = Real

print(f"\n{len(fails)} falha(s)", fails if fails else "")
sys.exit(1 if fails else 0)
