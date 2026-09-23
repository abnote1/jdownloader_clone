# Copilot Instructions for JDownloader Clone

**Última actualización**: 23 de septiembre de 2026  
**Versión**: 1.0

## Visión General del Proyecto

**JDownloader Clone** es un gestor de descargas moderno con arquitectura desacoplada:
- **Backend**: Python con FastAPI (API REST + WebSocket)
- **Frontend**: Electron UI
- **Sistema de Plugins**: Arquitectura extensible para detectar y procesar diferentes tipos de descarga

### Objetivo Principal
Crear una solución completa para descargar contenido de internet (videos, imágenes, archivos directos) con una arquitectura agnóstica respecto al frontend.

---

## Arquitectura del Proyecto

```
Electron UI (Frontend)
    ↓ (HTTP + WebSocket)
FastAPI Backend (API REST + WebSocket)
    ↓
Plugin System (YouTube, DirectHTTP, ImageScraper)
    ↓
DownloadManager (Cola, Threading, Dispatch)
```

### Estructura de Carpetas

```
/backend/
  ├── models.py              # DownloadItem, DownloadStatus
  ├── engine.py              # DownloadManager - orquestador
  ├── plugin_base.py         # Clase base abstracta para plugins
  ├── plugins/
  │   ├── youtube_plugin.py  # Descarga video con yt-dlp
  │   ├── direct_http_plugin.py  # Detecta y descarga archivos directos
  │   └── image_scraper_plugin.py # Scraping con Playwright
  └── api/
      └── main.py            # Servidor FastAPI

/electron_ui/
  ├── main.js                # Proceso principal Electron
  ├── preload.js             # Bridge seguro
  └── renderer/
      ├── index.html         # UI
      ├── renderer.js        # Lógica cliente
      └── styles.css         # Estilos
```

---

## Skills Disponibles 🔧

El proyecto cuenta con **skills especializados** que extienden la funcionalidad de Copilot para tareas recurrentes.

**Ubicación**: `.github/skills/`  
**Documentación completa**: Ver [docs/skills-orquestacion.md](../../docs/skills-orquestacion.md)

### Skills Implementados

| Skill | Descripción | Uso |
|-------|-------------|-----|
| **commit-message** | Genera mensajes de commit siguiendo Conventional Commits | `#commit-message: descripción del cambio` |

### Cómo Invocar un Skill

De forma natural en chat:
```
Usa la skill commit-message para: Agregué validación en el plugin de YouTube
```

O explícitamente:
```
#commit-message: Agregué validación en el plugin de YouTube
```

El skill generará un mensaje estructurado siguiendo el estándar del proyecto. Ver [docs/skills-orquestacion.md](../../docs/skills-orquestacion.md) para más detalles.

---

## Componentes Clave

### 1. DownloadManager (`backend/engine.py`)

**Responsabilidades:**
- Gestionar cola de descargas (FIFO)
- Mantener pool de threads para descargas concurrentes (máx. 5)
- Iterar plugins para encontrar el primero que pueda manejar la URL
- Actualizar estado de `DownloadItem` en tiempo real
- Emitir eventos vía WebSocket

**Restricciones:**
- Máximo 5 descargas simultáneas
- Uso de threading (no asyncio puro)
- Debe mantener referencia a todas las descargas activas

### 2. Plugin System (`backend/plugin_base.py` + plugins)

**Interfaz Base:**
```python
class BasePlugin(ABC):
    @abstractmethod
    async def can_handle(self, url: str) -> bool:
        """Determina si este plugin puede procesar la URL"""
        pass
    
    @abstractmethod
    async def download(self, item: DownloadItem) -> None:
        """Ejecuta la descarga y actualiza item.progress"""
        pass
```

**Flujo de Plugins:**
1. DownloadManager recibe URL
2. Itera plugins en orden: YouTube → DirectHTTP → ImageScraper
3. Primer plugin con `can_handle() == True` procesa la descarga
4. Plugin actualiza `item.progress`, `item.status`, `item.downloaded_bytes`, etc.

**Implementaciones Existentes:**

- **YoutubePlugin**: Usa `yt-dlp` para descargar videos de YouTube
  - `can_handle()`: Detecta URLs de youtube.com, youtu.be
  - `download()`: Extrae información + inicia descarga

- **DirectHttpPlugin**: Descarga archivos directos por extensión
  - `can_handle()`: Detecta extensiones comunes (.mp4, .zip, .pdf, etc.)
  - `download()`: Descarga HTTP simple con progreso byte a byte

- **ImageScraperPlugin**: Scraping dinámico con Playwright
  - `can_handle()`: Fallback si ningún plugin anterior funciona
  - `download()`: Abre navegador → detecta imágenes → descarga cada una

### 3. Models (`backend/models.py`)

