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
        self.born = time.monotonic()
        self.hit_fired = False

    def add(self, pos, radius, frame_idx):
        self.positions.append(pos)
        self.radii.append(radius)
        self.frames.append(frame_idx)
        self.last_seen = frame_idx


def consistent_direction(steps, min_speed, straight_cos, adj_ratio=1.7):
    """If the steps look like a real ball in flight, return the mean
    direction (unit vector) and mean speed; else (None, reason).

    A real thrown ball moves fast, straight, and with smoothly changing
    speed (perspective makes it decelerate/accelerate gradually) - sensor
    grain and chained flicker artifacts do none of that. Speeds are
    compared between ADJACENT steps so foreshortening is tolerated."""
    units, speeds = [], []
    for s in steps:
        n = np.hypot(s[0], s[1])
        if n < max(2.0, min_speed * 0.5):
            return None, 0.0, "approach step too slow (%.1f px/frame)" % n
        units.append(s / n)
        speeds.append(n)
    if float(np.mean(speeds)) < min_speed:
        return None, 0.0, "approach too slow on average (%.1f px/frame)" % np.mean(speeds)
    for a, b in zip(speeds, speeds[1:]):
        if max(a, b) > adj_ratio * min(a, b):
            return None, 0.0, "speed jump %.1fx between steps" % (max(a, b) / min(a, b))
    mean = np.sum(units, axis=0)
    norm = np.hypot(mean[0], mean[1])
    if norm < 1e-9:
        return None, 0.0, "no consistent direction"
    mean /= norm
    worst = min(float(u @ mean) for u in units)
    if worst < straight_cos:
        return None, 0.0, "approach not straight (%.0f deg wobble)" % np.degrees(np.arccos(max(-1.0, worst)))
    return mean, float(np.mean(speeds)), ""


# ordering of gate stages, used to report the deepest failure of a track
_STAGE_NAMES = ["short", "gap", "approach", "hover", "recede", "side", "turn"]


