# Clon de JDownloader (esqueleto)

Gestor de descargas con núcleo en Python, API interna (REST + WebSocket)
y sistema de plugins, pensado para que la UI de escritorio (y cualquier
proyecto futuro) hable con el mismo backend por HTTP.

## Estructura

```
backend/
  core/
    models.py         -> DownloadItem, DownloadStatus
    plugin_base.py     -> interfaz que implementa cada plugin
    engine.py           -> DownloadManager (cola, hilos, dispatch)
    plugins/
      olympus.py        -> capítulos de Olympus Scanlation (salta su caché rota)
      gdrive.py         -> archivos, carpetas y documentos de Google Drive
      mega.py           -> archivos y carpetas de MEGA (descifrado al vuelo)
      direct_http.py    -> descarga directa de archivos por extensión conocida
      video.py          -> vídeo/audio de ~1.700 webs con yt-dlp (listas, calidad, MP3)
      web.py            -> cualquier otra página (Playwright): contenido principal,
                           imágenes, vídeos y enlaces a Drive/MEGA/archivos
  api/
    main.py             -> API interna FastAPI (REST + WebSocket)
run.py                    -> arranca el servidor
```

## Instalación

```bash
pip install -r requirements.txt
playwright install chromium
```

## Arrancar el servidor

```bash
python run.py
```

Queda escuchando en `http://127.0.0.1:8642` y muestra por consola el
token de la API (o usa el que le pases en `JD_API_TOKEN`). Todas las
peticiones deben llevarlo en la cabecera `X-API-Token`; el WebSocket, en
la query (`?token=...`). La app de Electron lo genera y lo gestiona sola.

```bash
export TOKEN=...   # el que muestra run.py
```

## Probar la API

Añadir una descarga:

```bash
curl -X POST http://127.0.0.1:8642/descargas \
  -H "X-API-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=XXXXXXXXXXX"}'
```

Añadir una página para que detecte imágenes automáticamente:

```bash
curl -X POST http://127.0.0.1:8642/descargas \
  -H "X-API-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://ejemplo.com/galeria"}'
```

Ver el estado de todas las descargas:

```bash
curl -H "X-API-Token: $TOKEN" http://127.0.0.1:8642/descargas
```

Progreso en tiempo real: conectar por WebSocket a `ws://127.0.0.1:8642/progreso?token=$TOKEN`
(cualquier cliente, incluida la futura UI de Electron).

## Cómo añadir un plugin nuevo

1. Crear `backend/core/plugins/mi_plugin.py` heredando de `DownloadPlugin`.
2. Implementar `can_handle`, `analyze` (o solo `resolve`) y `download`.
3. Registrarlo en `backend/api/main.py` con `manager.register_plugin(...)`,
   en el orden correcto (los más específicos antes que `WebPlugin`).

Guía completa (uso, API, plugins, script de reparación): `docs/GUIA-PROYECTO.md`.

## Siguiente paso sugerido

Construir la UI de escritorio en Electron que consuma esta API: una
lista de descargas con barra de progreso (vía WebSocket) y un campo
para pegar enlaces (POST a `/descargas`).
