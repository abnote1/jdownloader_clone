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
      direct_http.py    -> descarga directa de archivos por extensión conocida
      youtube.py         -> descarga de vídeos de YouTube (yt-dlp)
      image_scraper.py   -> detecta imágenes en páginas dinámicas (Playwright)
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

Queda escuchando en `http://127.0.0.1:8642`.

## Probar la API

Añadir una descarga:

```bash
curl -X POST http://127.0.0.1:8642/descargas \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=XXXXXXXXXXX"}'
```

Añadir una página para que detecte imágenes automáticamente:

```bash
curl -X POST http://127.0.0.1:8642/descargas \
  -H "Content-Type: application/json" \
  -d '{"url": "https://ejemplo.com/galeria"}'
```

Ver el estado de todas las descargas:

```bash
curl http://127.0.0.1:8642/descargas
```

Progreso en tiempo real: conectar por WebSocket a `ws://127.0.0.1:8642/progreso`
(cualquier cliente, incluida la futura UI de Electron).

## Cómo añadir un plugin nuevo

1. Crear `backend/core/plugins/mi_plugin.py` heredando de `DownloadPlugin`.
2. Implementar `can_handle`, `resolve` y `download`.
3. Registrarlo en `backend/api/main.py` con `manager.register_plugin(...)`,
   en el orden correcto (los más específicos antes que los "catch-all").

## Siguiente paso sugerido

Construir la UI de escritorio en Electron que consuma esta API: una
lista de descargas con barra de progreso (vía WebSocket) y un campo
para pegar enlaces (POST a `/descargas`).
