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
  video: 'vídeo',
  youtube: 'vídeo',
  direct_http: 'directo',
  image_scraper: 'web',
  web: 'web',
  olympus: 'olympus',
  gdrive: 'drive',
  mega: 'mega',
};

const TIPO_META = {
  imagen:     { label: 'Imágenes',    icon: '▣' },
  video:      { label: 'Vídeos',      icon: '▶' },
  audio:      { label: 'Audio',       icon: '♪' },
  documento:  { label: 'Documentos',  icon: '▤' },
  comprimido: { label: 'Comprimidos', icon: '◫' },
  archivo:    { label: 'Archivos',    icon: '◻' },
  enlace:     { label: 'Enlaces',     icon: '↗' },
};

const ACTIVOS = ['queued', 'extracting', 'downloading'];
const FINALES = ['completed', 'error', 'cancelled'];

// Lo entrega el proceso principal de Electron al arrancar (ver init()).
let apiToken = null;

function api(ruta, opciones = {}) {
  return fetch(`${API_BASE}${ruta}`, {
    ...opciones,
    headers: { ...(opciones.headers || {}), 'X-API-Token': apiToken },
  });
}

async function apiJson(ruta, opciones = {}) {
  const res = await api(ruta, opciones);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);
  return data;
}

function postJson(ruta, cuerpo, extra = {}) {
  return apiJson(ruta, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cuerpo),
    ...extra,
  });
}

// id -> DownloadItem. 'order' guarda solo las descargas de primer nivel
// (los paquetes y las sueltas), las más recientes primero; los hijos de
// cada paquete van en 'children', en el orden en que llegaron.
const items = new Map();
const order = [];
const children = new Map();
const expanded = new Set();

const listEl = document.getElementById('download-list');
const emptyStateEl = document.getElementById('empty-state');
const statusbarEl = document.getElementById('statusbar');
const formEl = document.getElementById('add-form');
const inputEl = document.getElementById('url-input');
const directBtnEl = document.getElementById('direct-btn');
const folderPathEl = document.getElementById('folder-path');
const folderBtnEl = document.getElementById('folder-btn');

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
  const units = ['KB', 'MB', 'GB', 'TB'];
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

function slug(texto) {
  return (texto || '')
    .replace(/[^\p{L}\p{N}._-]+/gu, '-')
    .replace(/^[-.]+|[-.]+$/g, '')
    .slice(0, 80);
}

// ---------------------------------------------------------------------
// Lista de descargas
// ---------------------------------------------------------------------

function isPackage(item) {
  return (children.get(item.id) || []).length > 0;
}

function kidsOf(id) {
  return (children.get(id) || []).map((k) => items.get(k)).filter(Boolean);
}

// Estado "resumen" de un paquete a partir de sus hijos.
function aggregate(item) {
  const kids = kidsOf(item.id);
  const total = kids.length;
  const n = (st) => kids.filter((k) => st.includes(k.status)).length;
  const done = n(['completed']);
  const errores = n(['error']);
  const activos = n(ACTIVOS);
  const pausados = n(['paused']);
  const progreso = kids.reduce((s, k) => s + (k.status === 'completed' ? 100 : k.progress || 0), 0) / total;

  let status = 'completed';
  let label = `${done}/${total}`;
  if (activos) { status = 'downloading'; label = `descargando ${done}/${total}`; }
  else if (pausados) { status = 'paused'; label = `pausado ${done}/${total}`; }
  else if (errores) { status = 'error'; label = `${done}/${total} · ${errores} con error`; }
  else if (n(['cancelled']) === total) { status = 'cancelled'; label = 'cancelado'; }
  else { label = `completado ${done}/${total}`; }

  return {
    status, label, progreso, activos, pausados, errores,
    bytes: kids.reduce((s, k) => s + (k.downloaded_bytes || 0), 0),
    speed: kids.reduce((s, k) => s + (k.status === 'downloading' ? k.speed || 0 : 0), 0),
  };
}

