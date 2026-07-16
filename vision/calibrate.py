"""Homography calibration: camera pixels -> game screen coordinates.

Steps:
  1. Start the Godot game on the projector and press C to show the
     calibration pattern (white screen with 4 ArUco markers).
  2. Run:  python calibrate.py
  3. Aim the camera so it sees the whole projection. When all 4 markers are
     found the border turns green - press SPACE to save, Q to quit.

The result is written to calibration.json and used by detect.py.
"""

import cv2
import numpy as np

from common import MARKER_CENTERS, ARUCO_DICT, load_config, open_camera, save_calibration


def main():
    config = load_config()
    cam = open_camera(config)

    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(ARUCO_DICT),
        cv2.aruco.DetectorParameters(),
    )

    print("Looking for markers 0-3. SPACE = save calibration, Q = quit.")
    while True:
        ok, frame = cam.read()
        if not ok:
            raise SystemExit("Camera stopped delivering frames.")

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = detector.detectMarkers(gray)

        found = {}
        if ids is not None:
            cv2.aruco.drawDetectedMarkers(frame, corners, ids)
            for marker_corners, marker_id in zip(corners, ids.flatten()):
                if int(marker_id) in MARKER_CENTERS:
                    found[int(marker_id)] = marker_corners.reshape(4, 2).mean(axis=0)

        complete = len(found) == len(MARKER_CENTERS)
        color = (0, 200, 0) if complete else (0, 0, 255)
        msg = "All markers found - SPACE to save" if complete \
            else "Markers found: %d/%d" % (len(found), len(MARKER_CENTERS))
        cv2.rectangle(frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1), color, 6)
        cv2.putText(frame, msg, (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
        cv2.imshow("calibrate", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            print("Aborted, nothing saved.")
            break
        if key == ord(" ") and complete:
            src = np.array([found[i] for i in sorted(MARKER_CENTERS)], dtype=np.float64)
            dst = np.array([MARKER_CENTERS[i] for i in sorted(MARKER_CENTERS)], dtype=np.float64)
            homography, _ = cv2.findHomography(src, dst)
            h, w = frame.shape[:2]
            path = save_calibration(homography, (w, h))
            print("Calibration saved to", path)
            break

    cam.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
