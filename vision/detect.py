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
import sys
import time
from collections import deque

import cv2
import numpy as np

from common import load_config, load_calibration, open_camera
from studio import MeshyStudio


class Track:
    """One moving blob followed across frames."""

    _next_id = 0

    def __init__(self, pos, spos, radius, frame_idx):
        self.id = Track._next_id
        Track._next_id += 1
        self.positions = deque(maxlen=12)  # processing-scale camera pixels
        self.spos = deque(maxlen=12)       # screen space (aspect-corrected)
        self.radii = deque(maxlen=12)
        self.frames = deque(maxlen=12)  # frame index of each observation
        self.positions.append(pos)
        self.spos.append(np.asarray(spos, dtype=np.float64))
        self.radii.append(radius)
        self.frames.append(frame_idx)
        self.last_seen = frame_idx
        self.born = time.monotonic()
        self.hit_fired = False

    def add(self, pos, spos, radius, frame_idx):
        self.positions.append(pos)
        self.spos.append(np.asarray(spos, dtype=np.float64))
        self.radii.append(radius)
        self.frames.append(frame_idx)
        self.last_seen = frame_idx


def consistent_direction(velocities, min_speed, straight_cos, adj_ratio=1.9,
                         noise=0.006):
    """If the per-frame velocities look like a real ball in flight, return
    the mean direction (unit vector) and mean speed; else (None, reason).

    A real thrown ball moves fast, straight, and with smoothly changing
    speed (perspective and drag decelerate it gradually) - sensor grain and
    chained flicker artifacts do none of that.

    Both consistency tests are NOISE-AWARE, because blob centroids jitter
    by a fixed amount (`noise`, in screen units) regardless of speed: a
    2px-vs-4px difference is jitter, not a real 2x speed jump, and short
    steps have unreliable directions. Without this, a ball decelerating
    into the screen fails the checks exactly when it matters most."""
    units, speeds = [], []
    for s in velocities:
        n = np.hypot(s[0], s[1])
        if n < max(0.004, min_speed * 0.5):
            return None, 0.0, "approach step too slow (%.1f scr/1000)" % (n * 1000)
        units.append(s / n)
        speeds.append(n)
    if float(np.mean(speeds)) < min_speed:
        return None, 0.0, "approach too slow on average (%.1f scr/1000)" \
            % (np.mean(speeds) * 1000)
    for a, b in zip(speeds, speeds[1:]):
        if max(a, b) > adj_ratio * min(a, b) + noise:
            return None, 0.0, "speed jump %.1fx between steps" % (max(a, b) / min(a, b))
    mean = np.sum(units, axis=0)
    norm = np.hypot(mean[0], mean[1])
    if norm < 1e-9:
        return None, 0.0, "no consistent direction"
    mean /= norm
    # judge straightness only on steps long enough for their direction to
    # be meaningful; jitter-sized steps cannot disprove a straight flight
    judged = [(u, n) for u, n in zip(units, speeds) if n > 2.0 * noise]
    # ...but a flight whose steps are MOSTLY jitter-sized is not a flight:
    # one random excursion among tiny steps must not pass as an approach
    if 2 * len(judged) < len(units):
        return None, 0.0, "approach dominated by jitter-sized steps"
    if judged:
        worst_u, _ = min(judged, key=lambda un: float(un[0] @ mean))
        worst = float(worst_u @ mean)
        if worst < straight_cos:
            return None, 0.0, "approach not straight (%.0f deg wobble)" \
                % np.degrees(np.arccos(max(-1.0, worst)))
    return mean, float(np.mean(speeds)), ""


def associate(tracks, detections, frame_idx, max_match_dist, match_floor=15.0):
    """Match detections to tracks; returns {track_index: detection_index}.

    Globally greedy by distance-to-prediction, in TWO passes: tracks with
    a real velocity estimate (>= 2 observations) bid first, then newborn
    single-observation tracks compete for the leftovers. Both properties
    matter: global order stops the ball and its projector-shadow chains
    from stealing each other's blobs (they fly a few px apart), and the
    established-first pass stops a fresh junk blob born next to the
    ball's path from outbidding the ball's own track and fragmenting it.
    """
    assigned = {}
    matched_d = set()
    for established in (True, False):
        pairs = []
        for ti, track in enumerate(tracks):
            if ti in assigned or (len(track.positions) >= 2) != established:
                continue
            if established:
                lx, ly = track.positions[-1]
                qx, qy = track.positions[-2]
                step = max(1, track.frames[-1] - track.frames[-2])
                vx, vy = (lx - qx) / step, (ly - qy) / step
                # predict across the REAL frame gap: after a detection
                # dropout the ball is several steps ahead, and predicting
                # only one step used to break the track (losing the whole
                # approach history right before the hit)
                gap = frame_idx - track.frames[-1]
                pred = (lx + vx * gap, ly + vy * gap)
                last_speed = np.hypot(vx, vy)
                allowed = min(max_match_dist,
                              max(match_floor,
                                  0.8 * match_floor + 2.5 * last_speed))
            else:
                pred = track.positions[-1]
                allowed = max_match_dist
            for i in range(len(detections)):
                if i in matched_d:
                    continue
                d = np.hypot(detections[i][0][0] - pred[0],
                             detections[i][0][1] - pred[1])
                if d < allowed:
                    pairs.append((d, ti, i))
        pairs.sort(key=lambda q: q[0])
        for d, ti, i in pairs:
            if ti in assigned or i in matched_d:
                continue
            assigned[ti] = i
            matched_d.add(i)
    return assigned


