"""Ball tracker: watches the wall through the webcam, detects ball impacts
and sends them to the Godot game as UDP "hit" packets.

Run calibrate.py first, then:  python detect.py

How a hit is detected (config "mode"):
  "reversal" - a fast-moving blob whose direction of travel suddenly flips
               (the ball bouncing off the wall). Use this for real play.
  "instant"  - the first time a new fast-moving blob is seen. Handy for
               desk-testing by waving a ball in front of the camera.

Preview window keys:  Q = quit
"""

import json
import socket
import time
from collections import deque

import cv2
import numpy as np

from common import (
    load_config,
    load_calibration,
    open_camera,
    camera_to_game,
    game_area_polygon_px,
)
from studio import MeshyStudio


class Track:
    """One moving blob followed across frames."""

    _next_id = 0

    def __init__(self, pos, radius, frame_idx):
        self.id = Track._next_id
        Track._next_id += 1
        self.positions = deque(maxlen=8)  # processing-scale pixels
        self.radii = deque(maxlen=8)
        self.positions.append(pos)
        self.radii.append(radius)
        self.last_seen = frame_idx
        self.hit_fired = False

    def add(self, pos, radius, frame_idx):
        self.positions.append(pos)
        self.radii.append(radius)
        self.last_seen = frame_idx


def classify_color(frame_bgr, pos, radius, color_defs):
    """Ball color near pos -> color name or 'unknown'.

    The sample patch inevitably contains background pixels (the blob
    centroid lags the ball), so classify by the median of only the
    *colorful* pixels in the patch instead of the whole-patch median.
    """
    h, w = frame_bgr.shape[:2]
    x, y = int(pos[0]), int(pos[1])
    r = max(4, int(radius))
    x0, x1 = max(0, x - r), min(w, x + r)
    y0, y1 = max(0, y - r), min(h, y + r)
    if x0 >= x1 or y0 >= y1:
        return "unknown"
    patch = cv2.cvtColor(frame_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2HSV).reshape(-1, 3)
    lowest_s = min((c.get("s_min", 60) for c in color_defs), default=60)
    lowest_v = min((c.get("v_min", 60) for c in color_defs), default=60)
    colorful = patch[(patch[:, 1] >= lowest_s) & (patch[:, 2] >= lowest_v)]
    if len(colorful) < max(8, 0.1 * len(patch)):
        return "unknown"
    hue, sat, val = np.median(colorful, axis=0)
    for c in color_defs:
        if sat < c.get("s_min", 60) or val < c.get("v_min", 60):
            continue
        h_min, h_max = c["h_min"], c["h_max"]
        if h_min <= h_max:
            if h_min <= hue <= h_max:
                return c["name"]
        else:  # hue wrap-around (red)
            if hue >= h_min or hue <= h_max:
                return c["name"]
    return "unknown"


