# Product Requirements Document (PRD)
## JDownloader Clone

**Fecha:** 23 de septiembre de 2026  
**Versión:** 1.0  
**Autor:** Equipo de Desarrollo  
**Estado:** En Desarrollo

---

## 1. Resumen Ejecutivo

**JDownloader Clone** es un gestor de descargas moderno y extensible que funciona con una arquitectura de **backend en Python** (con API REST + WebSocket) y una **UI de escritorio en Electron**. El sistema detecta automáticamente el tipo de contenido (videos, imágenes, archivos directos) y aplica el plugin correspondiente para optimizar cada descarga.

La aplicación está diseñada para ser agnóstica respecto al frontend, permitiendo que cualquier cliente (Electron, web, móvil) consuma la misma API.

---

## 2. Visión y Objetivos

### Visión
Crear una solución completa, fácil de usar y extensible para descargar contenido de internet de cualquier tipo, desde videos en YouTube hasta galerías de imágenes en sitios dinámicos.

### Objetivos Principales
- ✅ Soporte para múltiples tipos de descarga (video, imágenes, archivos directos)
- ✅ Arquitectura modular basada en plugins
- ✅ API agnóstica, desacoplada de la UI
- ✅ Interfaz intuitiva en Electron
- ✅ Soporte para descargas concurrentes
- ✅ Actualizaciones en tiempo real mediante WebSocket

---

## 3. Descripción del Producto

### 3.1 Arquitectura General

```
┌──────────────────────┐
│   Electron UI        │  (Interfaz visual del usuario)
└──────────┬───────────┘
           │ HTTP + WebSocket
┌──────────▼───────────┐
│   FastAPI Backend    │  (API REST + WebSocket)
└──────────┬───────────┘
           │
┌──────────▼────────────────────┐
│   Plugin System               │
├───────────────────────────────┤
│ • YoutubePlugin               │
│ • DirectHttpPlugin            │
│ • ImageScraperPlugin          │
└───────────────────────────────┘
           │
┌──────────▼───────────────────┐
│   DownloadManager             │
│   (Cola, threading, dispatch) │
└──────────────────────────────┘
```

### 3.2 Componentes Principales

#### Backend (`/backend`)

**Core Components:**
- **`models.py`**: Define `DownloadItem` y `DownloadStatus` (estados de descarga)
- **`engine.py`**: `DownloadManager` - gestiona la cola de descargas, hilos y dispatch a plugins
- **`plugin_base.py`**: Clase base abstracta que todos los plugins deben implementar

**Plugins:**
- **`DirectHttpPlugin`**: Detecta y descarga archivos directos basados en extensión
- **`YoutubePlugin`**: Descarga videos de YouTube usando `yt-dlp`
- **`ImageScraperPlugin`**: Detecta y descarga imágenes de páginas dinámicas con Playwright

**API (`/backend/api`):**
- **`main.py`**: Servidor FastAPI que expone:
  - Endpoints REST para crear/listar/pausar/reanudar descargas
  - WebSocket para actualizaciones en tiempo real

#### Frontend (`/electron_ui`)

**Estructura:**
- **`main.js`**: Proceso principal de Electron
- **`preload.js`**: Bridge seguro entre proceso principal y renderer
- **`renderer/index.html`**: Interfaz visual
- **`renderer/renderer.js`**: Lógica del cliente
- **`renderer/styles.css`**: Estilos

---

## 4. Funcionalidades Principales

### 4.1 Gestión de Descargas

| Funcionalidad | Descripción |
|---------------|-------------|
| **Añadir Descarga** | Usuario pega un URL, el sistema detecta el tipo y crea una tarea de descarga |
| **Listar Descargas** | Muestra todas las descargas (activas, completadas, en error) |
| **Pausar Descarga** | Pausa una descarga en progreso |
| **Reanudar Descarga** | Continúa una descarga pausada |
| **Cancelar Descarga** | Cancela una descarga activa |
| **Progreso en Tiempo Real** | WebSocket actualiza progreso, velocidad, ETA en vivo |
| **Carpeta de Destino** | Usuario puede cambiar dónde se guardan los archivos |

### 4.2 Sistema de Plugins

Cada plugin implementa:
```python
class BasePlugin(ABC):
    def can_handle(self, url: str) -> bool
    async def download(self, item: DownloadItem) -> None
```

**Flujo de Plugin:**
1. Sistema recibe URL
2. Itera plugins en orden (YouTube → DirectHttp → ImageScraper)
3. Primer plugin que devuelve `True` en `can_handle()` procesa la descarga
4. Actualiza `DownloadItem` con progreso en tiempo real

