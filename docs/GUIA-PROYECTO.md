# Guía del proyecto: JDownloader Clone

> Análisis del estado real del código a 18/10/2026 (rama `V2`, último commit `965aadf`).
> Si algo de aquí contradice al `PRD.md` o a `.github/copilot-instructions.md`, **manda el código**:
> esos dos documentos describen una API distinta de la que existe (más abajo se detallan las diferencias).

---

## 1. Qué es

Un gestor de descargas de escritorio inspirado en JDownloader. Pegas un enlace, la app **analiza qué hay detrás** y te deja elegir qué bajar (o lo baja directamente con lo que detecte por defecto):

| Tipo de enlace | Qué encuentra / cómo lo baja | Plugin |
|---|---|---|
| Capítulo de Olympus Scanlation (`.../capitulo/N`) | Las páginas, leídas del HTML en segundos (saltando su caché rota) | `olympus` |
| Google Drive: archivo, carpeta (con subcarpetas) o Docs/Hojas/Presentaciones | Cada archivo con su ruta; los documentos de Google se exportan al formato que elijas (PDF, Word, Excel…) | `gdrive` |
| MEGA: archivo o carpeta (`mega.nz/file/…#clave`, `mega.nz/folder/…#clave`) | Cada archivo con su ruta; se descifra al vuelo mientras se descarga | `mega` |
| Archivo directo (`.zip`, `.pdf`, `.mp4`, `.jpg`…) | Descarga HTTP con pausa/reanudación real | `direct_http` |
| Vídeo/audio de ~1.700 webs (YouTube, Vimeo, Twitch, X, TikTok, SoundCloud…) | El vídeo, o cada vídeo de una lista; eliges calidad (mejor, 1080p, 720p…) o **solo audio** (MP3) | `video` |
| Cualquier otra página | La abre en un Chromium invisible y separa: **contenido principal** (p. ej. las páginas de un capítulo), otras imágenes (logos, portadas), vídeos/audios y enlaces a Drive/MEGA/archivos. Si la URL es un archivo sin extensión, lo baja tal cual | `web` |

Las imágenes del contenido principal se guardan numeradas en orden de lectura: `001.jpg`, `002.jpg`…

---

## 2. Cómo está montado

```
┌─────────────────────────────┐
│  Electron (electron_ui/)    │  ventana, lista de descargas, botones
└──────────────┬──────────────┘
               │ HTTP (REST) + WebSocket   →  127.0.0.1:8642
┌──────────────▼──────────────┐
│  API FastAPI (backend/api)  │  traduce peticiones a llamadas al motor
└──────────────┬──────────────┘
┌──────────────▼──────────────┐
│  DownloadManager (engine)   │  cola + 4 hilos trabajadores
└──────────────┬──────────────┘
     ┌─────────┬───────┼────────┬──────────┬──────┐
  olympus  gdrive  mega  direct_http  video  web     (plugins, en este orden)
```

- **Electron arranca el backend él solo**: `main.js` lanza `venv/bin/python run.py` al abrir la app y lo mata al cerrarla.
- **La UI nunca toca el motor directamente**: todo pasa por la API. Así se podría hacer otra UI (web, móvil…) sin tocar el backend.
- **Todo vive en memoria**: si cierras la app o el servidor se reinicia, la lista de descargas desaparece (los archivos ya bajados se quedan en disco).

### Ficheros importantes

| Fichero | Para qué sirve |
|---|---|
| `run.py` | Arranca el servidor (uvicorn, puerto 8642, con recarga automática) |
| `backend/core/models.py` | `DownloadItem` (una descarga) y `DownloadStatus` (sus estados) |
| `backend/core/engine.py` | `DownloadManager`: cola, hilos, elegir plugin, pausar/reanudar/cancelar |
| `backend/core/plugin_base.py` | Plantilla de plugin + `Analisis`/`Elemento` (lo que se encontró en un enlace) |
| `backend/core/descarga_http.py` | Descarga HTTP compartida: progreso, velocidad, reanudación, nombres, descifrado |
| `backend/core/plugins/*.py` | Los seis plugins |
| `backend/api/main.py` | Endpoints REST, WebSocket y registro de plugins |
| `electron_ui/main.js` | Proceso principal de Electron (ventana + lanza el backend + diálogo de carpeta) |
| `electron_ui/renderer/renderer.js` | Toda la lógica de la interfaz |
| `descargas/` | Carpeta de destino por defecto (ignorada por git) |

