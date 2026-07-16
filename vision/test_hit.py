"""Send a fake hit packet to the game, no camera needed.

Examples:
  python test_hit.py 0.5 0.5           # hit the middle of the screen
  python test_hit.py 0.2 0.8 red       # hit bottom-left area, red ball
"""

import json
import socket
import sys

from common import load_config


def main(args=None):
    if args is None:
        args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        raise SystemExit(1)
    config = load_config()
    packet = {
        "type": "hit",
        "x": float(args[0]),
        "y": float(args[1]),
        "color": args[2] if len(args) > 2 else "unknown",
    }
    addr = (config.get("udp_host", "127.0.0.1"), config.get("udp_port", 4242))
    socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(
        json.dumps(packet).encode("utf-8"), addr
    )
    print("sent", packet, "to udp://%s:%d" % addr)


if __name__ == "__main__":
    main()
