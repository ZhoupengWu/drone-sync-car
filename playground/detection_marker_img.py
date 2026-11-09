import cv2

dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())

img = cv2.imread("marker_67.png")

gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
corners, ids, _ = detector.detectMarkers(gray)

if ids is not None:
    cv2.aruco.drawDetectedMarkers(img, corners, borderColor=(0, 0, 255))

    for c, i in zip(corners, ids.flatten()):
        print(c)
        cx, cy = c[0].mean(axis=0)
        print(f"ID {i} centro=({cx:.0f}, {cy:.0f})")

cv2.imshow("ArUco", img)
cv2.waitKey(0)
cv2.destroyAllWindows()
