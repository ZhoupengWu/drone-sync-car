import cv2

markers = [1, 2, 3, 4, 5, 6, 7, 67]
borders = 50

for i in markers:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
    img = cv2.aruco.generateImageMarker(dictionary, i, 500)
    img = cv2.copyMakeBorder(img, borders, borders, borders, borders, cv2.BORDER_CONSTANT, value=255)
    cv2.imwrite(f"marker_{i}.png", img)