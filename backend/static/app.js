const API = "api"; // relative -- resolved against the <base> set in index.html

let allJobs = [];
let currentStateFilter = "ALL";
let currentPartition = "ALL";
let currentSearch = "";

// Watched jobs synced from the backend (server is the source of truth).
// Shape: { [job_id]: job_name }
let watched = {};

function setNotifyHint(msg) {
  const el = document.getElementById("notify-hint");
  el.textContent = msg || "";
  el.hidden = !msg;
}

async function onWatchToggle(checkbox) {
  const id = checkbox.dataset.jobId;
  const name = checkbox.dataset.jobName;
  try {
    const result = await fetchJson(`/watch/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, watch: checkbox.checked }),
    });
    watched = result.watched || {};
  } catch (e) {
    // Revert the visual toggle on error so the UI stays consistent with server state.
    checkbox.checked = !checkbox.checked;
    setNotifyHint(`Failed to update watch: ${e.message}`);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function stateBucket(state) {
  if (state === "RUNNING" || state === "COMPLETING" || state === "CONFIGURING") return "RUNNING";
  if (state === "PENDING") return "PENDING";
  return "OTHER";
}

async function fetchJson(path, opts) {
  const res = await fetch(`${API}${path}`, opts);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function fmtWhen(iso) {
  if (!iso) return "never";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleTimeString();
}

function renderStats(data) {
  const states = { RUNNING: 0, PENDING: 0 };
  for (const j of allJobs) {
    if (j.state === "RUNNING") states.RUNNING++;
    else if (j.state === "PENDING") states.PENDING++;
  }
  const partitions = new Set(allJobs.map((j) => j.partition)).size;

  document.getElementById("stat-cards").innerHTML = `
    <div class="card"><h3>Total jobs</h3><div class="big">${allJobs.length}</div></div>
    <div class="card"><h3>Running</h3><div class="big pos">${states.RUNNING}</div></div>
    <div class="card"><h3>Pending</h3><div class="big" style="color:var(--warn)">${states.PENDING}</div></div>
    <div class="card"><h3>Partitions</h3><div class="big">${partitions}</div></div>
  `;

  const statusEl = document.getElementById("header-status");
  if (data.error) {
    statusEl.textContent = `error: ${data.error}`;
    statusEl.classList.add("status-error");
  } else {
    statusEl.textContent = `updated ${fmtWhen(data.generated_at)} · host ${data.host || ""}`;
    statusEl.classList.remove("status-error");
  }
}

function populatePartitions() {
  const sel = document.getElementById("partition-filter");
  const partitions = Array.from(new Set(allJobs.map((j) => j.partition))).sort();
  const prev = sel.value || "ALL";
  sel.innerHTML = `<option value="ALL">All partitions</option>` +
    partitions.map((p) => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`).join("");
  sel.value = partitions.includes(prev) ? prev : "ALL";
}

function applyFilters() {
  const q = currentSearch.trim().toLowerCase();
  return allJobs.filter((j) => {
    if (currentStateFilter !== "ALL" && stateBucket(j.state) !== currentStateFilter) return false;
    if (currentPartition !== "ALL" && j.partition !== currentPartition) return false;
    if (q && !j.name.toLowerCase().includes(q)) return false;
    return true;
  });
}

function renderJobs() {
  const el = document.getElementById("jobs-list");
  const note = document.getElementById("jobs-note");
  const filtered = applyFilters();

  note.textContent = `${filtered.length} of ${allJobs.length} jobs shown`;

  if (!filtered.length) {
    el.innerHTML = `<div class="empty">No jobs match the current filters.</div>`;
    return;
  }

  const head = `
    <div class="job-row-head">
      <div></div><div class="id">Job ID</div><div>Name</div><div class="partition">Partition</div><div class="side">State &middot; Time</div><div class="notify-col">Notify</div>
    </div>`;

  const rows = filtered.map((j) => `
    <div class="job-row" data-state="${stateBucket(j.state)}">
      <div class="stripe"></div>
      <div class="id">#${escapeHtml(j.job_id)}</div>
      <div>
        <div class="name">${escapeHtml(j.name)}</div>
        <div class="tags">${escapeHtml(j.reason)} &middot; ${escapeHtml(j.nodes)} node(s) &middot; ${escapeHtml(j.cpus)} cpu</div>
      </div>
      <div class="partition">${escapeHtml(j.partition)}</div>
      <div class="side">${escapeHtml(j.state)} &middot; ${escapeHtml(j.time_used)} / ${escapeHtml(j.time_limit)}</div>
      <label class="notify-col switch" title="Notify me via Telegram when this job changes state">
        <input type="checkbox" data-job-id="${escapeHtml(j.job_id)}" data-job-name="${escapeHtml(j.name)}" ${watched[j.job_id] ? "checked" : ""}>
        <span class="slider"></span>
      </label>
    </div>`).join("");

  el.innerHTML = head + rows;
}

async function loadJobs() {
  try {
    const data = await fetchJson("/jobs");
    allJobs = data.jobs || [];

    // Sync the watched map from the server so all tabs/sessions stay consistent.
    if (data.watched) watched = data.watched;

    // Warn if Telegram is not yet configured.
    if (!data.telegram_configured) {
      setNotifyHint(
        "⚠️ Telegram notifications are not configured. " +
        "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable them."
      );
    } else {
      setNotifyHint("");
    }

    populatePartitions();
    renderJobs();
    renderStats(data);
  } catch (e) {
    const statusEl = document.getElementById("header-status");
    statusEl.textContent = `error: ${e.message}`;
    statusEl.classList.add("status-error");
  }
}

document.getElementById("jobs-list").addEventListener("change", (e) => {
  if (e.target.matches('.switch input[type="checkbox"]')) onWatchToggle(e.target);
});

document.getElementById("search").addEventListener("input", (e) => {
  currentSearch = e.target.value;
  renderJobs();
});

document.getElementById("partition-filter").addEventListener("change", (e) => {
  currentPartition = e.target.value;
  renderJobs();
});

document.querySelectorAll(".filter-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentStateFilter = btn.dataset.state;
    renderJobs();
  });
});

document.getElementById("refresh-btn").addEventListener("click", async () => {
  document.getElementById("header-status").textContent = "refreshing…";
  await fetchJson("/refresh", { method: "POST" }).catch(() => {});
  loadJobs();
});

// Bootstrap: load initial watched state from server, then start polling.
async function init() {
  try {
    const data = await fetchJson("/watched");
    watched = data.watched || {};
  } catch (e) {
    watched = {};
  }
  loadJobs();
  setInterval(loadJobs, 10000);
}

init();
