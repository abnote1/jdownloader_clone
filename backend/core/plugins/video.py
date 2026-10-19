import shutil
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from ..models import DownloadItem, DownloadStatus
from ..plugin_base import Analisis, DownloadPlugin, Elemento, limpiar_nombre

FORMATOS_FIJOS = [
    {"id": "mejor", "etiqueta": "Vídeo · mejor calidad"},
    {"id": "1080", "etiqueta": "Vídeo · hasta 1080p"},
    {"id": "720", "etiqueta": "Vídeo · hasta 720p"},
    {"id": "480", "etiqueta": "Vídeo · hasta 480p"},
    {"id": "360", "etiqueta": "Vídeo · hasta 360p"},
    {"id": "audio_mp3", "etiqueta": "Solo audio · MP3"},
    {"id": "audio", "etiqueta": "Solo audio · formato original"},
]


class _DescargaPausada(Exception):
    """Se usa internamente para cortar ydl.download() en cuanto el
    motor marca el item como PAUSED o CANCELLED."""


class _SinLog:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def _extractores():
    # Se cargan una vez: son ~1.700 clases con su expresión regular.
    if _extractores.cache is None:
        from yt_dlp.extractor import gen_extractor_classes
        _extractores.cache = [e for e in gen_extractor_classes() if e.IE_NAME != "generic"]
    return _extractores.cache


_extractores.cache = None