---

## 3. Cómo usarlo

### Requisitos
- Python 3 (el `venv` actual usa 3.13) y Node.js
- `ffmpeg` en el sistema (`sudo apt install ffmpeg`) — para unir vídeo+audio y convertir a MP3
- Chromium para Playwright
- `pycryptodome` (en `requirements.txt`) — para MEGA

### Instalación (solo la primera vez)
```bash
cd ~/Documentos/jdownloader_clone
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/playwright install chromium
cd electron_ui && npm install
```
> Ahora mismo todo esto **ya está instalado** en tu máquina.

### Arrancar
```bash
cd ~/Documentos/jdownloader_clone/electron_ui
npm start
```
Eso abre la ventana y arranca el backend. Si solo quieres el backend (para probar con `curl`):
```bash
cd ~/Documentos/jdownloader_clone
venv/bin/python run.py
```
Al arrancarlo así, `run.py` muestra por consola un **token**: todas las peticiones a la API tienen que llevarlo (ver sección 5). Si quieres fijarlo tú: `JD_API_TOKEN=loquesea venv/bin/python run.py`.

Con el servidor arrancado tienes documentación interactiva de la API en <http://127.0.0.1:8642/docs> (botón *Authorize* para meter el token).

---

## 4. Cómo se usa la ventana

- **Añadir…** (o Enter): analiza el enlace y abre el **selector de contenido**:
  - Todo lo encontrado, agrupado (contenido principal, otras imágenes, vídeo y audio, enlaces…), con miniaturas, tamaño y ruta.
  - **Fichas por tipo** (Imágenes, Vídeos, Documentos…): un clic marca o desmarca todo lo de ese tipo.
  - Casillas por elemento y por grupo, **Todo / Nada** y un **filtro por nombre**.
  - **Formato** (si aplica): calidad del vídeo o solo audio; formato de exportación de documentos de Google.
  - **Subcarpeta** donde guardarlo.
- **Directo**: descarga sin preguntar lo que el análisis marca por defecto (igual que la API sin selección).
- Un enlace con varios archivos aparece como **un paquete** en la lista: una fila con el progreso total (`12/32`) que se despliega con ▸.
- Botones de cada fila: ⏸ pausar · ▶ reanudar · ↻ reintentar (si hubo error) · ✕ cancelar o, si ya terminó, **quitar de la lista** (no borra archivos). En un paquete actúan sobre todos sus archivos.

## 4b. Cómo funciona una descarga por dentro

1. **Análisis** (`plugin.analyze(url)`): el primer plugin que dice "esto es mío" (`can_handle`, en el orden de arriba) devuelve un `Analisis`: título, lista de `Elemento`s (url, nombre, tipo, ruta, tamaño, si va marcado por defecto, qué plugin lo descarga) y formatos posibles.
2. **Selección**: desde la ventana, el usuario elige (`POST /analizar` + `POST /descargas/seleccion`); sin ventana (`POST /descargas`), se usan los marcados por defecto.
3. Si lo elegido es el propio enlace (un vídeo, un archivo de MEGA…) se descarga en ese mismo item. Si son varios, el item pasa a ser un **paquete** y cada elemento se encola como hijo (`parent_id`), con su plugin ya decidido (`plugin_forzado`) para no volver a analizarlo.
4. Los 4 hilos descargan los hijos; cada cambio va por WebSocket a la ventana.

### Estados posibles
`queued` (en cola) · `extracting` (analizando) · `downloading` · `paused` · `completed` · `error` · `cancelled`

