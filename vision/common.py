"""Shared bits between calibrate.py and detect.py."""

import json
import os
import sys

import cv2
import numpy as np

# When frozen into a portable executable (PyInstaller), keep config and
# calibration next to the .exe so the whole thing lives in one folder.
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(os.path.abspath(sys.executable))
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
CALIBRATION_PATH = os.path.join(HERE, "calibration.json")

# Defaults are for a PS3 Eye (CL-Eye or PS3EyeDirectShow driver): native
# 640x480 @ 60 fps, raw frames. For a regular webcam set capture_width/
# height to 1280/720 and fourcc to "MJPG" so it can reach 60 fps.
DEFAULT_CONFIG = {
    "camera_index": 0,
    "fourcc": "",
    "capture_width": 640,
    "capture_height": 480,
    "capture_fps": 60,
    "udp_host": "127.0.0.1",
    "udp_port": 4242,
    "udp_cmd_port": 4243,
    "preview": True,
    "meshy": {
        "api_key": "",
        "ai_model": "latest",
        "rig": True,
        "height_meters": 1.7,
    },
    "detection": {
        "mode": "reversal",
        "processing_width": 640,
        "diff_threshold": 25,
        "auto_threshold": True,
        "noise_multiplier": 6.0,
        "min_area": 30,
        "max_area": 2500,
        "min_speed": 6.0,
        "min_turn_deg": 45.0,
        "approach_frames": 4,
        "straightness_deg": 45.0,
        "max_match_dist": 55.0,
        "track_timeout_frames": 5,
        "cooldown_ms": 250,
        "cooldown_radius": 0.06,
    },
    "colors": [
        {"name": "lightblue", "h_min": 80, "h_max": 110, "s_min": 40, "v_min": 90},
        {"name": "orange", "h_min": 5, "h_max": 25, "s_min": 80, "v_min": 70},
    ],
}

# 4x3 grid of ArUco markers (ids 0-11, row-major) shown by the Godot
# calibration screen. Many well-spread points make the mapping accurate
# from low camera angles and on distorted screens, and calibration still
# works when only part of the grid is detected.
# Must stay in sync with godot/scripts/CalibrationScreen.gd.
GRID_XS = [0.14, 0.38, 0.62, 0.86]
GRID_YS = [0.15, 0.50, 0.85]
MARKER_CENTERS = {
    row * len(GRID_XS) + col: (GRID_XS[col], GRID_YS[row])
    for row in range(len(GRID_YS))
    for col in range(len(GRID_XS))
}

ARUCO_DICT = cv2.aruco.DICT_4X4_50


def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        print("Created default config:", CONFIG_PATH)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def update_meshy_config(updates):
    """Merge fields into the config's 'meshy' block and persist it."""
    cfg = load_config()
    cfg.setdefault("meshy", {}).update(updates)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    return cfg


def save_calibration(homography, frame_size, control_src=None, control_dst=None):
    data = {
        "homography": np.asarray(homography).tolist(),
        "frame_size": list(frame_size),  # [width, height] used at calibration time
    }
    if control_src is not None:
        data["control_src"] = np.asarray(control_src).tolist()  # camera px
        data["control_dst"] = np.asarray(control_dst).tolist()  # normalized screen
    with open(CALIBRATION_PATH, "w") as f:
        json.dump(data, f, indent=2)
    return CALIBRATION_PATH


def load_calibration():
    if not os.path.exists(CALIBRATION_PATH):
        raise SystemExit(
            "No calibration found (%s). Show the calibration screen in the game "
            "(press C) and run calibrate.py first." % CALIBRATION_PATH
        )
    with open(CALIBRATION_PATH) as f:
        data = json.load(f)
    return CalibrationMapper(
        np.array(data["homography"], dtype=np.float64),
        tuple(data["frame_size"]),
        data.get("control_src"),
        data.get("control_dst"),
    )


def _tps_kernel(r2):
    """Thin-plate spline kernel r^2 log r, as a function of squared radius."""
    with np.errstate(divide="ignore", invalid="ignore"):
        k = 0.5 * r2 * np.log(r2)
    return np.where(np.isfinite(k), k, 0.0)