# ordering of gate stages, used to report the deepest failure of a track
_STAGE_NAMES = ["short", "gap", "approach", "hover", "recede", "side", "turn"]


# gravity direction in screen space (aspect-corrected: 1.0 = screen height)
_DOWN = np.array([0.0, 1.0])
_DROP_COS = np.cos(np.radians(40.0))


def evaluate_contact(p, f, radii, cfg):
    """Check a track's history for the wall-contact signature.

    Operates in SCREEN space (aspect-corrected normalized coordinates,
    1.0 = screen height), where perspective is already removed: an angled
    throw at constant physical speed has constant speed here, and gravity
    is exactly +y. Units: speeds are screen-heights per frame.

    p: screen positions (np arrays), f: frame indices, radii: blob radii
    in camera px (passed through for the hit).
    Returns (hit, reason): hit = (screen_pos, radius, frames_back) or
    None; reason = deepest gate failure among candidate windows.
    """
    n = len(p)
    best_stage, best_reason = -1, "track too short (%d observations)" % n
    min_e = cfg.get("min_e", 2)  # 2 fast approach steps = minimum evidence
    for e in range(n - 3, n - 4 - cfg["hover_max"], -1):
        if e < min_e:
            break

        def fail(stage, reason):
            nonlocal best_stage, best_reason
            idx = _STAGE_NAMES.index(stage)
            if idx > best_stage:
                best_stage, best_reason = idx, reason

        if f[-1] - f[e] > (n - 1 - e) + 2:
            fail("gap", "bounce-out had missed frames")
            continue
        # Try the full approach window first, then shorter ones: a track's
        # first observations are often unreliable (the motion streak has
        # just appeared, its centroid jumps), and one bad early step must
        # not void an otherwise clean flight. Three consistent fast steps
        # are still far beyond what noise produces, and the contact kink
        # below is required on top of them either way.
        incoming, speed, vels, why = None, 0.0, None, ""
        used_alen = 0
        for alen in range(cfg["approach"], cfg.get("min_alen", 2) - 1, -1):
            if e - alen < 0:
                continue  # window does not fit; a shorter one may
            # approach must be a near-gap-free frame run (two misses
            # allowed; velocities are per-frame, so gaps do not distort
            # speeds)
            if f[e] - f[e - alen] > alen + 2:
                why = why or "approach had missed frames"
                continue
            cand = [(p[i + 1] - p[i]) / max(1, f[i + 1] - f[i])
                    for i in range(e - alen, e)]
            incoming, speed, why = consistent_direction(
                cand, cfg["min_speed"], cfg["straight_cos"])
            # A bare 2-step approach is enough evidence only for a ball
            # that is clearly FLYING and only when the track genuinely had
            # no room for more (turn right after birth - steep camera
            # angles compress the whole flight into a handful of
            # observations). A long track failing its 3-step windows must
            # not fall back to two.
            if incoming is not None and alen == 2 \
                    and (e >= 4 or speed < 2.5 * cfg["min_speed"]):
                incoming, why = None, "2-step approach not fast enough"
            if incoming is not None:
                vels = cand
                used_alen = alen
                break
        if incoming is None:
            fail("approach", why or "no usable approach window")
            continue
        hover = [p[i] for i in range(e + 1, n - 2)]
        hover_limit = max(0.03, speed * 1.2)
        if any(np.hypot(*(q - p[e])) > hover_limit for q in hover):
            fail("hover", "did not stay near the turn point")
            continue
        v_a = p[-2] - p[e]
        v_b = p[-1] - p[e]
        n_a = np.hypot(v_a[0], v_a[1])
        n_b = np.hypot(v_b[0], v_b[1])
        out_speed = float(np.hypot(*(p[-1] - p[-2]))) / max(1, f[-1] - f[-2])
        # A deadened ball can STICK to the soft screen instead of receding:
        # a clearly-flying straight approach that ends in a full stop
        # (post-turn observations pinned near the turn point, final step
        # ~zero) is a wall contact - nothing else stops a ball mid-air.
        stuck = (f[-1] - f[e] >= 2
                 and speed >= 1.5 * cfg["min_speed"]
                 and n_a <= hover_limit and n_b <= hover_limit
                 and out_speed <= max(0.008, 0.25 * speed))
        # receding distances jitter by centroid noise; only clearly
        # SHRINKING distance disproves the recede
        if not stuck and (n_a < 0.004 or n_b < 0.004 or n_b <= n_a - 0.005):
            fail("recede", "did not recede over two frames after the turn")
            continue
        # Contact = the trajectory BREAKS at the wall. A smooth flight
        # never does; a soft projector screen deadens the ball, so the
        # break shows as one of:
        #   turned    - image direction change (head-on-ish bounces)
        #   collapsed - sudden speed drop (screen absorbing the flight)
        #   dropped   - post-impact motion is gravity: straight DOWN in
        #               screen space, while the approach was not downward
        #               (the deadened ball falling off the screen)
        out_dir = v_b / n_b if n_b > 1e-9 else v_b
        cos_turn = float(v_b @ incoming) / max(n_b, 1e-9)
        # a turn verdict needs real displacement: a jitter-sized outgoing
        # step has no meaningful direction to have turned
        turned = cos_turn <= cfg["min_cos"] and n_b >= 0.008
        last_in = float(np.hypot(*(p[e] - p[e - 1]))) / max(1, f[e] - f[e - 1])
        # Compare the outgoing speed against the approach's OWN extrapolated
        # trend: steady deceleration (perspective, drag) continues its trend
        # and is no kink, while a wall breaks it. The trend is the geometric
        # mean speed ratio across the whole approach - a single step pair is
        # far too noisy to extrapolate from.
        aspeeds = [float(np.hypot(v[0], v[1])) for v in vels]
        trend = float(np.clip(
            (aspeeds[-1] / max(aspeeds[0], 1e-9)) ** (1.0 / max(1, len(aspeeds) - 1)),
            0.7, 1.1))
        horizon = min(6, max(1, f[-1] - f[e]))
        collapsed = out_speed < 0.55 * last_in * (trend ** horizon)
        # a real gravity drop: both post-turn observations downward, real
        # displacement (not jitter), and accelerating (distance roughly
        # doubles frame over frame) - while the approach was not downward
        dropped = (float(out_dir @ _DOWN) >= _DROP_COS
                   and float(v_a @ _DOWN) / n_a >= 0.5
                   and n_b >= 0.008
                   and n_b >= 1.6 * n_a
                   and float(incoming @ _DOWN) < _DROP_COS)
        if not (turned or collapsed or dropped or stuck):
            fail("turn", "no bounce kink (turn %.0f deg, kept %.0f%% speed)"
                 % (np.degrees(np.arccos(np.clip(cos_turn, -1.0, 1.0))),
                    100.0 * out_speed / max(last_in, 1e-6)))
            continue
        if cfg.get("debug"):
            print("CONTACT e=%d/%d turned=%s collapsed=%s dropped=%s stuck=%s "
                  "out=%.4f last_in=%.4f trend=%.2f horizon=%d n_a=%.4f n_b=%.4f"
                  % (e, n, turned, collapsed, dropped, stuck, out_speed,
                     last_in, trend, horizon, n_a, n_b))
        # The impact is where the incoming flight line meets the outgoing
        # (bounce or gravity-drop) line - a far better estimate than
        # extrapolating a fixed fraction of a step, because the contact
        # generally happens BETWEEN two observations.
        #
        # GRAVITY: the mean approach velocity equals the instantaneous
        # velocity at the window's MIDPOINT, and the flight keeps curving
        # past p[e] - a straight mean-direction extrapolation lands ABOVE
        # the real contact. Steepen to the end-of-window velocity and add
        # the parabolic sag for the frames extrapolated beyond p[e].
        g = cfg.get("gravity", 0.0)
        v_end = incoming * speed + _DOWN * (g * 0.5 * used_alen)
        v_n = float(np.hypot(v_end[0], v_end[1]))
        in_dir = v_end / v_n if v_n > 1e-9 else incoming
        cluster = np.mean([p[e]] + hover, axis=0)
        lag = cfg["lag"]
        hit_pos = cluster + v_end * lag + _DOWN * (0.5 * g * lag * lag)
        cross = float(in_dir[0] * out_dir[1] - in_dir[1] * out_dir[0])
        # (a stuck ball has no outgoing line to intersect - the rest
        # position IS the contact, so keep the cluster estimate)
        if not stuck and abs(cross) > 0.25:  # lines meet at a usable angle
            w = p[-1] - p[e]
            t = float(w[0] * out_dir[1] - w[1] * out_dir[0]) / cross
            if -0.5 * speed <= t <= 3.0 * speed + 0.05:
                frames_out = max(0.0, t) / max(speed, 1e-9)
                meet = p[e] + in_dir * t \
                    + _DOWN * (0.5 * g * frames_out * frames_out)
                # trust it only if it lands near the observed contact area
                if float(np.hypot(*(meet - cluster))) <= max(0.06, 2.0 * speed):
                    hit_pos = meet
        return (hit_pos, radii[e], n - 1 - e, incoming), ""
    return None, best_reason


