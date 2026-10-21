"""Desktop launch by default; explicit component flags run in the terminal."""
import argparse
import sys

from . import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(description='Control ComfyUI from the desktop or an SSH terminal.')
    parser.add_argument('--version', action='version', version=f'ComfyUI Control {__version__}')
    parser.add_argument('--start-server', action='store_true', help='Start the configured ComfyUI server in the foreground, without a desktop window.')
    parser.add_argument('--start-webui', action='store_true', help='Start the Mobile WebUI with saved network/authentication settings for this run.')
    parser.add_argument('--demo-webui', action='store_true', help='Preview the real WebUI with temporary sample data and simulated generation; no ComfyUI setup required.')
    parser.add_argument('--demo-host', default=None, help='Demo listening IP (default: 127.0.0.1; use 0.0.0.0 for LAN access).')
    parser.add_argument('--demo-port', type=int, default=None, help='Demo listening port (default: 8190).')
    options = parser.parse_args(argv)
    if options.demo_webui:
        if options.start_server or options.start_webui:
            parser.error('--demo-webui cannot be combined with --start-server or --start-webui.')
        try:
            from .mobile.demo import run
            return run(host=options.demo_host or '127.0.0.1', port=options.demo_port if options.demo_port is not None else 8190)
        except (ImportError, OSError, ValueError) as exc:
            print(f'Could not start demo WebUI: {exc}\nFor missing Qt/system libraries, see docs/SSH.md (Headless system dependencies).', file=sys.stderr)
            return 1
    if options.demo_host is not None or options.demo_port is not None:
        parser.error('--demo-host and --demo-port require --demo-webui.')
    if options.start_server or options.start_webui:
        from .headless import run
        return run(start_server=options.start_server, start_webui=options.start_webui)
    from .app import desktop_main
    return desktop_main()


if __name__ == '__main__':
    raise SystemExit(main())
