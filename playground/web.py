"""
Tello 360° Tour
===============
Sequenza automatica:
  1. Connette il drone
  2. Attiva la camera e avvia lo stream
  3. Serve il video live su http://localhost:5000/video_feed  (MJPEG via Flask)
  4. Decolla
  5. Ruota 360° in senso orario, fermandosi ogni 45°
  6. Atterra in modo sicuro

Requisiti:
  - djitellopy      (pip install djitellopy)
  - flask           (pip install flask)
  - opencv-python   (incluso in djitellopy)
  - Connesso alla rete Wi-Fi del Tello

Endpoints Flask:
  GET /            → pagina HTML con il video embedded
  GET /video_feed  → stream MJPEG grezzo (usabile anche in VLC, ffplay, ecc.)
  GET /status      → JSON con stato drone e stream
"""

import sys
import threading
import time
import webbrowser

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template_string
from djitellopy import Tello

# ─── Parametri ────────────────────────────────────────────────────────────────
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
ROTATION_DEGREES = 45  # Gradi per ogni step di rotazione
ROTATION_PAUSE_SEC = 5  # Pausa (s) tra una rotazione e l'altra
TAKEOFF_WAIT_SEC = 3  # Attesa dopo il decollo per stabilizzarsi
STREAM_INIT_SEC = 2  # Attesa inizializzazione stream
MIN_BATTERY_PCT = 20  # Batteria minima per procedere (%)
JPEG_QUALITY = 80  # Qualità JPEG frames (0-100)
TARGET_FPS = 15  # FPS target per lo stream MJPEG
# ──────────────────────────────────────────────────────────────────────────────

# ─── Stato globale condiviso tra Flask e il thread del tour ───────────────────
_tello: Tello | None = None
_frame_reader = None
_stream_active = False
_tour_status = "in attesa"
_battery = 0
# ──────────────────────────────────────────────────────────────────────────────

# ─── Flask app ────────────────────────────────────────────────────────────────
app = Flask(__name__)

_INDEX_HTML = """<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tello 360° Tour – Live Stream</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #111; color: #eee; font-family: sans-serif;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center; min-height: 100vh;
      gap: 16px; padding: 20px;
    }
    h1  { font-size: 1.5rem; }
    img {
      max-width: 95vw; max-height: 75vh;
      border: 2px solid #444; border-radius: 8px;
      background: #222;
    }
    .info {
      display: flex; gap: 24px; font-size: 0.9rem; color: #aaa;
    }
    .info span { color: #fff; font-weight: bold; }
    a { color: #7af; }
  </style>
</head>
<body>
  <h1>🚁 Tello 360° Tour – Live Stream</h1>
  <img src="/video_feed" alt="Live stream Tello">
  <div class="info">
    <div>Stato tour: <span id="status">–</span></div>
    <div>Batteria: <span id="battery">–</span>%</div>
    <div>Stream: <a href="/video_feed" target="_blank">/video_feed</a></div>
  </div>
  <script>
    async function poll() {
      try {
        const r = await fetch('/status');
        const d = await r.json();
        document.getElementById('status').textContent  = d.tour_status;
        document.getElementById('battery').textContent = d.battery;
      } catch {}
    }
    poll();
    setInterval(poll, 100);
  </script>
</body>
</html>"""


@app.route("/")
def index():
    """Pagina HTML con il video embedded e un pannello di stato."""
    return render_template_string(_INDEX_HTML)


@app.route("/status")
def status():
    """Restituisce lo stato corrente del drone e dello stream in JSON."""
    return jsonify(
        {
            "stream_active": _stream_active,
            "tour_status": _tour_status,
            "battery": _battery,
        }
    )


def _generate_frames():
    """Generatore MJPEG: legge i frame da djitellopy e li codifica in JPEG."""
    frame_interval = 1.0 / TARGET_FPS
    last_time = 0.0
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]

    while True:
        # Se il drone non è ancora pronto, mostra un frame di attesa
        if not _stream_active or _frame_reader is None:
            blank = np.zeros((480, 640, 3), dtype="uint8")
            cv2.putText(
                blank,
                "In attesa del drone...",
                (100, 240),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (200, 200, 200),
                2,
            )
            _, buf = cv2.imencode(".jpg", blank)
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            )
            time.sleep(0.1)
            continue

        # Throttle al TARGET_FPS
        now = time.time()
        if now - last_time < frame_interval:
            time.sleep(0.005)
            continue
        last_time = now

        try:
            frame = _frame_reader.frame
            if frame is None:
                time.sleep(0.05)
                continue
            # Converte BGR (formato OpenCV/djitellopy) → RGB (atteso dal browser)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ok, buf = cv2.imencode(".jpg", frame, encode_params)
            if not ok:
                continue
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            )
        except Exception:
            time.sleep(0.05)


