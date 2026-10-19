import os
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import unquote, urlparse

from .models import DownloadItem

_EXT_TIPO = {
    "imagen": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".avif"),
    "video": (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".flv", ".m3u8"),
    "audio": (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac"),
    "documento": (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                  ".txt", ".epub", ".cbz", ".cbr", ".odt", ".csv"),
    "comprimido": (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"),
}


def tipo_por_nombre(nombre: str) -> str:
    """Tipo de contenido según la extensión de un nombre o URL."""
    ext = os.path.splitext(urlparse(nombre).path if "://" in nombre else nombre)[1].lower()
    for tipo, exts in _EXT_TIPO.items():
        if ext in exts:
            return tipo
    return "archivo"


def nombre_desde_url(url: str) -> str:
    segmentos = [s for s in unquote(urlparse(url).path).split("/") if s]
    return segmentos[-1] if segmentos else urlparse(url).netloc


def limpiar_nombre(nombre: str, defecto: str = "descarga") -> str:
    """Nombre de archivo o carpeta seguro: sin separadores de ruta, sin
    '..' y sin caracteres que dan problemas en Windows/Linux."""
    nombre = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", nombre or "").strip(" .")
    return nombre[:180] or defecto


def limpiar_ruta(ruta: str) -> str:
    """Ruta relativa segura (p. ej. la estructura de carpetas de Drive o
    MEGA): cada componente se limpia y se descartan '.' y '..'."""
    partes = [p for p in re.split(r"[\\/]+", ruta or "") if p not in ("", ".", "..")]
    return os.path.join(*[limpiar_nombre(p) for p in partes]) if partes else ""


@dataclass
class Elemento:
    """Algo descargable que se encontró al analizar un enlace: el propio
    archivo, cada imagen de un capítulo, cada archivo de una carpeta de
    Drive/MEGA, cada vídeo de una lista..."""
    url: str
    nombre: str
    tipo: str = "archivo"
    # Plugin que lo descarga; None = el mismo que analizó el enlace
    plugin: Optional[str] = None
    # Subcarpeta relativa dentro del paquete (estructura de carpetas)
    ruta: str = ""
    tamano: Optional[int] = None
    seleccionado: bool = True
    # Para agrupar en la UI: "Páginas del capítulo", "Otras imágenes"...
    grupo: str = ""
    miniatura: Optional[str] = None
    # Datos internos para el plugin (claves de MEGA, ids de Drive...)
    opciones: Dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def to_dict(self):
        return {
            "id": self.id, "url": self.url, "nombre": self.nombre,
            "tipo": self.tipo, "plugin": self.plugin, "ruta": self.ruta,
            "tamano": self.tamano, "seleccionado": self.seleccionado,
            "grupo": self.grupo, "miniatura": self.miniatura,
        }


@dataclass
class Analisis:
    url: str
    plugin: str
    titulo: str
    elementos: List[Elemento]
    # Formatos entre los que puede elegir el usuario (vídeo, documentos
    # de Google...): [{"id": "720", "etiqueta": "Vídeo 720p"}, ...]
    formatos: List[Dict[str, str]] = field(default_factory=list)
    formato_defecto: Optional[str] = None
    # True = las imágenes van en orden de lectura y se guardan como
    # 001.ext, 002.ext...
    numerar: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self):
        for n, e in enumerate(self.elementos):
            e.id = e.id or str(n)

    def to_dict(self):
        return {
            "id": self.id, "url": self.url, "plugin": self.plugin,
            "titulo": self.titulo, "numerar": self.numerar,
            "formatos": self.formatos, "formato_defecto": self.formato_defecto,
            "elementos": [e.to_dict() for e in self.elementos],
        }


class DownloadPlugin(ABC):
    """
    Interfaz base que debe implementar cada plugin.

    Cada plugin decide si sabe manejar una URL (can_handle), qué
    contiene (analyze: un archivo, varias imágenes, una carpeta...) y
    cómo descargar cada cosa (download).

    El motor le asigna 'motor' al registrarlo, para que un plugin pueda
    preguntar si otro sabe manejar un enlace (p. ej. la web genérica
    detecta enlaces de MEGA dentro de una página).
    """

    name: str = "base"
    motor = None

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """True si este plugin sabe procesar la URL dada."""
        raise NotImplementedError

    def resolve(self, url: str, intento: int = 0) -> List[str]:
        """
        Forma sencilla de implementar analyze(): devuelve la lista de
        URLs descargables reales. Para un enlace directo, normalmente es
        [url]; para una página con varias imágenes, esas imágenes en
        orden de lectura.

        'intento' indica cuántas veces se ha reintentado ya esta
        descarga (0 la primera vez); los plugins pueden usarlo para
        ser más pacientes en los reintentos.
        """
        raise NotImplementedError

    def analyze(self, url: str) -> Analisis:
        """Qué hay detrás de la URL. Por defecto se apoya en resolve();
        los plugins que saben más (formatos, carpetas, nombres reales)
        lo sobrescriben."""
        urls = self.resolve(url)
        if urls == [url]:
            nombre = nombre_desde_url(url)
            return Analisis(url, self.name, nombre, [
                Elemento(url, nombre, tipo_por_nombre(nombre), plugin=self.name)
            ])
        return Analisis(
            url, self.name, nombre_desde_url(url),
            [Elemento(u, nombre_desde_url(u), "imagen" if tipo_por_nombre(u) in ("imagen", "archivo") else tipo_por_nombre(u),
                      plugin="direct_http", grupo="Páginas") for u in urls],
            numerar=True,
        )

    @abstractmethod
    def download(self, item: DownloadItem, url: str, dest_folder: str,
                 on_progress: Callable[[DownloadItem], None]) -> None:
        """
        Descarga 'url' a dest_folder, actualizando 'item' y llamando a
        on_progress(item) periódicamente. item.opciones trae lo que el
        análisis guardó en el Elemento y el formato elegido. Debe parar
        en cuanto item.status pase a PAUSED o CANCELLED.
        """
        raise NotImplementedError
