"""Entry point: python -m spacedrums_trainer [--fullscreen] [--port PORT] [--no-bloom]"""

from __future__ import annotations

import argparse

from . import config
from .hub import Hub
from .kit import Kit
from .profile import Profile
from .scheduler import Scheduler


def main():
    parser = argparse.ArgumentParser(prog="spacedrums_trainer")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--no-bloom", action="store_true")
    parser.add_argument("--port", help="serial port of the hub, e.g. /dev/ttyACM0 or COM3")
    parser.add_argument("--no-metronome", action="store_true")
    args = parser.parse_args()

    settings = config.load()
    if args.port:
        settings["port"] = args.port
    if args.no_metronome:
        settings["metronome"] = False

    # Audio first: the mixer needs its small buffer set before pygame.init().
    kit = Kit(volume=settings.get("volume", 0.9))

    from .ui.app import App
    from .ui.screens.home import HomeScreen

    app = App(fullscreen=args.fullscreen, bloom=not args.no_bloom)
    app.kit = kit
    app.scheduler = Scheduler()
    app.profile = Profile()
    app.settings = settings
    app.hub = Hub(kit, port=settings.get("port"), baud=settings.get("baud", 500000))

    if kit.missing:
        app.toast("Missing samples: " + ", ".join(kit.missing[:3]), 6.0)

    app.push(HomeScreen(app))
    try:
        app.run()
    finally:
        app.profile.save()


if __name__ == "__main__":
    main()
