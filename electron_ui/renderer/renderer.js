const API_BASE = 'http://127.0.0.1:8642';
const WS_URL = 'ws://127.0.0.1:8642/progreso';

const STATUS_META = {
  queued:      { label: 'en cola',      dot: 'var(--c-muted)', fill: 'var(--c-muted)' },
  extracting:  { label: 'analizando',   dot: 'var(--c-amber)', fill: 'var(--c-amber)' },
  downloading: { label: 'descargando',  dot: 'var(--c-teal)',  fill: 'var(--c-teal)' },
  paused:      { label: 'pausado',      dot: 'var(--c-amber)', fill: 'var(--c-amber)' },
  completed:   { label: 'completado',   dot: 'var(--c-green)', fill: 'var(--c-green)' },
  error:       { label: 'error',        dot: 'var(--c-red)',   fill: 'var(--c-red)' },
  cancelled:   { label: 'cancelado',    dot: 'var(--c-muted)', fill: 'var(--c-muted)' },
};

const PLUGIN_LABELS = {
  youtube: 'youtube',
  direct_http: 'directo',
  image_scraper: 'imágenes',
};

// id -> DownloadItem, y en qué orden se han visto por primera vez
const items = new Map();
const order = [];

const listEl = document.getElementById('download-list');
const emptyStateEl = document.getElementById('empty-state');
const statusbarEl = document.getElementById('statusbar');
const formEl = document.getElementById('add-form');
const inputEl = document.getElementById('url-input');

