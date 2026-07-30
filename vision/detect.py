"""Ball tracker: watches the wall through the camera, detects ball impacts
and sends them to the Godot game as UDP "hit" packets.

Run calibrate.py first, then:  python detect.py

Built for the reality of a small fast ball on a noisy camera (PS3 Eye):
  - the threshold floats above the measured sensor grain automatically
  - grain specks are erased by morphological opening before blob search
  - a fast ball shows up as a motion-blur STREAK, not a circle - blobs
    are accepted by area, tracked by centroid, and the ball radius is
    taken from the streak's narrow side
  - a hit ("reversal" mode) requires a consistent straight fast approach
    (a thrown ball flies straight; grain and light artifacts do not)
    followed by a sharp direction break - the bounce off the wall

"instant" mode fires on any short consistent motion instead - handy for
desk-testing by waving a ball in front of the camera.

Preview window keys:  Q = quit   M = toggle motion-mask view
"""

import json
import socket
import time
from collections import deque

import cv2
import numpy as np

from common import load_config, load_calibration, open_camera
from studio import MeshyStudio


class Track:
    """One moving blob followed across frames."""

    _next_id = 0

    def __init__(self, pos, radius, frame_idx):
        self.id = Track._next_id
        Track._next_id += 1
        self.positions = deque(maxlen=12)  # processing-scale pixels
        self.radii = deque(maxlen=12)
        self.frames = deque(maxlen=12)  # frame index of each observation
        self.positions.append(pos)
        self.radii.append(radius)
        self.frames.append(frame_idx)
        self.last_seen = frame_idx
        self.hit_fired = False

    def add(self, pos, radius, frame_idx):
        self.positions.append(pos)
        self.radii.append(radius)
        self.frames.append(frame_idx)
        self.last_seen = frame_idx


