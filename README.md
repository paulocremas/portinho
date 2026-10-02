# Portinho

Troque a música de um vídeo do YouTube por um arquivo do seu PC, alinhando pelo espectrograma.

1. **Vídeo** — cole o link do YouTube e clique *Carregar* (ou arraste um vídeo do PC para a janela).
   O vídeo é baixado direto, sem anúncios, e toca **sem o som original**.
2. **Música** — arraste o arquivo (WAV, MP3, FLAC, OGG, M4A…) para a janela ou clique na área tracejada.
3. **Alinhar** — o Portinho já sugere o encaixe sozinho. Para ajustar, **arraste** o espectrograma
   (vídeo em azul, música em laranja) até os desenhos coincidirem. Dá para arrastar tocando.
4. **Exportar vídeo…** salva um MP4 com a música no lugar.

| Ação | Como |
|---|---|
| mover um clipe | arrastar |
| ajuste fino | Shift + arrastar, ou ←/→ (10 ms; com Shift, 1 ms) |
| sem ímã | Ctrl + arrastar |
| ir para um ponto | clicar no clipe ou arrastar na régua |
| zoom / rolar | roda do mouse / Shift + roda ou botão direito |
| tocar / pausar | Espaço |
| desfazer / refazer | Ctrl+Z / Ctrl+Shift+Z |

## Instalar

**Linux (Ubuntu, Mint, Debian):**

    sudo apt install ./dist/portinho_1.0.0_amd64.deb

Aparece no menu como *Portinho*; no terminal, `portinho`. Para remover: `sudo apt remove portinho`.
Sem instalar: extraia `portinho_1.0.0_linux_x86_64.tar.gz` e rode `portinho/portinho`.

**Windows:** `Portinho-Setup-1.0.0.exe` (instalador, não pede administrador) ou `Portinho.exe` (portátil).

Problemas? `portinho --selftest` confere ffmpeg, download do YouTube, som e vídeo.

## Compilar

- **Linux:** `./packaging/build_linux.sh` → `dist/*.deb` e `dist/*.tar.gz`
- **Windows:** instale Python 3.11+ e [Inno Setup 6](https://jrsoftware.org/isinfo.php), rode `build.bat`
  → `dist\Portinho-Setup-1.0.0.exe` e `dist\Portinho.exe`
- **GitHub:** o workflow `.github/workflows/build.yml` gera os dois (Windows e Linux) a cada push,
  em *Actions → build → Artifacts*.

## Desenvolvimento

    pip install -r requirements.txt
    python run.py [vídeo] [música]
    QT_QPA_PLATFORM=offscreen python tests/test_gui.py video.mp4   # 32 testes da interface
