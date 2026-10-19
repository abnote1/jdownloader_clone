import mimetypes
import os
import re
import time
from typing import Callable, Dict, Optional
from urllib.parse import unquote, urlparse

import requests

from .models import DownloadItem, DownloadStatus

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

# Tipos para los que una respuesta HTML es seguro un error (página de
# "archivo no encontrado", aviso de cuota...), no el contenido.
TIPOS_BINARIOS = ("imagen", "video", "audio", "comprimido")

_EXT_PREFERIDA = {"image/jpeg": ".jpg", "image/webp": ".webp", "image/png": ".png",
                  "image/gif": ".gif", "image/avif": ".avif", "video/mp4": ".mp4",
                  "audio/mpeg": ".mp3", "application/zip": ".zip", "application/pdf": ".pdf"}


def nombre_seguro(path: str) -> str:
    """Saca el nombre de archivo de la ruta de la URL sin permitir que
    se salga de la carpeta de destino.

    Hay que decodificar ANTES de quedarse con el último segmento: si
    no, una URL como '/..%2F..%2F.bashrc.zip' pasa el basename intacta
    y al decodificarla se convierte en '../../.bashrc.zip'."""
    nombre = os.path.basename(unquote(path).replace("\\", "/"))
    if nombre in ("", ".", ".."):
        return "descarga.bin"
    return nombre


def _nombre_de_cabecera(cd: str) -> Optional[str]:
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", cd or "", re.I)
    if m:
        return nombre_seguro(m.group(1).strip('" '))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd or "", re.I)
    return nombre_seguro(m.group(1).strip()) if m else None


def _extension(content_type: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    return _EXT_PREFERIDA.get(ct) or mimetypes.guess_extension(ct) or ""


def _ruta_libre(carpeta: str, nombre: str) -> str:
    """'foto.jpg' -> 'foto (1).jpg' si ya existe: dos descargas
    distintas con el mismo nombre no se pisan."""
    ruta = os.path.join(carpeta, nombre)
    base, ext = os.path.splitext(nombre)
    n = 1
    while os.path.exists(ruta):
        ruta = os.path.join(carpeta, f"{base} ({n}){ext}")
        n += 1
    return ruta


def descargar_http(item: DownloadItem, url: str, dest_folder: str,
                   on_progress: Callable[[DownloadItem], None],
                   headers: Optional[Dict[str, str]] = None,
                   session: Optional[requests.Session] = None,
                   descifrador: Optional[Callable[[int], object]] = None,
                   tamano: Optional[int] = None) -> None:
    """Descarga por HTTP con progreso, pausa/cancelación y reanudación
    (cabecera Range).

    descifrador(offset) -> objeto con .decrypt(bytes): para contenido
    cifrado como el de MEGA, que se descifra al vuelo desde 'offset'.
    tamano: tamaño real si el servidor no manda Content-Length."""
    item.status = DownloadStatus.DOWNLOADING
    on_progress(item)

    http = session or requests
    cabeceras = {"User-Agent": USER_AGENT, **(headers or {})}

    # Si ya existe un archivo parcial de un intento anterior (pausado),
    # pedimos al servidor que continúe desde ahí con la cabecera Range.
    resume_from = 0
    if item.output_path and os.path.exists(item.output_path) and item.downloaded_bytes:
        resume_from = os.path.getsize(item.output_path)
    if resume_from:
        cabeceras["Range"] = f"bytes={resume_from}-"

    with http.get(url, stream=True, timeout=30, headers=cabeceras) as r:
        if resume_from and r.status_code == 416:
            # El servidor dice que ya no queda nada más que pedir:
            # lo más probable es que ya estuviera completo.
            item.progress = 100.0
            item.status = DownloadStatus.COMPLETED
            on_progress(item)
            return

        r.raise_for_status()

        content_type = r.headers.get("content-type", "")
        if "text/html" in content_type and item.tipo in TIPOS_BINARIOS:
            raise RuntimeError(
                f"El servidor devolvió una página web en lugar de {item.tipo} "
                "(enlace caducado, protegido o con límite de descargas)"
            )

        if not item.output_path:
            nombre = (item.filename
                      or _nombre_de_cabecera(r.headers.get("content-disposition"))
                      or nombre_seguro(urlparse(url).path))
            if not os.path.splitext(nombre)[1]:
                nombre += _extension(content_type)
            item.filename = nombre
            item.output_path = _ruta_libre(dest_folder, nombre)

        servidor_soporta_resume = resume_from and r.status_code == 206
        if resume_from and not servidor_soporta_resume:
            # El servidor ignoró el Range y manda el archivo entero:
            # no podemos "pegar" al final, hay que reiniciar desde 0.
            resume_from = 0

        modo_escritura = "ab" if servidor_soporta_resume else "wb"

        content_length = int(r.headers.get("content-length", 0)) or None
        total = (resume_from + content_length) if (servidor_soporta_resume and content_length) else content_length
        item.total_bytes = tamano or total

        cifra = descifrador(resume_from) if descifrador else None

        downloaded = resume_from
        ultimo_aviso = 0.0
        ventana_t, ventana_bytes = time.time(), downloaded

        with open(item.output_path, modo_escritura) as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if item.status == DownloadStatus.CANCELLED:
                    return
                if item.status == DownloadStatus.PAUSED:
                    item.downloaded_bytes = downloaded
                    item.speed = 0
                    on_progress(item)
                    return
                if not chunk:
                    continue
                f.write(cifra.decrypt(chunk) if cifra else chunk)
                downloaded += len(chunk)
                item.downloaded_bytes = downloaded
                if item.total_bytes:
                    item.progress = downloaded / item.total_bytes * 100

                # Avisos como mucho 4 veces por segundo: con trozos de
                # 64 KB a buena velocidad serían cientos por segundo
                # por el WebSocket.
                ahora = time.time()
                if ahora - ventana_t >= 1:
                    item.speed = (downloaded - ventana_bytes) / (ahora - ventana_t)
                    ventana_t, ventana_bytes = ahora, downloaded
                if ahora - ultimo_aviso >= 0.25:
                    ultimo_aviso = ahora
                    on_progress(item)

    item.speed = 0
    item.progress = 100.0
    item.status = DownloadStatus.COMPLETED
    on_progress(item)