### Pausa y reanudación
- **Archivos directos**: al reanudar pide al servidor que continúe desde el byte donde se quedó (cabecera `Range`). Si el servidor no lo permite, empieza de cero.
- **Vídeo**: yt‑dlp retoma el fichero `.part`.
- **MEGA**: también se reanuda; el descifrado continúa desde el byte exacto.
- La pausa no es instantánea: se aplica en el siguiente trozo descargado.

---

## 5. API (la real)

**Autenticación:** todas las rutas exigen la cabecera `X-API-Token: <token>` (si falta o no coincide → 401). El WebSocket lo lleva en la URL: `/progreso?token=<token>`. Electron genera un token aleatorio en cada arranque y se lo pasa al backend (variable `JD_API_TOKEN`) y a la ventana; tú no tienes que hacer nada.

```bash
curl -H "X-API-Token: $TOKEN" http://127.0.0.1:8642/descargas
```

| Método | Ruta | Cuerpo | Qué hace |
|---|---|---|---|
| POST | `/descargas` | `{"url": "...", "carpeta": "opcional/relativa"}` | Añade una descarga. Si das `carpeta`, se guarda ahí (y todas sus imágenes, si es un capítulo/galería) |
| GET | `/descargas` | — | Lista todas. `?parent_id=<id>` → solo las imágenes que salieron de esa descarga |
| GET | `/descargas/{id}` | — | Una descarga (404 si no existe) |
| POST | `/analizar` | `{"url": "..."}` | Qué hay en el enlace, sin descargar: `{id, titulo, plugin, elementos:[{id, url, nombre, tipo, ruta, tamano, seleccionado, grupo, miniatura}], formatos, formato_defecto}`. Puede tardar (las webs se abren en un navegador) |
| POST | `/descargas/seleccion` | `{"analisis_id", "elementos": [ids], "formato"?, "carpeta"?}` | Descarga solo lo elegido de un análisis (los análisis caducan tras 30 nuevos → 410) |
| POST | `/descargas/{id}/reintentar` | — | Vuelve a encolar una descarga con error o cancelada (misma carpeta y nombre) |
| POST | `/descargas/{id}/quitar` | — | La quita de la lista junto con sus imágenes (cancela las activas; **no borra archivos**) |
| POST | `/descargas/{id}/pausar` | — | Pausa |
| POST | `/descargas/{id}/reanudar` | — | Reanuda |
| POST | `/descargas/{id}/cancelar` | — | Cancela |
| GET | `/carpeta-destino` | — | Carpeta actual |
| POST | `/carpeta-destino` | `{"path": "..."}` | Cambia la carpeta (solo afecta a lo que se añada después) |
| WS | `/progreso` | — | Envía el `DownloadItem` completo (JSON) cada vez que cambia algo, o `{"id": ..., "eliminado": true}` al quitar uno |

Cada descarga incluye `parent_id` (el capítulo del que salió, si es una imagen) y `dest_subfolder`. `output_path` es siempre una **ruta absoluta**. Un capítulo pasa a `completed` cuando ya se han creado todas sus imágenes, y su `downloaded_bytes` indica **cuántas imágenes** tiene.

**Token para scripts:** al arrancar, el backend guarda su token en `~/.config/jdownloader-clone/api-token` (solo legible por ti). Un script local lo lee de ahí, así funciona aunque Electron genere uno nuevo en cada arranque. Si hay dos backends arrancados, gana el último.

> ⚠️ El `PRD.md` y `copilot-instructions.md` hablan de `PATCH .../pausa`, `DELETE /descargas/{id}`, `/config/carpeta`, WebSocket en `/ws` con eventos `download_updated`… **Nada de eso existe.** También dicen 5 descargas simultáneas (son 4) y plugins `async` (son síncronos, con hilos).

---

## 6. Olympus: por qué tiene plugin propio

