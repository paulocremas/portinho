import os
import subprocess
import sys


def _ensure_own_bundle():
    """No .exe portátil (onefile), um Portinho reaberto por outro (ex.: depois de atualizar) pode herdar
    a pasta temporária do processo antigo, que é apagada quando ele fecha -> "No module named ...".
    Cada pacote leva uma marca com a sua versão; se a pasta não for a nossa, reabre limpo."""
    if not getattr(sys, "frozen", False) or os.environ.get("PYINSTALLER_RESET_ENVIRONMENT") == "1":
        return
    from portinho import __version__
    mark = os.path.join(getattr(sys, "_MEIPASS", ""), "portinho_build.txt")
    try:
        ok = open(mark, encoding="utf-8").read().strip() == __version__
    except OSError:
        ok = False
    if not ok:
        from portinho.updater import clean_env
        subprocess.Popen([sys.executable] + sys.argv[1:], env=clean_env(), close_fds=True)
        sys.exit(0)


if __name__ == "__main__":
    _ensure_own_bundle()
    if "--selftest" in sys.argv:
        from portinho.selftest import run
        sys.exit(run(sys.argv[1:]))
    if "--check-update" in sys.argv:
        from portinho import __version__, updater
        info = updater.check()
        print(f"versão {__version__} · instalação: {updater.install_kind()} · internet: {updater.has_internet()}")
        print(f"atualização: {info.version} ({info.asset_name})" if info else "atualização: nenhuma")
        sys.exit(0)
    if "--install" in sys.argv or "--uninstall" in sys.argv:
        from portinho.installer_ui import run
        sys.exit(run(uninstall="--uninstall" in sys.argv))
    from portinho.app import main
    main()