**DownloadItem:**
```python
{
    "id": "uuid-aleatorio",
    "url": "https://...",
    "filename": "archivo.mp4",
    "status": "downloading",  # queued, extracting, downloading, paused, completed, error, cancelled
    "progress": 45.5,          # 0-100%
    "speed": 2.5,              # MB/s
    "total_bytes": 1000000,
    "downloaded_bytes": 455000,
    "error": null,
    "output_path": "/home/user/descargas/archivo.mp4",
    "plugin_name": "YoutubePlugin",
    "created_at": 1695382800.0
}
```

**Estados Válidos:**
- `queued`: Esperando procesamiento
- `extracting`: Plugin extrayendo información (YouTube)
- `downloading`: Descargando contenido
- `paused`: En pausa (usuario)
- `completed`: Descarga exitosa
- `error`: Error no recuperable
- `cancelled`: Cancelado por usuario

### 4. API REST (`backend/api/main.py`)

**Endpoints Principales:**
```
POST   /descargas              # Crear nueva descarga
GET    /descargas              # Listar todas
GET    /descargas/{id}         # Obtener detalles
PATCH  /descargas/{id}/pausa   # Pausar
PATCH  /descargas/{id}/reanuda # Reanudar
DELETE /descargas/{id}         # Cancelar
GET    /config/carpeta         # Obtener carpeta destino
POST   /config/carpeta         # Cambiar carpeta destino
```

**WebSocket Events (`/ws`):**

*Cliente ← Servidor:*
- `download_updated`: Actualización de progreso
  ```json
  {
    "id": "uuid",
    "progress": 45.5,
    "speed": 2.5,
    "status": "downloading",
    "downloaded_bytes": 455000,
    "total_bytes": 1000000
  }
  ```
- `download_completed`: Descarga exitosa
  ```json
  {
    "id": "uuid",
    "output_path": "/home/user/descargas/archivo.mp4"
  }
  ```
- `download_error`: Error en descarga
  ```json
  {
    "id": "uuid",
    "error_message": "Timeout en descarga"
  }
  ```

### 5. Frontend Electron (`electron_ui/`)

**Flujo Principal:**
1. `main.js`: Crea ventana principal + inicia proceso
2. `preload.js`: Expone APIs seguras (fetch, WebSocket) al renderer
3. `renderer/renderer.js`: Lógica cliente
   - Conecta WebSocket a `ws://localhost:8642`
   - Llama endpoints REST
   - Actualiza UI con eventos WebSocket
4. `renderer/index.html + styles.css`: Interfaz visual

**Responsabilidades del Renderer:**
- Formulario para agregar URLs
- Tabla de descargas (lista) con estados
- Mostrar progreso en tiempo real
- Botones: Pausar, Reanudar, Cancelar, Cambiar carpeta

---

## Guías de Desarrollo

### 1. Agregar un Nuevo Plugin

**Pasos:**

1. Crear archivo `backend/plugins/new_plugin.py`:
```python
from backend.plugin_base import BasePlugin
from backend.models import DownloadItem

class NewPlugin(BasePlugin):
    async def can_handle(self, url: str) -> bool:
        # Logica para detectar si tu plugin puede manejar la URL
        return "specific-domain.com" in url
    
    async def download(self, item: DownloadItem) -> None:
        # Logica de descarga
        # Actualizar: item.progress, item.status, item.downloaded_bytes
        # NO olvidar cambiar status a 'completed' o 'error' al final
        pass
```

2. Registrar en `backend/engine.py` en `DownloadManager.__init__()`:
```python
self.plugins = [
    YoutubePlugin(),
    NewPlugin(),  # Agregar aqui
    DirectHttpPlugin(),
    ImageScraperPlugin(),
]
```

**Restricciones:**
- Plugins se prueban en orden (primero match gana)
- Debe ser asincrónico (`async def`)
- SIEMPRE actualizar `item.status` al final
- Lanzar excepciones apropiadas (el DownloadManager las atrapa)

### 2. Agregar un Nuevo Endpoint REST

En `backend/api/main.py`:

```python
@app.get("/mi-nuevo-endpoint")
async def mi_nuevo_endpoint():
    return {"data": "respuesta"}
```

**Restricciones:**
- Validar input (usar Pydantic models)
- Retornar JSON
- Manejo de excepciones (return 400/500)
- Si modifica DownloadItem, emitir WebSocket event

### 3. Agregar una Característica UI

En `electron_ui/renderer/renderer.js`:

1. Agregar HTML en `index.html`
2. Event listener en `renderer.js`:
```javascript
document.getElementById("mi-boton").addEventListener("click", async () => {
    const response = await fetch("http://localhost:8642/mi-endpoint");
    const data = await response.json();
    // Actualizar UI
});
```

**Restricción:**
- WebSocket está en variable global `ws` (ya conectado)
- Usar `ws.send(JSON.stringify({...}))` para enviar eventos

---

## Patrones Comunes

### Actualizar Progreso de Descarga

