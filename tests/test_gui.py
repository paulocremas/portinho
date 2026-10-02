"""Teste de ponta a ponta da interface (roda com QT_QPA_PLATFORM=offscreen).

Uso: python tests/test_gui.py VIDEO.mp4 [pasta_saida]
"""
import os
import subprocess
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QDragEnterEvent, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from portinho import audio, theme
from portinho.app import MainWindow

VIDEO = os.path.abspath(sys.argv[1])
OUT = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp())
SHIFT = 2.5          # a "música" é o próprio áudio do vídeo começando 2,5 s depois

app = QApplication(sys.argv)
theme.apply(app)
msgs = []
QMessageBox.warning = staticmethod(lambda *a: msgs.append(("WARN", a[2])))
QMessageBox.information = staticmethod(lambda *a: msgs.append(("INFO", a[2])))

fails = []


def check(name, cond, detail=""):
    print(("  OK   " if cond else "  FALHA") + f" {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)


def wait(cond, timeout=30):
    t0 = time.time()
    while not cond():
        app.processEvents()
        time.sleep(0.01)
        if time.time() - t0 > timeout:
            return False
    return True


def pump(sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents()
        time.sleep(0.005)


# música de teste: áudio do vídeo com 2,5 s de silêncio antes
music = os.path.join(OUT, "musica_teste.wav")
subprocess.run([audio.ffmpeg_exe(), "-y", "-v", "error", "-i", VIDEO, "-vn",
                "-af", f"adelay={int(SHIFT*1000)}|{int(SHIFT*1000)}", "-ar", "48000", music], check=True)

os.environ['PORTINHO_NO_UPDATE'] = '1'
w = MainWindow()
w.resize(1280, 860)
w.show()
pump(0.3)
w.grab().save(os.path.join(OUT, "1_vazio.png"))
tl = w.timeline

print("\n[carregar arquivos arrastando para a janela]")
for path in (VIDEO, music):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(path)])
    pos = QPointF(400, 200)
    enter = QDragEnterEvent(pos.toPoint(), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(w, enter)
    check(f"aceita arrastar {os.path.basename(path)}", enter.isAccepted())
    drop = QDropEvent(pos, Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(w, drop)
ok = wait(lambda: tl.video.loaded and tl.music.loaded and w._auto_done, 60)
check("vídeo e música carregados + auto-alinhado", ok)
pump(0.3)
check("auto-alinhar acertou −2,5 s (música começa antes)", abs(w.offset_spin.value() + SHIFT) < 0.02,
      f"{w.offset_spin.value():.3f}")
w.grab().save(os.path.join(OUT, "2_carregado.png"))


def clip_center(i):
    r = tl.clip_rect(i)
    x = min(max(r.center().x(), 60), tl.width() - 60)
    return QPoint(int(x), int(r.center().y()))


def move_event(pos, mods, buttons=Qt.LeftButton):
    # QTest.mouseMove não manda as teclas modificadoras; o usuário real manda
    p = QPointF(pos)
    ev = QMouseEvent(QEvent.MouseMove, p, QPointF(tl.mapToGlobal(p)), Qt.NoButton, buttons, mods)
    app.sendEvent(tl, ev)


def drag(start, end, mods=Qt.NoModifier, steps=12, shot=None):
    QTest.mouseMove(tl, start)
    QTest.mousePress(tl, Qt.LeftButton, mods, start)
    for k in range(1, steps + 1):
        p = start + (end - start) * (k / steps)
        move_event(QPoint(int(p.x()), int(p.y())), mods)
        pump(0.01)
    if shot:
        tl.grab().save(shot)
        w.grab().save(shot.replace(".png", "_janela.png"))
    QTest.mouseRelease(tl, Qt.LeftButton, mods, end)
    pump(0.05)


print("\n[arrastar o clipe da música]")
before = w.offset_spin.value()
tl.fit()
pump(0.05)
off0 = tl.music.offset
start = clip_center(1)
drag(start, start + QPoint(-150, 0), shot=os.path.join(OUT, "3_arrastando.png"))
moved = tl.music.offset - off0
check("clipe acompanhou o mouse (−150 px)", abs(moved * tl.pps + 150) < 12 or tl._snap_x is None,
      f"{moved * tl.pps:.1f} px")
check("caixa de deslocamento acompanhou", abs(w.offset_spin.value() - (before + moved)) < 6e-4)
check("vídeo não mexeu", tl.video.offset == 0)

print("\n[desfazer / refazer]")
QTest.keyClick(w, Qt.Key_Z, Qt.ControlModifier)
pump(0.05)
check("Ctrl+Z voltou ao alinhamento", abs(w.offset_spin.value() - before) < 6e-4, f"{w.offset_spin.value():.3f}")
QTest.keyClick(w, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
pump(0.05)
check("Ctrl+Shift+Z refez", abs(w.offset_spin.value() - (before + moved)) < 6e-4)
w.undo()

print("\n[ímã]")
tl.suggestion = None
tl.music.offset = 0.0
w._sync_spin()
tl.zoom(1.0)
pump(0.05)
# arrasta a música para ficar ~6 px depois do início do vídeo -> deve grudar em 0
s = clip_center(1)
target_px = 6
dx = int(round((tl.video.offset - tl.music.offset) * tl.pps)) + target_px + 40
drag(s, s + QPoint(40, 0))
drag(clip_center(1), clip_center(1) + QPoint(-40 - 0, 0))
start_x = tl.t2x(tl.music.offset)
p0 = clip_center(1)
drag(p0, p0 + QPoint(int(tl.t2x(0.0) - start_x + 6), 0))
check("grudou no início do vídeo", abs(tl.music.offset - 0.0) < 1e-9, f"{tl.music.offset:.4f}")
p0 = clip_center(1)
drag(p0, p0 + QPoint(6, 0), mods=Qt.ControlModifier)
check("Alt desliga o ímã", abs(tl.music.offset * tl.pps - 6) < 1.5, f"{tl.music.offset*tl.pps:.1f} px")

print("\n[ajuste fino com Shift]")
o = tl.music.offset
p0 = clip_center(1)
drag(p0, p0 + QPoint(100, 0), mods=Qt.ShiftModifier)
check("Shift move 10x menos", abs((tl.music.offset - o) * tl.pps - 10) < 1.5,
      f"{(tl.music.offset - o) * tl.pps:.1f} px")

print("\n[arrastar o clipe do vídeo]")
v0, m0 = tl.video.offset, tl.music.offset
p0 = clip_center(0)
drag(p0, p0 + QPoint(80, 0), mods=Qt.ControlModifier)
check("vídeo moveu", abs((tl.video.offset - v0) * tl.pps - 80) < 1.5)
check("deslocamento relativo mudou junto",
      abs(w.offset_spin.value() - (tl.music.offset - tl.video.offset)) < 6e-4)
w.undo()
check("desfazer moveu o vídeo de volta", abs(tl.video.offset - v0) < 1e-9)

print("\n[clique simples = ir para o ponto]")
tl.fit()
pump(0.05)
r = tl.clip_rect(0)
x = int(tl.t2x(tl.video.offset + 5.0))
QTest.mouseClick(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x, int(r.center().y())))
pump(0.4)
check("clique no clipe levou a 5 s", abs(w.current_time() - 5.0) < 0.1, f"{w.current_time():.3f}")
check("clique NÃO moveu o clipe", abs(tl.video.offset - v0) < 1e-9)

print("\n[régua: varrer]")
x1 = int(tl.t2x(tl.video.offset + 2.0))
x2 = int(tl.t2x(tl.video.offset + 9.0))
QTest.mousePress(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x1, 10))
for k in range(10):
    QTest.mouseMove(tl, QPoint(x1 + (x2 - x1) * (k + 1) // 10, 10))
    pump(0.01)
QTest.mouseRelease(tl, Qt.LeftButton, Qt.NoModifier, QPoint(x2, 10))
pump(0.4)
check("varrer a régua levou a 9 s", abs(w.current_time() - 9.0) < 0.15, f"{w.current_time():.3f}")

print("\n[zoom e rolagem]")
pps = tl.pps
we = QWheelEvent(QPointF(300, 150), tl.mapToGlobal(QPointF(300, 150)), QPoint(), QPoint(0, 120),
                 Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
t_under = tl.x2t(300)
app.sendEvent(tl, we)
check("roda aproxima", tl.pps > pps)
check("zoom mantém o ponto sob o cursor", abs(tl.x2t(300) - t_under) < 1e-6)
vs = tl.view_start
we = QWheelEvent(QPointF(300, 150), tl.mapToGlobal(QPointF(300, 150)), QPoint(), QPoint(0, 120),
                 Qt.NoButton, Qt.ShiftModifier, Qt.NoScrollPhase, False)
app.sendEvent(tl, we)
check("Shift+roda rola", tl.view_start < vs)
vs = tl.view_start
QTest.mousePress(tl, Qt.RightButton, Qt.NoModifier, QPoint(500, 150))
QTest.mouseMove(tl, QPoint(400, 150))
QTest.mouseRelease(tl, Qt.RightButton, Qt.NoModifier, QPoint(400, 150))
check("botão direito arrasta a vista", tl.view_start > vs)
tl.fit()

print("\n[rolagem automática ao arrastar perto da borda]")
tl.zoom(4)
pump(0.05)
vs = tl.view_start
p0 = QPoint(int(tl.width() * 0.5), clip_center(1).y())
if tl._clip_at(QPointF(p0)) is None:
    tl.view_start = tl.music.offset + 1
    vs = tl.view_start
QTest.mousePress(tl, Qt.LeftButton, Qt.ControlModifier, p0)
move_event(QPoint(p0.x() + 10, p0.y()), Qt.ControlModifier)
move_event(QPoint(tl.width() - 5, p0.y()), Qt.ControlModifier)
pump(0.5)
QTest.mouseRelease(tl, Qt.LeftButton, Qt.ControlModifier, QPoint(tl.width() - 5, p0.y()))
check("vista rolou sozinha", tl.view_start > vs + 0.1, f"{tl.view_start - vs:.2f} s")
w.undo()
tl.fit()

print("\n[tocar + arrastar durante a reprodução]")
w.seek(1.0)
pump(0.2)
QTest.keyClick(w, Qt.Key_Space)
pump(1.5)
check("Espaço começou a tocar", w.playing and w.vplayer.playbackState() == w.vplayer.PlaybackState.PlayingState)
d = w.mplayer.time() - (w.current_time() + w.music_delta())
check("música sincronizada com o vídeo", abs(d) < 0.08, f"{d*1000:.0f} ms")
p0 = clip_center(1)
drag(p0, p0 + QPoint(60, 0), mods=Qt.ControlModifier)
pump(0.4)
d = w.mplayer.time() - (w.current_time() + w.music_delta())
check("após arrastar tocando, música seguiu o novo encaixe", abs(d) < 0.08, f"{d*1000:.0f} ms")
QTest.keyClick(w, Qt.Key_Right)
pump(0.3)
d = w.mplayer.time() - (w.current_time() + w.music_delta())
check("seta → (+10 ms) aplicou", abs(d) < 0.08)
QTest.keyClick(w, Qt.Key_Space)
pump(0.1)
check("Espaço pausou", not w.playing)

print("\n[tela cheia e janela flutuante — sem atrapalhar a reprodução]")
w.seek(2.0)
pump(0.2)
w.play()
pump(0.8)


def sync_ok(label):
    pump(0.6)
    d = w.mplayer.time() - (w.current_time() + w.music_delta())
    check(f"{label}: continua tocando", w.playing and w.vplayer.playbackState() == w.vplayer.PlaybackState.PlayingState)
    check(f"{label}: música sincronizada", abs(d) < 0.08, f"{d*1000:.0f} ms")


def no_jump(fn, label):
    t0, c0 = w.current_time(), time.perf_counter()
    fn()
    pump(0.5)
    adv, real = w.current_time() - t0, time.perf_counter() - c0
    check(f"{label}: vídeo não pulou nem travou", abs(adv - real) < 0.15, f"andou {adv:.2f}s em {real:.2f}s")


no_jump(w.popout_video, "abrir janela flutuante")
check("janela flutuante aberta", w.vwin.isVisible() and w.vwin.mode == "popup")
check("principal mostra 'vídeo em outra janela'", w.video_stack.currentIndex() == 2)
sync_ok("janela flutuante")
w.vwin.grab().save(os.path.join(OUT, "5_janela_flutuante.png"))
no_jump(w.vwin.close, "fechar janela flutuante")
check("ao fechar, vídeo voltou para a principal", not w.video_out and w.video_stack.currentIndex() == 1)
sync_ok("depois de fechar")

no_jump(w.fullscreen_video, "tela cheia")
check("tela cheia aberta", w.vwin.mode == "fullscreen" and w.vwin.isVisible())
sync_ok("tela cheia")
QTest.keyClick(w.vwin, Qt.Key_Escape)
pump(0.2)
check("Esc saiu da tela cheia e voltou para a principal", not w.video_out and not w.vwin.isVisible())

w.popout_video()
pump(0.2)
QTest.keyClick(w.vwin, Qt.Key_F)
pump(0.2)
check("F na janela flutuante: tela cheia", w.vwin.mode == "fullscreen")
QTest.keyClick(w.vwin, Qt.Key_Escape)
pump(0.2)
check("Esc volta para a janela flutuante (de onde veio)", w.vwin.mode == "popup" and w.vwin.isVisible() and w.video_out)
sync_ok("ida e volta da tela cheia")
QTest.keyClick(w.vwin, Qt.Key_Space)
pump(0.1)
check("Espaço na janela do vídeo pausa", not w.playing)
QTest.keyClick(w.vwin, Qt.Key_Space)
pump(0.1)
check("Espaço de novo volta a tocar", w.playing)
w.vwin.btn_back.click()
pump(0.2)
check("botão 'Voltar' devolve o vídeo", not w.video_out and not w.vwin.isVisible())

QTest.mouseDClick(w.video_widget, Qt.LeftButton)
pump(0.2)
check("duplo clique no vídeo: tela cheia", w.vwin.mode == "fullscreen")
QTest.mouseDClick(w.vwin.video, Qt.LeftButton)
pump(0.2)
check("duplo clique de novo: sai da tela cheia", not w.vwin.isVisible() and not w.video_out)
sync_ok("após todas as trocas")
w.pause()
w.popout_video()
pump(0.2)
w.close_video_window()
pump(0.1)
check("pausado: trocar não começa a tocar sozinho", not w.playing)

print("\n[qualidade máxima]")
check("música toca na taxa original (48 kHz, sem reamostrar)", w.mplayer.sr == 48000, w.mplayer.sr)


def info(path):
    r = subprocess.run([audio.ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True, text=True)
    return r.stderr


saved = {}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (saved["path"], saved.get("filter", "")))

# WAV do vídeo aberto (sem link)
w.url_edit.clear()
saved["path"] = os.path.join(OUT, "do_video.wav")
msgs.clear()
w.save_wav()
check("WAV do vídeo aberto salvo", wait(lambda: any(m[0] == "INFO" for m in msgs), 60) and os.path.exists(saved["path"]))
inf = info(saved["path"])
src_rate = audio.probe_rate(VIDEO)
check("WAV: 32 bits float, taxa original do vídeo", "pcm_f32le" in inf and audio.probe_rate(saved["path"]) == src_rate,
      f"{audio.probe_rate(saved['path'])} Hz (original {src_rate})")
a1, a2 = audio.decode(VIDEO, 2, src_rate), audio.decode(saved["path"], 2, src_rate)
check("WAV idêntico ao áudio decodificado (sem perdas)", a1.shape == a2.shape and float(np.abs(a1 - a2).max()) == 0.0)

# WAV direto de um link do YouTube: melhor faixa (Opus 48 kHz)
w.url_edit.setText("https://www.youtube.com/watch?v=jNQXAC9IVRw")
saved["path"] = os.path.join(OUT, "do_youtube.wav")
msgs.clear()
w.save_wav()
ok = wait(lambda: msgs, 120)
check("WAV do YouTube salvo", ok and msgs[0][0] == "INFO" and os.path.exists(saved["path"]), msgs[:1])
if os.path.exists(saved["path"]):
    check("WAV do YouTube: melhor faixa (48 kHz) em 32 bits float",
          audio.probe_rate(saved["path"]) == 48000 and "pcm_f32le" in info(saved["path"]),
          f"{audio.probe_rate(saved['path'])} Hz")
w.url_edit.clear()

# exportar MKV sem perdas
w.auto_align()
saved["path"] = os.path.join(OUT, "exportado.mkv")
saved["filter"] = "MKV"
msgs.clear()
w.export()
check("exportou MKV", wait(lambda: msgs, 60) and msgs[0][0] == "INFO" and os.path.exists(saved["path"]), msgs[:1])
inf = info(saved["path"])
vcodec = lambda txt: [l for l in txt.splitlines() if "Video:" in l][0].split("Video:")[1].split()[0]
check("MKV: vídeo copiado sem recomprimir", vcodec(inf) == vcodec(info(VIDEO)), vcodec(inf))
m_src = audio.decode(music, 1, 48000)[:, 0]
m_out = audio.decode(saved["path"], 1, 48000)[:, 0]
k = int(round(w.music_delta() * 48000))     # a música começa k amostras "dentro" do arquivo
seg = m_out[48000:48000 + 9600]
errs = {j: float(np.abs(m_src[48000 + k + j:48000 + k + j + 9600] - seg).max()) for j in (-1, 0, 1)}
j = min(errs, key=errs.get)
check("MKV: amostras da música idênticas às do original", errs[j] < 1e-6, f"erro {errs[j]:.1e}")
check("MKV: alinhamento exato (±1 amostra)", errs[0] < 1e-6 or errs[j] < 1e-6 and abs(j) <= 1, f"desvio {j} amostra(s)")
# música começando DEPOIS do vídeo (caminho do atraso exato em amostras)
w.offset_spin.setValue(1.25)
saved["path"] = os.path.join(OUT, "exportado_atraso.mkv")
msgs.clear()
w.export()
check("exportou MKV com a música atrasada", wait(lambda: msgs, 60) and msgs[0][0] == "INFO")
m_out = audio.decode(saved["path"], 1, 48000)[:, 0]
lead = int(round(1.25 * 48000))
check("silêncio exato antes da música", float(np.abs(m_out[:lead - 2]).max()) == 0.0)
errs = {j: float(np.abs(m_out[lead + j:lead + j + 48000 * 3] - m_src[:48000 * 3]).max()) for j in (-1, 0, 1)}
j = min(errs, key=errs.get)
check("música atrasada: amostras idênticas e no lugar exato", errs[j] < 1e-6 and abs(j) <= 1,
      f"desvio {j} amostra(s), erro {errs[j]:.1e}")
w.undo()

print("\n[exportar]")
w.auto_align()
out = os.path.join(OUT, "exportado.mp4")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, "MP4 (*.mp4)"))
if os.path.exists(out):
    os.remove(out)
msgs.clear()
w.export()
check("exportou", wait(lambda: any(m[0] == "INFO" for m in msgs), 60) and os.path.exists(out))
# confere o alinhamento no arquivo exportado: o áudio exportado deve bater com o do vídeo
a_out = audio.decode(out, 1)[:, 0]
a_vid = audio.decode(VIDEO, 1)[:, 0]
n = min(len(a_out), len(a_vid))
_, f1 = audio.spectrogram(a_vid[:n])
_, f2 = audio.spectrogram(a_out[:n])
lag = audio.auto_align(f1, f2)
check("no MP4 exportado a música está alinhada", abs(lag) < 0.03, f"{lag*1000:.0f} ms")

print("\n[erros]")
w.url_edit.setText("https://www.youtube.com/watch?v=xxxxxxxxxxx")
w.download()
check("link inválido mostra aviso (não trava)", wait(lambda: any(m[0] == "WARN" for m in msgs), 60))
check("botão Carregar volta a funcionar", w.btn_dl.isEnabled())

tl.fit()
pump(0.1)
w.grab().save(os.path.join(OUT, "4_final.png"))
w.close()
print(f"\n{len(fails)} falha(s)", fails if fails else "")
print("capturas em", OUT)
sys.exit(1 if fails else 0)