def consistent_direction(steps, min_speed, straight_cos, speed_ratio=3.0):
    """If every step is fast, aligned with the mean direction, and of
    similar length, return the mean direction (unit vector); else None.
    A real thrown ball moves fast, straight, and at near-constant speed -
    sensor grain and chained flicker artifacts do none of that."""
    units, speeds = [], []
    for s in steps:
        n = np.hypot(s[0], s[1])
        if n < min_speed:
            return None
        units.append(s / n)
        speeds.append(n)
    if max(speeds) > speed_ratio * min(speeds):
        return None
    mean = np.sum(units, axis=0)
    norm = np.hypot(mean[0], mean[1])
    if norm < 1e-9:
        return None
    mean /= norm
    if any(float(u @ mean) < straight_cos for u in units):
        return None
    return mean


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
        mapper = load_calibration()
    except SystemExit as e:
        print("WARNING: %s" % e)
        print("Running WITHOUT hit detection (camera + Model Studio only).")
        mapper = None
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
    # reported to the game via pong events so it can show tracking state
    studio.calibrated = mapper is not None

    det = config.get("detection", {})
    proc_width = det.get("processing_width", 640)
    min_area = det.get("min_area", 30)
    max_area = det.get("max_area", 2500)
    min_speed = det.get("min_speed", 6.0)  # px/frame at processing scale
    max_match_dist = det.get("max_match_dist", 55.0)
    track_timeout = det.get("track_timeout_frames", 5)
    mode = det.get("mode", "reversal")
    # contact = a sharp trajectory break: the direction must change by at
    # least this many degrees between incoming and outgoing motion
    min_turn_deg = det.get("min_turn_deg", 60.0)
    min_cos = np.cos(np.radians(min_turn_deg))
    # a hit needs this many consecutive fast, straight steps before the
    # turn - noise cannot fake a real approach flight
    approach_frames = det.get("approach_frames", 4)
    straight_cos = np.cos(np.radians(det.get("straightness_deg", 45.0)))
    # observations allowed to cluster at the contact point before receding
    hover_max = det.get("hover_max", 3)
    # motion-diff centroids trail the ball by ~half a streak; nudge the
    # contact estimate forward along the approach by this * approach speed
    lag_correction = det.get("lag_correction", 0.5)
    base_threshold = det.get("diff_threshold", 25)
    auto_threshold = det.get("auto_threshold", True)
    noise_multiplier = det.get("noise_multiplier", 6.0)
    cooldown_ms = det.get("cooldown_ms", 250)
    cooldown_radius = det.get("cooldown_radius", 0.06)  # normalized game units
    preview = config.get("preview", True)
    show_mask = False
    color_defs = config.get("colors", [])
    kernel3 = np.ones((3, 3), np.uint8)

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

        if mapper is None:
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
            game_poly = mapper.game_polygon_px((small.shape[1], small.shape[0]))

        if prev_gray is None:
            prev_gray = gray
            continue

        # --- motion detection -------------------------------------------
        diff = cv2.absdiff(gray, prev_gray)
        prev_gray = gray
        thr = float(base_threshold)
        if auto_threshold:
            # most pixels are static, so the median absolute difference is
            # the sensor grain level - float the threshold above it
            thr = max(thr, noise_multiplier * float(np.median(diff[::4, ::4])))
        _, mask = cv2.threshold(diff, thr, 255, cv2.THRESH_BINARY)
        # opening erases isolated grain specks; the dilation afterwards
        # reconnects the ball's motion-blur streak
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel3)
        mask = cv2.dilate(mask, kernel3, iterations=1)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if not (min_area <= area <= max_area):
                continue
            m = cv2.moments(cnt)
            if m["m00"] <= 0:
                continue
            center = (m["m10"] / m["m00"], m["m01"] / m["m00"])
            # a fast ball is a motion-blur streak: its narrow side is the
            # ball diameter no matter how fast it flies
            (_, (rw, rh), _) = cv2.minAreaRect(cnt)
            radius = max(2.0, min(rw, rh) / 2.0)
            detections.append((center, radius))

        # --- track association --------------------------------------------
        # Constant-velocity prediction: a moving ball's blob chain matches
        # its own predicted continuation, so the streak's leading and
        # trailing diff blobs form separate stable chains instead of
        # cross-stealing each other's detections. (Both chains see the
        # bounce; the duplicate hit is absorbed by the cooldown.)
        unmatched = list(range(len(detections)))
        for track in tracks:
            if len(track.positions) >= 2:
                lx, ly = track.positions[-1]
                qx, qy = track.positions[-2]
                pred = (2.0 * lx - qx, 2.0 * ly - qy)
            else:
                pred = track.positions[-1]
            best, best_d = None, max_match_dist
            for i in unmatched:
                d = np.hypot(detections[i][0][0] - pred[0],
                             detections[i][0][1] - pred[1])
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
            p = [np.array(pt, dtype=np.float64) for pt in track.positions]
            hit_pos = None
            hit_radius = 0.0
            hit_span = 0  # how many frames ago the contact frame was
            if mode == "instant" and len(p) >= 3:
                steps = [p[-2] - p[-3], p[-1] - p[-2]]
                if consistent_direction(steps, min_speed, straight_cos) is not None:
                    hit_pos = p[-1]
                    hit_radius = track.radii[-1]
            elif mode == "reversal":
                # Wall contact has a fixed physical shape:
                #   1. consistent straight fast APPROACH (a real thrown
                #      ball; grain and flicker cannot fake one)
                #   2. optional short HOVER: observations clustered at the
                #      contact point (the streak folds onto itself)
                #   3. RECEDE: two consecutive observations moving away,
                #      turned >= min_turn_deg from the approach (a clean
                #      bounce ~180 deg, a dead drop down the wall ~90 deg).
                #      A one-frame light artifact can never recede twice.
                f = list(track.frames)
                n = len(p)
                for e in range(n - 3, n - 4 - hover_max, -1):
                    if e < approach_frames:
                        break
                    # approach must be a gap-free frame run - a fast ball is
                    # detected every frame at 60 fps, chained noise is not;
                    # hover/recede may miss a couple (impact diff is small)
                    if f[e] - f[e - approach_frames] != approach_frames:
                        continue
                    if f[-1] - f[e] > (n - 1 - e) + 1:
                        continue
                    steps = [p[i + 1] - p[i]
                             for i in range(e - approach_frames, e)]
                    incoming = consistent_direction(steps, min_speed, straight_cos)
                    if incoming is None:
                        continue
                    speed = float(np.mean([np.hypot(s[0], s[1]) for s in steps]))
                    hover = [p[i] for i in range(e + 1, n - 2)]
                    if any(np.hypot(*(q - p[e])) > speed * 1.2 for q in hover):
                        continue
                    v_a = p[-2] - p[e]
                    v_b = p[-1] - p[e]
                    n_a = np.hypot(v_a[0], v_a[1])
                    n_b = np.hypot(v_b[0], v_b[1])
                    if n_a < 2.0 or n_b <= n_a:
                        continue  # not receding over both post-turn frames
                    # both post-turn observations must lie on the turned side
                    if float(v_a @ incoming) / n_a > np.cos(np.radians(0.6 * min_turn_deg)):
                        continue
                    if float(v_b @ incoming) / n_b <= min_cos:
                        # contact = the hover cluster, nudged forward by the
                        # half-streak lag of motion-diff centroids
                        cluster = np.mean([p[e]] + hover, axis=0)
                        hit_pos = cluster + incoming * (speed * lag_correction)
                        hit_radius = track.radii[e]
                        hit_span = n - 1 - e
                        break
            if hit_pos is None:
                continue
            track.hit_fired = True
            hit_pos = (float(hit_pos[0]), float(hit_pos[1]))

            # Transform the hit point plus a point one ball-radius away, so
            # the game can draw the mark at the ball's real projected size.
            mapped = mapper.map_points(
                [hit_pos, (hit_pos[0] + hit_radius, hit_pos[1])],
                (small.shape[1], small.shape[0]),
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

            # sample the ball color from the contact frame at the contact
            # point - that is exactly where and when the ball is in view
            frame_back = min(hit_span + 1, len(recent_frames))
            color = classify_color(recent_frames[-frame_back], hit_pos,
                                   max(4.0, hit_radius), color_defs)

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
            if show_mask:
                small = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
            cv2.polylines(small, [game_poly], True, (0, 200, 0), 2)
            for track in tracks:
                pts = np.array(track.positions, dtype=np.int32)
                cv2.polylines(small, [pts], False, (255, 180, 0), 2)
                cv2.circle(small, (int(pts[-1][0]), int(pts[-1][1])), 4, (255, 180, 0), -1)
            cv2.putText(small, "thr %.0f  blobs %d  M=mask" % (thr, len(detections)),
                        (10, small.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (200, 200, 200), 1)
            cv2.imshow("detect", small)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("m"):
                show_mask = not show_mask

    cam.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
