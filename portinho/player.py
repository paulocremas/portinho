"""Reprodução da música selecionada, com posição exata em amostras."""
import threading

import numpy as np
import sounddevice as sd

from .audio import SR


class MusicPlayer:
    def __init__(self):
        self.data = None          # float32 (n, 2)
        self.pos = 0              # posição em amostras (pode ser negativa = silêncio antes)
        self.volume = 1.0
        self.playing = False
        self._lock = threading.Lock()
        self._stream = None
        self._cb_start = None     # amostra do início do último bloco entregue
        self._cb_dac = 0.0        # horário (relógio do stream) em que esse bloco toca

    def set_data(self, data):
        with self._lock:
            self.data = data
            self.pos = 0

    @property
    def duration(self):
        return 0.0 if self.data is None else len(self.data) / SR

    def _latency(self):
        return self._stream.latency if self._stream is not None else 0.0

    def time(self):
        """Tempo (s) que está saindo no alto-falante agora.

        Usa o relógio do dispositivo: os blocos de áudio são pedidos em rajadas,
        então contar amostras sozinho "pula" dezenas de ms.
        """
        st = self._stream
        if st is None or self._cb_start is None or not self.playing:
            return self.pos / SR - self._latency()
        return self._cb_start / SR + (st.time - self._cb_dac)

    def seek(self, seconds):
        with self._lock:
            lat = self._latency()
            self.pos = int(round((seconds + lat) * SR))
            if self._stream is not None:
                # estimativa até o próximo bloco chegar
                self._cb_start = self.pos
                self._cb_dac = self._stream.time + lat

    def play(self, seconds):
        if self._stream is None:
            self._stream = sd.OutputStream(samplerate=SR, channels=2, dtype="float32",
                                           callback=self._callback)
            self._stream.start()
        self.seek(seconds)
        self.playing = True

    def pause(self):
        self.playing = False

    def close(self):
        self.playing = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _callback(self, out, frames, t, _status):
        out.fill(0)
        with self._lock:
            if not self.playing or self.data is None:
                return
            start, end = self.pos, self.pos + frames
            self.pos = end
            if t.outputBufferDacTime > 0:
                self._cb_start, self._cb_dac = start, t.outputBufferDacTime
            else:
                self._cb_start = None
            data = self.data
            vol = self.volume
        a, b = max(start, 0), min(end, len(data))
        if b > a:
            out[a - start:b - start] = data[a:b] * vol
        np.clip(out, -1, 1, out=out)
