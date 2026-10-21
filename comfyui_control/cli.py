"""Desktop launch by default; explicit component flags run in the terminal."""
import argparse

from . import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(description='Control ComfyUI from the desktop or an SSH terminal.')
    parser.add_argument('--version', action='version', version=f'ComfyUI Control {__version__}')
    parser.add_argument('--start-server', action='store_true', help='Start the configured ComfyUI server in the foreground, without a desktop window.')
    parser.add_argument('--start-webui', action='store_true', help='Start the Mobile WebUI with saved network/authentication settings for this run.')
    options = parser.parse_args(argv)
    if options.start_server or options.start_webui:
        from .headless import run
        return run(start_server=options.start_server, start_webui=options.start_webui)
    from .app import desktop_main
    return desktop_main()


if __name__ == '__main__':
    raise SystemExit(main())
