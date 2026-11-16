import cv2

class Marker:
    def __init__(self):
        self.detector = cv2.aruco.ArucoDetector(
            cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250),
            cv2.aruco.DetectorParameters(),
        )

    def detect(self, frame, target_id=None):
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray)

        if ids is None:
            return frame, None

        cv2.aruco.drawDetectedMarkers(frame, corners, ids)

        for c, i in zip(corners, ids.flatten()):
            if target_id is not None and int(i) != target_id:
                continue

            pts = c[0]
            cx, cy = pts.mean(axis=0)

            return frame, {
                "id": int(i),
                "err_x": float((cx - w / 2) / (w / 2)),
                "err_y": float((cy - h / 2) / (h / 2)),
                "area": float(cv2.contourArea(pts)),
            }

        return frame, None