def evaluate_contact(p, f, radii, cfg):
    """Check a track's history for the wall-contact signature.

    p: positions (np arrays), f: frame indices, radii: blob radii.
    cfg: dict with approach, min_speed, straight_cos, hover_max, min_cos,
    side_cos, lag.
    Returns (hit, reason): hit = (pos, radius, frames_back) or None;
    reason = human-readable deepest gate failure among candidate windows.
    """
    n = len(p)
    best_stage, best_reason = -1, "track too short (%d observations)" % n
    for e in range(n - 3, n - 4 - cfg["hover_max"], -1):
        if e < cfg["approach"]:
            break

        def fail(stage, reason):
            nonlocal best_stage, best_reason
            idx = _STAGE_NAMES.index(stage)
            if idx > best_stage:
                best_stage, best_reason = idx, reason

        # approach must be a near-gap-free frame run (one miss allowed)
        if f[e] - f[e - cfg["approach"]] > cfg["approach"] + 1:
            fail("gap", "approach had missed frames")
            continue
        if f[-1] - f[e] > (n - 1 - e) + 1:
            fail("gap", "bounce-out had missed frames")
            continue
        steps = [p[i + 1] - p[i] for i in range(e - cfg["approach"], e)]
        incoming, speed, why = consistent_direction(
            steps, cfg["min_speed"], cfg["straight_cos"])
        if incoming is None:
            fail("approach", why)
            continue
        hover = [p[i] for i in range(e + 1, n - 2)]
        hover_limit = max(10.0, speed * 1.2)
        if any(np.hypot(*(q - p[e])) > hover_limit for q in hover):
            fail("hover", "did not stay near the turn point")
            continue
        v_a = p[-2] - p[e]
        v_b = p[-1] - p[e]
        n_a = np.hypot(v_a[0], v_a[1])
        n_b = np.hypot(v_b[0], v_b[1])
        if n_a < 1.5 or n_b <= n_a:
            fail("recede", "did not recede over two frames after the turn")
            continue
        # Contact = the trajectory BREAKS at the wall. A smooth flight
        # never does; a bounce always kinks in direction (image-space turn)
        # or in speed (the wall absorbs the depth component, which barely
        # shows as a turn from a low camera angle but shows as a sudden
        # slowdown). Foreshortening slows a flight gradually - the approach
        # gate's adjacent-step ratio guarantees that - so a step drop below
        # half the last approach step is a real kink.
        cos_turn = float(v_b @ incoming) / n_b
        turned = cos_turn <= cfg["min_cos"]
        out_speed = float(np.hypot(*(p[-1] - p[-2])))
        last_in = float(np.hypot(*(p[e] - p[e - 1])))
        collapsed = out_speed < 0.5 * last_in
        if not (turned or collapsed):
            fail("turn", "no bounce kink (turn %.0f deg, kept %.0f%% speed)"
                 % (np.degrees(np.arccos(np.clip(cos_turn, -1.0, 1.0))),
                    100.0 * out_speed / max(last_in, 1e-6)))
            continue
        cluster = np.mean([p[e]] + hover, axis=0)
        hit_pos = cluster + incoming * (speed * cfg["lag"])
        return (hit_pos, radii[e], n - 1 - e), ""
    return None, best_reason


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
    contact_cfg = {
        "approach": approach_frames,
        "min_speed": min_speed,
        "straight_cos": straight_cos,
        "hover_max": hover_max,
        "min_cos": min_cos,
        "lag": lag_correction,
    }
    # Vanish hits: a ball on a long consistent approach that stops being
    # detected mid-frame (away from the camera edges) has hit the wall -
    # near impact it slows below the motion threshold, so the bounce
    # itself is often invisible. Nothing else enters the projection.
    vanish_hits = det.get("vanish_hits", True)
    vanish_silence = det.get("vanish_silence", 3)     # frames of silence
    vanish_approach = approach_frames + 2             # longer proof needed
    vanish_lead = det.get("vanish_lead", 0.75)        # steps past last obs
    edge_margin = det.get("edge_margin", 25)          # px at processing scale
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
    recent_hits_cam = []  # (time, camera px) - debris suppression for vanish hits
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

        # retire stale tracks; print a post-mortem for any that looked like
        # a real throw but never fired, saying which gate rejected it
        alive = []
        for t in tracks:
            if frame_idx - t.last_seen <= track_timeout:
                alive.append(t)
                continue
            if not t.hit_fired and len(t.positions) >= approach_frames + 3:
                tp = [np.array(q, dtype=np.float64) for q in t.positions]
                speeds = [np.hypot(*(tp[i + 1] - tp[i])) for i in range(len(tp) - 1)]
                if max(speeds) >= min_speed:
                    _, reason = evaluate_contact(
                        tp, list(t.frames), list(t.radii), contact_cfg)
                    tf = list(t.frames)
                    gaps = (tf[-1] - tf[0]) - (len(tf) - 1)
                    path = "|".join("%d,%d" % (q[0], q[1]) for q in tp[-9:])
                    print("MISS track#%d len=%d vmax=%.0f gaps=%d: %s  path=%s"
                          % (t.id, len(tp), max(speeds), gaps, reason, path))
        tracks = alive

        # --- hit detection ----------------------------------------------
        for track in tracks:
            if track.hit_fired:
                continue
            silence = frame_idx - track.last_seen
            p = [np.array(pt, dtype=np.float64) for pt in track.positions]
            hit_pos = None
            hit_radius = 0.0
            hit_span = 0  # how many frames ago the contact frame was
            if silence == 0 and mode == "instant" and len(p) >= 3:
                steps = [p[-2] - p[-3], p[-1] - p[-2]]
                direction, _, _ = consistent_direction(steps, min_speed, straight_cos)
                if direction is not None:
                    hit_pos = p[-1]
                    hit_radius = track.radii[-1]
            elif silence == 0 and mode == "reversal":
                # Wall contact with a visible bounce: a consistent straight
                # fast APPROACH, an optional short HOVER cluster at the
                # contact point, then a trajectory KINK (turn or sudden
                # slowdown). See evaluate_contact.
                hit, _ = evaluate_contact(
                    p, list(track.frames), list(track.radii), contact_cfg)
                if hit is not None:
                    hit_pos, hit_radius, hit_span = hit
            elif (vanish_hits and mode == "reversal"
                  and silence == vanish_silence and len(p) >= vanish_approach + 1):
                # Wall contact with an INVISIBLE bounce: the ball slowed
                # below detection right at the wall and the track went
                # silent mid-frame. Demand a longer gap-free consistent
                # approach ending at the final observation, away from the
                # camera edges (an exiting ball dies at the border).
                f = list(track.frames)
                if f[-1] - f[-1 - vanish_approach] <= vanish_approach + 1:
                    steps = [p[i + 1] - p[i]
                             for i in range(len(p) - 1 - vanish_approach, len(p) - 1)]
                    incoming, speed, _ = consistent_direction(
                        steps, min_speed, straight_cos)
                    x, y = p[-1]
                    inside = (edge_margin < x < small.shape[1] - edge_margin
                              and edge_margin < y < small.shape[0] - edge_margin)
                    # motion whose approach STARTED near a recent hit is the
                    # OUTGOING ball - its later fade is not a new impact
                    now_t = time.monotonic()
                    start = p[-1 - vanish_approach]
                    debris = any(
                        now_t - t_hit < 1.5
                        and np.hypot(start[0] - hp[0], start[1] - hp[1]) < 80.0
                        for t_hit, hp in recent_hits_cam)
                    # if another live track continues the flight ahead along
                    # the same line, the ball did not hit anything - the
                    # tracker just hiccuped and re-acquired it
                    continued = False
                    if incoming is not None:
                        for other in tracks:
                            if other is track or frame_idx - other.last_seen > 1:
                                continue
                            d = np.array(other.positions[-1]) - p[-1]
                            along = float(d @ incoming)
                            perp = float(np.hypot(*(d - along * incoming)))
                            if 0.0 < along < speed * (silence + 3) and perp < 40.0:
                                continued = True
                                break
                    if incoming is not None and inside and not debris and not continued:
                        hit_pos = p[-1] + incoming * (speed * vanish_lead)
                        hit_radius = track.radii[-1]
                        hit_span = silence
            if hit_pos is None:
                continue
            track.hit_fired = True
            # sample color where the ball was last actually seen
            sample_pos = p[-1] if hit_span >= 1 and silence > 0 else hit_pos
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
            color = classify_color(recent_frames[-frame_back], sample_pos,
                                   max(4.0, hit_radius), color_defs)

            packet = {
                "type": "hit",
                "x": round(float(norm[0]), 4),
                "y": round(float(norm[1]), 4),
                "r": round(r_norm, 4),
                "color": color,
            }
            sock.sendto(json.dumps(packet).encode("utf-8"), udp_addr)
            recent_hits_cam.append((now, hit_pos))
            recent_hits_cam[:] = [(t, q) for t, q in recent_hits_cam if now - t < 2.0]
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
