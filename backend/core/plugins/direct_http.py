from urllib.parse import urlparse

from ..descarga_http import descargar_http, nombre_seguro
from ..plugin_base import DownloadPlugin

# Extensiones que consideramos "archivo directo": si la URL acaba en
# una de estas, no hace falta analizar la página, se descarga tal cual.
# (Como plugin forzado descarga cualquier URL, tenga extensión o no.)
FILE_EXTENSIONS = (
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".epub", ".cbz", ".cbr",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".avif",
    ".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus",
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".exe", ".msi", ".dmg", ".apk", ".deb", ".appimage",
)

# Se mantiene el nombre por compatibilidad
_nombre_seguro = nombre_seguro


class DirectHttpPlugin(DownloadPlugin):
    """Descarga directa por HTTP/HTTPS de un archivo."""

    name = "direct_http"

    def can_handle(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return path.endswith(FILE_EXTENSIONS)

    def resolve(self, url: str, intento: int = 0):
        return [url]

    def download(self, item, url, dest_folder, on_progress):
        descargar_http(item, url, dest_folder, on_progress,
                       headers=item.opciones.get("headers"))
