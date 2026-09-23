import asyncio
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..core.engine import DownloadManager
from ..core.models import DownloadItem
from ..core.plugins.direct_http import DirectHttpPlugin
from ..core.plugins.youtube import YoutubePlugin
from ..core.plugins.image_scraper import ImageScraperPlugin

app = FastAPI(title="API interna - gestor de descargas")

# Permite que la UI de escritorio (Electron) o cualquier futuro
# proyecto consuma la API sin problemas de CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = DownloadManager(dest_folder="./descargas")

# Orden de registro importante: los plugins específicos primero,
# el "catch-all" (image_scraper) el último.
manager.register_plugin(YoutubePlugin())
manager.register_plugin(DirectHttpPlugin())
manager.register_plugin(ImageScraperPlugin())

active_sockets: List[WebSocket] = []
event_loop: Optional[asyncio.AbstractEventLoop] = None


@app.on_event("startup")
async def startup():
    global event_loop
    event_loop = asyncio.get_event_loop()

    def broadcast(item: DownloadItem):
        # Este callback lo invocan los hilos de descarga (no async),
        # así que despachamos la difusión al loop de asyncio.
        if event_loop:
            asyncio.run_coroutine_threadsafe(_broadcast(item), event_loop)

    manager.on_update(broadcast)


async def _broadcast(item: DownloadItem):
    data = item.to_dict()
    desconectados = []
    for ws in active_sockets:
        try:
            await ws.send_json(data)
        except Exception:
            desconectados.append(ws)
    for ws in desconectados:
        active_sockets.remove(ws)


class NuevaDescarga(BaseModel):
    url: str


@app.post("/descargas")
def crear_descarga(payload: NuevaDescarga):
    item = manager.add(payload.url)
    return item.to_dict()


@app.get("/descargas")
def listar_descargas():
    return [i.to_dict() for i in manager.list_items()]


@app.get("/descargas/{item_id}")
def obtener_descarga(item_id: str):
    item = manager.items.get(item_id)
    if not item:
        return {"error": "no encontrado"}
    return item.to_dict()


@app.post("/descargas/{item_id}/cancelar")
def cancelar_descarga(item_id: str):
    manager.cancel(item_id)
    return {"ok": True}



@app.post("/descargas/{item_id}/pausar")
def pausar_descarga(item_id: str):
    manager.pause(item_id)
    return {"ok": True}


@app.post("/descargas/{item_id}/reanudar")
def reanudar_descarga(item_id: str):
    manager.resume(item_id)
    return {"ok": True}



@app.websocket("/progreso")
async def progreso(websocket: WebSocket):
    await websocket.accept()
    active_sockets.append(websocket)
    try:
        while True:
            # Solo mantiene viva la conexión; el servidor empuja los
            # datos, el cliente no necesita enviar nada relevante.
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_sockets.remove(websocket)
