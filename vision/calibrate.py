"""Calibration: camera pixels -> game screen coordinates.

Steps:
  1. Start the game on the projector and press C to show the calibration
     pattern (white screen with a 4x3 grid of ArUco markers).
  2. Run:  python calibrate.py
  3. Aim the camera so it sees the projection. Marker observations are
     accumulated over time (a marker only has to be detected now and
     then, not in every frame). When enough markers are locked in, the
     border turns green - press SPACE to save, Q to quit.

The fit is a RANSAC homography (any camera angle) plus a thin-plate
spline correction (distorted/curved screens), computed from the median
of many observations per marker for accuracy. Works with a partial view
of the grid - MIN_MARKERS locked markers are enough.
"""

import time

import cv2
import numpy as np

from common import (
    MARKER_CENTERS,
    CalibrationMapper,
    aruco_detector,
    ball_hsv_sample,
    hue_distance,
    load_config,
    open_camera,
    save_calibration,
    save_colors,
)

MIN_MARKERS = 6    # markers needed for a fit (of the 12 in the grid)
MIN_OBS = 5        # observations per marker before it counts as locked
MAX_OBS = 90       # rolling window per marker


def marker_center(corners4):
    """Projectively correct marker center: the intersection of the two
    diagonals (the corner average is biased under strong perspective)."""
    p0, p1, p2, p3 = [np.asarray(p, dtype=np.float64) for p in corners4]
    d1, d2 = p2 - p0, p3 - p1
    denom = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denom) < 1e-9:
        return (p0 + p1 + p2 + p3) / 4.0
    t = ((p1[0] - p0[0]) * d2[1] - (p1[1] - p0[1]) * d2[0]) / denom
    return p0 + t * d1


def fit_calibration(centers_by_id, frame_size):
    """Fit from {marker_id: (cx, cy) median camera px}.

    Returns (homography, control_src, control_dst, stats) or raises
    ValueError if the data cannot produce a solid fit.
    """
    ids = sorted(centers_by_id)
    if len(ids) < MIN_MARKERS:
        raise ValueError("only %d markers, need %d" % (len(ids), MIN_MARKERS))
    src = np.array([centers_by_id[i] for i in ids], dtype=np.float64)
    dst = np.array([MARKER_CENTERS[i] for i in ids], dtype=np.float64)

    # RANSAC only to reject gross misdetections (wrong ids, reflections);
    # genuine screen distortion must survive so the spline layer can
    # correct it. 0.02 normalized ~ 26 px on a 1280-wide screen.
    homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 0.02)
    if homography is None:
        raise ValueError("homography estimation failed")
    inliers = mask.ravel().astype(bool)
    if inliers.sum() < MIN_MARKERS:
        raise ValueError("only %d consistent markers after RANSAC" % inliers.sum())

    src_in, dst_in = src[inliers], dst[inliers]
    base = cv2.perspectiveTransform(
        src_in.reshape(-1, 1, 2), homography).reshape(-1, 2)
    residual = np.linalg.norm(dst_in - base, axis=1)
    stats = {
        "markers": int(inliers.sum()),
        "rejected": int(len(ids) - inliers.sum()),
        # homography-only error at the control points; the thin-plate
        # spline layer corrects this at runtime
        "residual_mean": float(residual.mean()),
        "residual_max": float(residual.max()),
    }
    return homography, src_in, dst_in, stats


def _hue_center(samples):
    """Robust circular hue center + spread from (h, s, v) samples.

    Histogram peak first (stray samples - a hand, a reflection - must not
    drag the estimate), then median of the samples near the peak.
    """
    hues = np.array([s[0] for s in samples], dtype=np.float64)
    hist = np.bincount(hues.astype(int) % 180, minlength=180).astype(float)
    smooth = np.convolve(np.tile(hist, 3), np.ones(9), "same")[180:360]
    peak = int(np.argmax(smooth))
    dist = np.minimum(np.abs(hues - peak), 180 - np.abs(hues - peak))
    core = [s for s, d in zip(samples, dist) if d <= 25]
    ch = np.array([s[0] for s in core], dtype=np.float64)
    shifted = ((ch - peak + 90.0) % 180.0) - 90.0
    center = (peak + float(np.median(shifted))) % 180.0
    spread = 1.4826 * float(np.median(np.abs(shifted - np.median(shifted))))
    s_med = float(np.median([s[1] for s in core]))
    v_med = float(np.median([s[2] for s in core]))
    return center, max(4.0, spread), s_med, v_med, len(core)


