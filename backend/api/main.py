import asyncio
import os
import secrets
from typing import List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Security, WebSocket, WebSocketDisconnect
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..core.engine import DownloadManager
from ..core.models import DownloadItem
from ..core.plugins.direct_http import DirectHttpPlugin
from ..core.plugins.gdrive import GoogleDrivePlugin
from ..core.plugins.mega import MegaPlugin
from ..core.plugins.olympus import OlympusPlugin
from ..core.plugins.video import VideoPlugin
from ..core.plugins.web import WebPlugin

# Token compartido entre el backend y la UI. Lo genera quien arranca el
# servidor (Electron o run.py) y lo pasa en la variable de entorno.
# Sin él, cualquier página abierta en el navegador podría usar la API
# (añadir descargas, cambiar la carpeta, leer la lista por WebSocket):
# CORS no basta, porque los POST sin cuerpo y los WebSocket no lo
# respetan.
API_TOKEN = os.environ.get("JD_API_TOKEN") or secrets.token_urlsafe(32)

# Se deja también en un fichero solo legible por el usuario, para que
# scripts locales (p. ej. repair_olympus2.py) puedan usar la API aunque
# Electron genere un token nuevo en cada arranque.
TOKEN_FILE = os.path.expanduser("~/.config/jdownloader-clone/api-token")


def _guardar_token():
    os.makedirs(os.path.dirname(TOKEN_FILE), mode=0o700, exist_ok=True)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(API_TOKEN)
    os.chmod(TOKEN_FILE, 0o600)  # por si ya existía con otros permisos

_cabecera_token = APIKeyHeader(name="X-API-Token", auto_error=False)


def _token_valido(token: Optional[str]) -> bool:
    return bool(token) and secrets.compare_digest(token, API_TOKEN)


def verificar_token(token: Optional[str] = Security(_cabecera_token)):
    if not _token_valido(token):
        raise HTTPException(status_code=401, detail="Token de API inválido o ausente")


app = FastAPI(title="API interna - gestor de descargas")
router = APIRouter(dependencies=[Depends(verificar_token)])

# Permite que la UI de escritorio (Electron) o cualquier futuro
# proyecto consuma la API sin problemas de CORS. La protección real
# es el token, no esto.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = DownloadManager(dest_folder="./descargas")

# Orden de registro importante: los plugins específicos primero,
# el "catch-all" (web) el último. direct_http va antes que video para
# que un .mp4 suelto se baje directamente, sin pasar por yt-dlp.
manager.register_plugin(OlympusPlugin())
manager.register_plugin(GoogleDrivePlugin())
manager.register_plugin(MegaPlugin())
manager.register_plugin(DirectHttpPlugin())
manager.register_plugin(VideoPlugin())
manager.register_plugin(WebPlugin())

active_sockets: List[WebSocket] = []
event_loop: Optional[asyncio.AbstractEventLoop] = None


@app.on_event("startup")
async def startup():
    global event_loop
    event_loop = asyncio.get_event_loop()

    # Aquí y no al importar el módulo: un simple "import" (tests,
    # comprobaciones) no debe pisar el token del servidor que corre.
    _guardar_token()

    def broadcast(item: DownloadItem):
        # Este callback lo invocan los hilos de descarga (no async),
        # así que despachamos la difusión al loop de asyncio.
        if event_loop:
            asyncio.run_coroutine_threadsafe(_broadcast(item), event_loop)

    manager.on_update(broadcast)

    def broadcast_eliminado(item_id: str):
        if event_loop:
            asyncio.run_coroutine_threadsafe(_enviar_a_todos({"id": item_id, "eliminado": True}), event_loop)

    manager.on_remove(broadcast_eliminado)


async def _broadcast(item: DownloadItem):
    await _enviar_a_todos(item.to_dict())


async def _enviar_a_todos(data: dict):
    desconectados = []
    for ws in active_sockets:
        try:
            await ws.send_json(data)
        except Exception:
            desconectados.append(ws)
    for ws in desconectados:
        if ws in active_sockets:
            active_sockets.remove(ws)


