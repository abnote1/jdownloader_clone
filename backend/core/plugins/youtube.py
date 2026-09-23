from ..plugin_base import DownloadPlugin
from ..models import DownloadItem, DownloadStatus


class _DescargaPausada(Exception):
    """Se usa internamente para cortar ydl.download() en cuanto el
    motor marca el item como PAUSED o CANCELLED."""


class YoutubePlugin(DownloadPlugin):
    """Descarga vídeos de YouTube (y sitios compatibles) usando yt-dlp."""

    name = "youtube"

    DOMAINS = ("youtube.com", "youtu.be", "m.youtube.com")

    def can_handle(self, url: str) -> bool:
        return any(dominio in url for dominio in self.DOMAINS)

    def resolve(self, url: str):
        # yt-dlp resuelve formatos/streams internamente durante download(),
        # así que aquí simplemente devolvemos la URL de entrada.
        return [url]

    def download(self, item: DownloadItem, url: str, dest_folder: str, on_progress):
        import shutil
        import yt_dlp  # se importa aquí para no exigir la dependencia si no se usa

        item.status = DownloadStatus.EXTRACTING
        on_progress(item)

        # yt-dlp a veces falla al autodetectar ffmpeg aunque esté instalado
        # (procesos de recarga en caliente, PATH distinto entre terminales...).
        # Buscamos la ruta explícitamente y se la pasamos, así no depende
        # de su autodetección interna.
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            item.status = DownloadStatus.ERROR
            item.error = (
                "ffmpeg no está en el PATH de este proceso. "
                "Instálalo con 'sudo apt install ffmpeg' y reinicia el servidor."
            )
            on_progress(item)
            return

        def hook(d):
            # Se comprueba en cada "tick" de progreso: si el motor ha
            # marcado el item como pausado o cancelado desde fuera,
            # cortamos yt-dlp a media descarga.
            if item.status in (DownloadStatus.PAUSED, DownloadStatus.CANCELLED):
                raise _DescargaPausada()

            if d["status"] == "downloading":
                item.status = DownloadStatus.DOWNLOADING
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes", 0)
                item.total_bytes = total
                item.downloaded_bytes = downloaded
                if total:
                    item.progress = downloaded / total * 100
                item.speed = d.get("speed") or 0
                on_progress(item)
            elif d["status"] == "finished":
                item.output_path = d.get("filename")
                on_progress(item)

        ydl_opts = {
            "outtmpl": f"{dest_folder}/%(title)s.%(ext)s",
            "progress_hooks": [hook],
            "format": "bestvideo+bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "ffmpeg_location": ffmpeg_path,
            # Ya es el valor por defecto, pero lo dejamos explícito:
            # es lo que permite que la próxima llamada retome el .part
            # existente en vez de volver a descargar todo el vídeo.
            "continuedl": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except _DescargaPausada:
            # El estado (PAUSED o CANCELLED) ya lo puso quien llamó a
            # pause()/cancel(); aquí solo hace falta salir sin marcar
            # error ni completado.
            on_progress(item)
            return

        item.progress = 100.0
        item.status = DownloadStatus.COMPLETED
        on_progress(item)