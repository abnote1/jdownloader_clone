# CLAUDE.md

Download manager (JDownloader-like): Python core + FastAPI API + Electron UI. Code, comments, UI strings and API routes are in **Spanish** — keep it that way. User-facing docs: `docs/GUIA-PROYECTO.md`.

## Source of truth
Trust the code, not `docs/PRD.md` or `.github/copilot-instructions.md`. Those describe a nonexistent API (PATCH/DELETE routes, `/config/carpeta`, `/ws` with typed events, async plugins, 5 workers, wrong file paths like `backend/engine.py`).

## Run
- Full app: `cd electron_ui && npm start` — `main.js` spawns `../venv/bin/python ../run.py` itself and kills it on quit.
- Backend only: `venv/bin/python run.py` → `127.0.0.1:8642`, uvicorn `reload=True` (state is wiped on every .py edit). OpenAPI at `/docs`.
- Smoke check: `venv/bin/python -c "import backend.api.main"` (instantiates the manager + 4 threads; creates `./descargas`). The user often has the app running on 8642 with reload: backend edits go live immediately, and a half-done multi-file edit (renames) can crash the reloaded worker.
- Test server without touching the user's app/token: `PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright HOME=<scratch> venv/bin/python -m uvicorn backend.api.main:app --port 8699`, token in `<scratch>/.config/jdownloader-clone/api-token`. UI can be tested by copying `electron_ui/renderer` to scratch, `sed 8642→8699`, and loading it in Playwright with an `add_init_script` stub for `window.electronAPI`.
- Needs system `ffmpeg` (merging, MP3), Playwright Chromium, `pycryptodome` (MEGA).
- No tests, no linter, no CI.

## Architecture
- `models.py` — `DownloadItem` (+ `parent_id`, `plugin_forzado`, `tipo`, `opciones` dict: `formato`, `headers`, `mega` keys…). `to_dict()` is the wire format for REST and WS (omits `opciones` except `formato`).
- `plugin_base.py` — `DownloadPlugin` (`can_handle`, `analyze`, `download`; `resolve` optional shortcut: base `analyze()` wraps it, multi-URL → images via `direct_http`, `numerar=True`). `Analisis` (titulo, elementos, formatos, formato_defecto, numerar, id) and `Elemento` (url, nombre, tipo, plugin, ruta, tamano, seleccionado, grupo, miniatura, opciones; `opciones["expandir"]` = link that must itself be analyzed). Helpers `tipo_por_nombre`, `limpiar_nombre`, `limpiar_ruta` (sanitize remote names/paths — always use them for names coming from sites).
- `descarga_http.py` — `descargar_http(item, url, dest, on_progress, headers, session, descifrador, tamano)`: shared streaming download. Name from item.filename → Content-Disposition → URL; adds extension from Content-Type; `_ruta_libre` avoids overwrite; Range resume; rejects HTML for binary `tipo`s; throttles notifications to 4/s; computes speed. `descifrador(offset)` → object with `.decrypt` (MEGA AES-CTR).
- `engine.py` — `DownloadManager`: 4 daemon threads. `register_plugin` sets `plugin.motor = self` (web uses `motor._find_plugin` to classify links). `_process`: skip cancelled/removed → if `plugin_forzado`: `download()` directly → else `analyze()`, take `seleccionado` elements; single element with `url == item.url` and no `expandir` → download in same item with the element's plugin; else `_crear_hijos` (subfolder = dest_subfolder or slug(titulo); images numbered `001.ext` when `numerar`; children get `plugin_forzado`; `expandir` ones get no forced plugin and their own subfolder), then parent COMPLETED with `downloaded_bytes` = child count (after children exist). UI path: `analizar()` caches up to 30 `Analisis`; `add_seleccion()` builds the package from chosen ids.
- Plugins, registration order matters: `olympus` (requests + `?nc=` cache-bust, decoy `/cp/cp-N.jpg` detection, 4 retries) → `gdrive` (embeddedfolderview listing, recursive ≤10 levels; usercontent download + virus-warning form resubmit; Docs/Sheets/Slides export with formatos) → `mega` (public API `g.api.mega.co.nz/cs`, file + folder links incl. legacy `#!`/`#F!`, node keys AES-ECB with folder key, attrs AES-CBC, content AES-CTR with offset-aware resume; MAC not verified; folder path untested against a live link) → `direct_http` (extension whitelist; as forced plugin any URL) → `video` (yt-dlp, any non-generic extractor; playlists → entries, `watch?v=&list=` preselects only v; formatos mejor/1080…/audio_mp3/audio; retries once on 403) → `web` (catch-all: non-HTML URL → direct file; Playwright with real UA; soft-redirect-to-home → reopen home + click injected link (komiwa); JS scroll + reload pass; "reader" container = deepest element holding ≥50% of big images → `Contenido principal` named `Página NNN`; other images unselected; `<video>/<audio>`/network media → `video`; links other plugins handle → elements, Drive/MEGA/video/olympus with `expandir`). **web must stay last.**
- Pause/cancel are cooperative: `pause()`/`cancel()` only set `item.status`; downloaders poll it per chunk / yt-dlp hook.
- `api/main.py` — module-level `manager`; CORS `*`; worker-thread → asyncio bridge via `run_coroutine_threadsafe`. Auth: HTTP routes on `router` with `Depends(verificar_token)` (`X-API-Token`); WS `?token=`. Token from env `JD_API_TOKEN` (Electron generates; `run.py` generates+prints); startup handler writes it to `~/.config/jdownloader-clone/api-token` (0600) — on startup, not import.
- Routes: `POST /analizar {url}` (sync, may take ~10–60 s; 400/502), `POST /descargas/seleccion {analisis_id, elementos, formato?, carpeta?}` (410 if analysis evicted), `POST /descargas {url, carpeta?}` (auto mode), `GET /descargas[?parent_id=]`, `GET /descargas/{id}` (404), `POST /descargas/{id}/{pausar,reanudar,cancelar,reintentar,quitar}`, `GET/POST /carpeta-destino`, `WS /progreso` (item dicts, or `{"id", "eliminado": true}`).
- `electron_ui/renderer/` — vanilla JS. Top-level items in `order`, children in `children` map rendered in a collapsible `ul.child-list` after the parent; package rows show `aggregate()` of children; row buttons: primary (pause/resume/retry), secondary (cancel/quitar), applied to all children for packages. `<dialog id="grabber">` = content selector (analysis → groups, type chips, filter, format, subfolder → `/descargas/seleccion`). "Directo" button = `POST /descargas`. `init()` waits for the backend before loading. Always use the `api()`/`apiJson()`/`postJson()` helpers (token).
- All state in memory; no persistence.

