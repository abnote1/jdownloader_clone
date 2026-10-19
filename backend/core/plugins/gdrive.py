import html
import re
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from ..descarga_http import USER_AGENT, descargar_http
from ..plugin_base import Analisis, DownloadPlugin, Elemento, limpiar_nombre, tipo_por_nombre

# Documentos nativos de Google: no hay archivo como tal, se exportan.
EXPORTAR = {
    "document": [("pdf", "PDF"), ("docx", "Word (.docx)"), ("odt", "OpenDocument (.odt)"), ("txt", "Texto (.txt)")],
    "spreadsheets": [("xlsx", "Excel (.xlsx)"), ("pdf", "PDF"), ("ods", "OpenDocument (.ods)"), ("csv", "CSV (primera hoja)")],
    "presentation": [("pdf", "PDF"), ("pptx", "PowerPoint (.pptx)"), ("odp", "OpenDocument (.odp)")],
}

PROFUNDIDAD_MAXIMA = 10


def _sesion() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _parsear(url: str) -> Tuple[str, str]:
    """-> (clase, id) con clase 'carpeta', 'archivo' o un tipo de
    documento de Google ('document', 'spreadsheets', 'presentation')."""
    p = urlparse(url)
    m = re.search(r"/folders/([\w-]{10,})", p.path)
    if m:
        return "carpeta", m.group(1)
    m = re.search(r"/(document|spreadsheets|presentation)/d/([\w-]{10,})", p.path)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"/file/d/([\w-]{10,})", p.path)
    if m:
        return "archivo", m.group(1)
    qid = parse_qs(p.query).get("id", [None])[0]
    if qid:
        return ("carpeta" if "folderview" in p.path else "archivo"), qid
    raise ValueError("Enlace de Google Drive no reconocido")


