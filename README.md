# Portinho

Troque a música de um vídeo do YouTube por um arquivo do seu PC, alinhando pelo espectrograma.

## Como baixar e instalar

### Windows

1. Abra a página de **[Releases](https://github.com/paulocremas/portinho/releases/latest)** e baixe
   **`Portinho-Setup-1.0.0.exe`**.
2. Dê **dois cliques** no arquivo baixado e siga *Avançar → Instalar* (não pede senha de administrador).
   Se aparecer *"O Windows protegeu o computador"*, clique em **Mais informações → Executar assim mesmo**.
3. Abra o **Portinho** pelo menu Iniciar ou pelo atalho na área de trabalho.

Prefere sem instalar? Baixe **`Portinho.exe`** e é só abrir.

### Linux

1. Abra a página de **[Releases](https://github.com/paulocremas/portinho/releases/latest)** e baixe
   o arquivo **`portinho_1.0.0_amd64.deb`**.
2. Na pasta *Downloads*, dê **dois cliques** no arquivo e clique em **Instalar** (vai pedir sua senha).
   Pelo terminal: `sudo apt install ~/Downloads/portinho_1.0.0_amd64.deb`
3. Abra o **Portinho** pelo menu de aplicativos.

**Sem senha de administrador:** baixe `portinho_1.0.0_linux_x86_64.tar.gz`, clique com o botão direito
→ *Extrair aqui*, entre na pasta `portinho` e dê dois cliques em **`instalar.sh`** (escolha *Executar*).

Depois de instalado, o Portinho avisa sozinho quando sair uma versão nova.

## Como usar

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
| tela cheia | botão ⛶, tecla F ou duplo clique no vídeo (Esc sai) |
| janela flutuante | botão ao lado da tela cheia; fechar a janela devolve o vídeo |

Tela cheia e janela flutuante não pausam nem dessincronizam a reprodução.

**Atualizações:** ao abrir, o Portinho checa se há internet e uma versão nova em
[Releases](https://github.com/paulocremas/portinho/releases). Se houver, pergunta se você quer
atualizar e mostra o download e a instalação. Sem internet ou sem novidade, abre normalmente.

## Instalar

**Linux (Ubuntu, Mint, Debian):**

    sudo apt install ./dist/portinho_1.0.0_amd64.deb

Aparece no menu como *Portinho*; no terminal, `portinho`. Para remover: `sudo apt remove portinho`.
Sem senha: extraia `portinho_1.0.0_linux_x86_64.tar.gz` e rode `portinho/instalar.sh`
(instala no seu usuário, com tela de progresso; para remover, `portinho --uninstall`).
Ou rode direto `portinho/portinho`, sem instalar.

**Windows:** `Portinho-Setup-1.0.0.exe` (instalador, não pede administrador) ou `Portinho.exe` (portátil).

Problemas? `portinho --selftest` confere ffmpeg, download do YouTube, som e vídeo;
`portinho --check-update` mostra a versão, o tipo de instalação e se há atualização.

## Compilar

- **Linux:** `./packaging/build_linux.sh` → `dist/*.deb` e `dist/*.tar.gz`
- **Windows:** instale Python 3.11+ e [Inno Setup 6](https://jrsoftware.org/isinfo.php), rode `build.bat`
  → `dist\Portinho-Setup-1.0.0.exe` e `dist\Portinho.exe`
- **GitHub:** o workflow `.github/workflows/build.yml` gera os dois (Windows e Linux) a cada push,
  em *Actions → build → Artifacts*.

## Desenvolvimento

    pip install -r requirements.txt
    python run.py [vídeo] [música]
    QT_QPA_PLATFORM=offscreen python tests/test_gui.py video.mp4          # interface
    QT_QPA_PLATFORM=offscreen python tests/test_update.py                 # atualizador
    QT_QPA_PLATFORM=offscreen python tests/test_e2e_linux.py dist/*.tar.gz  # pacote real
