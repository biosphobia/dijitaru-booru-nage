"""Shared bits between calibrate.py and detect.py."""

import json
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
CALIBRATION_PATH = os.path.join(HERE, "calibration.json")

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
    cam = cv2.VideoCapture(config.get("camera_index", 0))
    if not cam.isOpened():
        raise SystemExit("Could not open camera index %s" % config.get("camera_index", 0))
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