Algunos capítulos "no se descargaban" (p. ej. el 1 o el 87 de *Archimago*). **No era culpa del descargador**: la web de Olympus tiene una caché que a veces guarda una versión rota del capítulo, con imágenes de relleno (`/cp/cp-1.jpg`) que no existen. Mientras esa versión siga en caché, todo el mundo ve "La página 1 no ha cargado", también en el navegador.

El plugin `olympus` (`backend/core/plugins/olympus.py`):
- Pide el capítulo con un parámetro inventado en la URL (`?nc=...`) para saltarse esa caché y obligar al servidor a generarlo de nuevo.
- Saca las páginas del propio HTML (las reconoce por el texto "página N"), así que no abre ningún navegador ni hace scroll: tarda segundos en lugar de minutos y no se mezclan las portadas de "series recomendadas".
- Si aun así recibe páginas de relleno, reintenta hasta 4 veces y, si no lo consigue, la descarga queda en error con el mensaje "Olympus sigue sirviendo páginas vacías…".

Funciona con cualquier dominio que contenga "olympus" (la web cambia de dominio a menudo). Si un día cambian el diseño del lector y deja de encontrar páginas, ese es el fichero a revisar.

## 7. Script `repair_olympus2.py` (reparar capítulos del servidor)

`~/repair_olympus2.py` pide al servidor (`192.168.1.100`) los capítulos con error, los descarga con esta app y sube las imágenes. Antes manejaba JDownloader a base de clics de ratón; ahora usa la API.

```bash
# con la app abierta (npm start) o el backend arrancado (python run.py)
~/Documentos/jdownloader_clone/venv/bin/python ~/repair_olympus2.py
```

- Cada capítulo se descarga en `<carpeta de destino>/repair_olympus/<id cómic>/<id capítulo>/`, con las páginas numeradas `001.webp`…; las verás aparecer en la ventana de la app.
- Reintentos: si fallan **algunas páginas**, repite solo esas; si falla el capítulo entero o tarda más de 5 min, lo quita y lo vuelve a enviar. Máximo 2 intentos.
- Solo sube el capítulo si **todas** sus páginas se descargaron (un capítulo a medias no se da por reparado).
- Si un capítulo falla, sigue con el siguiente y al final muestra un resumen de reparados/fallidos.
- Tras subir con éxito borra la carpeta del capítulo y lo quita de la lista; si la subida falla, deja los archivos.
- Variables opcionales: `REPAIR_SERVER` (otro servidor), `JD_API` (otro puerto), `JD_API_TOKEN` (token manual).

La versión anterior (con `pyautogui`) está en `~/repair_olympus2.py.bak`.

### Ejecución automática diaria (04:00)

Un temporizador de systemd lanza `~/repair_olympus_diario.sh` cada día a las 04:00. Ese script arranca el motor (sin ventana), espera a que responda, ejecuta `repair_olympus2.py` y cierra el motor. Si a esa hora tienes la app abierta, la usa y **no** la cierra. Si el ordenador estaba apagado, se ejecuta al encenderlo. Funciona aunque no hayas iniciado sesión (linger activado).

| Para… | Comando |
|---|---|
| Ver cuándo toca la próxima | `systemctl --user list-timers repair-olympus.timer` |
| Lanzarlo ahora a mano | `systemctl --user start repair-olympus.service` |
| Ver los logs | `ls ~/.local/share/jdownloader-clone/logs/` (se guardan 30 días) o `journalctl --user -u repair-olympus` |
| Desactivarlo | `systemctl --user disable --now repair-olympus.timer` |
| Cambiar la hora | editar `OnCalendar=` en `~/.config/systemd/user/repair-olympus.timer` y `systemctl --user daemon-reload` |

> Los capítulos de **komiwa.net** (cómic 72) ya funcionan con el plugin `web`: komiwa manda a su portada si entras directamente a un capítulo, y el plugin lo detecta y entra "navegando" desde la portada. Si una web nueva falla, el panel *Añadir…* de la ventana enseña qué detecta en ella.

## 8. Cómo añadir un plugin nuevo

