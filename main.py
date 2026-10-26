import os
import cv2
import time
import threading
from flask import Flask, Response, jsonify, render_template, request
from djitellopy import Tello
import webbrowser
from dotenv import load_dotenv

load_dotenv()

ip_address = os.getenv("IP_ADDRESS", "127.0.0.1")
port_ip_address = int(os.getenv("PORT_IP_ADDRESS", 5000))

Tello.FRAME_GRAB_TIMEOUT = 10
BATTERIA_MINIMA = 15

app = Flask(__name__)
lock = threading.Lock()
tello = Tello()
frameReader = None



def clamp(valore):
    return max(-100, min(100, int(valore)))

def openBroswer():
    time.sleep(5)
    webbrowser.open(f"http://{ip_address}:{port_ip_address}")

@app.route("/")
def index():
    return render_template("index.html")

@app.get("/status")
def status():
    with lock:
        try:
            batteria = tello.query_battery()
        except Exception:
            batteria = None

    return jsonify({"battery": batteria, "flying": tello.is_flying})

@app.post("/takeoff")
def takeoff():
    with lock:
        try:
            if tello.query_battery() < BATTERIA_MINIMA:
                return (
                    jsonify(ok=False, error="Batteria troppo scarica per decollare"),
                    400,
                )

            tello.takeoff()
        except Exception as exc:
            return jsonify(ok=False, error=str(exc)), 500

    return jsonify(ok=True)

@app.post("/land")
def land():
    with lock:
        try:
            tello.send_rc_control(0, 0, 0, 0)
            tello.land()
        except Exception as exc:
            return jsonify(ok=False, error=str(exc)), 500

    return jsonify(ok=True)

@app.post("/emergency")
def emergency():
    try:
        tello.emergency()
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 500

    return jsonify(ok=True)

@app.post("/rc")
def rc():
    dati = request.get_json(silent=True) or {}

    if tello.is_flying:
        tello.send_rc_control(
            clamp(dati.get("lr", 0)),
            clamp(dati.get("fb", 0)),
            clamp(dati.get("ud", 0)),
            clamp(dati.get("yaw", 0)),
        )

    return jsonify(ok=True)

def generateFrames():
    while True:
        if frameReader is None or frameReader.frame is None:
            time.sleep(0.1)

            continue

        frame = cv2.cvtColor(frameReader.frame, cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode(".jpg", frame)

        if ok:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"

        time.sleep(1 / 15)

@app.route("/video_feed")
def videoFeed():
    return Response(generateFrames(), mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    try:
        tello.connect(wait_for_state=False)
        time.sleep(3)

        tello.streamon()
        time.sleep(3)

        frameReader = tello.get_frame_read()
        print(f"Pannello su http://{ip_address}:{port_ip_address}")
        app.run(
            host=ip_address,
            port=port_ip_address,
            threaded=True,
            use_reloader=False
        )
    finally:
        try:
            if tello.is_flying:
                tello.send_rc_control(0, 0, 0, 0)
                tello.land()
        except Exception as exc:
            print("Errore atterraggio:", exc)

        tello.end()