def main():
    config = load_config()
    # Calibration is only needed to map ball hits to game coordinates.
    # The camera, the Model Studio and the live viewfinder must work
    # without it, so start anyway and just disable hit detection.
    try:
        homography, calib_size = load_calibration()
    except SystemExit as e:
        print("WARNING: %s" % e)
        print("Running WITHOUT hit detection (camera + Model Studio only).")
        homography, calib_size = None, None
    cam = open_camera(config)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_addr = (config.get("udp_host", "127.0.0.1"), config.get("udp_port", 4242))

    # command channel: the game sends Model Studio commands here
    cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cmd_sock.bind(("127.0.0.1", config.get("udp_cmd_port", 4243)))
    cmd_sock.setblocking(False)
    studio = MeshyStudio(
        config, lambda event: sock.sendto(json.dumps(event).encode("utf-8"), udp_addr)
    )

    det = config.get("detection", {})
    proc_width = det.get("processing_width", 640)
    min_area = det.get("min_area", 30)
    max_area = det.get("max_area", 2500)
    min_circularity = det.get("min_circularity", 0.4)
    min_speed = det.get("min_speed", 6.0)  # px/frame at processing scale
    max_match_dist = det.get("max_match_dist", 90.0)
    track_timeout = det.get("track_timeout_frames", 5)
    mode = det.get("mode", "reversal")
    # contact = a sharp trajectory break: the direction must change by at
    # least this many degrees between incoming and outgoing motion
    min_turn_deg = det.get("min_turn_deg", 60.0)
    min_cos = np.cos(np.radians(min_turn_deg))
    # a blob must have been tracked this many frames before it can fire -
    # something merely appearing inside the projection is never a hit
    min_track_frames = det.get("min_track_frames", 3)
    cooldown_ms = det.get("cooldown_ms", 250)
    cooldown_radius = det.get("cooldown_radius", 0.06)  # normalized game units
    preview = config.get("preview", True)
    color_defs = config.get("colors", [])

    print("Sending hits to udp://%s:%d  (mode: %s)" % (udp_addr[0], udp_addr[1], mode))

    prev_gray = None
    tracks = []
    recent_hits = []  # (time, normalized_pos)
    recent_frames = deque(maxlen=4)  # small color frames, for sampling pre-impact color
    frame_idx = 0
    game_poly = None

    while True:
        ok, frame = cam.read()
        if not ok:
            raise SystemExit("Camera stopped delivering frames.")
        frame_idx += 1

        # Model Studio commands from the game (photo capture, generation...)
        while True:
            try:
                raw, _ = cmd_sock.recvfrom(4096)
            except (BlockingIOError, InterruptedError):
                break
            try:
                cmd = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(cmd, dict):
                studio.handle(cmd, frame)
        studio.stream_frame(frame)

        h, w = frame.shape[:2]
        scale = proc_width / float(w)
        small = cv2.resize(frame, (proc_width, int(h * scale)))

        if homography is None:
            # uncalibrated: camera + studio only, no hit detection
            if preview:
                cv2.putText(small, "NO CALIBRATION - hits disabled", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                cv2.imshow("detect", small)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
            continue

        recent_frames.append(small)
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)

        if game_poly is None:
            game_poly = game_area_polygon_px(
                homography, calib_size, (small.shape[1], small.shape[0])
            )

        if prev_gray is None:
            prev_gray = gray
            continue

        # --- motion detection -------------------------------------------
        diff = cv2.absdiff(gray, prev_gray)
        prev_gray = gray
        _, mask = cv2.threshold(diff, det.get("diff_threshold", 25), 255, cv2.THRESH_BINARY)
        mask = cv2.dilate(mask, None, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if not (min_area <= area <= max_area):
                continue
            perimeter = cv2.arcLength(cnt, True)
            if perimeter <= 0:
                continue
            circularity = 4.0 * np.pi * area / (perimeter * perimeter)
            if circularity < min_circularity:
                continue
            (cx, cy), radius = cv2.minEnclosingCircle(cnt)
            detections.append(((cx, cy), radius))

        # --- track association (nearest neighbour) ----------------------
        unmatched = list(range(len(detections)))
        for track in tracks:
            best, best_d = None, max_match_dist
            for i in unmatched:
                d = np.hypot(
                    detections[i][0][0] - track.positions[-1][0],
                    detections[i][0][1] - track.positions[-1][1],
                )
                if d < best_d:
                    best, best_d = i, d
            if best is not None:
                track.add(detections[best][0], detections[best][1], frame_idx)
                unmatched.remove(best)
        for i in unmatched:
            tracks.append(Track(detections[i][0], detections[i][1], frame_idx))
        tracks = [t for t in tracks if frame_idx - t.last_seen <= track_timeout]

        # --- hit detection ----------------------------------------------
        for track in tracks:
            if track.hit_fired or track.last_seen != frame_idx:
                continue
            p = track.positions
            hit_pos = None
            hit_radius = 0.0
            if mode == "instant" and len(p) >= 2:
                if np.hypot(p[-1][0] - p[-2][0], p[-1][1] - p[-2][1]) >= min_speed:
                    hit_pos = p[-1]
                    hit_radius = track.radii[-1]
            elif mode == "reversal" and len(p) >= min_track_frames:
                # Wall contact = a sharp break in the trajectory: the blob was
                # moving fast, then its direction changed by >= min_turn_deg
                # (a clean bounce flips ~180 deg; a dead bounce that drops
                # down the wall turns ~90 deg - both count). span=1 catches a
                # flip between adjacent frames; span=2 skips over the
                # near-stationary frame right at the impact point.
                for span in (1, 2):
                    if len(p) < 2 * span + 1:
                        continue
                    mid = -1 - span
                    v1 = (p[mid][0] - p[mid - span][0], p[mid][1] - p[mid - span][1])
                    v2 = (p[-1][0] - p[mid][0], p[-1][1] - p[mid][1])
                    n1, n2 = np.hypot(*v1), np.hypot(*v2)
                    incoming_speed = n1 / span
                    if incoming_speed < min_speed or n2 < 1e-6:
                        continue
                    cos_turn = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
                    if cos_turn <= min_cos:
                        hit_pos = p[mid]  # the turning point = the wall contact
                        hit_radius = track.radii[mid]
                        break
            if hit_pos is None:
                continue
            track.hit_fired = True

            # Transform the hit point plus a point one ball-radius away, so
            # the game can draw the mark at the ball's real projected size.
            mapped = camera_to_game(
                [hit_pos, (hit_pos[0] + hit_radius, hit_pos[1])],
                homography, (small.shape[1], small.shape[0]), calib_size,
            )
            norm = mapped[0]
            r_norm = float(np.hypot(*(mapped[1] - mapped[0])))  # fraction of screen width-ish
            if not (-0.02 <= norm[0] <= 1.02 and -0.02 <= norm[1] <= 1.02):
                continue  # outside the projected game area
            norm = np.clip(norm, 0.0, 1.0)

            # cooldown: ignore near-duplicate hits (double bounces etc.)
            now = time.monotonic()
            recent_hits[:] = [
                (t, pos) for t, pos in recent_hits if (now - t) * 1000.0 < cooldown_ms
            ]
            if any(np.hypot(norm[0] - pos[0], norm[1] - pos[1]) < cooldown_radius
                   for _, pos in recent_hits):
                continue
            recent_hits.append((now, (float(norm[0]), float(norm[1]))))

            # sample the ball color a couple of frames back, while it was
            # still in flight (less contaminated by the projection); frame
            # and position index must match so we sample where the ball WAS
            back = min(3, len(p), len(recent_frames))
            color = classify_color(recent_frames[-back], p[-back], 8, color_defs)

            packet = {
                "type": "hit",
                "x": round(float(norm[0]), 4),
                "y": round(float(norm[1]), 4),
                "r": round(r_norm, 4),
                "color": color,
            }
            sock.sendto(json.dumps(packet).encode("utf-8"), udp_addr)
            print("HIT", packet)
            if preview:
                cv2.circle(small, (int(hit_pos[0]), int(hit_pos[1])), 18, (0, 0, 255), 3)

        # --- preview ------------------------------------------------------
        if preview:
            cv2.polylines(small, [game_poly], True, (0, 200, 0), 2)
            for track in tracks:
                pts = np.array(track.positions, dtype=np.int32)
                cv2.polylines(small, [pts], False, (255, 180, 0), 2)
                cv2.circle(small, (int(pts[-1][0]), int(pts[-1][1])), 4, (255, 180, 0), -1)
            cv2.imshow("detect", small)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break

    cam.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
