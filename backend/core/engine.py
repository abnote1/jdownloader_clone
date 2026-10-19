import os
import re
import threading
import queue
from collections import OrderedDict
from typing import Any, Dict, List, Callable, Optional
from urllib.parse import unquote, urlparse

from .models import DownloadItem, DownloadStatus
from .plugin_base import Analisis, DownloadPlugin, Elemento, limpiar_nombre, limpiar_ruta

# Análisis hechos desde la UI que se guardan esperando a que el usuario
# elija qué descargar.
MAX_ANALISIS_GUARDADOS = 30


class DownloadManager:
    """
    Núcleo del gestor de descargas: mantiene una cola, reparte el
    trabajo entre varios hilos y delega en el plugin adecuado según
    la URL. Se usa siempre a través de la API interna (ver api/main.py),
    nunca directamente desde una UI.
    """

    def __init__(self, dest_folder: str = "./descargas", max_workers: int = 4):
        # Siempre absoluta: los clientes de la API (scripts, UI) no
        # comparten el directorio de trabajo del servidor, así que
        # output_path tiene que servirles tal cual.
        self.dest_folder = os.path.abspath(dest_folder)
        os.makedirs(self.dest_folder, exist_ok=True)

        self.plugins: List[DownloadPlugin] = []
        self.items: Dict[str, DownloadItem] = {}
        self._queue: "queue.Queue[DownloadItem]" = queue.Queue()
        self._listeners: List[Callable[[DownloadItem], None]] = []
        self._remove_listeners: List[Callable[[str], None]] = []
        self._analisis: "OrderedDict[str, Analisis]" = OrderedDict()
        self._lock = threading.Lock()

        for _ in range(max_workers):
            hilo = threading.Thread(target=self._worker_loop, daemon=True)
            hilo.start()


    def set_dest_folder(self, path: str):
        """Cambia la carpeta de destino para las descargas que se
        añadan a partir de ahora (las que ya estén en curso no se
        mueven)."""
        path = os.path.abspath(path)
        os.makedirs(path, exist_ok=True)
        self.dest_folder = path

    def register_plugin(self, plugin: DownloadPlugin):
        # El orden importa: se usa el primer plugin cuyo can_handle()
        # devuelva True, así que los plugins "catch-all" (como
        # image_scraper) deben registrarse los últimos.
        plugin.motor = self
        self.plugins.append(plugin)

    def _plugin(self, nombre: str) -> Optional[DownloadPlugin]:
        return next((p for p in self.plugins if p.name == nombre), None)

    def on_update(self, callback: Callable[[DownloadItem], None]):
        self._listeners.append(callback)

    def on_remove(self, callback: Callable[[str], None]):
        self._remove_listeners.append(callback)

    def _notify(self, item: DownloadItem):
        # Un hilo puede seguir con un item que ya se quitó de la lista
        # (hasta que vea el CANCELLED); no hay que "resucitarlo" en la UI.
        if item.id not in self.items:
            return
        for cb in self._listeners:
            cb(item)

    def _find_plugin(self, url: str) -> Optional[DownloadPlugin]:
        for plugin in self.plugins:
            if plugin.can_handle(url):
                return plugin
        return None

 

    def add(self, url: str, dest_subfolder: Optional[str] = None,
            filename: Optional[str] = None,
            parent_id: Optional[str] = None,
            plugin_forzado: Optional[str] = None,
            tipo: Optional[str] = None,
            opciones: Optional[Dict[str, Any]] = None) -> DownloadItem:
        plugin = self._plugin(plugin_forzado) if plugin_forzado else self._find_plugin(url)
        item = DownloadItem(
            url=url,
            filename=filename,
            plugin_name=plugin.name if plugin else None,
            dest_subfolder=dest_subfolder,
            parent_id=parent_id,
            plugin_forzado=plugin_forzado,
            tipo=tipo,
            opciones=dict(opciones or {}),
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

    @staticmethod
    def _slug(texto: str) -> str:
        """Nombre de carpeta a partir de un título ('Capítulo 3 | Web')."""
        slug = re.sub(r"[^\w.-]+", "-", texto or "").strip("-.")
        return slug[:80]

    @staticmethod
    def _nombre_numerado(url: str, posicion: int, total: int) -> str:
        """'001.webp', '002.webp'... para que las páginas de un capítulo
        queden en orden de lectura. Con el nombre original no basta:
        'c-14-10.webp' se ordena antes que 'c-14-2.webp'."""
        ext = os.path.splitext(unquote(urlparse(url).path))[1].lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext):
            ext = ""
        return f"{posicion:0{max(3, len(str(total)))}d}{ext}"




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
    




    def retry(self, item_id: str) -> bool:
        """Vuelve a encolar un item que acabó en error o cancelado,
        conservando su carpeta y nombre de archivo (las páginas de un
        capítulo siguen numeradas igual)."""
        item = self.items.get(item_id)
        if not item or item.status not in (DownloadStatus.ERROR, DownloadStatus.CANCELLED):
            return False
        item.status = DownloadStatus.QUEUED
        item.error = None
        item.progress = 0.0
        item.speed = 0.0
        item.downloaded_bytes = 0  # direct_http reescribe el archivo desde cero
        item.intento += 1
        self._notify(item)
        self._queue.put(item)
        return True

    def remove(self, item_id: str) -> List[str]:
        """Quita de la lista un item y todos los que salieron de él
        (las imágenes de un capítulo), cancelando los que sigan
        activos. No borra archivos del disco. Devuelve los ids quitados."""
        with self._lock:
            ids = [item_id] if item_id in self.items else []
            # Recorrido en anchura por parent_id (madre -> hijos -> ...)
            i = 0
            while i < len(ids):
                ids.extend(x.id for x in self.items.values() if x.parent_id == ids[i])
                i += 1
            for x in ids:
                item = self.items.pop(x)
                if item.status not in (DownloadStatus.COMPLETED, DownloadStatus.ERROR):
                    item.status = DownloadStatus.CANCELLED
        for x in ids:
            for cb in self._remove_listeners:
                cb(x)
        return ids

    # ---- Análisis y selección (la UI enseña qué hay y el usuario elige)

    def analizar(self, url: str) -> Analisis:
        plugin = self._find_plugin(url)
        if not plugin:
            raise ValueError("Ningún plugin puede manejar esta URL")
        analisis = plugin.analyze(url)
        with self._lock:
            self._analisis[analisis.id] = analisis
            while len(self._analisis) > MAX_ANALISIS_GUARDADOS:
                self._analisis.popitem(last=False)
        return analisis

    def add_seleccion(self, analisis_id: str, ids: List[str], formato: Optional[str] = None,
                      carpeta: Optional[str] = None) -> DownloadItem:
        """Descarga solo los elementos elegidos de un análisis previo."""
        analisis = self._analisis.get(analisis_id)
        if not analisis:
            raise KeyError("El análisis ha caducado; vuelve a analizar el enlace")
        elegidos = [e for e in analisis.elementos if e.id in set(ids)]
        if not elegidos:
            raise ValueError("No se ha elegido nada para descargar")
        formato = formato or analisis.formato_defecto

        if len(elegidos) == 1 and elegidos[0].url == analisis.url and not elegidos[0].opciones.get("expandir"):
            # Un único archivo: un solo item, sin paquete
            e = elegidos[0]
            return self.add(e.url, dest_subfolder=carpeta, filename=limpiar_nombre(e.nombre),
                            plugin_forzado=e.plugin or analisis.plugin, tipo=e.tipo,
                            opciones={**e.opciones, **({"formato": formato} if formato else {})})

        madre = DownloadItem(url=analisis.url, plugin_name=analisis.plugin,
                             filename=analisis.titulo, dest_subfolder=carpeta,
                             status=DownloadStatus.EXTRACTING)
        with self._lock:
            self.items[madre.id] = madre
        self._notify(madre)
        self._crear_hijos(madre, analisis, elegidos, formato)
        return madre

    def _crear_hijos(self, madre: DownloadItem, analisis: Analisis,
                     elementos: List[Elemento], formato: Optional[str]):
        # Todo el paquete va en una subcarpeta: la que pidió el cliente
        # o, si no, una con el título/nombre del capítulo, carpeta, etc.
        carpeta = madre.dest_subfolder or self._slug(analisis.titulo) or self._slug_from_url(madre.url)
        madre.filename = madre.filename or analisis.titulo
        imagenes = [e for e in elementos if e.tipo == "imagen"]
        for e in elementos:
            if analisis.numerar and e.tipo == "imagen":
                # Las imágenes vienen en orden de lectura: 001, 002...
                posicion = imagenes.index(e) + 1
                nombre = self._nombre_numerado(e.url, posicion, len(imagenes))
            else:
                nombre = limpiar_nombre(e.nombre)
            sub = os.path.join(carpeta, limpiar_ruta(e.ruta)) if e.ruta else carpeta
            opciones = dict(e.opciones)
            if formato:
                opciones["formato"] = formato
            if opciones.pop("expandir", False):
                # Un enlace que a su vez hay que analizar (carpeta de
                # Drive, lista, otro capítulo): su propia subcarpeta.
                self.add(e.url, dest_subfolder=os.path.join(sub, limpiar_nombre(e.nombre)),
                         parent_id=madre.id, tipo=e.tipo, opciones=opciones)
            else:
                self.add(e.url, dest_subfolder=sub, filename=nombre, parent_id=madre.id,
                         plugin_forzado=e.plugin or analisis.plugin, tipo=e.tipo, opciones=opciones)
        # Se marca completada DESPUÉS de crear los hijos: quien vea la
        # madre en COMPLETED ya puede contar con todos ellos.
        madre.status = DownloadStatus.COMPLETED
        madre.downloaded_bytes = len(elementos)
        madre.progress = 100.0
        self._notify(madre)

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
        # Cancelado o quitado mientras esperaba en la cola.
        if item.status == DownloadStatus.CANCELLED or item.id not in self.items:
            return

        plugin = self._plugin(item.plugin_forzado) if item.plugin_forzado else self._find_plugin(item.url)
        if not plugin:
            item.status = DownloadStatus.ERROR
            item.error = "Ningún plugin puede manejar esta URL"
            self._notify(item)
            return

        item.plugin_name = plugin.name

        # Carpeta de destino de este item: la general, o una subcarpeta
        # propia si viene marcado como parte de un capítulo/galería.
        item_dest_folder = self.dest_folder
        if item.dest_subfolder:
            item_dest_folder = os.path.join(self.dest_folder, item.dest_subfolder)
            os.makedirs(item_dest_folder, exist_ok=True)

        if item.plugin_forzado:
            # Ya se sabe qué es (una página de un capítulo, un archivo
            # de una carpeta de MEGA...): se descarga sin analizar.
            plugin.download(item, item.url, item_dest_folder, on_progress=self._notify)
            return

        item.status = DownloadStatus.EXTRACTING
        self._notify(item)

        try:
            analisis = plugin.analyze(item.url)
        except Exception as e:
            item.status = DownloadStatus.ERROR
            item.error = f"Error al analizar: {e}"
            self._notify(item)
            return

        # Sin interfaz se descarga lo que el análisis marca por defecto
        # (las páginas del capítulo, el vídeo, todos los archivos...).
        elegidos = [e for e in analisis.elementos if e.seleccionado]
        if not elegidos:
            item.status = DownloadStatus.ERROR
            item.error = "No se encontró nada que descargar en el enlace"
            self._notify(item)
            return

        e = elegidos[0]
        if len(elegidos) == 1 and e.url == item.url and not e.opciones.get("expandir"):
            # Caso simple: el enlace ES el archivo (vídeo, archivo de
            # MEGA...). Se descarga en este mismo item, con el plugin que
            # diga el análisis (p. ej. la web genérica detecta que es un
            # archivo sin extensión y lo pasa a direct_http).
            descargador = self._plugin(e.plugin) if e.plugin else plugin
            item.plugin_name = descargador.name
            item.tipo = item.tipo or e.tipo
            item.opciones = {**e.opciones, **item.opciones}
            if analisis.formato_defecto:
                item.opciones.setdefault("formato", analisis.formato_defecto)
            if not item.filename and e.nombre and descargador.name != "video":
                item.filename = limpiar_nombre(e.nombre)
            descargador.download(item, item.url, item_dest_folder, on_progress=self._notify)
            return

        # La URL se expandió en varios elementos (imágenes de un
        # capítulo, archivos de una carpeta...): cada uno se encola como
        # item propio, hijo de este.
        self._crear_hijos(item, analisis, elegidos, item.opciones.get("formato") or analisis.formato_defecto)
