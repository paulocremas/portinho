#!/usr/bin/env bash
# Gera dist/portinho/ (app), dist/portinho_<versão>_amd64.deb (instalador) e um .tar.gz portátil.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=".venv/bin/python"

if [ ! -x "$PY" ]; then
    if command -v uv >/dev/null; then uv venv -q .venv; else python3 -m venv .venv; fi
fi
if command -v uv >/dev/null; then uv pip install -q --python "$PY" -r requirements.txt
else "$PY" -m pip install -q -r requirements.txt; fi

# deno: o yt-dlp precisa dele para abrir todos os formatos do YouTube
mkdir -p build/deno
if [ ! -x build/deno/deno ]; then
    curl -fsSL -o build/deno/deno.zip \
        https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip
    (cd build/deno && unzip -oq deno.zip && rm deno.zip)
fi

VERSION=$("$PY" -c "import portinho; print(portinho.__version__)")
QT_QPA_PLATFORM=offscreen "$PY" packaging/make_icon.py >/dev/null

"$PY" -m PyInstaller --noconfirm --clean --onedir --windowed --name portinho \
    --icon assets/icon.png \
    --add-data "assets:assets" \
    --add-binary "build/deno/deno:." \
    --collect-all imageio_ffmpeg \
    --collect-all yt_dlp_ejs \
    --collect-submodules yt_dlp \
    run.py

# libxcb-cursor0: o Qt precisa dela no X11 e muitas distros não instalam por padrão.
# Embute no pacote para o .tar.gz portátil abrir em qualquer lugar.
INTERNAL=dist/portinho/_internal
if [ ! -e "$INTERNAL/libxcb-cursor.so.0" ]; then
    LIB=$(ldconfig -p | awk '/libxcb-cursor.so.0 /{print $NF; exit}')
    if [ -n "$LIB" ]; then
        cp -L "$LIB" "$INTERNAL/"
    else
        mkdir -p build/xcbcursor && (cd build/xcbcursor && apt-get download libxcb-cursor0 >/dev/null \
            && dpkg-deb -x libxcb-cursor0_*.deb x)
        cp -L build/xcbcursor/x/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0 "$INTERNAL/"
    fi
fi

# ---------- .deb ----------
PKG="build/deb/portinho_${VERSION}_amd64"
rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/512x512/apps"
cp -a dist/portinho "$PKG/opt/portinho"
ln -s /opt/portinho/portinho "$PKG/usr/bin/portinho"
cp packaging/portinho.desktop "$PKG/usr/share/applications/portinho.desktop"
cp assets/icon.png "$PKG/usr/share/icons/hicolor/512x512/apps/portinho.png"
chmod -R u+rwX,go+rX,go-w "$PKG"
SIZE=$(du -sk "$PKG" | cut -f1)
cat > "$PKG/DEBIAN/control" <<CTRL
Package: portinho
Version: ${VERSION}
Section: video
Priority: optional
Architecture: amd64
Depends: libportaudio2, libegl1, libgl1, libxkbcommon-x11-0
Installed-Size: ${SIZE}
Maintainer: Paulo Cremasco <cremascopaulo@gmail.com>
Description: Troque a música de um vídeo do YouTube
 Cole o link do YouTube, escolha a música e arraste os espectrogramas
 até encaixar. O vídeo toca sem o som original; exporta MP4.
CTRL
cat > "$PKG/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
exit 0
POST
chmod 755 "$PKG/DEBIAN/postinst"
fakeroot dpkg-deb --build -Zxz "$PKG" "dist/portinho_${VERSION}_amd64.deb" >/dev/null

# ---------- portátil (com instalador gráfico) ----------
rm -rf build/tar && mkdir -p build/tar
cp -al dist/portinho build/tar/portinho
cat > build/tar/portinho/instalar.sh <<'INST'
#!/bin/sh
# Instala o Portinho no seu usuário (menu de aplicativos), com tela de progresso. Não pede senha.
exec "$(dirname "$(readlink -f "$0")")/portinho" --install
INST
chmod 755 build/tar/portinho/instalar.sh
tar -C build/tar -czf "dist/portinho_${VERSION}_linux_x86_64.tar.gz" portinho

echo
echo "Pronto:"
ls -lh dist/*.deb dist/*.tar.gz