def _listar_carpeta(s: requests.Session, carpeta_id: str, ruta: str, profundidad: int,
                    elementos: List[Elemento]) -> str:
    """Lee la vista 'embeddedfolderview' (una petición por carpeta) y
    baja recursivamente por las subcarpetas. Devuelve el nombre de la
    carpeta."""
    r = s.get("https://drive.google.com/embeddedfolderview", params={"id": carpeta_id}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(
            "Google Drive no deja ver la carpeta: tiene que estar compartida "
            "como 'Cualquier persona con el enlace'"
        )
    titulo = re.search(r"<title>(.*?)</title>", r.text, re.S)
    nombre_carpeta = html.unescape(titulo.group(1).strip()) if titulo else carpeta_id

    for href, texto in re.findall(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
        href = html.unescape(href)
        nombre = html.unescape(re.sub(r"<[^>]+>", "", texto)).strip()
        m = re.match(r"https://drive\.google\.com/file/d/([\w-]{10,})", href)
        if m:
            elementos.append(Elemento(
                f"https://drive.google.com/file/d/{m.group(1)}/view", nombre or m.group(1),
                tipo_por_nombre(nombre), plugin="gdrive", ruta=ruta,
            ))
            continue
        m = re.match(r"https://docs\.google\.com/(document|spreadsheets|presentation)/d/([\w-]{10,})", href)
        if m:
            clase, doc_id = m.groups()
            ext = EXPORTAR[clase][0][0]
            elementos.append(Elemento(
                f"https://docs.google.com/{clase}/d/{doc_id}/edit", f"{nombre}.{ext}",
                "documento", plugin="gdrive", ruta=ruta, opciones={"exportar": ext},
            ))
            continue
        m = re.search(r"/folders/([\w-]{10,})", href)
        if m and m.group(1) != carpeta_id and profundidad < PROFUNDIDAD_MAXIMA:
            sub = f"{ruta}/{limpiar_nombre(nombre)}" if ruta else limpiar_nombre(nombre)
            _listar_carpeta(s, m.group(1), sub, profundidad + 1, elementos)
    return nombre_carpeta


def _enlace_descarga(s: requests.Session, archivo_id: str) -> Tuple[str, Optional[str], Optional[requests.Response]]:
    """Devuelve (url, nombre, respuesta abierta o None).

    Los archivos pequeños se sirven directamente. Los grandes devuelven
    antes una página de aviso ("no se puede analizar en busca de virus")
    con un formulario: se reenvía con sus campos (confirm, uuid...)."""
    url = "https://drive.usercontent.google.com/download?" + urlencode({"id": archivo_id, "export": "download"})
    r = s.get(url, stream=True, timeout=30)
    if r.status_code == 404:
        raise RuntimeError("El archivo de Google Drive no existe o no es público")
    r.raise_for_status()
    if "text/html" not in r.headers.get("content-type", ""):
        cd = r.headers.get("content-disposition", "")
        m = re.search(r"filename\*=UTF-8''([^;]+)|filename=\"([^\"]+)\"", cd)
        nombre = requests.utils.unquote(m.group(1)) if m and m.group(1) else (m.group(2) if m else None)
        return url, nombre, r

    pagina = r.text
    r.close()
    accion = re.search(r'<form[^>]+action="([^"]+)"', pagina)
    if not accion:
        if "quota" in pagina.lower() or "too many users" in pagina.lower():
            raise RuntimeError("Google Drive: demasiadas descargas de este archivo hoy; prueba mañana")
        raise RuntimeError("Google Drive no ofreció la descarga (¿archivo privado?)")
    campos = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', pagina))
    nombre = re.search(r'class="uc-name-size"><a[^>]*>([^<]+)</a>', pagina)
    return (html.unescape(accion.group(1)) + "?" + urlencode(campos),
            html.unescape(nombre.group(1)) if nombre else None, None)


def _titulo_documento(s: requests.Session, url: str) -> Optional[str]:
    try:
        t = re.search(r"<title>(.*?)</title>", s.get(url, timeout=30).text, re.S)
    except requests.RequestException:
        return None
    if not t:
        return None
    return re.sub(r"\s+-\s+Google (Docs|Sheets|Slides|Drive|Documentos|Hojas de cálculo|Presentaciones)\s*$", "",
                  html.unescape(t.group(1).strip())) or None


class GoogleDrivePlugin(DownloadPlugin):
    """Archivos y carpetas públicos de Google Drive, y documentos de
    Google (Docs, Hojas, Presentaciones) exportados al formato elegido."""

    name = "gdrive"

    def can_handle(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host in ("drive.google.com", "docs.google.com", "drive.usercontent.google.com")

    def analyze(self, url: str) -> Analisis:
        clase, id_ = _parsear(url)
        s = _sesion()

        if clase == "carpeta":
            elementos: List[Elemento] = []
            titulo = _listar_carpeta(s, id_, "", 0, elementos)
            return Analisis(url, self.name, titulo, elementos)

        if clase in EXPORTAR:
            nombre = _titulo_documento(s, url) or id_
            return Analisis(
                url, self.name, nombre,
                [Elemento(url, nombre, "documento", plugin=self.name)],
                formatos=[{"id": ext, "etiqueta": etiqueta} for ext, etiqueta in EXPORTAR[clase]],
                formato_defecto=EXPORTAR[clase][0][0],
            )

        _, nombre, r = _enlace_descarga(s, id_)
        tamano = int(r.headers["content-length"]) if r is not None and r.headers.get("content-length") else None
        if r is not None:
            r.close()
        nombre = nombre or _titulo_documento(s, f"https://drive.google.com/file/d/{id_}/view") or id_
        return Analisis(url, self.name, nombre, [
            Elemento(url, nombre, tipo_por_nombre(nombre), plugin=self.name, tamano=tamano)
        ])

    def download(self, item, url, dest_folder, on_progress):
        clase, id_ = _parsear(url)
        s = _sesion()

        if clase in EXPORTAR:
            formato = item.opciones.get("formato") or item.opciones.get("exportar") or EXPORTAR[clase][0][0]
            if item.filename and not item.filename.lower().endswith("." + formato):
                item.filename = f"{item.filename.rsplit('.', 1)[0] if '.' in item.filename else item.filename}.{formato}"
            destino = f"https://docs.google.com/{clase}/d/{id_}/export?format={formato}"
            descargar_http(item, destino, dest_folder, on_progress, session=s)
            return

        if clase == "carpeta":
            raise RuntimeError("Las carpetas de Drive se descargan archivo a archivo")

        destino, nombre, r = _enlace_descarga(s, id_)
        if r is not None:
            r.close()
        if not item.filename and nombre:
            item.filename = limpiar_nombre(nombre)
        descargar_http(item, destino, dest_folder, on_progress, session=s)