function rowTemplate(item) {
  const li = document.createElement('li');
  li.className = 'download-row';
  li.dataset.id = item.id;
  li.innerHTML = `
    <span class="status-dot"></span>
    <div class="row-main">
      <div class="row-name-line">
        <button class="row-toggle" hidden aria-label="Mostrar u ocultar el contenido del paquete">▸</button>
        <div class="row-name"></div>
      </div>
      <div class="row-meta">
        <div class="progress-track"><div class="progress-fill"></div></div>
        <span class="row-status-label"></span>
      </div>
      <div class="row-error" hidden></div>
    </div>
    <span class="row-size"></span>
    <span class="row-speed"></span>
    <span class="row-badge"></span>
    <button class="row-pause-resume"></button>
    <button class="row-cancel">✕</button>
  `;
  li.querySelector('.row-toggle').addEventListener('click', () => toggleExpanded(item.id));
  li.querySelector('.row-pause-resume').addEventListener('click', () => primaryAction(item.id));
  li.querySelector('.row-cancel').addEventListener('click', () => secondaryAction(item.id));
  return li;
}

function childListFor(parentId) {
  let ul = listEl.querySelector(`ul.child-list[data-parent="${parentId}"]`);
  if (!ul) {
    ul = document.createElement('ul');
    ul.className = 'child-list';
    ul.dataset.parent = parentId;
    ul.hidden = !expanded.has(parentId);
    const parentLi = listEl.querySelector(`li[data-id="${parentId}"]`);
    if (parentLi) parentLi.after(ul);
    else listEl.appendChild(ul);
  }
  return ul;
}

function setButton(btn, texto, titulo) {
  btn.style.display = texto ? '' : 'none';
  btn.textContent = texto || '';
  btn.title = titulo || '';
  btn.setAttribute('aria-label', titulo || '');
}

function renderRow(item) {
  let li = listEl.querySelector(`li[data-id="${item.id}"]`);
  if (!li) {
    li = rowTemplate(item);
    const padre = item.parent_id && items.get(item.parent_id);
    if (padre) {
      li.classList.add('child');
      childListFor(item.parent_id).appendChild(li);
    } else {
      listEl.appendChild(li);
    }
  }

  const paquete = isPackage(item);
  const agg = paquete ? aggregate(item) : null;
  const status = agg ? agg.status : item.status;
  const meta = STATUS_META[status] || STATUS_META.queued;

  li.classList.toggle('package', paquete);
  const toggle = li.querySelector('.row-toggle');
  toggle.hidden = !paquete;
  toggle.textContent = expanded.has(item.id) ? '▾' : '▸';

  li.querySelector('.status-dot').style.setProperty('--dot-color', meta.dot);
  const nombre = paquete ? item.filename || displayName(item) : displayName(item);
  li.querySelector('.row-name').textContent = nombre;
  li.querySelector('.row-name').title = item.url;
  li.querySelector('.progress-fill').style.width = `${agg ? agg.progreso : item.progress || 0}%`;
  li.querySelector('.progress-fill').style.setProperty('--fill-color', meta.fill);
  const label = li.querySelector('.row-status-label');
  label.textContent = agg ? agg.label : (item.formato && item.status === 'queued' ? `en cola · ${item.formato}` : meta.label);
  label.style.setProperty('--label-color', meta.dot);
  li.querySelector('.row-size').textContent = formatBytes(agg ? agg.bytes : item.downloaded_bytes);
  li.querySelector('.row-speed').textContent = formatSpeed(agg ? agg.speed : item.speed);
  li.querySelector('.row-badge').textContent = PLUGIN_LABELS[item.plugin_name] || item.plugin_name || '';

  const errorEl = li.querySelector('.row-error');
  if (!paquete && item.error) {
    errorEl.hidden = false;
    errorEl.textContent = item.error;
    errorEl.title = item.error;
  } else {
    errorEl.hidden = true;
  }

  const primario = li.querySelector('.row-pause-resume');
  const secundario = li.querySelector('.row-cancel');
  if (paquete) {
    if (agg.activos) setButton(primario, '⏸', 'Pausar todo el paquete');
    else if (agg.pausados) setButton(primario, '▶', 'Reanudar el paquete');
    else if (agg.errores) setButton(primario, '↻', 'Reintentar los que fallaron');
    else setButton(primario, null);
    setButton(secundario, '✕', agg.activos || agg.pausados ? 'Cancelar el paquete' : 'Quitar de la lista (no borra archivos)');
  } else {
    if (item.status === 'downloading' || item.status === 'extracting') setButton(primario, '⏸', 'Pausar');
    else if (item.status === 'paused') setButton(primario, '▶', 'Reanudar');
    else if (item.status === 'error' || item.status === 'cancelled') setButton(primario, '↻', 'Reintentar');
    else setButton(primario, null);
    setButton(secundario, '✕', FINALES.includes(item.status) ? 'Quitar de la lista (no borra archivos)' : 'Cancelar');
  }
}

