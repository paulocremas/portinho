"""Decodificação de áudio (via ffmpeg), espectrograma e auto-alinhamento."""
import os
import re
import subprocess
import sys

import numpy as np

SR = 44100          # taxa de amostragem usada em tudo
N_FFT = 2048
HOP = 512           # ~86 colunas de espectrograma por segundo
FPS = SR / HOP
SPEC_ROWS = 256     # altura (bins de frequência em escala log)


def resource_dir():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _popen_kwargs():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def probe_rate(path):
    """Taxa de amostragem original da primeira faixa de áudio (None se não achar)."""
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, **_popen_kwargs())
    m = re.search(r"Audio:.*?(\d+) Hz", proc.stderr.decode(errors="replace"))
    return int(m.group(1)) if m else None


def decode(path, channels=2, sr=SR):
    """Decodifica qualquer arquivo de áudio/vídeo para float32 (n, channels) na taxa `sr`."""
    cmd = [ffmpeg_exe(), "-v", "error", "-i", path, "-vn",
           "-f", "f32le", "-acodec", "pcm_f32le", "-ac", str(channels), "-ar", str(sr), "-"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_popen_kwargs())
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace").strip() or "ffmpeg falhou")
    data = np.frombuffer(proc.stdout, dtype=np.float32)
    if data.size == 0:
        raise RuntimeError("O arquivo não contém áudio.")
    return data.reshape(-1, channels).copy()


def _colormap():
    # Paleta tipo "magma"
    anchors = np.array([
        [0, 0, 4], [28, 16, 68], [79, 18, 123], [129, 37, 129],
        [181, 54, 122], [229, 80, 100], [251, 135, 97], [254, 194, 135], [252, 253, 191],
    ], dtype=np.float32)
    x = np.linspace(0, 1, len(anchors))
    t = np.linspace(0, 1, 256)
    lut = np.stack([np.interp(t, x, anchors[:, c]) for c in range(3)], axis=1)
    return lut.astype(np.uint8)


_LUT = _colormap()


def spectrogram(mono):
    """Retorna (rgb uint8 [SPEC_ROWS, frames, 3], flux float32 [frames]).

    flux = envelope de "onsets", usado no auto-alinhamento.
    """
    mono = mono.astype(np.float32)
    n_frames = max(1, 1 + (len(mono) - N_FFT) // HOP) if len(mono) >= N_FFT else 1
    if len(mono) < N_FFT:
        mono = np.pad(mono, (0, N_FFT - len(mono)))
    window = np.hanning(N_FFT).astype(np.float32)

    freqs = np.fft.rfftfreq(N_FFT, 1 / SR)
    log_f = np.geomspace(30, SR / 2, SPEC_ROWS)
    bin_idx = np.clip(np.searchsorted(freqs, log_f), 0, len(freqs) - 1)

    out = np.empty((n_frames, SPEC_ROWS), dtype=np.float32)
    flux = np.zeros(n_frames, dtype=np.float32)
    prev = None
    chunk = 4096
    for start in range(0, n_frames, chunk):
        stop = min(n_frames, start + chunk)
        idx = (np.arange(start, stop)[:, None] * HOP) + np.arange(N_FFT)[None, :]
        frames = mono[idx] * window
        mag = np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)
        db = 20 * np.log10(mag[:, bin_idx] + 1e-6)
        out[start:stop] = db
        # fluxo espectral
        d = np.diff(db, axis=0, prepend=db[:1] if prev is None else prev[None, :])
        flux[start:stop] = np.maximum(d, 0).sum(axis=1)
        prev = db[-1]

    hi = np.percentile(out, 99.5)
    lo = hi - 80
    norm = np.clip((out - lo) / (hi - lo), 0, 1)
    img = _LUT[(norm * 255).astype(np.uint8)]          # (frames, rows, 3)
    img = np.ascontiguousarray(img.transpose(1, 0, 2)[::-1])  # graves embaixo
    return img, flux


