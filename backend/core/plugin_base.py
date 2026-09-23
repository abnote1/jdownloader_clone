from abc import ABC, abstractmethod
from typing import List, Callable
from .models import DownloadItem


class DownloadPlugin(ABC):
    """
    Interfaz base que debe implementar cada plugin.

    Cada plugin decide si sabe manejar una URL (can_handle), la
    "resuelve" en uno o más enlaces de descarga real (resolve), y
    sabe cómo descargarlos (download).
    """

    name: str = "base"

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """True si este plugin sabe procesar la URL dada."""
        raise NotImplementedError

    @abstractmethod
    def resolve(self, url: str) -> List[str]:
        """
        A partir de una URL de entrada (una página, un vídeo, un
        archivo...), devuelve la lista de URLs descargables reales.
        Para un enlace directo, normalmente es [url].
        Para una página con varias imágenes, es la lista de esas
        imágenes.
        """
        raise NotImplementedError

    @abstractmethod
    def download(self, item: DownloadItem, url: str, dest_folder: str,
                 on_progress: Callable[[DownloadItem], None]) -> None:
        """
        Descarga 'url' (una de las resueltas por resolve) a
        dest_folder, actualizando 'item' y llamando a
        on_progress(item) periódicamente.
        """
        raise NotImplementedError
