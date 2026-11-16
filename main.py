import os
import cv2
import math
import time
import threading
from flask import Flask, Response, jsonify, render_template, request
from djitellopy import Tello
import webbrowser
from dotenv import load_dotenv
from services.marker import Marker

load_dotenv()

ip_address = os.getenv("IP_ADDRESS", "127.0.0.1")
port_ip_address = int(os.getenv("PORT_IP_ADDRESS", 5000))

Tello.FRAME_GRAB_TIMEOUT = 10
BATTERIA_MINIMA = 15

# Parametri dell'inseguimento: parti bassi e alza con cautela
MAX_AUTO_SPEED = 35  # limite di velocità in modalità auto (0-100)
KP_YAW = 60  # rotazione per centrare il marker in orizzontale
KP_UD = 50  # su/giù per centrare il marker in verticale
KP_FWD = 60  # avanti/indietro per mantenere la distanza
DEADZONE = 0.08  # errori più piccoli di così vengono ignorati

app = Flask(__name__)
lock = threading.Lock()
tello = Tello()
frameReader = None
marker = Marker()

# Stato condiviso tra il thread di visione e le route Flask
state_lock = threading.Lock()
state = {
    "auto": False,
    "target_id": None,
    "area_target": None,
    "info": None,
    "command": [0, 0, 0, 0]
}
latest_jpeg = None


def clamp(valore):
    return max(-100, min(100, int(valore)))

def limit(valore):
    return max(-MAX_AUTO_SPEED, min(MAX_AUTO_SPEED, int(valore)))

def deadzone(errore):
    return 0 if abs(errore) < DEADZONE else errore

def compute_command(info, area_target):
    """Ritorna (leftRight, forwardBack, upDown, yaw) per centrare il marker."""

    yaw = limit(KP_YAW * deadzone(info["err_x"]))
    up_down = limit(-KP_UD * deadzone(info["err_y"]))  # y dell'immagine cresce verso il basso

    forward_back = 0
    if area_target:
        # il lato apparente del marker è proporzionale a 1/distanza, cioè alla radice dell'area
        err_dist = 1 - math.sqrt(info["area"] / area_target)
        forward_back = limit(KP_FWD * deadzone(err_dist))

    return (0, forward_back, up_down, yaw)

def stop_auto():
    """Disattiva la modalità auto e ferma il drone."""

    with state_lock:
        state["auto"] = False
        state["command"] = [0, 0, 0, 0]

        try:
            tello.send_rc_control(0, 0, 0, 0)
        except Exception as exc:
            print("Errore stop:", exc)

def openBrowser():
    time.sleep(5)
    webbrowser.open(f"http://{ip_address}:{port_ip_address}")

def vision_loop():
    """Legge i frame, rileva il marker e se auto è attivo, guida il drone."""

    global latest_jpeg

    while True:
        try:
            if frameReader is None or frameReader.frame is None:
                time.sleep(0.1)
                continue

            frame = cv2.cvtColor(frameReader.frame, cv2.COLOR_RGB2BGR)

            with state_lock:
                target_id = state["target_id"]

            frame, info = marker.detect(frame, target_id)

            with state_lock:
                state["info"] = info
                auto = state["auto"]

                if auto and info:
                    command = compute_command(info, state["area_target"])
                else:
                    command = (0, 0, 0, 0)

                state["command"] = list(command)

                if auto and tello.is_flying:
                    tello.send_rc_control(*command)

            h, w = frame.shape[:2]
            cv2.drawMarker(frame, (w // 2, h // 2), (0, 255, 0), cv2.MARKER_CROSS, 24, 2)

            if auto:
                etichetta = "AUTO" if tello.is_flying else "AUTO (prova a terra)"
                cv2.putText(
                    frame,
                    etichetta,
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 165, 255),
                    2,
                )

            ok, buf = cv2.imencode(".jpg", frame)

            if ok:
                latest_jpeg = buf.tobytes()

            time.sleep(1 / 15)
        except Exception as exc:
            print("Errore nel thread di visione: ", exc)
            time.sleep(0.5)

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

@app.get("/auto_state")
def auto_state():
    with state_lock:
        return jsonify(
            auto=state["auto"],
            target_id=state["target_id"],
            area_target=state["area_target"],
            info=state["info"],
            command=state["command"],
            flying=tello.is_flying,
        )

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
    stop_auto()

    with lock:
        try:
            tello.send_rc_control(0, 0, 0, 0)
            tello.land()
        except Exception as exc:
            return jsonify(ok=False, error=str(exc)), 500

    return jsonify(ok=True)

@app.post("/emergency")
def emergency():
    stop_auto()

    try:
        tello.emergency()
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 500

    return jsonify(ok=True)

@app.post("/rc")
def rc():
    data = request.get_json(silent=True) or {}

    if state["auto"]:
        return jsonify(ok=True, ignored=True)

    if tello.is_flying:
        tello.send_rc_control(
            clamp(data.get("leftRight", 0)),
            clamp(data.get("forwardBack", 0)),
            clamp(data.get("upDown", 0)),
            clamp(data.get("yaw", 0)),
        )

    return jsonify(ok=True)

@app.post("/auto")
def set_auto():
    data = request.get_json(silent=True) or {}

    if data.get("enabled"):
        with state_lock:
            state["auto"] = True
    else:
        stop_auto()

    return jsonify(ok=True, auto=state["auto"])

@app.post("/target")
def set_target():
    data = request.get_json(silent=True) or {}
    value = data.get("id")

    try:
        target = None if value in (None, "") else int(value)
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Id marker non valido"), 400

    if target is not None and not 0 <= target <= 249:
        return jsonify(ok=False, error="L'id deve essere tra 0 e 249"), 400

    with state_lock:
        state["target_id"] = target

    return jsonify(ok=True, id=target)

@app.post("/calibrate")
def calibrate():
    """Memorizza l'area attuale del marker come distanza obiettivo."""

    with state_lock:
        info = state["info"]

        if info is None:
            return jsonify(ok=False, error="Nessun marker visibile"), 400

        state["area_target"] = info["area"]

        return jsonify(ok=True, area_target=info["area"])

def generateFrames():
    while True:
        jpeg = latest_jpeg

        if jpeg is None:
            time.sleep(0.1)

            continue

        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

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

        threading.Thread(target=vision_loop, daemon=True).start()
        threading.Thread(target=openBrowser, daemon=True).start()

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
            print("Errore atterraggio: ", exc)

        tello.end()