En cualquier plugin:
```python
async def download(self, item: DownloadItem) -> None:
    item.status = "downloading"
    
    # En loop mientras descargar datos
    for chunk in data:
        item.downloaded_bytes += len(chunk)
        item.progress = (item.downloaded_bytes / item.total_bytes) * 100
        item.speed = calcular_velocidad()
        # DownloadManager emite WebSocket automáticamente
```

### Manejo de Errores en Plugin

```python
async def download(self, item: DownloadItem) -> None:
    try:
        # Logica descarga
        pass
    except Exception as e:
        item.status = "error"
        item.error = str(e)
        # DownloadManager emite error vía WebSocket
        raise  # Importante: relanzar para que DownloadManager maneje
```

### Validar URL en Enpoint

```python
from urllib.parse import urlparse

@app.post("/descargas")
async def crear_descarga(url: str):
    try:
        parsed = urlparse(url)
        if not parsed.scheme:
            return {"error": "URL inválida"}, 400
    except:
        return {"error": "URL malformada"}, 400
    # Continuar...
```

---

## Stack Tecnológico

**Backend:**
- Python 3.9+
- FastAPI (API REST + WebSocket)
- aiohttp (requests async)
- yt-dlp (descarga YouTube)
- Playwright (scraping dinámico)

**Frontend:**
- Electron 28+
- JavaScript vanilla (sin frameworks)
- HTML5 + CSS3

**Otros:**
- Git (version control)
- GitHub (hosting + issues/PRs)

---

## Criterios de Calidad de Código

### Backend (Python)

1. **Nombrado**: Variables/funciones descriptivas en snake_case
2. **Tipos**: Usar type hints (`async def foo(x: int) -> str:`)
3. **Docstrings**: En cada función/clase (triple comillas)
4. **Manejo de Errores**: Try/except específicos, no bare `except`
5. **Async/Await**: Usar siempre para operaciones I/O
6. **Logging**: `import logging` para debug (no `print`)

### Frontend (JavaScript)

1. **Nombrado**: camelCase para variables/funciones
2. **Comments**: Explicar lógica compleja
3. **Error Handling**: Catch de excepciones en fetch/ws
4. **Eventos**: Event listeners con cleanup si es necesario
5. **DOM**: Usar `getElementById`, `querySelector`, no jQuery

---

## Workflow de Desarrollo

### Testing Local

1. **Backend**: `python backend/api/main.py` (arranca en `localhost:8642`)
2. **Frontend**: `npm start` en `electron_ui/` (arranca Electron)
3. **Verificar**: WebSocket conecta, descargas avanzan, UI actualiza

### Commits

**Usa la skill `commit-message` (`.github/skills/commit-message/SKILL.md`) para generar mensajes siguiendo Conventional Commits:**

```
<tipo>(ámbito): resumen imperativo ≤50 chars

[cuerpo opcional explicando el PORQUÉ]

[Closes #issue | Refs #123]
```

**Tipos**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `style`, `perf`, `ci`, `revert`

**Ejemplos:**
- ✓ `feat(backend): añadir plugin para Vimeo`
- ✓ `fix(engine): resolver timeout en descargas concurrentes`
- ✓ `docs(readme): actualizar instrucciones de instalación`

Referencia issues: `Closes #123` (cierra automáticamente en merge)

### PRs

- Incluir descripción clara
- Referenciar PRD cuando sea relevante
- Pruebas manuales en los cambios principales

---

## Consideraciones Importantes

### Seguridad

- ✅ Validar URLs antes de procesar
- ✅ Sanitizar filenames (evitar path traversal: `../`)
- ✅ CORS abierto solo en desarrollo

### Rendimiento

- ✅ Máx. 5 descargas concurrentes
- ✅ WebSocket actualiza cada 500ms
- ✅ API responde en < 100ms

### Confiabilidad

- ✅ Manejo de estados coherentes
- ✅ Logging en cada operación crítica
- ✅ Recuperación de errores de red (v1.1 +)

---

## Roadmap a Alto Nivel

### MVP (Actual ✓)
- Backend core
- 3 plugins principales
- UI básica con WebSocket

### v1.1 (Próximo)
- Historial persistente (JSON/SQLite)
- Resume de descargas
- Configuración avanzada

### v2.0 (Futuro)
- Client web (React/Vue)
- Plugin marketplace
- Cloud sync

---

## Contacto y Recursos

- **Repositorio**: https://github.com/abnote1/jdownloader_clone
- **Rama de desarrollo**: `V1`
- **Issues/PRs**: GitHub Issues
- **PRD Completo**: `docs/PRD.md`

---

**Instrucciones para Copilot**: Al asistir en este proyecto, sigue esta arquitectura, respeta los patrones establecidos y consulta esta guía para entender responsabilidades de cada componente. Cuando agregues features, considera mover lógica al backend (API) antes que al frontend.