### 4.3 Estados de Descarga

```
QUEUED ──→ EXTRACTING ──→ DOWNLOADING ──→ COMPLETED
                              ↓
                            PAUSED
                              ↓
                          DOWNLOADING
                              ↓
                          CANCELLED / ERROR
```

---

## 5. Especificaciones Técnicas

### 5.1 Stack Tecnológico

**Backend:**
- Python 3.9+
- FastAPI (API REST + WebSocket)
- aiohttp (requests asincronos)
- yt-dlp (descarga de YouTube)
- Playwright (scraping dinámico)

**Frontend:**
- Electron 28+
- JavaScript vanilla
- CSS 3

**Base de Datos:**
- Sistema de archivos (carpeta `descargas/` local)
- Historial en JSON (optional, v2)

### 5.2 API REST Endpoints

```
POST   /descargas              # Crear nueva descarga
GET    /descargas              # Listar todas las descargas
GET    /descargas/{id}         # Obtener detalles de una descarga
PATCH  /descargas/{id}/pausa   # Pausar descarga
PATCH  /descargas/{id}/reanuda # Reanudar descarga
DELETE /descargas/{id}         # Cancelar descarga
GET    /config/carpeta         # Obtener carpeta de destino
POST   /config/carpeta         # Cambiar carpeta de destino
```

### 5.3 WebSocket Events

**Cliente ← Servidor:**
- `download_updated`: {id, progress, speed, status, downloaded_bytes, total_bytes}
- `download_completed`: {id, output_path}
- `download_error`: {id, error_message}

**Cliente → Servidor:**
- `subscribe`: Suscribirse a actualizaciones de descarga
- `unsubscribe`: Desuscribirse

### 5.4 Estructura de Datos

**DownloadItem:**
```json
{
  "id": "uuid-aleatorio",
  "url": "https://youtube.com/watch?v=...",
  "filename": "video_final.mp4",
  "status": "downloading",
  "progress": 45.5,
  "speed": 2.5,
  "total_bytes": 1000000,
  "downloaded_bytes": 455000,
  "error": null,
  "output_path": "/home/user/descargas/video_final.mp4",
  "plugin_name": "YoutubePlugin",
  "created_at": 1695382800.0
}
```

---

## 6. Flujo de Casos de Uso

### 6.1 Descargar un Video de YouTube

```
1. Usuario abre la app
2. Pega URL de YouTube en el input
3. Click "Añadir"
4. API crea DownloadItem
5. YoutubePlugin detecta + yt-dlp extrae info
6. DownloadManager inicia descarga en thread
7. WebSocket emite actualizaciones de progreso
8. UI muestra progreso en vivo (%, vel, ETA)
9. Descarga completada → archivo guardado en carpeta destino
```

### 6.2 Descargar Imágenes de una Página

```
1. Usuario pega URL de galería (ej: Instagram, Pinterest)
2. Sistema no detecta YouTube ni extensión directa
3. ImageScraperPlugin actúa: abre navegador con Playwright
4. Detecta todas las imágenes en la página
5. Descarga cada una en subcarpeta nombrada por fecha
6. UI muestra progreso individual por imagen
```

### 6.3 Descargar Archivo Directo

```
1. Usuario pega URL de archivo directo (PDF, ZIP, etc.)
2. DirectHttpPlugin detecta por extensión
3. Inicia descarga HTTP simple
4. Actualiza progreso byte a byte
5. Completa cuando recibe Content-Length
```

---

## 7. Requisitos Funcionales

### 7.1 Core (MVP)

- [x] Backend FastAPI con soporte WebSocket
- [x] Plugin de descarga directa HTTP
- [x] Plugin de YouTube con yt-dlp
- [x] Plugin de scraping de imágenes con Playwright
- [x] DownloadManager con cola y threading
- [x] UI básica en Electron
- [x] Mostrar lista de descargas
- [x] Pausar/Reanudar descargas
- [x] Cambiar carpeta de destino
- [x] Actualizar estado en tiempo real vía WebSocket

### 7.2 Versión 1.1 (Planeada)

- [ ] Historial persistente (JSON/SQLite)
- [ ] Caché de descarga (resume)
- [ ] Limite de conexiones simultáneas configurable
- [ ] Soporte para listas de reproducción (YouTube)
- [ ] Gestor avanzado de plugins (cargar dinámicamente)
- [ ] Tema oscuro/claro

### 7.3 Versión 2.0 (Futuro)