function displayName(item) {
  if (item.output_path) {
    const parts = item.output_path.split(/[\\/]/);
    return parts[parts.length - 1];
  }
  if (item.filename) return item.filename;
  try {
    const u = new URL(item.url);
    const base = u.pathname.split('/').filter(Boolean).pop();
    return base || u.hostname;
  } catch {
    return item.url;
  }
}

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${value.toFixed(1)} ${units[i]}`;
}

function formatSpeed(bytesPerSecond) {
  if (!bytesPerSecond) return '';
  return `${formatBytes(bytesPerSecond)}/s`;
}

function rowTemplate(item) {
  const li = document.createElement('li');
  li.className = 'download-row';
  li.dataset.id = item.id;
  li.innerHTML = `
    <span class="status-dot"></span>
    <div class="row-main">
      <div class="row-name"></div>
      <div class="row-meta">
        <div class="progress-track"><div class="progress-fill"></div></div>
        <span class="row-status-label"></span>
      </div>
      <div class="row-error" hidden></div>
    </div>
    <span class="row-size"></span>
    <span class="row-speed"></span>
    <span class="row-badge"></span>
    <button class="row-pause-resume" title="Pausar" aria-label="Pausar o reanudar descarga"></button>
    <button class="row-cancel" title="Cancelar" aria-label="Cancelar descarga">✕</button>
  `;
  li.querySelector('.row-pause-resume').addEventListener('click', () => togglePauseResume(item.id));
  li.querySelector('.row-cancel').addEventListener('click', () => cancelDownload(item.id));
  return li;
}

function renderRow(item) {
  let li = listEl.querySelector(`[data-id="${item.id}"]`);
  if (!li) {
    li = rowTemplate(item);
    listEl.appendChild(li);
  }

  const meta = STATUS_META[item.status] || STATUS_META.queued;

  li.querySelector('.status-dot').style.setProperty('--dot-color', meta.dot);
  li.querySelector('.row-name').textContent = displayName(item);
  li.querySelector('.row-name').title = item.url;
  li.querySelector('.progress-fill').style.width = `${item.progress || 0}%`;
  li.querySelector('.progress-fill').style.setProperty('--fill-color', meta.fill);
  li.querySelector('.row-status-label').textContent = meta.label;
  li.querySelector('.row-status-label').style.setProperty('--label-color', meta.dot);
  li.querySelector('.row-size').textContent = formatBytes(item.downloaded_bytes);
  li.querySelector('.row-speed').textContent = formatSpeed(item.speed);
  li.querySelector('.row-badge').textContent = PLUGIN_LABELS[item.plugin_name] || item.plugin_name || '';

  const errorEl = li.querySelector('.row-error');
  if (item.error) {
    errorEl.hidden = false;
    errorEl.textContent = item.error;
    errorEl.title = item.error;
  } else {
    errorEl.hidden = true;
  }

  const cancelBtn = li.querySelector('.row-cancel');
  cancelBtn.style.display = ['completed', 'error', 'cancelled'].includes(item.status) ? 'none' : '';

  const pauseResumeBtn = li.querySelector('.row-pause-resume');
  if (item.status === 'downloading' || item.status === 'extracting') {
    pauseResumeBtn.style.display = '';
    pauseResumeBtn.textContent = '⏸';
    pauseResumeBtn.title = 'Pausar';
  } else if (item.status === 'paused') {
    pauseResumeBtn.style.display = '';
    pauseResumeBtn.textContent = '▶';
    pauseResumeBtn.title = 'Reanudar';
  } else {
    pauseResumeBtn.style.display = 'none';
  }
}


function upsertItem(item) {
  const esNuevo = !items.has(item.id);
  if (esNuevo) {
    order.unshift(item.id); // los más recientes arriba
  }
  items.set(item.id, item);
  renderRow(item);
  if (esNuevo) {
    reorderList(); // solo hace falta reordenar cuando entra uno nuevo
  }
  updateStatusbar();
  updateEmptyState();
}

function reorderList() {
  for (const id of order) {
    const li = listEl.querySelector(`[data-id="${id}"]`);
    if (li) listEl.appendChild(li);
  }
}

function updateEmptyState() {
  emptyStateEl.style.display = items.size === 0 ? '' : 'none';
}

function updateStatusbar() {
  const counts = { downloading: 0, queued: 0, extracting: 0, completed: 0, error: 0 };
  for (const item of items.values()) {
    if (counts[item.status] !== undefined) counts[item.status]++;
  }
  const total = items.size;
  statusbarEl.textContent =
    `${total} elemento${total === 1 ? '' : 's'} · ` +
    `${counts.downloading + counts.extracting} activos · ` +
    `${counts.queued} en cola · ` +
    `${counts.completed} completados` +
    (counts.error ? ` · ${counts.error} con error` : '');
}

async function loadInitial() {
  try {
    const res = await fetch(`${API_BASE}/descargas`);
    const data = await res.json();
    for (const item of data.reverse()) {
      upsertItem(item);
    }
  } catch (err) {
    statusbarEl.textContent = 'Sin conexión con el servidor (¿está corriendo python run.py?)';
  }
}

async function addDownload(url) {
  try {
    const res = await fetch(`${API_BASE}/descargas`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const item = await res.json();
    upsertItem(item);
  } catch (err) {
    statusbarEl.textContent = 'Sin conexión con el servidor (¿está corriendo python run.py?)';
  }
}

async function cancelDownload(id) {
  try {
    await fetch(`${API_BASE}/descargas/${id}/cancelar`, { method: 'POST' });
  } catch {
    // el próximo mensaje del WebSocket (o un refresco) reflejará el estado real
  }
}



async function togglePauseResume(id) {
  const item = items.get(id);
  if (!item) return;
  const endpoint = item.status === 'paused' ? 'reanudar' : 'pausar';
  try {
    await fetch(`${API_BASE}/descargas/${id}/${endpoint}`, { method: 'POST' });
  } catch {
    // el próximo mensaje del WebSocket (o un refresco) reflejará el estado real
  }
}


function connectWebSocket() {
  const ws = new WebSocket(WS_URL);

  ws.addEventListener('message', (event) => {
    try {
      const item = JSON.parse(event.data);
      upsertItem(item);
    } catch {
      // mensaje no reconocido, se ignora
    }
  });

  ws.addEventListener('close', () => {
    setTimeout(connectWebSocket, 2000);
  });

  ws.addEventListener('error', () => ws.close());
}

formEl.addEventListener('submit', (event) => {
  event.preventDefault();
  const url = inputEl.value.trim();
  if (!url) return;
  addDownload(url);
  inputEl.value = '';
});

loadInitial();
connectWebSocket();