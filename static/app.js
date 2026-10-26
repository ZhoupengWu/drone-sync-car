const premuti = new Map();
const velocita = document.getElementById('velocita');
const messaggio = document.getElementById('messaggio');
let timer = null;

velocita.addEventListener("input", () => {
    document.getElementById('velocitaValore').textContent = velocita.value;
});

function mostra(testo) {
    messaggio.textContent = testo;
}

async function post(url, corpo) {
    try {
        const r = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(corpo || {})
        });
        const d = await r.json();

        if (!d.ok) mostra(d.error || 'Errore');

        return d;
    } catch (e) {
        mostra('Drone non raggiungibile');

        return { ok: false };
    }
}

function vettore() {
    const v = { lr: 0, fb: 0, ud: 0, yaw: 0 };

    for (const chiave of premuti.keys()) {
        const [asse, dir] = chiave.split(':');
        v[asse] += Number(dir) * Number(velocita.value);
    }

    return v;
}

function invia() {
    post('/rc', vettore());
}

function aggiorna() {
    if (premuti.size > 0 && !timer) {
        invia();
        timer = setInterval(invia, 100);
    } else if (premuti.size === 0 && timer) {
        clearInterval(timer);
        timer = null;
        post('/rc', { lr: 0, fb: 0, ud: 0, yaw: 0 });
    }
}

function preme(asse, dir, el) {
    premuti.set(asse + ':' + dir, el);

    if (el) el.classList.add('attivo');

    aggiorna();
}

function rilascia(asse, dir, el) {
    premuti.delete(asse + ':' + dir);

    if (el) el.classList.remove('attivo');

    aggiorna();
}

function fermaTutto() {
    for (const el of premuti.values()) if (el) el.classList.remove('attivo');

    premuti.clear();
    aggiorna();
    post('/rc', { lr: 0, fb: 0, ud: 0, yaw: 0 });
}

document.querySelectorAll('button[data-axis]').forEach(b => {
    const asse = b.dataset.axis, dir = Number(b.dataset.dir);
    b.addEventListener('pointerdown', e => { b.setPointerCapture(e.pointerId); preme(asse, dir, b); });

    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(ev => b.addEventListener(ev, () => rilascia(asse, dir, b)));
});

const tasti = {
    w: ['fb', 1], s: ['fb', -1], a: ['lr', -1], d: ['lr', 1],
    r: ['ud', 1], f: ['ud', -1], q: ['yaw', -1], e: ['yaw', 1]
};

function bottoneDi(asse, dir) {
    return document.querySelector(`button[data-axis="${asse}"][data-dir="${dir}"]`);
}

window.addEventListener('keydown', e => {
    if (e.repeat) return;

    if (e.code === 'Space') {
        e.preventDefault();
        fermaTutto();

        return;
    }

    const t = tasti[e.key.toLowerCase()];

    if (t) preme(t[0], t[1], bottoneDi(t[0], t[1]));
});

window.addEventListener('keyup', e => {
    const t = tasti[e.key.toLowerCase()];

    if (t) rilascia(t[0], t[1], bottoneDi(t[0], t[1]));
});

window.addEventListener('blur', fermaTutto);

document.addEventListener('visibilitychange', () => {
    if (document.hidden) fermaTutto();
});

const bDecolla = document.getElementById('decolla');
const bAtterra = document.getElementById('atterra');

bDecolla.addEventListener('click', async () => {
    bDecolla.disabled = true;
    mostra('Decollo in corso…');
    const d = await post('/takeoff');

    if (d.ok) mostra('In volo');

    bDecolla.disabled = false;
});

bAtterra.addEventListener('click', async () => {
    fermaTutto();
    bAtterra.disabled = true;
    mostra('Atterraggio in corso…');
    const d = await post('/land');

    if (d.ok) mostra('Atterrato');

    bAtterra.disabled = false;
});

document.getElementById('emergenza').addEventListener('click', async () => {
    if (!confirm('Spegnere subito i motori? Se il drone è in volo cadrà.')) return;

    fermaTutto();
    const d = await post('/emergency');

    if (d.ok) mostra('Motori spenti');
});

async function stato() {
    try {
        const d = await (await fetch('/status')).json();
        document.getElementById('batteria').textContent = d.battery ?? '–';
        document.getElementById('volo').textContent = d.flying ? 'in volo' : 'a terra';
    } catch { }
}

stato();
setInterval(stato, 10000);
