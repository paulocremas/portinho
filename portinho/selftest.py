"""`portinho --selftest [URL]`: confere se tudo que o app precisa está funcionando."""
import os
import shutil
import sys
import tempfile
import time

TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def run(argv):
    if sys.stdout is None:
        # .exe com janela (sem console) no Windows: grava ao lado do programa
        sys.stdout = open(os.path.join(os.path.dirname(sys.executable), "portinho_selftest.txt"),
                          "w", encoding="utf-8")
    url = next((a for a in argv if a.startswith("http")), TEST_URL)
    results = []

    def step(name, fn):
        t0 = time.time()
        try:
            info = fn()
            results.append(True)
            print(f"  OK     {name}  {info or ''}  [{time.time() - t0:.1f}s]", flush=True)
            return info
        except Exception as e:
            results.append(False)
            print(f"  FALHA  {name}: {e}", flush=True)

    from . import audio
    tmp = tempfile.mkdtemp(prefix="portinho_")
    print("Portinho — autoteste")

    def ffmpeg():
        exe = audio.ffmpeg_exe()
        if not (os.path.exists(exe) or shutil.which(exe)):
            raise RuntimeError(f"não encontrado: {exe}")
        return exe

    step("ffmpeg embutido", ffmpeg)

    def deno():
        exe = os.path.join(audio.resource_dir(), "deno.exe" if os.name == "nt" else "deno")
        if not os.path.exists(exe):
            raise RuntimeError("deno não embutido")
        return exe

    step("deno embutido", deno)

    state = {}

    def download():
        from . import download as dl
        info, state["video"] = dl.fetch(url, "bv*[height<=360][vcodec!^=av01]+ba/b[height<=360]/b", "%(id)s.%(ext)s",
                                        lambda d: None, tmp, merge="mkv")
        return f"{info.get('title')!r} ({os.path.getsize(state['video']) // 1024} KB)"

    step("baixar do YouTube", download)

    def spec():
        data = audio.decode(state["video"])
        rgb, flux = audio.spectrogram(data.mean(axis=1))
        return f"{len(data) / audio.SR:.1f}s de áudio, espectrograma {rgb.shape[1]}x{rgb.shape[0]}"

    if "video" in state:
        step("ler áudio + espectrograma", spec)

    def sound():
        import sounddevice as sd
        dev = sd.query_devices(kind="output")
        n = [0]

        def cb(out, frames, t, s):
            out.fill(0)
            n[0] += frames
        with sd.OutputStream(samplerate=audio.SR, channels=2, dtype="float32", callback=cb):
            time.sleep(0.5)
        rate = n[0] / 0.5
        if rate < audio.SR * 0.8:
            raise RuntimeError(f"dispositivo '{dev['name']}' consome só {rate:.0f} amostras/s")
        return f"'{dev['name']}' ({rate:.0f} amostras/s)"

    step("saída de som", sound)

    def qt_video():
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QMediaPlayer
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv[:1])
        p = QMediaPlayer()
        p.setSource(QUrl.fromLocalFile(state["video"]))
        t0 = time.time()
        while p.duration() <= 0 and time.time() - t0 < 10:
            app.processEvents()
            time.sleep(0.02)
        if p.duration() <= 0:
            raise RuntimeError(p.errorString() or "não abriu o vídeo")
        return f"plataforma {app.platformName()}, duração {p.duration() / 1000:.1f}s"

    if "video" in state:
        step("reprodutor de vídeo (Qt)", qt_video)

    shutil.rmtree(tmp, ignore_errors=True)
    from .log import LOG_PATH
    print(f"\nRegistro: {LOG_PATH}")
    ok = all(results)
    print("\nTudo certo!" if ok else f"\n{results.count(False)} problema(s).")
    return 0 if ok else 1