function upsertItem(item) {
  const esNuevo = !items.has(item.id);
  items.set(item.id, item);

  const padre = item.parent_id && items.get(item.parent_id);
  if (esNuevo) {
    if (padre) {
      if (!children.has(item.parent_id)) children.set(item.parent_id, []);
      children.get(item.parent_id).push(item.id);
    } else {
      order.unshift(item.id); // los más recientes arriba
    }
  }
  renderRow(item);
  if (padre) renderRow(padre); // el resumen del paquete cambia con cada hijo
  if (esNuevo && !padre) reorderList(); // solo hace falta reordenar cuando entra uno nuevo
  updateStatusbar();
  updateEmptyState();
}

function removeItem(id) {
  const item = items.get(id);
  items.delete(id);
  const i = order.indexOf(id);
  if (i !== -1) order.splice(i, 1);
  listEl.querySelector(`li[data-id="${id}"]`)?.remove();
  listEl.querySelector(`ul.child-list[data-parent="${id}"]`)?.remove();
  children.delete(id);
  if (item?.parent_id && children.has(item.parent_id)) {
    children.set(item.parent_id, children.get(item.parent_id).filter((k) => k !== id));
    const padre = items.get(item.parent_id);
    if (padre) renderRow(padre);
  }
  updateStatusbar();
  updateEmptyState();
}

function reorderList() {
  for (const id of order) {
    const li = listEl.querySelector(`li[data-id="${id}"]`);
    if (li) listEl.appendChild(li);
    const ul = listEl.querySelector(`ul.child-list[data-parent="${id}"]`);
    if (ul) listEl.appendChild(ul);
  }
}

function toggleExpanded(id) {
  if (expanded.has(id)) expanded.delete(id);
  else expanded.add(id);
  const ul = listEl.querySelector(`ul.child-list[data-parent="${id}"]`);
  if (ul) ul.hidden = !expanded.has(id);
  const item = items.get(id);
  if (item) renderRow(item);
}

function updateEmptyState() {
  emptyStateEl.style.display = items.size === 0 ? '' : 'none';
}

function updateStatusbar() {
  const counts = { downloading: 0, queued: 0, extracting: 0, completed: 0, error: 0, paused: 0 };
  let total = 0;
  for (const item of items.values()) {
    if (isPackage(item)) continue; // se cuentan sus archivos, no el paquete
    total++;
    if (counts[item.status] !== undefined) counts[item.status]++;
  }
  statusbarEl.textContent =
    `${total} elemento${total === 1 ? '' : 's'} · ` +
    `${counts.downloading + counts.extracting} activos · ` +
    `${counts.queued} en cola · ` +
    (counts.paused ? `${counts.paused} pausados · ` : '') +
    `${counts.completed} completados` +
    (counts.error ? ` · ${counts.error} con error` : '');
}

// --- acciones de cada fila -------------------------------------------

async function accion(id, endpoint) {
  try {
    await api(`/descargas/${id}/${endpoint}`, { method: 'POST' });
  } catch {
    // el próximo mensaje del WebSocket (o un refresco) reflejará el estado real
  }
}

function primaryAction(id) {
  const item = items.get(id);
  if (!item) return;
  if (isPackage(item)) {
    const agg = aggregate(item);
    const kids = kidsOf(id);
    if (agg.activos) kids.filter((k) => ['downloading', 'extracting'].includes(k.status)).forEach((k) => accion(k.id, 'pausar'));
    else if (agg.pausados) kids.filter((k) => k.status === 'paused').forEach((k) => accion(k.id, 'reanudar'));
    else kids.filter((k) => k.status === 'error' || k.status === 'cancelled').forEach((k) => accion(k.id, 'reintentar'));
    return;
  }
  if (item.status === 'paused') accion(id, 'reanudar');
  else if (item.status === 'error' || item.status === 'cancelled') accion(id, 'reintentar');
  else accion(id, 'pausar');
}

function secondaryAction(id) {
  const item = items.get(id);
  if (!item) return;
  if (isPackage(item)) {
    const agg = aggregate(item);
    if (agg.activos || agg.pausados) {
      kidsOf(id).filter((k) => !FINALES.includes(k.status)).forEach((k) => accion(k.id, 'cancelar'));
    } else {
      accion(id, 'quitar');
    }
    return;
  }
  accion(id, FINALES.includes(item.status) ? 'quitar' : 'cancelar');
}

// --- carga inicial, carpeta y añadir ---------------------------------