@app.route("/video_feed")
def video_feed():
    """Endpoint MJPEG: apribile nel browser, in VLC o in qualsiasi client HTTP."""
    return Response(
        _generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# ──────────────────────────────────────────────────────────────────────────────


# ─── Logica del tour ──────────────────────────────────────────────────────────
def _run_tour() -> None:
    """Esegue il 360° tour in un thread separato."""
    global _tello, _frame_reader, _stream_active, _tour_status, _battery

    separator = "=" * 60
    print(separator)
    print("  TELLO 360° TOUR  –  Stream live via Flask MJPEG")
    print(separator)

    # ── Connessione ───────────────────────────────────────────────
    _tour_status = "connessione..."
    print("\n[1/5] Connessione al Tello...")
    _tello = Tello()
    try:
        # wait_for_state=False evita il timeout sul pacchetto UDP 8890
        # spesso bloccato dal firewall Windows
        _tello.connect(wait_for_state=False)
    except Exception as exc:
        print(f"  ❌ Connessione fallita: {exc}")
        print("     Verifica di essere connesso alla rete Wi-Fi del Tello.")
        _tour_status = "errore connessione"
        return

    time.sleep(2)
    try:
        _battery = _tello.get_battery()
    except Exception:
        _battery = 0

    print(f"  ✅ Connesso! Batteria: {_battery}%")

    if _battery < MIN_BATTERY_PCT:
        print(f"  ❌ Batteria troppo bassa ({_battery}%). Minimo: {MIN_BATTERY_PCT}%")
        _tello.end()
        _tour_status = "batteria insufficiente"
        return

    try:
        # ── Attiva streaming video ────────────────────────────────
        _tour_status = "avvio stream..."
        print("\n[2/5] Attivazione streaming video...")
        _tello.streamon()
        _frame_reader = _tello.get_frame_read()
        time.sleep(STREAM_INIT_SEC)
        _stream_active = True
        print(f"  ✅ Stream attivo → http://localhost:{FLASK_PORT}/")

        # ── Decollo ───────────────────────────────────────────────
        _tour_status = "decollo"
        print("\n[3/5] Decollo...")
        _tello.takeoff()
        time.sleep(TAKEOFF_WAIT_SEC)
        try:
            height = _tello.get_height()
        except Exception:
            height = "?"
        print(f"  ✅ In volo! Altezza: {height} cm")

        # ── Rotazione 360° a step di ROTATION_DEGREES ────────────
        total_steps = 360 // ROTATION_DEGREES
        print(f"\n[4/5] Rotazione 360° – {total_steps} step da {ROTATION_DEGREES}°")
        print(f"       Pausa tra ogni step: {ROTATION_PAUSE_SEC}s")
        print(separator)

        for step in range(total_steps):
            angle_done = (step + 1) * ROTATION_DEGREES
            try:
                _battery = _tello.get_battery()
            except Exception:
                pass
            _tour_status = f"rotazione step {step + 1}/{total_steps} ({angle_done}°)"
            print(
                f"  → Step {step + 1:2d}/{total_steps}: "
                f"+{ROTATION_DEGREES}°  (totale: {angle_done:3d}°)  "
                f"Batteria: {_battery}%"
            )

            _tello.rotate_clockwise(ROTATION_DEGREES)
            time.sleep(ROTATION_PAUSE_SEC)

        print(separator)
        print("  ✅ Rotazione 360° completata!")
        _tour_status = "completato"

    except KeyboardInterrupt:
        print("\n  ⚠️  Interruzione manuale (Ctrl+C)")
        _tour_status = "interrotto"
    except Exception as exc:
        import traceback

        print(f"\n  ❌ Errore durante il volo: {exc}")
        traceback.print_exc()
        _tour_status = f"errore: {exc}"
    finally:
        # ── Atterraggio sicuro (sempre) ───────────────────────────
        print("\n[5/5] 🛬 Atterraggio in corso...")
        try:
            _tello.land()
            print("  ✅ Atterrato con successo!")
        except Exception as exc:
            print(f"  ⚠️  Errore atterraggio: {exc}")

        print("\n🧹 Cleanup risorse...")
        _stream_active = False
        try:
            _tello.streamoff()
            print("  ✅ Stream disattivato")
        except Exception:
            pass
        try:
            _tello.end()
            print("  ✅ Drone disconnesso")
        except Exception:
            pass

    print("\n" + separator)
    print("  SESSIONE COMPLETATA")
    print(separator)


# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    # Avvia il tour in un thread daemon (così termina insieme al processo principale)
    tour_thread = threading.Thread(target=_run_tour, daemon=True, name="TelloTour")
    tour_thread.start()

    # Apri il browser dopo che Flask è partito
    def _open_browser():
        time.sleep(2)
        webbrowser.open(f"http://localhost:{FLASK_PORT}/")

    threading.Thread(target=_open_browser, daemon=True).start()

    print(f"\n  🌐  Stream disponibile su:")
    print(f"       http://localhost:{FLASK_PORT}/            ← pagina HTML")
    print(f"       http://localhost:{FLASK_PORT}/video_feed  ← MJPEG grezzo")
    print(f"       http://localhost:{FLASK_PORT}/status      ← JSON stato\n")

    # Flask gira nel thread principale (threaded=True per gestire più client)
    app.run(host=FLASK_HOST, port=FLASK_PORT, threaded=True)


if __name__ == "__main__":
    main()
