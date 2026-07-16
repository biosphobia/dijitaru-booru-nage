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

DEFAULT_CONFIG = {
    "camera_index": 0,
    "fourcc": "MJPG",
    "capture_width": 1280,
    "capture_height": 720,
    "capture_fps": 60,
    "udp_host": "127.0.0.1",
    "udp_port": 4242,
    "preview": True,
    "detection": {
        "mode": "reversal",
        "processing_width": 640,
        "diff_threshold": 25,
        "min_area": 30,
        "max_area": 2500,
        "min_circularity": 0.4,
        "min_speed": 6.0,
        "max_match_dist": 90.0,
        "track_timeout_frames": 5,
        "cooldown_ms": 250,
        "cooldown_radius": 0.06,
    },
    "colors": [
        {"name": "red", "h_min": 170, "h_max": 10, "s_min": 80, "v_min": 60},
        {"name": "orange", "h_min": 11, "h_max": 25, "s_min": 80, "v_min": 60},
        {"name": "yellow", "h_min": 26, "h_max": 40, "s_min": 80, "v_min": 60},
        {"name": "green", "h_min": 41, "h_max": 85, "s_min": 60, "v_min": 50},
        {"name": "blue", "h_min": 95, "h_max": 130, "s_min": 60, "v_min": 50},
    ],
}

# Normalized game-screen coordinates of the four ArUco marker CENTERS shown
# by the Godot calibration screen (godot/scripts/CalibrationScreen.gd).
# Must stay in sync with that file.
MARKER_CENTERS = {
    0: (0.1, 0.1),  # top-left
    1: (0.9, 0.1),  # top-right
    2: (0.9, 0.9),  # bottom-right
    3: (0.1, 0.9),  # bottom-left
}

ARUCO_DICT = cv2.aruco.DICT_4X4_50


def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        print("Created default config:", CONFIG_PATH)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_calibration(homography, frame_size):
    data = {
        "homography": np.asarray(homography).tolist(),
        "frame_size": list(frame_size),  # [width, height] used at calibration time
    }
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
    return np.array(data["homography"], dtype=np.float64), tuple(data["frame_size"])


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

    # MJPG lets most USB webcams deliver 720p at 60 fps instead of 5-30.
    fourcc = config.get("fourcc", "MJPG")
    if fourcc:
        cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, config.get("capture_width", 1280))
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, config.get("capture_height", 720))
    cam.set(cv2.CAP_PROP_FPS, config.get("capture_fps", 60))
    return cam


def camera_to_game(points_px, homography, frame_size, calib_frame_size):
    """Map camera pixel coordinates -> normalized game coordinates [0,1].

    Handles the current capture resolution differing from the resolution the
    calibration was made at by rescaling first.
    """
    pts = np.asarray(points_px, dtype=np.float64).reshape(-1, 1, 2)
    sx = calib_frame_size[0] / frame_size[0]
    sy = calib_frame_size[1] / frame_size[1]
    pts[:, 0, 0] *= sx
    pts[:, 0, 1] *= sy
    out = cv2.perspectiveTransform(pts, homography)
    return out.reshape(-1, 2)


def game_area_polygon_px(homography, calib_frame_size, frame_size):
    """The projected game rectangle's outline in current-camera pixels
    (for drawing on the preview)."""
    unit = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float64).reshape(-1, 1, 2)
    inv = np.linalg.inv(homography)
    pts = cv2.perspectiveTransform(unit, inv).reshape(-1, 2)
    pts[:, 0] *= frame_size[0] / calib_frame_size[0]
    pts[:, 1] *= frame_size[1] / calib_frame_size[1]
    return pts.astype(np.int32)