async function loadInitial() {
  try {
    const data = await apiJson('/descargas');
    // La API las da en orden de creación: los paquetes antes que sus hijos
    for (const item of data) upsertItem(item);
    updateStatusbar();
  } catch (err) {
    statusbarEl.textContent = 'Sin conexión con el servidor (¿está corriendo python run.py?)';
  }
}

async function loadFolder() {
  try {
    const data = await apiJson('/carpeta-destino');
    folderPathEl.textContent = data.path;
    folderPathEl.title = data.path;
  } catch {
    folderPathEl.textContent = '(sin conexión)';
  }
}

async function changeFolder() {
  if (!window.electronAPI) return; // por si se abre fuera de Electron
  const chosen = await window.electronAPI.elegirCarpeta();
  if (!chosen) return; // el usuario canceló el diálogo

  try {
    const data = await postJson('/carpeta-destino', { path: chosen });
    folderPathEl.textContent = data.path;
    folderPathEl.title = data.path;
  } catch {
    statusbarEl.textContent = 'No se pudo cambiar la carpeta (¿está corriendo python run.py?)';
  }
}

async function addDirect(url) {
  try {
    upsertItem(await postJson('/descargas', { url }));
  } catch (err) {
    statusbarEl.textContent = `No se pudo añadir: ${err.message}`;
  }
}

// ---------------------------------------------------------------------
// Selector de contenido: analiza el enlace y deja elegir qué bajar
// ---------------------------------------------------------------------

const g = {
  dialog: document.getElementById('grabber'),
  title: document.getElementById('grabber-title'),
  plugin: document.getElementById('grabber-plugin'),
  url: document.getElementById('grabber-url'),
  loading: document.getElementById('grabber-loading'),
  error: document.getElementById('grabber-error'),
  errorMsg: document.getElementById('grabber-error-msg'),
  body: document.getElementById('grabber-body'),
  chips: document.getElementById('type-chips'),
  filter: document.getElementById('grabber-filter'),
  formatWrap: document.getElementById('format-wrap'),
  format: document.getElementById('grabber-format'),
  folder: document.getElementById('grabber-folder'),
  list: document.getElementById('grabber-list'),
  count: document.getElementById('grabber-count'),
  ok: document.getElementById('grabber-ok'),
};

const grab = { url: null, analisis: null, seleccion: new Set(), abort: null };

function showGrabberState(estado) {
  g.loading.hidden = estado !== 'loading';
  g.error.hidden = estado !== 'error';
  g.body.hidden = estado !== 'ready';
  g.ok.hidden = estado !== 'ready';
}

async function openGrabber(url) {
  grab.url = url;
  grab.analisis = null;
  grab.seleccion = new Set();
  grab.abort?.abort();
  grab.abort = new AbortController();

  g.title.textContent = 'Analizando enlace…';
  g.plugin.hidden = true;
  g.url.textContent = url;
  g.count.textContent = '';
  g.filter.value = '';
  showGrabberState('loading');
  if (!g.dialog.open) g.dialog.showModal();

  try {
    const analisis = await postJson('/analizar', { url }, { signal: grab.abort.signal });
    if (grab.url !== url) return; // se cerró o se abrió otro mientras tanto
    grab.analisis = analisis;
    renderGrabber();
  } catch (err) {
    if (err.name === 'AbortError') return;
    g.title.textContent = 'No se pudo analizar el enlace';
    g.errorMsg.textContent = err.message;
    showGrabberState('error');
  }
}

function closeGrabber() {
  grab.abort?.abort();
  grab.url = null;
  if (g.dialog.open) g.dialog.close();
}

function grupoDe(e) {
  return e.grupo || (TIPO_META[e.tipo] || TIPO_META.archivo).label;
}

