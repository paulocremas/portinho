import sys

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        from portinho.selftest import run
        sys.exit(run(sys.argv[1:]))
    from portinho.app import main
    main()