class NuevaDescarga(BaseModel):
    url: str
    # Subcarpeta (relativa a la carpeta de destino) donde guardar esta
    # descarga y, si se expande en varias imágenes, todas ellas.
    carpeta: Optional[str] = None


def _validar_carpeta(carpeta: Optional[str]) -> Optional[str]:
    if not carpeta:
        return None
    normal = os.path.normpath(carpeta.replace("\\", "/"))
    if os.path.isabs(normal) or normal == "." or normal.split(os.sep)[0] == "..":
        raise HTTPException(status_code=400, detail="'carpeta' debe ser una ruta relativa dentro de la carpeta de destino")
    return normal


def _obtener(item_id: str) -> DownloadItem:
    item = manager.items.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Descarga no encontrada")
    return item


@router.post("/descargas")
def crear_descarga(payload: NuevaDescarga):
    item = manager.add(payload.url, dest_subfolder=_validar_carpeta(payload.carpeta))
    return item.to_dict()


@router.get("/descargas")
def listar_descargas(parent_id: Optional[str] = None):
    items = manager.list_items()
    if parent_id is not None:
        items = [i for i in items if i.parent_id == parent_id]
    return [i.to_dict() for i in items]


class NuevoAnalisis(BaseModel):
    url: str


@router.post("/analizar")
def analizar_enlace(payload: NuevoAnalisis):
    """Qué hay detrás de un enlace (archivos, imágenes, vídeos, formatos),
    sin descargar nada. Puede tardar: las webs se abren en un navegador."""
    try:
        return manager.analizar(payload.url.strip()).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo analizar el enlace: {e}")


class Seleccion(BaseModel):
    analisis_id: str
    elementos: List[str]
    formato: Optional[str] = None
    carpeta: Optional[str] = None


@router.post("/descargas/seleccion")
def descargar_seleccion(payload: Seleccion):
    try:
        item = manager.add_seleccion(payload.analisis_id, payload.elementos, payload.formato,
                                     _validar_carpeta(payload.carpeta))
    except KeyError as e:
        raise HTTPException(status_code=410, detail=str(e.args[0]))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return item.to_dict()


@router.get("/descargas/{item_id}")
def obtener_descarga(item_id: str):
    return _obtener(item_id).to_dict()


@router.post("/descargas/{item_id}/reintentar")
def reintentar_descarga(item_id: str):
    _obtener(item_id)
    if not manager.retry(item_id):
        raise HTTPException(status_code=409, detail="Solo se pueden reintentar descargas con error o canceladas")
    return {"ok": True}


@router.post("/descargas/{item_id}/quitar")
def quitar_descarga(item_id: str):
    """Quita la descarga (y las imágenes que salieron de ella) de la
    lista. Cancela las que sigan activas; no borra archivos."""
    _obtener(item_id)
    return {"ok": True, "quitados": manager.remove(item_id)}


@router.post("/descargas/{item_id}/cancelar")
def cancelar_descarga(item_id: str):
    manager.cancel(item_id)
    return {"ok": True}



@router.post("/descargas/{item_id}/pausar")
def pausar_descarga(item_id: str):
    manager.pause(item_id)
    return {"ok": True}


@router.post("/descargas/{item_id}/reanudar")
def reanudar_descarga(item_id: str):
    manager.resume(item_id)
    return {"ok": True}


class CarpetaDestino(BaseModel):
    path: str


@router.get("/carpeta-destino")
def obtener_carpeta_destino():
    return {"path": manager.dest_folder}


@router.post("/carpeta-destino")
def cambiar_carpeta_destino(payload: CarpetaDestino):
    manager.set_dest_folder(payload.path)
    return {"ok": True, "path": manager.dest_folder}

    

app.include_router(router)


@app.websocket("/progreso")
async def progreso(websocket: WebSocket):
    # Los navegadores no dejan poner cabeceras en un WebSocket, así
    # que aquí el token viaja en la query: /progreso?token=...
    if not _token_valido(websocket.query_params.get("token")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    active_sockets.append(websocket)
    try:
        while True:
            # Solo mantiene viva la conexión; el servidor empuja los
            # datos, el cliente no necesita enviar nada relevante.
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_sockets:
            active_sockets.remove(websocket)

