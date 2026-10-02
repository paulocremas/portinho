import sys

if __name__ == "__main__":
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