class VideoPlugin(DownloadPlugin):
    """
    Vídeo y audio de cualquier web que soporte yt-dlp (YouTube, Vimeo,
    Twitch, X/Twitter, TikTok, Dailymotion, SoundCloud... ~1.700).

    El análisis lista los vídeos de una lista de reproducción como
    subelementos y ofrece formatos (calidad o solo audio). Como plugin
    forzado también descarga vídeos sueltos que la web genérica
    encuentre en una página (<video>, .m3u8, .mp4).
    """

    name = "video"

    def can_handle(self, url: str) -> bool:
        if urlparse(url).scheme not in ("http", "https"):
            return False
        return any(e.suitable(url) for e in _extractores())

    def analyze(self, url: str) -> Analisis:
        import yt_dlp

        opciones = {"quiet": True, "skip_download": True, "extract_flat": "in_playlist",
                    "logger": _SinLog(), "noplaylist": False}
        with yt_dlp.YoutubeDL(opciones) as ydl:
            info = ydl.extract_info(url, download=False)

        if info.get("_type") in ("playlist", "multi_video"):
            # Un enlace de vídeo dentro de una lista (watch?v=X&list=Y)
            # viene con solo ese vídeo marcado; el resto se puede elegir.
            elegido = parse_qs(urlparse(url).query).get("v", [None])[0]
            elementos = []
            for e in info.get("entries") or []:
                if not e:
                    continue
                enlace = e.get("webpage_url") or e.get("url")
                if not enlace or not str(enlace).startswith("http"):
                    continue
                elementos.append(Elemento(
                    enlace, e.get("title") or e.get("id") or enlace, "video", plugin=self.name,
                    seleccionado=(elegido is None or e.get("id") == elegido),
                    miniatura=_miniatura(e), grupo="Lista de reproducción",
                    opciones={"duracion": e.get("duration")},
                ))
            return Analisis(url, self.name, info.get("title") or "Lista de reproducción", elementos,
                            formatos=FORMATOS_FIJOS, formato_defecto="mejor")

        tiene_video = any((f.get("vcodec") or "none") != "none" for f in info.get("formats") or [info])
        alturas = sorted({f["height"] for f in info.get("formats") or []
                          if f.get("height") and (f.get("vcodec") or "none") != "none"}, reverse=True)
        formatos = [f for f in FORMATOS_FIJOS
                    if not f["id"].isdigit() or any(h >= int(f["id"]) for h in alturas)]
        if not tiene_video:
            formatos = [f for f in FORMATOS_FIJOS if f["id"].startswith("audio")]

        tamano = info.get("filesize") or info.get("filesize_approx")
        return Analisis(url, self.name, info.get("title") or url, [Elemento(
            url, info.get("title") or info.get("id") or "video",
            "video" if tiene_video else "audio", plugin=self.name,
            tamano=tamano, miniatura=_miniatura(info),
            opciones={"duracion": info.get("duration")},
        )], formatos=formatos, formato_defecto=formatos[0]["id"])

    def download(self, item: DownloadItem, url: str, dest_folder: str, on_progress):
        import yt_dlp  # se importa aquí para no exigir la dependencia si no se usa

        item.status = DownloadStatus.EXTRACTING
        on_progress(item)

        # yt-dlp a veces falla al autodetectar ffmpeg aunque esté instalado
        # (procesos de recarga en caliente, PATH distinto entre terminales...).
        # Buscamos la ruta explícitamente y se la pasamos, así no depende
        # de su autodetección interna.
        ffmpeg_path = shutil.which("ffmpeg")
        formato = item.opciones.get("formato") or "mejor"
        if not ffmpeg_path and formato == "audio_mp3":
            raise RuntimeError("Para convertir a MP3 hace falta ffmpeg ('sudo apt install ffmpeg')")

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

        nombre = limpiar_nombre(item.filename).replace("%", "%%") if item.filename else "%(title)s"
        ydl_opts = {
            "outtmpl": f"{dest_folder}/{nombre}.%(ext)s",
            "progress_hooks": [hook],
            "format": _selector(formato, bool(ffmpeg_path)),
            "noplaylist": True,
            "quiet": True,
            "logger": _SinLog(),
            # Ya es el valor por defecto, pero lo dejamos explícito:
            # es lo que permite que la próxima llamada retome el .part
            # existente en vez de volver a descargar todo el vídeo.
            "continuedl": True,
        }
        if ffmpeg_path:
            ydl_opts["ffmpeg_location"] = ffmpeg_path
        if formato == "audio_mp3":
            ydl_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                                           "preferredquality": "0"}]

        try:
            info = None
            for intento in range(2):
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                    break
                except yt_dlp.utils.DownloadError as e:
                    # YouTube a veces da 403 con una URL de descarga
                    # recién sacada; volver a extraerla suele bastar.
                    if intento == 0 and "403" in str(e):
                        continue
                    raise
        except _DescargaPausada:
            # El estado (PAUSED o CANCELLED) ya lo puso quien llamó a
            # pause()/cancel(); aquí solo hace falta salir sin marcar
            # error ni completado.
            on_progress(item)
            return
        except yt_dlp.utils.DownloadError as e:
            if isinstance(getattr(e, "exc_info", [None, None])[1], _DescargaPausada):
                on_progress(item)
                return
            raise RuntimeError(str(e).replace("ERROR: ", "")) from None

        descargas = (info or {}).get("requested_downloads") or []
        if descargas and descargas[0].get("filepath"):
            item.output_path = descargas[0]["filepath"]
        item.speed = 0
        item.progress = 100.0
        item.status = DownloadStatus.COMPLETED
        on_progress(item)


def _selector(formato: str, hay_ffmpeg: bool) -> str:
    if formato.startswith("audio"):
        return "bestaudio/best"
    if not hay_ffmpeg:
        # Sin ffmpeg no se pueden unir vídeo y audio por separado
        return f"best[height<={formato}]/best" if formato.isdigit() else "best"
    if formato.isdigit():
        return f"bestvideo[height<={formato}]+bestaudio/best[height<={formato}]/best"
    return "bestvideo+bestaudio/best"


def _miniatura(info: dict) -> Optional[str]:
    if info.get("thumbnail"):
        return info["thumbnail"]
    miniaturas: List[dict] = info.get("thumbnails") or []
    return miniaturas[-1].get("url") if miniaturas else None
