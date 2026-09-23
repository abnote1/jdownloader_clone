import os
import re
import threading
import queue
from typing import Dict, List, Callable, Optional
from urllib.parse import urlparse

from .models import DownloadItem, DownloadStatus
from .plugin_base import DownloadPlugin


class DownloadManager:
    """
    Núcleo del gestor de descargas: mantiene una cola, reparte el
    trabajo entre varios hilos y delega en el plugin adecuado según
    la URL. Se usa siempre a través de la API interna (ver api/main.py),
    nunca directamente desde una UI.
    """

    def __init__(self, dest_folder: str = "./descargas", max_workers: int = 4):
        self.dest_folder = dest_folder
        os.makedirs(dest_folder, exist_ok=True)

        self.plugins: List[DownloadPlugin] = []
        self.items: Dict[str, DownloadItem] = {}
        self._queue: "queue.Queue[DownloadItem]" = queue.Queue()
        self._listeners: List[Callable[[DownloadItem], None]] = []
        self._lock = threading.Lock()

        for _ in range(max_workers):
            hilo = threading.Thread(target=self._worker_loop, daemon=True)
            hilo.start()


    def set_dest_folder(self, path: str):
        """Cambia la carpeta de destino para las descargas que se
        añadan a partir de ahora (las que ya estén en curso no se
        mueven)."""
        os.makedirs(path, exist_ok=True)
        self.dest_folder = path

    def register_plugin(self, plugin: DownloadPlugin):
        # El orden importa: se usa el primer plugin cuyo can_handle()
        # devuelva True, así que los plugins "catch-all" (como
        # image_scraper) deben registrarse los últimos.
        self.plugins.append(plugin)

    def on_update(self, callback: Callable[[DownloadItem], None]):
        self._listeners.append(callback)

    def _notify(self, item: DownloadItem):
        for cb in self._listeners:
            cb(item)

    def _find_plugin(self, url: str) -> Optional[DownloadPlugin]:
        for plugin in self.plugins:
            if plugin.can_handle(url):
                return plugin
        return None

 

    def add(self, url: str, dest_subfolder: Optional[str] = None) -> DownloadItem:
        plugin = self._find_plugin(url)
        item = DownloadItem(
            url=url,
            plugin_name=plugin.name if plugin else None,
            dest_subfolder=dest_subfolder,
        )
        with self._lock:
            self.items[item.id] = item
        self._queue.put(item)
        self._notify(item)
        return item

    @staticmethod
    def _slug_from_url(url: str) -> str:
        """Convierte una URL en un nombre de carpeta legible, usando el
        último segmento de la ruta (p. ej. el slug del capítulo)."""
        segments = [s for s in urlparse(url).path.split("/") if s]
        base = segments[-1] if segments else urlparse(url).netloc
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-")
        return slug[:80] or "descarga"




    def cancel(self, item_id: str):
        item = self.items.get(item_id)
        if item:
            item.status = DownloadStatus.CANCELLED
            self._notify(item)

    def pause(self, item_id: str):
        item = self.items.get(item_id)
        if item and item.status in (DownloadStatus.DOWNLOADING, DownloadStatus.EXTRACTING):
            item.status = DownloadStatus.PAUSED
            self._notify(item)

    def resume(self, item_id: str):
        item = self.items.get(item_id)
        if item and item.status == DownloadStatus.PAUSED:
            item.status = DownloadStatus.QUEUED
            self._notify(item)
            self._queue.put(item)
    




    def list_items(self) -> List[DownloadItem]:
        return list(self.items.values())

    def _worker_loop(self):
        while True:
            item = self._queue.get()
            try:
                self._process(item)
            except Exception as e:
                item.status = DownloadStatus.ERROR
                item.error = str(e)
                self._notify(item)
            finally:
                self._queue.task_done()

    def _process(self, item: DownloadItem):
        plugin = self._find_plugin(item.url)
        if not plugin:
            item.status = DownloadStatus.ERROR
            item.error = "Ningún plugin puede manejar esta URL"
            self._notify(item)
            return

        item.plugin_name = plugin.name
        item.status = DownloadStatus.EXTRACTING
        self._notify(item)

        try:
            resolved_urls = plugin.resolve(item.url)
        except Exception as e:
            item.status = DownloadStatus.ERROR
            item.error = f"Error al resolver: {e}"
            self._notify(item)
            return

          # Carpeta de destino de este item: la general, o una subcarpeta
        # propia si viene marcado como parte de un capítulo/galería.
        item_dest_folder = self.dest_folder
        if item.dest_subfolder:
            item_dest_folder = os.path.join(self.dest_folder, item.dest_subfolder)
            os.makedirs(item_dest_folder, exist_ok=True)

        if resolved_urls == [item.url]:
            # Caso simple: descarga directa (vídeo, archivo...)
            plugin.download(item, item.url, item_dest_folder, on_progress=self._notify)
        else:
            # La URL de entrada se expandió en varios enlaces
            # descargables (p. ej. imágenes detectadas en una página
            # de carga dinámica): cada uno se encola como item propio,
            # todos dentro de una misma subcarpeta con el nombre del
            # capítulo/galería de origen.
            carpeta = self._slug_from_url(item.url)
            item.status = DownloadStatus.COMPLETED
            item.downloaded_bytes = len(resolved_urls)
            self._notify(item)
            for sub_url in resolved_urls:
                self.add(sub_url, dest_subfolder=carpeta)
