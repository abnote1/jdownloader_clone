import re
import time
import uuid
from html.parser import HTMLParser
from typing import List, Tuple
from urllib.parse import urljoin, urlparse

import requests

from ..plugin_base import DownloadPlugin
from ..models import DownloadItem, DownloadStatus

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

# El lector pone a cada página un alt del tipo
# "<serie>, capítulo 87, página 3": así se distinguen de las portadas
# de "series recomendadas" y se sabe su orden.
ALT_PAGINA = re.compile(r"p[áa]gina\s+(\d+)\s*$", re.IGNORECASE)


class _ExtractorPaginas(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paginas: List[Tuple[int, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag != "img":
            return
        a = dict(attrs)
        m = ALT_PAGINA.search(a.get("alt") or "")
        if m and a.get("src"):
            self.paginas.append((int(m.group(1)), a["src"]))


class OlympusPlugin(DownloadPlugin):
    """
    Capítulos de Olympus Scanlation (olympusxyz.com y los dominios que
    vaya estrenando).

    Las URLs de todas las páginas vienen ya en el HTML que renderiza el
    servidor, así que no hace falta navegador ni scroll. El problema es
    su caché: a veces guarda una versión rota del capítulo con imágenes
    de relleno ("/cp/cp-1.jpg", que dan 404; en la web se ve "La página
    1 no ha cargado") y se la sirve a todo el mundo. Añadir un
    parámetro inventado a la URL fuerza a renderizarlo de nuevo.
    """

    name = "olympus"

    REINTENTOS = 4

    def can_handle(self, url: str) -> bool:
        parsed = urlparse(url)
        return "olympus" in parsed.netloc.lower() and "/capitulo/" in parsed.path

    def resolve(self, url: str, intento: int = 0) -> List[str]:
        for n in range(self.REINTENTOS):
            paginas = self._paginas(url)
            if paginas and not any(self._es_relleno(p) for p in paginas):
                return paginas
            time.sleep(1 + n)

        if not paginas:
            raise RuntimeError("No se encontraron páginas en el capítulo")
        raise RuntimeError(
            "Olympus sigue sirviendo páginas vacías para este capítulo "
            f"tras {self.REINTENTOS} intentos; prueba de nuevo más tarde"
        )

    def _paginas(self, url: str) -> List[str]:
        separador = "&" if "?" in url else "?"
        sin_cache = f"{url}{separador}nc={uuid.uuid4().hex[:8]}"
        r = requests.get(
            sin_cache,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"},
            timeout=30,
        )
        r.raise_for_status()

        extractor = _ExtractorPaginas()
        extractor.feed(r.text)

        vistas = set()
        paginas = []
        for _, src in sorted(extractor.paginas, key=lambda p: p[0]):
            absoluta = urljoin(url, src)
            if absoluta not in vistas:
                vistas.add(absoluta)
                paginas.append(absoluta)
        return paginas

    @staticmethod
    def _es_relleno(url: str) -> bool:
        return urlparse(url).path.startswith("/cp/")

    def download(self, item: DownloadItem, url: str, dest_folder: str, on_progress):
        # Igual que image_scraper: solo resuelve, las páginas las baja
        # direct_http cuando el motor las reencola.
        item.status = DownloadStatus.ERROR
        item.error = "olympus no descarga directamente, solo resuelve enlaces"
        on_progress(item)