function renderGrabber() {
  const a = grab.analisis;
  g.title.textContent = a.titulo;
  g.plugin.hidden = false;
  g.plugin.textContent = PLUGIN_LABELS[a.plugin] || a.plugin;
  grab.seleccion = new Set(a.elementos.filter((e) => e.seleccionado).map((e) => e.id));

  g.formatWrap.hidden = !a.formatos.length;
  g.format.innerHTML = '';
  for (const f of a.formatos) {
    const opt = document.createElement('option');
    opt.value = f.id;
    opt.textContent = f.etiqueta;
    opt.selected = f.id === a.formato_defecto;
    g.format.appendChild(opt);
  }

  g.folder.value = a.elementos.length > 1 ? slug(a.titulo) : '';

  // Grupos en el orden en que aparecen (el análisis ya pone primero lo principal)
  const grupos = new Map();
  for (const e of a.elementos) {
    const k = grupoDe(e);
    if (!grupos.has(k)) grupos.set(k, []);
    grupos.get(k).push(e);
  }

  g.list.innerHTML = '';
  for (const [nombre, elems] of grupos) {
    const head = document.createElement('li');
    head.className = 'grab-group';
    head.dataset.grupo = nombre;
    head.innerHTML = `<label><input type="checkbox" class="grab-group-check" /> <span class="grab-group-name"></span> <span class="muted grab-group-count"></span></label>`;
    head.querySelector('.grab-group-name').textContent = nombre;
    head.querySelector('input').addEventListener('change', (ev) => {
      for (const e of elems) if (filaVisible(e)) setSel(e.id, ev.target.checked);
      syncGrabber();
    });
    g.list.appendChild(head);

    for (const e of elems) {
      const li = document.createElement('li');
      li.className = 'grab-row';
      li.dataset.id = e.id;
      li.dataset.grupo = nombre;
      const meta = TIPO_META[e.tipo] || TIPO_META.archivo;
      li.innerHTML = `
        <label class="grab-check"><input type="checkbox" /></label>
        <span class="grab-thumb"></span>
        <span class="grab-name"></span>
        <span class="grab-path muted"></span>
        <span class="grab-size muted"></span>`;
      const thumb = li.querySelector('.grab-thumb');
      if (e.miniatura) {
        const img = document.createElement('img');
        img.loading = 'lazy';
        img.alt = '';
        img.src = e.miniatura;
        img.addEventListener('error', () => { thumb.textContent = meta.icon; });
        thumb.appendChild(img);
      } else {
        thumb.textContent = meta.icon;
      }
      li.querySelector('.grab-name').textContent = e.nombre;
      li.querySelector('.grab-name').title = e.url;
      li.querySelector('.grab-path').textContent = e.ruta || '';
      li.querySelector('.grab-size').textContent = formatBytes(e.tamano);
      const cb = li.querySelector('input');
      cb.setAttribute('aria-label', e.nombre);
      cb.addEventListener('change', () => { setSel(e.id, cb.checked); syncGrabber(); });
      g.list.appendChild(li);
    }
  }

  renderChips();
  showGrabberState('ready');
  syncGrabber();
}

function setSel(id, on) {
  if (on) grab.seleccion.add(id);
  else grab.seleccion.delete(id);
}

function filaVisible(e) {
  const q = g.filter.value.trim().toLowerCase();
  return !q || e.nombre.toLowerCase().includes(q) || (e.ruta || '').toLowerCase().includes(q);
}

// Fichas por tipo de contenido: marcan/desmarcan todo lo de ese tipo
function renderChips() {
  g.chips.innerHTML = '';
  const tipos = new Map();
  for (const e of grab.analisis.elementos) tipos.set(e.tipo, (tipos.get(e.tipo) || 0) + 1);
  if (tipos.size < 2) return; // con un solo tipo no aportan nada
  for (const [tipo, n] of tipos) {
    const meta = TIPO_META[tipo] || TIPO_META.archivo;
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.dataset.tipo = tipo;
    chip.innerHTML = `<span class="chip-icon"></span> <span class="chip-label"></span> <span class="chip-n"></span>`;
    chip.querySelector('.chip-icon').textContent = meta.icon;
    chip.querySelector('.chip-label').textContent = meta.label;
    chip.querySelector('.chip-n').textContent = n;
    chip.addEventListener('click', () => {
      const delTipo = grab.analisis.elementos.filter((e) => e.tipo === tipo);
      const todos = delTipo.every((e) => grab.seleccion.has(e.id));
      for (const e of delTipo) setSel(e.id, !todos);
      syncGrabber();
    });
    g.chips.appendChild(chip);
  }
}

