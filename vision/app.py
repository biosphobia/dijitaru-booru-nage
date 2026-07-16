"""Single entry point for the portable BooruVision executable.

Double-click (or run with no arguments) for an interactive menu, or use
subcommands:

  BooruVision calibrate            camera -> screen calibration
  BooruVision detect               run the ball tracker (default)
  BooruVision test [x y [color]]   send one fake hit to the game
"""

import sys

BANNER = r"""
  Dijitaru Booru Nage - vision tools
  ----------------------------------
  1) calibrate  - aim the camera, game must show the calibration screen (press C in game)
  2) detect     - start the ball tracker (do this after calibrating)
  3) test       - send one fake hit to the middle of the game screen
  q) quit
"""


def menu():
    print(BANNER)
    while True:
        choice = input("choose [1/2/3/q]: ").strip().lower()
        if choice in ("1", "calibrate"):
            return "calibrate", []
        if choice in ("2", "detect", ""):
            return "detect", []
        if choice in ("3", "test"):
            return "test", ["0.5", "0.5"]
        if choice in ("q", "quit", "exit"):
            return None, []


def run(cmd, args):
    if cmd == "calibrate":
        import calibrate
        calibrate.main()
    elif cmd == "detect":
        import detect
        detect.main()
    elif cmd == "test":
        import test_hit
        test_hit.main(args or ["0.5", "0.5"])
    else:
        print(__doc__)
        raise SystemExit(1)


def main():
    if len(sys.argv) > 1:
        cmd, args = sys.argv[1], sys.argv[2:]
    else:
        cmd, args = menu()
        if cmd is None:
            return
    try:
        run(cmd, args)
    except SystemExit as e:
        if e.code not in (0, None):
            print(e)
        # In the double-clicked executable, keep the window open so error
        # messages can actually be read.
        if getattr(sys, "frozen", False):
            input("\nPress Enter to close...")
        raise
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
