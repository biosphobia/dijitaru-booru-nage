"""Send a fake hit packet to the game, no camera needed.

Examples:
  python test_hit.py 0.5 0.5           # hit the middle of the screen
  python test_hit.py 0.2 0.8 red       # hit bottom-left area, red ball
"""

import json
import socket
import sys

from common import load_config


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    config = load_config()
    packet = {
        "type": "hit",
        "x": float(sys.argv[1]),
        "y": float(sys.argv[2]),
        "color": sys.argv[3] if len(sys.argv) > 3 else "unknown",
    }
    addr = (config.get("udp_host", "127.0.0.1"), config.get("udp_port", 4242))
    socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(
        json.dumps(packet).encode("utf-8"), addr
    )
    print("sent", packet, "to udp://%s:%d" % addr)


if __name__ == "__main__":
    main()