// Refleja la selección en casillas, grupos, fichas y pie
function syncGrabber() {
  const a = grab.analisis;
  if (!a) return;
  const porId = new Map(a.elementos.map((e) => [e.id, e]));

  for (const li of g.list.querySelectorAll('.grab-row')) {
    const e = porId.get(li.dataset.id);
    li.hidden = !filaVisible(e);
    li.querySelector('input').checked = grab.seleccion.has(e.id);
    li.classList.toggle('off', !grab.seleccion.has(e.id));
  }
  for (const head of g.list.querySelectorAll('.grab-group')) {
    const elems = a.elementos.filter((e) => grupoDe(e) === head.dataset.grupo);
    const sel = elems.filter((e) => grab.seleccion.has(e.id)).length;
    const cb = head.querySelector('input');
    cb.checked = sel === elems.length;
    cb.indeterminate = sel > 0 && sel < elems.length;
    head.querySelector('.grab-group-count').textContent = `${sel}/${elems.length}`;
    head.hidden = !elems.some(filaVisible);
  }
  for (const chip of g.chips.querySelectorAll('.chip')) {
    const delTipo = a.elementos.filter((e) => e.tipo === chip.dataset.tipo);
    const sel = delTipo.filter((e) => grab.seleccion.has(e.id)).length;
    chip.classList.toggle('on', sel === delTipo.length);
    chip.classList.toggle('partial', sel > 0 && sel < delTipo.length);
    chip.setAttribute('aria-pressed', sel === delTipo.length ? 'true' : sel ? 'mixed' : 'false');
  }

  const elegidos = a.elementos.filter((e) => grab.seleccion.has(e.id));
  const bytes = elegidos.reduce((s, e) => s + (e.tamano || 0), 0);
  g.count.textContent = `${elegidos.length} de ${a.elementos.length} seleccionados` + (bytes ? ` · ${formatBytes(bytes)}` : '');
  g.ok.disabled = elegidos.length === 0;
  g.ok.textContent = elegidos.length ? `Descargar (${elegidos.length})` : 'Descargar';
}

async function confirmGrabber() {
  const a = grab.analisis;
  if (!a || !grab.seleccion.size) return;
  g.ok.disabled = true;
  try {
    const item = await postJson('/descargas/seleccion', {
      analisis_id: a.id,
      elementos: a.elementos.filter((e) => grab.seleccion.has(e.id)).map((e) => e.id),
      formato: a.formatos.length ? g.format.value : null,
      carpeta: g.folder.value.trim() || null,
    });
    upsertItem(item);
    closeGrabber();
  } catch (err) {
    g.count.textContent = `No se pudo añadir: ${err.message}`;
    g.ok.disabled = false;
  }
}

g.filter.addEventListener('input', syncGrabber);
document.getElementById('sel-all').addEventListener('click', () => {
  for (const e of grab.analisis?.elementos || []) if (filaVisible(e)) setSel(e.id, true);
  syncGrabber();
});
document.getElementById('sel-none').addEventListener('click', () => {
  for (const e of grab.analisis?.elementos || []) if (filaVisible(e)) setSel(e.id, false);
  syncGrabber();
});
document.getElementById('grabber-close').addEventListener('click', closeGrabber);
document.getElementById('grabber-cancel').addEventListener('click', closeGrabber);
document.getElementById('grabber-direct').addEventListener('click', () => {
  const url = grab.url;
  closeGrabber();
  if (url) addDirect(url);
});
g.ok.addEventListener('click', confirmGrabber);
g.dialog.addEventListener('cancel', () => grab.abort?.abort()); // tecla Esc

// ---------------------------------------------------------------------

function connectWebSocket() {
  const ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent(apiToken)}`);

  ws.addEventListener('message', (event) => {
    try {
      const item = JSON.parse(event.data);
      if (item.eliminado) {
        removeItem(item.id);
      } else {
        upsertItem(item);
      }
    } catch {
      // mensaje no reconocido, se ignora
    }
  });

  ws.addEventListener('close', () => {
    setTimeout(connectWebSocket, 2000);
  });

  ws.addEventListener('error', () => ws.close());
}

function takeUrl() {
  const url = inputEl.value.trim();
  if (url) inputEl.value = '';
  return url;
}

formEl.addEventListener('submit', (event) => {
  event.preventDefault();
  const url = takeUrl();
  if (url) openGrabber(url);
});

directBtnEl.addEventListener('click', () => {
  const url = takeUrl();
  if (url) addDirect(url);
});

folderBtnEl.addEventListener('click', changeFolder);

async function init() {
  if (window.electronAPI) {
    apiToken = await window.electronAPI.obtenerToken();
  }
  // Electron lanza el backend a la vez que abre la ventana: se espera a
  // que responda (hasta ~30 s) antes de pedir la lista.
  for (let i = 0; i < 60; i++) {
    try {
      if ((await api('/carpeta-destino')).ok) break;
    } catch {
      // todavía arrancando
    }
    statusbarEl.textContent = 'Arrancando el motor de descargas…';
    await new Promise((r) => setTimeout(r, 500));
  }
  loadInitial();
  loadFolder();
  connectWebSocket();
}

init();