def evaluate_contact_reversed(p, f, radii, cfg):
    """evaluate_contact on the time-reversed track.

    A bounce is provable from either side: when a steep camera angle
    compresses the visible APPROACH to one or two observations, the
    OUTGOING flight still carries full evidence. Reversed, the outgoing
    leg becomes a clean approach and the incoming leg the recede.
    Gravity keeps its sign under time reversal (the spatial curve is the
    same parabola); the centroid-lag nudge would point the wrong way, so
    it is disabled.
    """
    if len(p) > 9:
        # only for angle-compressed flights: a long track with no valid
        # forward approach is junk, not a foreshortened throw
        return None, "track long enough for forward evidence"
    rp = list(reversed(p))
    rf = [-x for x in reversed(f)]
    rr = list(reversed(radii))
    # the outgoing leg carries the proof here, so demand full windows
    hit, why = evaluate_contact(rp, rf, rr,
                                dict(cfg, lag=0.0, min_e=3, min_alen=3))
    if hit is None:
        return None, why
    pos, rad, back_rev, inc_rev = hit
    n = len(p)
    return (pos, rad, n - 1 - back_rev, -inc_rev), why


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


def _disable_quickedit():
    """Windows console 'QuickEdit' pauses the whole process when the user
    clicks inside the window - the tracker silently freezes mid-game.
    Turn it off for this console."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            # clear ENABLE_QUICK_EDIT_MODE (0x40); 0x80 = ENABLE_EXTENDED_FLAGS
            k32.SetConsoleMode(handle, (mode.value & ~0x40) | 0x80)
    except Exception:
        pass


def main():
    _disable_quickedit()
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
    # With a calibration, all pixel-space constants are DERIVED from the
    # local image scale (px per screen-height unit), so any reasonable
    # camera distance and angle works without retuning: the expected ball
    # blob size comes from the physical ball and screen sizes, the match
    # radius from how far a ball can travel between frames.
    auto_scale = det.get("auto_scale", True)
    ball_diameter_m = det.get("ball_diameter_m", 0.04)
    # minimum ball speed in screen units per frame (1.0 = screen height);
    # 0.012 at 60 fps on a ~1.7 m screen is roughly 1.2 m/s
    min_speed = det.get("min_speed_norm", 0.012)
    # physical aspect of the projection, to make screen space isotropic
    screen_aspect = det.get("screen_aspect", 16.0 / 9.0)
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
    # gravity in screen units per frame^2 needs the physical screen height;
    # the frame interval is measured live (see the loop), this is the seed
    screen_height_m = det.get("screen_height_m", 2.0)
    frame_dt = 1.0 / max(1.0, float(config.get("capture_fps", 60)))
    contact_cfg = {
        "approach": approach_frames,
        "min_speed": min_speed,
        "straight_cos": straight_cos,
        "hover_max": hover_max,
        "min_cos": min_cos,
        "lag": lag_correction,
        "gravity": 9.81 * frame_dt * frame_dt / screen_height_m,
        "min_e": det.get("min_approach_steps", 3),
        "debug": det.get("debug", False),
    }
    # Vanish hits: a ball on a long consistent approach that stops being
    # detected mid-frame (away from the camera edges) has hit the wall -
    # near impact it slows below the motion threshold, so the bounce
    # itself is often invisible. Nothing else enters the projection.
    vanish_hits = det.get("vanish_hits", True)
    vanish_silence = det.get("vanish_silence", 3)     # frames of silence
    vanish_approach = det.get("vanish_approach_steps", approach_frames + 1)
    # steps of travel past the last observation: the ball fades ~when its
    # remaining screen distance is 1-2 mean steps (it converges onto the
    # impact point), and the diff centroid trails another half step
    vanish_lead = det.get("vanish_lead", 1.75)
    edge_margin = det.get("edge_margin", 25)          # px at processing scale
    # a SLOW ball can fade from detection without hitting anything (its
    # frame difference shrinks) - vanish hits need clearly-flying speed
    vanish_min_speed = det.get("vanish_min_speed_norm", min_speed * 2.0)
    # shorter vanish windows are allowed for proportionally FASTER flights
    vanish_windows = [(vanish_approach, 1.0), (4, 1.2), (3, 1.5)]
    vanish_windows = [(w, m) for w, m in vanish_windows if w <= vanish_approach]
    # Emerge hits: the mirror of vanish. A consistent fast chain that
    # BEGINS mid-wall (not at a screen edge, not moving inward from the
    # projection border, no predecessor track behind it) is a ball the
    # wall just ejected - the impact itself was below detection.
    emerge_hits = det.get("emerge_hits", True)
    emerge_approach = det.get("emerge_approach_steps", 4)
    emerge_min_speed = det.get("emerge_min_speed_norm", min_speed * 2.0)
    emerge_lead = det.get("emerge_lead", 0.75)        # steps before first obs
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
    graveyard = []  # (last_frame, last screen pos) of recently pruned tracks
    noise_sample_mask = None  # pixels used to estimate sensor grain
    recent_hits = []  # (time, normalized_pos)
    recent_hits_s = []  # (time, screen pos) - twin/debris suppression
    recent_frames = deque(maxlen=4)  # small color frames, for sampling pre-impact color
    frame_idx = 0
    game_poly = None

    last_frame_t = None

    while True:
        ok, frame = cam.read()
        if not ok:
            raise SystemExit("Camera stopped delivering frames.")
        frame_idx += 1
        # measure the real frame interval (cameras do not always deliver
        # the configured fps) - gravity per frame^2 depends on it squared
        t_now = time.monotonic()
        if last_frame_t is not None and 0.001 < t_now - last_frame_t < 0.5:
            frame_dt = 0.98 * frame_dt + 0.02 * (t_now - last_frame_t)
            contact_cfg["gravity"] = min(
                0.01, 9.81 * frame_dt * frame_dt / screen_height_m)
        last_frame_t = t_now

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
            match_floor = 15.0
            scale_pts, ball_r_grid = None, None
            if auto_scale:
                scale_pts, scales = mapper.scale_grid(
                    (small.shape[1], small.shape[0]), screen_aspect)
                # expected ball radius in px at each grid point, from the
                # physical ball and projection sizes
                ball_r_grid = np.maximum(
                    1.5, scales * (0.5 * ball_diameter_m / screen_height_m))
                s_med = float(np.median(scales))
                # a ball can cross ~12% of the screen height per frame at
                # most; the floor keeps slow tracks from teleporting
                max_match_dist = float(np.clip(0.12 * s_med, 30.0, 130.0))
                match_floor = float(np.clip(0.035 * s_med, 8.0, 25.0))
                a_lo = 0.35 * np.pi * ball_r_grid ** 2
                a_hi = 25.0 * np.pi * ball_r_grid ** 2
                min_area = max(8.0, float(a_lo.min()))
                max_area = float(a_hi.max())
                print("auto-scale: px/screen-unit %.0f  ball r %.1f-%.1fpx  "
                      "match %.0f/%.0fpx  area %.0f-%.0f"
                      % (s_med, ball_r_grid.min(), ball_r_grid.max(),
                         match_floor, max_match_dist, min_area, max_area))

        if prev_gray is None:
            prev_gray = gray
            continue

        # --- motion detection -------------------------------------------
        diff = cv2.absdiff(gray, prev_gray)
        prev_gray = gray
        thr = float(base_threshold)
        if auto_threshold:
            # The grain estimate must come from pixels OUTSIDE the game
            # projection: when the projected content animates, a whole-frame
            # median explodes and the floating threshold blinds the tracker
            # to the real ball (throws silently produce nothing at all).
            if noise_sample_mask is None:
                m = np.ones(gray.shape, np.uint8)
                cv2.fillPoly(m, [game_poly], 0)
                sub = m[::4, ::4].astype(bool)
                # too little room visible around the projection -> whole frame
                noise_sample_mask = sub if int(sub.sum()) >= 1500 else sub | True
            sample = diff[::4, ::4][noise_sample_mask]
            # most sampled pixels are static, so the median absolute
            # difference is the sensor grain level - float above it
            thr = max(thr, noise_multiplier * float(np.median(sample)))
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
            if ball_r_grid is not None:
                # size-check against the LOCAL expected ball size: at a
                # steep angle a valid blob near the camera is many times
                # larger than one across the screen
                k = int(np.argmin(((scale_pts - center) ** 2).sum(axis=1)))
                r_exp = ball_r_grid[k]
                if not (0.35 * np.pi * r_exp ** 2 <= area
                        <= 25.0 * np.pi * r_exp ** 2):
                    continue
            # a fast ball is a motion-blur streak: its narrow side is the
            # ball diameter no matter how fast it flies
            (_, (rw, rh), _) = cv2.minAreaRect(cnt)
            radius = max(2.0, min(rw, rh) / 2.0)
            detections.append((center, radius))

        # map detections into screen space (aspect-corrected, isotropic):
        # all contact physics runs there, where perspective is removed
        if detections:
            spts = mapper.map_points(
                [d[0] for d in detections], (small.shape[1], small.shape[0]))
            spts[:, 0] *= screen_aspect
        else:
            spts = np.zeros((0, 2))

        # --- track association --------------------------------------------
        # Constant-velocity prediction: a moving ball's blob chain matches
        # its own predicted continuation, so the streak's leading and
        # trailing diff blobs form separate stable chains instead of
        # cross-stealing each other's detections. (Both chains see the
        # bounce; the duplicate hit is absorbed by the cooldown.)
        # The match radius scales with the track's own speed: a slow track
        # cannot teleport onto an unrelated blob across the frame.
        assigned = associate(tracks, detections, frame_idx, max_match_dist,
                             match_floor)
        for ti, i in assigned.items():
            tracks[ti].add(detections[i][0], spts[i],
                           detections[i][1], frame_idx)
        matched_d = set(assigned.values())
        for i in range(len(detections)):
            if i not in matched_d:
                tracks.append(Track(detections[i][0], spts[i],
                                    detections[i][1], frame_idx))

        # retire stale tracks; print a post-mortem for any that looked like
        # a real throw but never fired, saying which gate rejected it
        alive = []
        for t in tracks:
            if frame_idx - t.last_seen <= track_timeout:
                alive.append(t)
                continue
            graveyard.append((t.frames[-1], np.array(t.spos[-1])))
            if not t.hit_fired and len(t.positions) >= 5:
                ts = list(t.spos)
                sspeeds = [np.hypot(*(ts[i + 1] - ts[i])) for i in range(len(ts) - 1)]
                if max(sspeeds) >= min_speed:
                    _, reason = evaluate_contact(
                        ts, list(t.frames), list(t.radii), contact_cfg)
                    tf = list(t.frames)
                    gaps = (tf[-1] - tf[0]) - (len(tf) - 1)
                    path = "|".join("%d,%d" % (q[0], q[1])
                                    for q in list(t.positions)[-9:])
                    print("MISS track#%d len=%d vmax=%.0f/1000 gaps=%d: %s  path=%s"
                          % (t.id, len(ts), max(sspeeds) * 1000, gaps, reason, path))
        tracks = alive
        graveyard[:] = [(fr, q) for fr, q in graveyard if frame_idx - fr <= 15]

        # --- hit detection (all gates in screen space) -------------------
        for track in tracks:
            if track.hit_fired:
                continue
            silence = frame_idx - track.last_seen
            p = [np.array(pt, dtype=np.float64) for pt in track.positions]
            s = list(track.spos)
            hit_s = None
            hit_radius = 0.0
            hit_span = 0  # how many frames ago the contact frame was
            hit_dir = None  # approach direction (for twin-estimate merging)
            if silence == 0 and mode == "instant" and len(s) >= 3:
                tf = list(track.frames)
                vels = [(s[-2] - s[-3]) / max(1, tf[-2] - tf[-3]),
                        (s[-1] - s[-2]) / max(1, tf[-1] - tf[-2])]
                direction, _, _ = consistent_direction(vels, min_speed, straight_cos)
                if direction is not None:
                    hit_s = s[-1]
                    hit_radius = track.radii[-1]
                    hit_dir = direction
            elif silence == 0 and mode == "reversal":
                # Wall contact with a visible break: a consistent straight
                # fast APPROACH, an optional short HOVER cluster at the
                # contact point, then a trajectory KINK (turn, sudden
                # slowdown, or the deadened ball dropping straight down).
                hit, _ = evaluate_contact(
                    s, list(track.frames), list(track.radii), contact_cfg)
                if hit is None:
                    # provable from the other side too: a steep camera
                    # angle can compress the approach to 1-2 observations
                    # while the outgoing flight is long and clean
                    hit, _ = evaluate_contact_reversed(
                        s, list(track.frames), list(track.radii), contact_cfg)
                if hit is not None:
                    hit_s, hit_radius, hit_span, hit_dir = hit
                elif (emerge_hits
                        and emerge_approach + 1 <= len(s) <= emerge_approach + 2):
                    # EMERGE: a chain that begins mid-wall is a ball the
                    # wall just ejected (the impact was below detection).
                    # Try once at birth+window, once more skipping a
                    # possibly-junky first observation.
                    start = len(s) - 1 - emerge_approach
                    fq = list(track.frames)
                    now_t = time.monotonic()
                    if fq[-1] - fq[start] <= emerge_approach + 2:
                        vels = [(s[i + 1] - s[i]) / max(1, fq[i + 1] - fq[i])
                                for i in range(start, len(s) - 1)]
                        outgoing, speed, _ = consistent_direction(
                            vels, min_speed, straight_cos)
                        s0 = s[start]
                        x0c, y0c = p[start]
                        inside = (edge_margin < x0c < small.shape[1] - edge_margin
                                  and edge_margin < y0c < small.shape[0] - edge_margin)
                        ok = (outgoing is not None and speed >= emerge_min_speed
                              and inside)
                        if ok:
                            # a chain starting at the projection BORDER and
                            # moving inward is a ball ENTERING the game
                            # area, not one ejected by the wall
                            edges = [(s0[0], np.array([1.0, 0.0])),
                                     (screen_aspect - s0[0], np.array([-1.0, 0.0])),
                                     (s0[1], np.array([0.0, 1.0])),
                                     (1.0 - s0[1], np.array([0.0, -1.0]))]
                            d_edge, inward = min(edges, key=lambda q: q[0])
                            if d_edge < 0.10 and float(outgoing @ inward) > 0.5:
                                ok = False
                        if ok:
                            # outgoing debris of a REGISTERED hit also
                            # emerges - born at the hit point
                            if any(now_t - t_h < 1.5
                                   and float(np.hypot(*(s0 - hq))) < 0.12
                                   for t_h, hq in recent_hits_s):
                                ok = False
                        if ok:
                            # a track that broke and re-acquired also
                            # "emerges": look for a predecessor that went
                            # silent just behind the chain start
                            birth = fq[start]
                            cands = [(o.frames[-1], o.spos[-1]) for o in tracks
                                     if o is not track and o.last_seen <= birth]
                            for died, q in cands + graveyard:
                                if not (0 <= birth - died <= 4):
                                    continue
                                d = s0 - np.asarray(q)
                                along = float(d @ outgoing)
                                perp = float(np.hypot(*(d - along * outgoing)))
                                if -0.02 < along < speed * (birth - died + 2) \
                                        and perp < 0.10:
                                    ok = False
                                    break
                        if ok:
                            g = contact_cfg["gravity"]
                            v_start = outgoing * speed \
                                - _DOWN * (g * 0.5 * emerge_approach)
                            hit_s = s0 - v_start * emerge_lead \
                                + _DOWN * (0.5 * g * emerge_lead * emerge_lead)
                            hit_radius = track.radii[start]
                            hit_span = len(s) - 1 - start
                            hit_dir = -outgoing
            elif (vanish_hits and mode == "reversal"
                  and silence == vanish_silence and len(s) >= 4):
                # Wall contact with an INVISIBLE break: the soft screen
                # deadened the ball below detection and the track went
                # silent mid-frame. Demand a gap-free consistent approach
                # ending at the final observation, away from the camera
                # edges (an exiting ball dies at the border). Shorter
                # windows are accepted only for proportionally faster
                # flights (steep camera angles compress the visible arc).
                f = list(track.frames)
                incoming, speed = None, 0.0
                for va, mult in vanish_windows:
                    if len(s) < va + 1 or f[-1] - f[-1 - va] > va + 2:
                        continue
                    vels = [(s[i + 1] - s[i]) / max(1, f[i + 1] - f[i])
                            for i in range(len(s) - 1 - va, len(s) - 1)]
                    incoming, speed, _ = consistent_direction(
                        vels, min_speed, straight_cos)
                    if incoming is not None \
                            and speed >= vanish_min_speed * mult:
                        vanish_approach_used = va
                        break
                    incoming = None
                if incoming is not None:
                    x, y = p[-1]
                    inside = (edge_margin < x < small.shape[1] - edge_margin
                              and edge_margin < y < small.shape[0] - edge_margin)
                    # motion flying AWAY from a recent hit (the hit lies
                    # behind it along its own flight line) is the OUTGOING
                    # ball - its later fade is not a new impact. A fresh
                    # throw at the same spot has the old hit AHEAD of it,
                    # or FLEW PAST it: the hit then lies far ahead of the
                    # track's start, while debris is born AT the hit
                    now_t = time.monotonic()
                    debris = False
                    if incoming is not None:
                        for t_hit, hq in recent_hits_s:
                            if now_t - t_hit >= 1.5:
                                continue
                            d = hq - s[-1]
                            along = float(d @ incoming)
                            perp = float(np.hypot(*(d - along * incoming)))
                            along_start = float((hq - s[0]) @ incoming)
                            if along < 0.02 and perp < 0.12 \
                                    and along_start < 0.05:
                                debris = True
                                break
                    # if another live track continues the flight ahead along
                    # the same line, the ball did not hit anything - the
                    # tracker just hiccuped and re-acquired it
                    continued = False
                    if incoming is not None:
                        for other in tracks:
                            if other is track or frame_idx - other.last_seen > 1:
                                continue
                            d = other.spos[-1] - s[-1]
                            along = float(d @ incoming)
                            perp = float(np.hypot(*(d - along * incoming)))
                            if 0.0 < along < speed * (silence + 3) and perp < 0.10:
                                continued = True
                                break
                    if inside and not debris and not continued:
                        # extrapolate with the END-of-window velocity plus
                        # gravity sag; the straight mean-direction lead
                        # landed hits above the real impact (see
                        # evaluate_contact for the same correction)
                        g = contact_cfg["gravity"]
                        v_end = incoming * speed \
                            + _DOWN * (g * 0.5 * vanish_approach_used)
                        hit_s = s[-1] + v_end * vanish_lead \
                            + _DOWN * (0.5 * g * vanish_lead * vanish_lead)
                        hit_radius = track.radii[-1]
                        hit_span = silence
                        hit_dir = incoming
            if hit_s is None:
                continue
            track.hit_fired = True

            # camera anchor at the contact observation: used for the ball
            # radius mapping and for color sampling
            anchor_idx = max(0, len(p) - 1 - (hit_span if silence == 0 else 0))
            cam_anchor = p[anchor_idx] if silence == 0 else p[-1]
            mapped = mapper.map_points(
                [cam_anchor, (cam_anchor[0] + hit_radius, cam_anchor[1])],
                (small.shape[1], small.shape[0]),
            )
            r_norm = float(np.hypot(*(mapped[1] - mapped[0])))
            # sample the ball color from the contact frame at the contact
            # point - that is exactly where and when the ball is in view
            frame_back = min(hit_span + 1, len(recent_frames))
            color = classify_color(recent_frames[-frame_back], cam_anchor,
                                   max(4.0, hit_radius), color_defs)

            hit_s = np.array(hit_s, dtype=np.float64)
            now = time.monotonic()
            # Every suppressed hit is PRINTED: a silent swallow here looks
            # exactly like a missed throw in the field, which is undebuggable.
            # the streak's twin diff chain sees the same impact a beat later
            # with a slightly different contact estimate - one physical hit
            if any(now - t < 0.4 and float(np.hypot(*(hit_s - q))) < 0.18
                   for t, q in recent_hits_s):
                print("DUP  twin-chain duplicate of a just-sent hit, merged")
                continue
            # back to plain normalized game coordinates; corner hits whose
            # extrapolated contact lands a hair outside still count (the
            # lead/lag estimates can overshoot the projection edge)
            norm = np.array([hit_s[0] / screen_aspect, hit_s[1]])
            if not (-0.05 <= norm[0] <= 1.05 and -0.05 <= norm[1] <= 1.05):
                print("DROP hit outside the game area (%.3f, %.3f)"
                      % (norm[0], norm[1]))
                continue
            norm = np.clip(norm, 0.0, 1.0)

            # cooldown: ignore near-duplicate hits (double bounces etc.)
            recent_hits[:] = [
                (t, pos) for t, pos in recent_hits if (now - t) * 1000.0 < cooldown_ms
            ]
            if any(np.hypot(norm[0] - pos[0], norm[1] - pos[1]) < cooldown_radius
                   for _, pos in recent_hits):
                print("DROP hit at (%.3f, %.3f) within cooldown of a recent hit"
                      % (norm[0], norm[1]))
                continue
            recent_hits.append((now, (float(norm[0]), float(norm[1]))))

            packet = {
                "type": "hit",
                "x": round(float(norm[0]), 4),
                "y": round(float(norm[1]), 4),
                "r": round(r_norm, 4),
                "color": color,
            }
            sock.sendto(json.dumps(packet).encode("utf-8"), udp_addr)
            recent_hits_s.append((now, hit_s))
            recent_hits_s[:] = [(t, q) for t, q in recent_hits_s if now - t < 2.0]
            print("HIT", packet)
            if preview:
                cv2.circle(small, (int(cam_anchor[0]), int(cam_anchor[1])),
                           18, (0, 0, 255), 3)

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