## External clients (keep their contracts stable)
- `~/repair_olympus2.py` (outside repo): `POST /descargas {url, carpeta}`, polls parent + `?parent_id=`, relies on `downloaded_bytes` = child count once parent is COMPLETED, `reintentar`, `quitar`, absolute `output_path`, image extensions `.jpg/.jpeg/.png/.webp`. Also gets komiwa.net chapters (comic 72) → handled by `web`.
- Daily 04:00 systemd user timer `repair-olympus.timer` → `~/repair_olympus_diario.sh` (uvicorn without reload on 8642 unless already up, runs the script, kills backend; logs `~/.local/share/jdownloader-clone/logs/`; linger enabled).

## Known bugs (unfixed — confirm with user before fixing)
- Pause during EXTRACTING is overwritten (downloader sets DOWNLOADING), and resume then double-enqueues.
- Fast pause→resume race: worker still in loop sees QUEUED and continues while a second worker picks the re-queued item → two writers on one file.
- Cancel leaves partial files.
- If a backend is already running on 8642 when Electron starts, the spawned one fails to bind and the UI gets 401 (token mismatch) unless both share `JD_API_TOKEN`.
- `electron-builder` `files` excludes backend/venv and `PYTHON_BIN` is relative to `__dirname` → packaged builds can't start the backend.
- Shared `DownloadItem` fields mutated across threads without locking (only `items` dict insert is locked).
- `intento` is incremented by `retry()` but no plugin reads it.

## Conventions
- Conventional Commits (see `.github/skills/commit-message/SKILL.md`), Spanish descriptions, e.g. `fix(backend): ...`.
- Branches: `main`, `V1`, `V2` (current). Remote `origin` = github.com/abnote1/jdownloader_clone.
- Comments explain *why* in Spanish prose; match that density.
- New plugin: subclass `DownloadPlugin`, implement `analyze` (or `resolve`), use `descargar_http` for HTTP, poll `item.status` for PAUSED/CANCELLED, call `on_progress(item)`, register in `api/main.py` before `WebPlugin`.