class CalibrationMapper:
    """Camera pixels -> normalized game coordinates.

    A RANSAC homography carries the perspective (works from any camera
    angle on a flat screen); a thin-plate spline over the calibration
    control points smoothly corrects whatever the homography cannot
    express (keystone correction artifacts, curved walls, lens
    distortion). With no control points it is a plain homography.
    """

    def __init__(self, homography, frame_size, control_src=None, control_dst=None,
                 smoothing=1e-6):
        self.homography = np.asarray(homography, dtype=np.float64)
        self.frame_size = tuple(frame_size)
        self._tps = None
        if control_src is not None and len(control_src) >= 6:
            src = np.asarray(control_src, dtype=np.float64).reshape(-1, 2)
            dst = np.asarray(control_dst, dtype=np.float64).reshape(-1, 2)
            base = cv2.perspectiveTransform(
                src.reshape(-1, 1, 2), self.homography).reshape(-1, 2)
            residual = dst - base
            if np.max(np.abs(residual)) > 1e-9:
                self._tps = self._fit_tps(src, residual, smoothing)

    def _norm(self, pts_px):
        return pts_px / np.asarray(self.frame_size, dtype=np.float64)

    def _fit_tps(self, src_px, residual, lam):
        pts = self._norm(src_px)
        n = len(pts)
        d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)
        K = _tps_kernel(d2) + lam * np.eye(n)
        P = np.hstack([np.ones((n, 1)), pts])
        A = np.zeros((n + 3, n + 3))
        A[:n, :n] = K
        A[:n, n:] = P
        A[n:, :n] = P.T
        b = np.zeros((n + 3, 2))
        b[:n] = residual
        return pts, np.linalg.solve(A, b)

    def _tps_eval(self, pts_px):
        ctrl, w = self._tps
        q = self._norm(pts_px)
        d2 = ((q[:, None, :] - ctrl[None, :, :]) ** 2).sum(-1)
        return _tps_kernel(d2) @ w[:len(ctrl)] \
            + np.hstack([np.ones((len(q), 1)), q]) @ w[len(ctrl):]

    def map_points(self, points_px, frame_size):
        """Map camera pixels (at the given capture size) to normalized game
        coordinates, rescaling to the calibration-time capture size first."""
        pts = np.asarray(points_px, dtype=np.float64).reshape(-1, 2).copy()
        pts[:, 0] *= self.frame_size[0] / frame_size[0]
        pts[:, 1] *= self.frame_size[1] / frame_size[1]
        out = cv2.perspectiveTransform(pts.reshape(-1, 1, 2), self.homography).reshape(-1, 2)
        if self._tps is not None:
            out = out + self._tps_eval(pts)
        return out

    def game_polygon_px(self, frame_size):
        """The projected game rectangle's outline in current-camera pixels
        (preview drawing only - homography approximation)."""
        unit = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64).reshape(-1, 1, 2)
        inv = np.linalg.inv(self.homography)
        pts = cv2.perspectiveTransform(unit, inv).reshape(-1, 2)
        pts[:, 0] *= frame_size[0] / self.frame_size[0]
        pts[:, 1] *= frame_size[1] / self.frame_size[1]
        return pts.astype(np.int32)


def open_camera(config):
    index = config.get("camera_index", 0)

    # Pick the native backend per OS: AVFoundation on macOS (required for
    # camera-permission prompts to work properly), DirectShow on Windows
    # (much faster startup and lets MJPG reach 60 fps on most webcams).
    if sys.platform == "darwin":
        backend = cv2.CAP_AVFOUNDATION
    elif sys.platform.startswith("win"):
        backend = cv2.CAP_DSHOW
    else:
        backend = cv2.CAP_ANY

    cam = cv2.VideoCapture(index, backend)
    if not cam.isOpened() and backend != cv2.CAP_ANY:
        cam = cv2.VideoCapture(index)  # fall back to whatever OpenCV picks
    if not cam.isOpened():
        raise SystemExit(
            "Could not open camera index %s. On macOS, make sure the terminal "
            "app has Camera permission (System Settings > Privacy & Security "
            "> Camera)." % index
        )

    # Optional pixel-format override. Leave "" for raw-frame cameras like
    # the PS3 Eye; set "MJPG" for regular webcams so they reach 60 fps at
    # 720p (harmlessly ignored where unsupported).
    fourcc = config.get("fourcc", "")
    if fourcc:
        cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, config.get("capture_width", 640))
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, config.get("capture_height", 480))
    cam.set(cv2.CAP_PROP_FPS, config.get("capture_fps", 60))
    return cam


def aruco_detector():
    """ArUco detector tuned for easy but accurate pickup: wide adaptive
    threshold sweep and low perimeter floor find small/skewed markers at
    low camera angles; sub-pixel corner refinement keeps them accurate."""
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 45
    params.adaptiveThreshWinSizeStep = 4
    params.minMarkerPerimeterRate = 0.01
    params.errorCorrectionRate = 0.8
    return cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(ARUCO_DICT), params)
