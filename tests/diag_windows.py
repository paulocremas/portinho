"""Diagnóstico de vídeo no Windows (roda no GitHub Actions): reprodução por codec e download."""
import os
import subprocess
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer, QMediaFormat, QVideoSink, QAudioOutput
from PySide6.QtWidgets import QApplication

from portinho import audio

app = QApplication([])
T = tempfile.mkdtemp()
FF = audio.ffmpeg_exe()
print("Qt multimedia backend:", os.environ.get("QT_MEDIA_BACKEND", "(padrão)"))
print("decoders de vídeo suportados:", [QMediaFormat.videoCodecName(c) for c in QMediaFormat().supportedVideoCodecs(QMediaFormat.Decode)])


def play(path, secs=3):
    p = QMediaPlayer()
    ao = QAudioOutput()
    ao.setVolume(0)
    p.setAudioOutput(ao)
    sink = QVideoSink()
    p.setVideoSink(sink)
    n, errs = [0], []
    sink.videoFrameChanged.connect(lambda f: n.__setitem__(0, n[0] + 1))
    p.errorOccurred.connect(lambda e, m: errs.append(f"{e.name}: {m}"))
    p.setSource(QUrl.fromLocalFile(path))
    p.play()
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        time.sleep(0.01)
    return n[0], p.mediaStatus().name, errs, p.duration()


for name, vargs, aargs, ext in (
        ("h264+aac mp4", ["-c:v", "libx264", "-pix_fmt", "yuv420p"], ["-c:a", "aac"], "mp4"),
        ("vp9+opus mkv", ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8"], ["-c:a", "libopus"], "mkv"),
        ("vp9+opus webm", ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8"], ["-c:a", "libopus"], "webm"),
        ("h264+opus mkv", ["-c:v", "libx264", "-pix_fmt", "yuv420p"], ["-c:a", "libopus"], "mkv")):
    out = os.path.join(T, f"t.{name.replace(' ', '_').replace('+', '_')}.{ext}")
    r = subprocess.run([FF, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30",
                        "-f", "lavfi", "-i", "sine=f=440", "-t", "4", *vargs, *aargs, out], capture_output=True, text=True)
    if r.returncode:
        print(f"[{name}] não consegui gerar: {r.stderr[-200:]}")
        continue
    print(f"[{name}] quadros={play(out)}")

print("\n--- download do YouTube (pode cair no 'não é um robô' do datacenter)")
try:
    import yt_dlp
    from portinho.app import VIDEO_FORMAT
    opts = {"format": VIDEO_FORMAT, "merge_output_format": "mkv", "outtmpl": os.path.join(T, "%(id)s.%(ext)s"),
            "ffmpeg_location": FF, "quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as y:
        i = y.extract_info("https://www.youtube.com/watch?v=jNQXAC9IVRw", download=True)
        f = i["requested_downloads"][0]["filepath"]
    print("baixou:", f, os.path.getsize(f), "->", play(f))
except Exception:
    traceback.print_exc()
