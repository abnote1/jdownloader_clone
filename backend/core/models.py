from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any
import uuid
import time


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class DownloadItem:
    url: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    filename: Optional[str] = None
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: float = 0.0
    speed: float = 0.0
    total_bytes: Optional[int] = None
    downloaded_bytes: int = 0
    error: Optional[str] = None
    output_path: Optional[str] = None
    plugin_name: Optional[str] = None
    dest_subfolder: Optional[str] = None
    # id de la descarga "madre" (p. ej. el capítulo) cuando este item
    # salió de expandir una página en varias imágenes.
    parent_id: Optional[str] = None
    # Si está puesto, el item se descarga con ese plugin sin volver a
    # analizar la URL (p. ej. las imágenes de un capítulo -> direct_http).
    plugin_forzado: Optional[str] = None
    # video, audio, imagen, documento, comprimido, archivo
    tipo: Optional[str] = None
    # Datos para el plugin: formato elegido ("mejor", "720", "audio_mp3"...),
    # claves de MEGA, cabeceras HTTP...
    opciones: Dict[str, Any] = field(default_factory=dict)
    intento: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "filename": self.filename,
            "status": self.status.value,
            "progress": round(self.progress, 2),
            "speed": self.speed,
            "total_bytes": self.total_bytes,
            "downloaded_bytes": self.downloaded_bytes,
            "error": self.error,
            "output_path": self.output_path,
            "plugin_name": self.plugin_name,
            "parent_id": self.parent_id,
            "tipo": self.tipo,
            "formato": self.opciones.get("formato"),
            "dest_subfolder": self.dest_subfolder,
            "created_at": self.created_at,
        }
