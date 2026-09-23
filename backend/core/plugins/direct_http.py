import os
import requests
from urllib.parse import urlparse, unquote

from ..plugin_base import DownloadPlugin
from ..models import DownloadItem, DownloadStatus

# Extensiones que consideramos "archivo directo": si la URL acaba en
# una de estas, no hace falta analizar la página, se descarga tal cual.
FILE_EXTENSIONS = (
    ".zip", ".rar", ".7z", ".tar", ".gz", ".iso",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
    ".mp3", ".wav", ".flac",
    ".mp4", ".mkv", ".avi", ".mov", ".webm",
    ".exe", ".msi", ".dmg", ".apk",
)


class DirectHttpPlugin(DownloadPlugin):
    """Descarga directa por HTTP/HTTPS de un archivo con extensión conocida."""

    name = "direct_http"

    def can_handle(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return path.endswith(FILE_EXTENSIONS)

    def resolve(self, url: str):
        return [url]

    def download(self, item: DownloadItem, url: str, dest_folder: str, on_progress):
        item.status = DownloadStatus.DOWNLOADING
        on_progress(item)

        filename = item.filename or unquote(os.path.basename(urlparse(url).path)) or "descarga.bin"
        dest_path = item.output_path or os.path.join(dest_folder, filename)
        item.output_path = dest_path

        # Si ya existe un archivo parcial de un intento anterior (pausado),
        # pedimos al servidor que continúe desde ahí con la cabecera Range.
        resume_from = 0
        if os.path.exists(dest_path) and item.downloaded_bytes:
            resume_from = os.path.getsize(dest_path)

        headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}

        with requests.get(url, stream=True, timeout=30, headers=headers) as r:
            if resume_from and r.status_code == 416:
                # El servidor dice que ya no queda nada más que pedir:
                # lo más probable es que ya estuviera completo.
                item.progress = 100.0
                item.status = DownloadStatus.COMPLETED
                on_progress(item)
                return

            r.raise_for_status()

            servidor_soporta_resume = resume_from and r.status_code == 206
            if resume_from and not servidor_soporta_resume:
                # El servidor ignoró el Range y manda el archivo entero:
                # no podemos "pegar" al final, hay que reiniciar desde 0.
                resume_from = 0

            modo_escritura = "ab" if servidor_soporta_resume else "wb"

            content_length = int(r.headers.get("content-length", 0)) or None
            total = (resume_from + content_length) if (servidor_soporta_resume and content_length) else content_length
            item.total_bytes = total

            downloaded = resume_from
            chunk_size = 1024 * 64

            with open(dest_path, modo_escritura) as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if item.status == DownloadStatus.CANCELLED:
                        return
                    if item.status == DownloadStatus.PAUSED:
                        item.downloaded_bytes = downloaded
                        on_progress(item)
                        return
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    item.downloaded_bytes = downloaded
                    if total:
                        item.progress = downloaded / total * 100
                    on_progress(item)

        item.progress = 100.0
        item.status = DownloadStatus.COMPLETED
        on_progress(item)