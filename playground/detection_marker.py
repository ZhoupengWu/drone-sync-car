import cv2

dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())

camera = cv2.VideoCapture(0, cv2.CAP_MSMF)

while True:
    ok, frame = camera.read()

    if not ok:
        break

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, rejected = detector.detectMarkers(gray)

    if ids is not None:
        cv2.aruco.drawDetectedMarkers(frame, corners, ids)

        for c, i in zip(corners, ids.flatten()):
            cx, cy = c[0].mean(axis=0)
            print(f"ID {i} centro=({cx:.0f}, {cy:.0f})")

    cv2.imshow("ArUco", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()