NOTE_NAMES = ["Dó", "Dó♯", "Ré", "Mi♭", "Mi", "Fá", "Fá♯", "Sol", "Lá♭", "Lá", "Si♭", "Si"]
# perfis de Krumhansl-Kessler: quanto cada grau "pertence" a um tom maior/menor
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def chroma(mono, sr=SR):
    """Energia média de cada uma das 12 notas (Dó..Si) ao longo do áudio."""
    n_fft, hop = 8192, 4096                       # ~5 Hz por bin: separa as notas dos graves
    mono = mono.astype(np.float32)
    if len(mono) < n_fft:
        mono = np.pad(mono, (0, n_fft - len(mono)))
    n_frames = 1 + (len(mono) - n_fft) // hop
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    band = (freqs >= 55) & (freqs <= 2000)       # Lá1 até ~Si6: onde mora a harmonia
    pc = np.round(69 + 12 * np.log2(freqs[band] / 440)).astype(int) % 12
    window = np.hanning(n_fft).astype(np.float32)
    total = np.zeros(12)
    for start in range(0, n_frames, 256):
        stop = min(n_frames, start + 256)
        idx = (np.arange(start, stop)[:, None] * hop) + np.arange(n_fft)[None, :]
        mag = np.abs(np.fft.rfft(mono[idx] * window, axis=1))[:, band]
        # só os picos do espectro (notas), não o "chão" de ruído/bateria
        peak = np.zeros_like(mag, dtype=bool)
        peak[:, 1:-1] = (mag[:, 1:-1] > mag[:, :-2]) & (mag[:, 1:-1] >= mag[:, 2:])
        peak &= mag > np.median(mag, axis=1, keepdims=True) * 4
        w = np.sqrt(np.where(peak, mag, 0))
        c = np.zeros((stop - start, 12))
        for k in range(12):
            c[:, k] = w[:, pc == k].sum(axis=1)
        norm = c.sum(axis=1, keepdims=True)
        total += (c / np.where(norm > 0, norm, 1)).sum(axis=0)   # cada quadro pesa igual
    return total


def detect_key(mono, sr=SR):
    """Retorna (tônica 0..11, "maior"/"menor", confiança 0..1) ou None se não houver harmonia."""
    c = chroma(mono, sr)
    if c.sum() <= 0:
        return None
    best = []
    for mode, prof in (("maior", _MAJOR), ("menor", _MINOR)):
        for t in range(12):
            best.append((float(np.corrcoef(c, np.roll(prof, t))[0, 1]), t, mode))
    best.sort(reverse=True)
    r, tonic, mode = best[0]
    return tonic, mode, max(0.0, r)


def key_name(key):
    tonic, mode, _ = key
    return f"{NOTE_NAMES[tonic]} {mode}"


def semitone_diff(a, b):
    """Semitons para levar o tom `a` até `b` (-5..+6), comparando tons menores pelo relativo maior."""
    ta = (a[0] + 3) % 12 if a[1] == "menor" else a[0]
    tb = (b[0] + 3) % 12 if b[1] == "menor" else b[0]
    return (tb - ta + 5) % 12 - 5


def auto_align(video_flux, music_flux, max_lag_s=None):
    """Retorna d (segundos) tal que tempo_musica = tempo_video + d."""
    v = video_flux - video_flux.mean()
    m = music_flux - music_flux.mean()
    v /= (v.std() + 1e-9)
    m /= (m.std() + 1e-9)
    n = len(v) + len(m)
    nfft = 1 << (n - 1).bit_length()
    corr = np.fft.irfft(np.conj(np.fft.rfft(v, nfft)) * np.fft.rfft(m, nfft), nfft)
    lags = np.arange(nfft)
    lags[lags > nfft // 2] -= nfft
    # normaliza pela sobreposição para não favorecer só o lag 0
    overlap = np.minimum(len(v), len(m) - lags) - np.maximum(0, -lags)
    overlap = np.clip(overlap, 1, None).astype(np.float64)
    min_overlap = 0.25 * min(len(v), len(m))
    score = np.where(overlap >= min_overlap, corr / np.sqrt(overlap), -np.inf)
    if max_lag_s is not None:
        score[np.abs(lags) > max_lag_s * FPS] = -np.inf
    i = int(np.argmax(score))
    # interpolação parabólica para precisão abaixo de 1 quadro (~11.6 ms)
    frac = 0.0
    a, b, c = score[i - 1], score[i], score[(i + 1) % nfft]
    if np.isfinite(a) and np.isfinite(c) and (a - 2 * b + c) < 0:
        frac = 0.5 * (a - c) / (a - 2 * b + c)
    return (float(lags[i]) + frac) / FPS
