const $ = (id) => document.getElementById(id);

const logEl = $("log");

function log(obj) {
  const text = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
  logEl.textContent = text;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const raw = await res.text();
  let data;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch {
    data = raw;
  }
  if (!res.ok) {
    const msg = data?.detail || data?.message || data || res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function instanceName() {
  const v = $("instance").value.trim();
  if (!v) throw new Error("Completá el nombre de instancia");
  return v;
}

function showQr(payload) {
  const wrap = $("qr-wrap");
  const img = $("qr-img");
  const b64 = payload?.base64 || payload?.qrcode?.base64;
  if (!b64) {
    wrap.classList.add("hidden");
    return;
  }
  img.src = b64.startsWith("data:") ? b64 : `data:image/png;base64,${b64}`;
  wrap.classList.remove("hidden");
}

$("btn-create").addEventListener("click", async () => {
  try {
    const name = instanceName();
    const data = await api("/api/instances", {
      method: "POST",
      body: JSON.stringify({ instance_name: name, qrcode: true }),
    });
    log(data);
    showQr(data?.qrcode || data);
  } catch (e) {
    log(String(e.message || e));
  }
});

$("btn-qr").addEventListener("click", async () => {
  try {
    const name = instanceName();
    const data = await api(`/api/instances/${encodeURIComponent(name)}/connect`);
    log(data);
    showQr(data);
  } catch (e) {
    log(String(e.message || e));
  }
});

$("btn-state").addEventListener("click", async () => {
  try {
    const name = instanceName();
    const data = await api(`/api/instances/${encodeURIComponent(name)}/state`);
    log(data);
  } catch (e) {
    log(String(e.message || e));
  }
});

$("btn-logout").addEventListener("click", async () => {
  try {
    const name = instanceName();
    const data = await api(`/api/instances/${encodeURIComponent(name)}/logout`, {
      method: "POST",
    });
    log(data);
    $("qr-wrap").classList.add("hidden");
  } catch (e) {
    log(String(e.message || e));
  }
});

$("btn-delete").addEventListener("click", async () => {
  try {
    const name = instanceName();
    if (!confirm(`¿Borrar la instancia "${name}" en Evolution?`)) return;
    const data = await api(`/api/instances/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
    log(data);
    $("qr-wrap").classList.add("hidden");
    await refreshInstances();
  } catch (e) {
    log(String(e.message || e));
  }
});

$("btn-send").addEventListener("click", async () => {
  try {
    const name = instanceName();
    const number = $("number").value.trim();
    const text = $("text").value;
    if (!number) throw new Error("Completá el número o JID");
    if (!text.trim()) throw new Error("Completá el texto");
    const data = await api(`/api/instances/${encodeURIComponent(name)}/send-text`, {
      method: "POST",
      body: JSON.stringify({ number, text }),
    });
    log(data);
  } catch (e) {
    log(String(e.message || e));
  }
});

function renderInstances(list) {
  const root = $("instances");
  root.innerHTML = "";
  if (!Array.isArray(list) || list.length === 0) {
    root.innerHTML = `<p class="muted">No hay instancias o la respuesta tiene otro formato.</p>`;
    return;
  }
  for (const row of list) {
    const inst = row.instance || row;
    const name = inst.instanceName || inst.name || "(sin nombre)";
    const status = inst.status || inst.state || "";
    const el = document.createElement("div");
    el.className = "chip";
    el.innerHTML = `
      <span><strong>${name}</strong> <span class="muted">${status}</span></span>
      <button type="button" data-use="${name}">Usar</button>
    `;
    el.querySelector("button").addEventListener("click", () => {
      $("instance").value = name;
    });
    root.appendChild(el);
  }
}

async function refreshInstances() {
  try {
    const data = await api("/api/instances");
    log(data);
    renderInstances(data);
  } catch (e) {
    log(String(e.message || e));
  }
}

$("btn-refresh").addEventListener("click", refreshInstances);

async function loadWebhookDefault() {
  try {
    const cfg = await api("/api/config");
    const el = $("webhook-url");
    if (cfg?.webhook_public_url && !el.value.trim()) {
      el.value = cfg.webhook_public_url;
    }
  } catch {
    /* sin .env remoto */
  }
}

$("btn-webhook-get").addEventListener("click", async () => {
  try {
    const name = instanceName();
    const data = await api(`/api/instances/${encodeURIComponent(name)}/webhook`);
    log(data);
    if (data?.url) $("webhook-url").value = data.url;
  } catch (e) {
    log(String(e.message || e));
  }
});

$("btn-webhook-set").addEventListener("click", async () => {
  try {
    const name = instanceName();
    const url = $("webhook-url").value.trim();
    const body = url ? { url } : {};
    const data = await api(`/api/instances/${encodeURIComponent(name)}/webhook`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    log(data);
  } catch (e) {
    log(String(e.message || e));
  }
});

function formatTs(ts) {
  if (ts == null) return "";
  const d = new Date(typeof ts === "number" && ts < 1e12 ? ts * 1000 : ts);
  return Number.isNaN(d.getTime()) ? String(ts) : d.toLocaleString();
}

function renderInbox(data) {
  const root = $("inbox");
  const items = data?.items || [];
  const hits = data?.recent_webhooks || [];
  const tip = data?.diagnostics?.tip_es || "";

  let html = "";
  if (hits.length) {
    html += `<p class="muted small"><strong>Webhooks recibidos por este servidor</strong> (últimos ${hits.length})</p>`;
    html += hits
      .map(
        (h) => `
      <div class="inbox-item hit">
        <div class="meta">
          ${formatTs(h.ts)} · <code>${escapeHtml(h.event || "?")}</code>
          · instancia <strong>${escapeHtml(h.instance || "—")}</strong>
          · +${h.added_messages ?? 0} msg · ${h.raw_bytes ?? 0} bytes
        </div>
        ${h.hint ? `<div class="hint">${escapeHtml(h.hint)}</div>` : ""}
        <div class="keys">${escapeHtml((h.payload_keys || []).join(", "))}</div>
      </div>`
      )
      .join("");
  } else {
    html += `<p class="muted small">${escapeHtml(tip)}</p>`;
  }

  html += `<p class="muted small" style="margin-top:1rem"><strong>Mensajes entrantes parseados</strong></p>`;
  if (!items.length) {
    html += `<p class="muted">Ningún mensaje entrante aún. Si hay filas arriba con eventos pero +0 msg, el JSON no coincide con el parser.</p>`;
  } else {
    html += items
      .map(
        (m) => `
      <div class="inbox-item">
        <div class="meta">
          ${formatTs(m.ts)} · instancia <strong>${escapeHtml(m.instance || "?")}</strong>
          · ${escapeHtml(m.from_jid || "")}
          ${m.is_reply_to_prior ? " · ↩︎ respuesta" : ""}
        </div>
        <div class="body">${escapeHtml(m.text || "")}</div>
      </div>`
      )
      .join("");
  }

  root.innerHTML = html;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function refreshInbox() {
  try {
    let q = "?limit=80";
    try {
      const inst = $("instance").value.trim();
      if (inst) q += `&instance=${encodeURIComponent(inst)}`;
    } catch {
      /* */
    }
    const data = await api(`/api/inbox${q}`);
    renderInbox(data);
  } catch {
    /* silencioso en poll */
  }
}

$("btn-inbox-refresh").addEventListener("click", refreshInbox);

$("btn-inbox-clear").addEventListener("click", async () => {
  if (!confirm("¿Vaciar el buzón de prueba en memoria?")) return;
  try {
    await api("/api/inbox", { method: "DELETE" });
    await refreshInbox();
  } catch (e) {
    log(String(e.message || e));
  }
});

let inboxTimer = null;
function setupInboxPoll() {
  const tick = () => {
    if ($("inbox-auto").checked) refreshInbox();
  };
  inboxTimer = setInterval(tick, 2500);
  $("inbox-auto").addEventListener("change", () => {
    if ($("inbox-auto").checked) refreshInbox();
  });
}

refreshInstances();
loadWebhookDefault();
refreshInbox();
setupInboxPoll();
