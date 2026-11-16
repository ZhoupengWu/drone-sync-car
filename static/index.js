const pressedControls = new Map();

const speed_slider = document.getElementById("speedSlider");
const status_message = document.getElementById("statusMessage");
const takeoff_button = document.getElementById("takeoffButton");
const land_button = document.getElementById("landButton");
const emergency_button = document.getElementById("emergencyButton");

let sendTimer = null;

const STOP_COMMAND = { leftRight: 0, forwardBack: 0, upDown: 0, yaw: 0 };

// Tasti della tastiera -> [asse, direzione]
const keyBindings = {
    w: ["forwardBack", 1],
    s: ["forwardBack", -1],
    a: ["leftRight", -1],
    d: ["leftRight", 1],
    r: ["upDown", 1],
    f: ["upDown", -1],
    q: ["yaw", -1],
    e: ["yaw", 1]
};

speed_slider.addEventListener("input", () => {
    document.getElementById("speedValue").textContent = speed_slider.value;
});

function showMessage(text) {
    status_message.textContent = text;
}

async function postJson(url, body) {
    try {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(body || {})
        });
        const data = await response.json();

        if (!data.ok) showMessage(data.error || "Errore");

        return data;
    } catch (error) {
        showMessage("Drone non raggiungibile");

        return { ok: false };
    }
}

function buildRcCommand() {
    const command = { ...STOP_COMMAND };

    for (const controlKey of pressedControls.keys()) {
        const [axis, direction] = controlKey.split(":");
        command[axis] += Number(direction) * Number(speed_slider.value);
    }

    return command;
}

function sendRcCommand() {
    postJson("/rc", buildRcCommand());
}

/**
 * Avvia l'invio ripetuto (ogni 100 ms) quando c'è almeno un controllo premuto
 * e lo ferma, mandando uno stop, quando vengono rilasciati tutti
 */
function updateSendLoop() {
    if (pressedControls.size > 0 && !sendTimer) {
        sendRcCommand();
        sendTimer = setInterval(sendRcCommand, 100);
    } else if (pressedControls.size === 0 && sendTimer) {
        clearInterval(sendTimer);
        sendTimer = null;
        postJson("/rc", STOP_COMMAND);
    }
}

function pressControl(axis, direction, button) {
    pressedControls.set(axis + ":" + direction, button);

    // un comando manuale riprende il controllo: spegne la modalità auto
    if (autoOn) setAuto(false);

    if (button) button.classList.add("active");

    updateSendLoop();
}

function releaseControl(axis, direction, button) {
    pressedControls.delete(axis + ":" + direction);

    if (button) button.classList.remove("active");

    updateSendLoop();
}

function stopAll() {
    for (const button of pressedControls.values()) {
        if (button) button.classList.remove("active");
    }

    pressedControls.clear();
    updateSendLoop();
    postJson("/rc", STOP_COMMAND);
}

function findButton(axis, direction) {
    return document.querySelector(`button[data-axis="${axis}"][data-direction="${direction}"]`);
}

document.querySelectorAll("button[data-axis]").forEach(button => {
    const axis = button.dataset.axis;
    const direction = Number(button.dataset.direction);

    button.addEventListener("pointerdown", event => {
        button.setPointerCapture(event.pointerId);
        pressControl(axis, direction, button);
    });

    ["pointerup", "pointercancel", "lostpointercapture"].forEach(eventName => {
        button.addEventListener(eventName, () => releaseControl(axis, direction, button));
    });
});

window.addEventListener("keydown", event => {
    if (event.target === target_input) return;

    if (event.repeat) return;

    if (event.code === "Space") {
        event.preventDefault();

        if (autoOn) setAuto(false);

        stopAll();

        return;
    }

    const binding = keyBindings[event.key.toLowerCase()];

    if (binding) pressControl(binding[0], binding[1], findButton(binding[0], binding[1]));
});

window.addEventListener("keyup", event => {
    if (event.target === target_input) return;

    const binding = keyBindings[event.key.toLowerCase()];

    if (binding) releaseControl(binding[0], binding[1], findButton(binding[0], binding[1]));
});

// Se la pagina perde il focus o viene nascosta, il drone si ferma
window.addEventListener("blur", stopAll);

document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopAll();
});

takeoff_button.addEventListener("click", async () => {
    takeoff_button.disabled = true;
    showMessage("Decollo in corso...");
    const data = await postJson("/takeoff");

    if (data.ok) showMessage("In volo");

    takeoff_button.disabled = false;
});

land_button.addEventListener("click", async () => {
    stopAll();
    land_button.disabled = true;
    showMessage("Atterraggio in corso...");
    const data = await postJson("/land");

    if (data.ok) showMessage("Atterrato");

    land_button.disabled = false;
});

emergency_button.addEventListener("click", async () => {
    if (!confirm("Spegnere subito i motori? Se il drone è in volo cadrà.")) return;

    stopAll();
    const data = await postJson("/emergency");

    if (data.ok) showMessage("Motori spenti");
});

async function refreshStatus() {
    try {
        const response = await fetch("/status");
        const data = await response.json();

        document.getElementById("batteryValue").textContent = data.battery ?? "-";
        document.getElementById("flightState").textContent = data.flying ? "in volo" : "a terra";
    } catch { }
}

refreshStatus();
setInterval(refreshStatus, 10000);

// ---------- Inseguimento marker ----------
const auto_button = document.getElementById("autoButton");
const calibrate_button = document.getElementById("calibrateButton");
const target_input = document.getElementById("targetInput");
const auto_info = document.getElementById("autoInfo");

let autoOn = false;

function renderAuto() {
    auto_button.classList.toggle("active", autoOn);
    auto_button.setAttribute("aria-pressed", String(autoOn));
    auto_button.querySelector("small").textContent = autoOn ? "ON" : "OFF";
}

async function setAuto(enabled) {
    autoOn = enabled;
    renderAuto();
    await postJson("/auto", { enabled });
}

auto_button.addEventListener("click", () => setAuto(!autoOn));

calibrate_button.addEventListener("click", async () => {
    const data = await postJson("/calibrate");

    if (data.ok) showMessage("Distanza memorizzata");
});

target_input.addEventListener("change", () => {
    const value = target_input.value === "" ? null : Number(target_input.value);

    postJson("/target", { id: value });
});

async function refreshAutoState() {
    try {
        const response = await fetch("/auto_state");
        const data = await response.json();

        autoOn = data.auto;
        renderAuto();

        const [, forwardBack, upDown, yaw] = data.command;
        const seen = data.info
            ? `marker ${data.info.id}, area ${Math.round(data.info.area)}`
            : "marker non visibile";
        const distance = data.area_target
            ? `distanza obiettivo: area ${Math.round(data.area_target)}`
            : "distanza non memorizzata";
        const simulated = data.auto && !data.flying ? " (prova a terra: comandi non inviati)" : "";

        auto_info.textContent =
            `${seen} · ${distance} · avanti ${forwardBack}, su ${upDown}, rotazione ${yaw}${simulated}`;
    } catch { }
}

setInterval(refreshAutoState, 300);