1. Crea `backend/core/plugins/mi_plugin.py` con una clase que herede de `DownloadPlugin` e implemente:
   - `can_handle(url)` → `True` si sabe tratar ese enlace.
   - `analyze(url)` → un `Analisis` con sus `Elemento`s. Atajo: implementar solo `resolve(url)` (lista de URLs en **orden de lectura**) y la clase base monta el análisis.
   - `download(item, url, carpeta, on_progress)` → descarga, va actualizando `item` y llamando a `on_progress(item)`; debe parar si `item.status` pasa a `paused` o `cancelled`. Para HTTP, usa `descargar_http()` de `descarga_http.py`.
2. Regístralo en `backend/api/main.py` **antes** de `WebPlugin`.

---

## 9. Estado actual y trabajo a medias

Tienes **cambios sin commitear** en la rama `V2`:
- El scraper genérico (`image_scraper.py`) pasó a ser `web.py`: scroll de casi una pantalla cada 400 ms y luego un repaso de las imágenes grandes que no cargaron (más rápido y más fiable que los 650 ms fijos de antes).
- **Reintentos** (`intento`): el campo lo incrementa `reintentar`, pero ningún plugin lo usa todavía.

---

## 10. Problemas detectados (revisión del código)

Ordenados de más a menos importante. Ninguno está corregido; es una lista para decidir qué arreglar.

### Seguridad — ✅ corregidos el 18/10/2026
1. ~~**Path traversal en descargas directas**~~: el nombre del archivo ahora se limpia en `_nombre_seguro()` (`direct_http.py`).
2. ~~**Cualquier web puede controlar la app**~~: la API exige un token secreto en cada petición y en el WebSocket.

### Fallos de comportamiento
3. ~~**Cancelar algo que está en cola no sirve**~~ ✅ corregido.
4. **Pausar durante "analizando" se pierde**: el plugin pone después el estado a `downloading` y sigue. Si además pulsas reanudar, la descarga se mete dos veces en la cola.
5. **Pausar y reanudar muy rápido** puede hacer que dos hilos descarguen el mismo archivo a la vez.
6. ~~**Imágenes sin extensión en la URL fallan**~~ ✅ la extensión se saca del `Content-Type`. (Las `data:` se ignoran.)
7. ~~**Archivos con el mismo nombre se sobrescriben**~~ ✅ ahora se guardan como `nombre (1).ext`.
8. ~~**Al abrir la app sale "Sin conexión"**~~ ✅ la ventana espera a que arranque el motor.
9. Cancelar no borra el archivo parcial.

### Menores
10. ~~`GET /descargas/{id}` devuelve 200 con `{"error": ...}` en lugar de 404~~ ✅ corregido.
11. `npm run dist` genera un paquete que **no incluye el backend Python**: el AppImage/.deb no funcionaría fuera de esta carpeta.
12. ~~La barra de estado no cuenta las descargas pausadas~~ ✅
14. MEGA: no se verifica el MAC (la firma de integridad) del archivo descifrado. Las carpetas de MEGA no se han podido probar con un enlace real (no hay carpetas públicas de prueba); los archivos sí.
15. Drive: la vista de carpeta que se usa podría no listar carpetas enormes enteras; si faltan archivos, se nota en el recuento del selector.
13. `run.py` usa `reload=True`: al editar cualquier `.py` se reinicia el servidor y se pierde la lista.

---

## 11. Siguientes pasos sugeridos

1. ~~Arreglar los dos problemas de seguridad~~ ✅
2. ~~Hacer que el motor respete `cancelled` antes de empezar a procesar un elemento~~ ✅ (falta la pausa durante el análisis).
3. Terminar los reintentos (`intento`) o quitarlos.
4. Guardar la lista de descargas en disco (JSON o SQLite) para que sobreviva a reinicios.
5. Reintentar la carga inicial en la UI hasta que el backend responda.
6. Actualizar `PRD.md` y `copilot-instructions.md` a la API real.
