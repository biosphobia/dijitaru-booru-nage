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

import cv2
import numpy as np

from common import (
    MARKER_CENTERS,
    CalibrationMapper,
    aruco_detector,
    load_config,
    open_camera,
    save_calibration,
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
            break

    cam.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
