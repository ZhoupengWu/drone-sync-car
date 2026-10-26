import cv2
from flask import Flask, render_template, Response

app = Flask(__name__)
camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)

def generateFrame():
    while True:
        ok, frame = camera.read()

        if not ok:
            break

        ok, buffer = cv2.imencode(".jpg", frame)

        if not ok:
            continue

        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"

@app.route("/")
def homepage():
    return render_template("index.html")

@app.route("/video_feed")
def videoFeed():
    return Response(generateFrame(), mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    app.run(
        "127.0.0.1",
        9000,
        debug=True
    )