def learn_colors(cam, config, mapper, frame_size):
    """Sample real thrown balls per color and save a learned classifier.

    For each configured color: the player throws a few balls of that
    color at the projection; ball-sized moving blobs inside the game
    area are color-sampled mid-flight, under the real projector light.
    """
    det = config.get("detection", {})
    names = [c["name"] for c in config.get("colors", [])] or ["orange", "blue"]
    screen_h = det.get("screen_height_m", 2.0)
    ball_d = det.get("ball_diameter_m", 0.04)
    scale_pts, scales = mapper.scale_grid(
        frame_size, det.get("screen_aspect", 16.0 / 9.0))
    r_grid = np.maximum(2.0, scales * (0.5 * ball_d / screen_h))
    poly = mapper.game_polygon_px(frame_size)

    learned = []
    prev_gray = None
    for name in names:
        samples = []       # (h, s, v)
        dots = []          # sample positions for the preview
        throws = 0
        last_sample_t = 0.0
        burst_n = 0
        print("COLOR '%s': throw 3 or more %s balls at the projection."
              % (name, name.upper()))
        while True:
            ok, frame = cam.read()
            if not ok:
                raise SystemExit("Camera stopped delivering frames.")
            gray = cv2.GaussianBlur(
                cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                _, mask = cv2.threshold(diff, 28, 255, cv2.THRESH_BINARY)
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                        np.ones((3, 3), np.uint8))
                mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
                cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
                now = time.monotonic()
                for cnt in cnts:
                    area = cv2.contourArea(cnt)
                    m = cv2.moments(cnt)
                    if m["m00"] <= 0:
                        continue
                    c = (m["m10"] / m["m00"], m["m01"] / m["m00"])
                    k = int(np.argmin(((scale_pts - c) ** 2).sum(axis=1)))
                    r_exp = r_grid[k]
                    if not (0.35 * np.pi * r_exp ** 2 <= area
                            <= 25.0 * np.pi * r_exp ** 2):
                        continue
                    if cv2.pointPolygonTest(
                            poly.astype(np.float32), c, False) < 0:
                        continue
                    hsv = ball_hsv_sample(frame, c, max(4.0, 1.2 * r_exp))
                    if hsv is None:
                        continue
                    if now - last_sample_t > 0.6:
                        if burst_n >= 3:
                            throws += 1
                        burst_n = 0
                    burst_n += 1
                    last_sample_t = now
                    samples.append(tuple(float(x) for x in hsv))
                    dots.append((int(c[0]), int(c[1])))
                # a finished burst counts once things go quiet
                if burst_n >= 3 and now - last_sample_t > 0.6:
                    throws += 1
                    burst_n = 0
            prev_gray = gray

            view = frame.copy()
            cv2.polylines(view, [poly], True, (0, 200, 0), 2)
            for d in dots[-120:]:
                cv2.circle(view, d, 3, (255, 180, 0), -1)
            done = throws >= 3 and len(samples) >= 20
            col = (0, 200, 0) if done else (0, 165, 255)
            cv2.putText(view,
                        "COLOR '%s': %d throws, %d samples" % (
                            name, throws, len(samples)),
                        (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, col, 2)
            cv2.putText(view,
                        "throw %s balls - SPACE=done  N=skip color  Q=quit"
                        % name.upper(),
                        (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
            cv2.rectangle(view, (0, 0), (view.shape[1] - 1, view.shape[0] - 1),
                          col, 6)
            cv2.imshow("calibrate", view)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                print("Color learning aborted; colors unchanged.")
                return
            if key == ord("n"):
                print("  skipped '%s' (keeping its old definition)." % name)
                samples = []
                break
            if key == ord(" ") and len(samples) >= 12:
                break
        if len(samples) >= 12:
            center, spread, s_med, v_med, used = _hue_center(samples)
            learned.append({
                "name": name,
                "h_center": round(center, 1),
                "h_spread": round(spread, 1),
                "s_min": int(max(25, 0.5 * s_med)),
                "v_min": int(max(30, 0.5 * v_med)),
            })
            print("  '%s': hue %.0f (spread %.0f), sat %.0f, val %.0f "
                  "from %d samples" % (name, center, spread, s_med, v_med, used))

    if len(learned) < 2:
        print("Fewer than two colors learned; config colors unchanged.")
        return
    d = hue_distance(learned[0]["h_center"], learned[1]["h_center"])
    if d < 25:
        print("WARNING: the two ball colors are only %.0f hue apart under "
              "this light - distinction will be unreliable. Config colors "
              "left unchanged; try different balls or lighting." % d)
        return
    path = save_colors(learned)
    print("Learned ball colors saved to %s (hue separation %.0f)." % (path, d))


def main():
    config = load_config()
    cam = open_camera(config)
    detector = aruco_detector()

    obs = {i: [] for i in MARKER_CENTERS}  # id -> list of centers (camera px)

    print("Accumulating marker observations. SPACE = save, R = reset, Q = quit.")
    while True:
        ok, frame = cam.read()
        if not ok:
            raise SystemExit("Camera stopped delivering frames.")

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = detector.detectMarkers(gray)
        if ids is not None:
            cv2.aruco.drawDetectedMarkers(frame, corners, ids)
            for marker_corners, marker_id in zip(corners, ids.flatten()):
                if int(marker_id) in obs:
                    center = marker_center(marker_corners.reshape(4, 2))
                    entries = obs[int(marker_id)]
                    entries.append(center)
                    if len(entries) > MAX_OBS:
                        entries.pop(0)

        locked = {
            i: np.median(np.array(entries), axis=0)
            for i, entries in obs.items() if len(entries) >= MIN_OBS
        }
        for center in locked.values():
            cv2.circle(frame, (int(center[0]), int(center[1])), 6, (0, 200, 0), -1)

        ready = len(locked) >= MIN_MARKERS
        color = (0, 200, 0) if ready else (0, 0, 255)
        msg = "%d/%d markers locked" % (len(locked), len(MARKER_CENTERS))
        if ready:
            msg += " - SPACE to save"
        cv2.rectangle(frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1), color, 6)
        cv2.putText(frame, msg, (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
        cv2.imshow("calibrate", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            print("Aborted, nothing saved.")
            break
        if key == ord("r"):
            obs = {i: [] for i in MARKER_CENTERS}
            print("Observations reset.")
        if key == ord(" ") and ready:
            h, w = frame.shape[:2]
            try:
                homography, src, dst, stats = fit_calibration(locked, (w, h))
            except ValueError as e:
                print("Fit failed: %s - keep collecting or press R to reset." % e)
                continue
            path = save_calibration(homography, (w, h), src, dst)
            print("Calibration saved to", path)
            print("  markers used: %d (rejected as outliers: %d)" %
                  (stats["markers"], stats["rejected"]))
            print("  screen distortion beyond flat perspective: "
                  "mean %.1f px, max %.1f px (on a 1280x720 screen) - "
                  "corrected by the spline layer" %
                  (stats["residual_mean"] * 1280, stats["residual_max"] * 1280))
            # learn the real ball colors under this projector light:
            # a few throws per color, sampled mid-flight (skippable)
            mapper = CalibrationMapper(homography, (w, h), src, dst)
            learn_colors(cam, config, mapper, (w, h))
            break

    cam.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