- [ ] Client web (React/Vue)
- [ ] Sincronización entre dispositivos
- [ ] Caché distribuido
- [ ] Plugin marketplace
- [ ] Scheduler de descargas
- [ ] Integración con cloud storage (Google Drive, OneDrive)

---

## 8. Requisitos No Funcionales

### 8.1 Rendimiento

- Soporte mínimo para **5 descargas concurrentes**
- Actualización de UI cada **500ms** (WebSocket)
- Tiempo de respuesta API: **< 100ms**
- Inicialización de app: **< 2 segundos**

### 8.2 Escalabilidad

- Plugin system permite agregar nuevos handlers sin tocar core
- Arquitectura desacoplada permite múltiples clientes
- DownloadManager usa threading para concurrencia

### 8.3 Seguridad

- CORS abierto en desarrollo (será restringido en producción)
- Validación de URLs antes de procesar
- Sanitización de filenames para evitar path traversal
- WebSocket solo local en desarrollo (127.0.0.1:8642)

### 8.4 Confiabilidad

- Manejo de errores en cada plugin
- Reintentos automáticos en fallos de red (v1.1)
- Logging detallado de cada operación
- Estados de descarga persistentes (v1.1)

---

## 9. Interfaz de Usuario (Wireframe)

### 9.1 Pantalla Principal

```
┌─────────────────────────────────────────────────────┐
│ Clon de JDownloader                      [_] [-] [X] │
├─────────────────────────────────────────────────────┤
│ [   URL input...           ] [Añadir]                │
│ Carpeta: /home/user/descargas [Cambiar]             │
├─────────────────────────────────────────────────────┤
│ ID    │ Archivo          │ Estado      │ Progreso   │
├─────────────────────────────────────────────────────┤
│ 1a2b  │ video.mp4        │ ↓45%        │ ████░░░░░░ │
│       │ Vel: 2.5 MB/s    │ ETA: 2m30s  │            │
│ ┌─────────────────────────────────────────────────┐ │
│ │                                                 │ │
│ │ Botones: [⏸ Pausar] [⏹ Cancelar]              │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ 5c9d  │ gallery.zip      │ ✓Completado │ 100%       │
├─────────────────────────────────────────────────────┤
│ 3e4f  │ data.csv         │ ⚠Error      │ 0%         │
│       │ Error: timeout   │             │            │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Botones: [🔄 Reintentar] [⏹ Cancelar]         │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## 10. Plan de Desarrollo

### Fase 1 (Current) - MVP
- Backend core completo ✓
- Electron UI básica ✓
- 3 plugins principales ✓

### Fase 2 (v1.1)
- Persistencia de historial
- Resume de descargas
- Configuración avanzada

### Fase 3 (v1.5)
- Client web
- Plugin marketplace
- Scheduler

### Fase 4 (v2.0)
- Cloud sync
- Mobile client
- API pública

---

## 11. Criterios de Éxito

- [x] Backend arranca sin errores
- [x] API responde en < 100ms
- [x] UI muestra lista de descargas
- [x] WebSocket actualiza progreso en tiempo real
- [x] Descargas de YouTube funcionan completas
- [x] Scraping de imágenes funciona
- [x] Pause/Resume funcionan
- [ ] > 95% uptime en producción
- [ ] < 1% tasa de errores no recuperables

---

## 12. Riesgos y Mitigación

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|-----------|
| YouTube cambia API | Media | Alto | Usar yt-dlp mantenido por comunidad |
| Cambios en CORS | Baja | Medio | Config flexible de CORS |
| Memory leak en threading | Baja | Alto | Pool de threads limitado, testing |
| Timeout en descargas largas | Media | Medio | Reconnect automático + resume |

---

## 13. Glossario

- **Plugin**: Componente extensible que implementa lógica específica de un tipo de descarga
- **DownloadManager**: Orquestador central que gestiona cola, threading y dispatch
- **API REST**: Interfaz HTTP sincrónica para operaciones CRUD
- **WebSocket**: Protocolo bidireccional para actualizaciones en tiempo real
- **Backend**: Servidor Python (FastAPI) que ejecuta las descargas
- **Frontend**: UI (Electron) que el usuario interactúa
- **Preload Script**: Script de Electron que expone APIs seguras al renderer

---

## 14. Contacto y Preguntas

**Repositorio**: https://github.com/abnote1/jdownloader_clone  
**Rama de desarrollo**: `V1`  
**Issues/PRs**: GitHub Issues

---

**Documento actualizado**: 23 de septiembre de 2026
