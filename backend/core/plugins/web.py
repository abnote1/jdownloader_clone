from typing import Dict, List
from urllib.parse import urlparse

import requests

from ..descarga_http import USER_AGENT, nombre_seguro, _nombre_de_cabecera
from ..models import DownloadItem, DownloadStatus
from ..plugin_base import Analisis, DownloadPlugin, Elemento, nombre_desde_url, tipo_por_nombre

# Recoge del DOM, ya renderizado y después del scroll, todo lo que se
# puede descargar. Para separar las páginas de un capítulo de logos,
# portadas y banners busca el contenedor "lector": el elemento más
# profundo que contiene al menos la mitad de las imágenes grandes.
JS_RECOGER = r"""
() => {
  const abs = (u) => { try { return new URL(u, document.baseURI).href } catch { return null } };
  const LAZY = ["data-src", "data-original", "data-lazy-src", "data-lazy", "data-echo", "data-url", "src"];
  const imgs = [];
  for (const el of document.querySelectorAll("img")) {
    let src = el.currentSrc || "";
    if (!src || src.startsWith("data:")) {
      src = "";
      for (const a of LAZY) {
        const v = el.getAttribute(a);
        if (v && !v.startsWith("data:")) { src = abs(v); break; }
      }
    }
    if (!src || !/^https?:/.test(src)) continue;
    const r = el.getBoundingClientRect();
    imgs.push({ el, src, w: Math.round(r.width), h: Math.round(r.height),
                nw: el.naturalWidth, nh: el.naturalHeight, alt: el.alt || "" });
  }

  const grande = (x) => x.w >= 300 || x.nw >= 500;
  const grandes = imgs.filter(grande);
  const cuenta = new Map();
  for (const x of grandes) {
    for (let e = x.el.parentElement; e; e = e.parentElement) cuenta.set(e, (cuenta.get(e) || 0) + 1);
  }
  let lector = null, mejor = -1;
  const umbral = Math.max(1, Math.ceil(grandes.length / 2));
  for (const [el, c] of cuenta) {
    if (c < umbral) continue;
    let prof = 0;
    for (let e = el; e; e = e.parentElement) prof++;
    if (prof > mejor) { mejor = prof; lector = el; }
  }

  const medios = [];
  for (const m of document.querySelectorAll("video, audio")) {
    const fuentes = [m.currentSrc, m.getAttribute("src"),
                     ...[...m.querySelectorAll("source")].map((s) => s.getAttribute("src"))];
    for (const f of fuentes) {
      const u = f && abs(f);
      if (u && /^https?:/.test(u)) medios.push({ src: u, tipo: m.tagName === "AUDIO" ? "audio" : "video" });
    }
  }

  const iframes = [...document.querySelectorAll("iframe[src]")].map((f) => abs(f.getAttribute("src"))).filter(Boolean);

  const enlaces = [];
  for (const a of document.querySelectorAll("a[href]")) {
    const u = abs(a.getAttribute("href"));
    // Se conserva el fragmento '#': en MEGA es la clave del archivo
    if (u && /^https?:/.test(u)) enlaces.push({ href: u, texto: (a.textContent || "").trim().slice(0, 120) });
  }

  return {
    imagenes: imgs.map((x) => ({ src: x.src, w: x.w, h: x.h, nw: x.nw, nh: x.nh, alt: x.alt,
                                 principal: !!(lector && grande(x) && lector.contains(x.el)) })),
    medios, iframes, enlaces,
  };
}
"""

# Baja la página en pasos de casi una pantalla para que los lectores con
# carga perezosa disparen la carga de cada imagen, y luego repasa las
# imágenes grandes que se quedaron sin cargar llevándolas al centro.
JS_SCROLL = r"""
async () => {
  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
  const alto = () => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
  const paso = Math.max(600, Math.floor(window.innerHeight * 0.9));
  let pos = 0;
  for (let n = 0; n < 800 && pos < alto(); n++) {
    window.scrollTo(0, pos);
    await dormir(400);
    pos += paso;
  }
  window.scrollTo(0, alto());
  await dormir(800);

  const pendientes = [...document.querySelectorAll("img")]
    .filter((i) => i.getBoundingClientRect().width >= 300 && (!i.complete || i.naturalWidth === 0))
    .slice(0, 300);
  for (const i of pendientes) {
    i.scrollIntoView({ block: "center" });
    for (let t = 0; t < 20 && (!i.complete || i.naturalWidth === 0); t++) await dormir(150);
  }
}
"""

TIPOS_RED = ("video/", "audio/", "application/vnd.apple.mpegurl", "application/x-mpegurl")


class WebPlugin(DownloadPlugin):
    """
    Cualquier otra página web (plugin "de último recurso").

    La abre en un Chromium sin ventana (así funcionan también las webs
    que cargan el contenido con JavaScript), hace scroll y clasifica lo
    que encuentra:
      - Páginas del capítulo / imágenes del contenido principal
      - Otras imágenes (logos, portadas, banners), sin marcar
      - Vídeos y audios (etiquetas <video>/<audio>, streams, iframes)
      - Enlaces a archivos, Google Drive, MEGA, vídeos... que otros
        plugins saben descargar

    Si la URL no es una página sino un archivo (aunque no tenga
    extensión), lo detecta y lo descarga tal cual.

    IMPORTANTE: debe registrarse SIEMPRE el último en el DownloadManager,
    porque can_handle() acepta cualquier URL http(s) como fallback.
    """

    name = "web"

    def can_handle(self, url: str) -> bool:
        return urlparse(url).scheme in ("http", "https")

    def analyze(self, url: str) -> Analisis:
        directo = self._archivo_directo(url)
        if directo:
            return Analisis(url, self.name, directo.nombre, [directo])
        return self._analizar_pagina(url)

    def _archivo_directo(self, url: str):
        """Si la URL sirve un archivo (no HTML), no hace falta navegador."""
        try:
            with requests.get(url, stream=True, timeout=20, allow_redirects=True,
                              headers={"User-Agent": USER_AGENT}) as r:
                tipo = r.headers.get("content-type", "")
                if r.status_code != 200 or not tipo or "html" in tipo or "xml" in tipo:
                    return None
                nombre = _nombre_de_cabecera(r.headers.get("content-disposition")) or nombre_seguro(urlparse(r.url).path)
                largo = r.headers.get("content-length")
        except requests.RequestException:
            return None
        principal = tipo.split("/")[0]
        tipo_elem = {"image": "imagen", "video": "video", "audio": "audio"}.get(principal) or tipo_por_nombre(nombre)
        return Elemento(url, nombre, tipo_elem, plugin="direct_http",
                        tamano=int(largo) if largo and largo.isdigit() else None)

    def _analizar_pagina(self, url: str) -> Analisis:
        from playwright.sync_api import sync_playwright

        medios_red: Dict[str, str] = {}

        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                contexto = browser.new_context(user_agent=USER_AGENT, locale="es-ES",
                                               viewport={"width": 1280, "height": 900})
                page = contexto.new_page()

                def on_response(response):
                    tipo = response.headers.get("content-type", "")
                    u = response.url
                    if u.endswith((".ts", ".m4s")) or "mp2t" in tipo:
                        return  # trozos sueltos de un stream
                    if tipo.startswith(TIPOS_RED) or ".m3u8" in u:
                        medios_red.setdefault(u, "audio" if tipo.startswith("audio/") else "video")

                page.on("response", on_response)
                self._abrir(page, url)
                page.evaluate(JS_SCROLL)
                page.wait_for_timeout(1000)
                datos = page.evaluate(JS_RECOGER)
                titulo = page.title() or nombre_desde_url(url)
                final = page.url
            finally:
                browser.close()

        return self._clasificar(url, final, titulo, datos, medios_red)

    @staticmethod
    def _abrir(page, url: str):
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1500)

        pedida = urlparse(url)
        if urlparse(page.url).path not in ("", "/") or pedida.path in ("", "/"):
            return

        # La web nos ha mandado a su portada. Algunas (p. ej. komiwa) lo
        # hacen si se entra directamente a un capítulo; navegando desde
        # dentro de la propia web sí lo muestran: se abre la portada y se
        # pulsa un enlace inyectado al capítulo.
        page.goto(f"{pedida.scheme}://{pedida.netloc}/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(1500)
        page.evaluate("""(u) => {
            const a = document.createElement('a');
            a.href = u; a.id = '__jdclone'; a.textContent = '.';
            document.body.appendChild(a);
        }""", url)
        page.click("#__jdclone")
        try:
            page.wait_for_url(lambda u: urlparse(u).path not in ("", "/"), timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        if urlparse(page.url).path in ("", "/"):
            raise RuntimeError(
                "La web redirige a su portada: el enlace ha caducado o la web no deja abrirlo"
            )

    def _clasificar(self, url, final, titulo, datos, medios_red) -> Analisis:
        vistos = set()
        principales: List[Elemento] = []
        otras: List[Elemento] = []
        medios: List[Elemento] = []
        enlaces: List[Elemento] = []
        cabeceras = {"Referer": final}

        for img in datos["imagenes"]:
            if img["src"] in vistos:
                continue
            if 0 < img["nw"] < 64 and 0 < img["nh"] < 64:
                continue  # iconos y píxeles de seguimiento
            vistos.add(img["src"])
            elem = Elemento(img["src"], nombre_desde_url(img["src"]), "imagen", plugin="direct_http",
                            miniatura=img["src"], opciones={"headers": cabeceras})
            if img["principal"]:
                elem.grupo = "Contenido principal"
                # Se guardan como 001.jpg, 002.jpg...: el nombre de la
                # URL (a menudo un hash) no aporta nada en la lista.
                elem.nombre = f"Página {len(principales) + 1:03d}"
                principales.append(elem)
            else:
                elem.grupo, elem.seleccionado = "Otras imágenes", False
                otras.append(elem)

        for m in datos["medios"] + [{"src": u, "tipo": t} for u, t in medios_red.items()]:
            if m["src"] in vistos:
                continue
            vistos.add(m["src"])
            medios.append(Elemento(m["src"], nombre_desde_url(m["src"]), m["tipo"], plugin="video",
                                   grupo="Vídeo y audio", opciones={"headers": cabeceras}))

        motor = self.motor
        for href in datos["iframes"] + [e["href"] for e in datos["enlaces"]]:
            if href in vistos or href.split("#")[0] in (url, final):
                continue
            vistos.add(href)
            plugin = motor._find_plugin(href) if motor else None
            if not plugin or plugin.name == self.name:
                continue  # otra página normal de la web: no es contenido
            texto = next((e["texto"] for e in datos["enlaces"] if e["href"] == href), "")
            if plugin.name == "direct_http":
                enlaces.append(Elemento(href, nombre_desde_url(href), tipo_por_nombre(href),
                                        plugin="direct_http", grupo="Archivos enlazados"))
            else:
                # Drive, MEGA, vídeos, capítulos... se analizan al
                # descargarlos (pueden ser carpetas o listas).
                enlaces.append(Elemento(href, texto or nombre_desde_url(href), "enlace", plugin=plugin.name,
                                        grupo=f"Enlaces ({plugin.name})", opciones={"expandir": True}))

        # Qué se marca por defecto: el contenido principal; si no hay,
        # los vídeos/audios; si tampoco, los enlaces descargables.
        if principales:
            for e in medios + enlaces:
                e.seleccionado = False
        elif medios:
            for e in enlaces:
                e.seleccionado = False

        elementos = principales + medios + enlaces + otras
        return Analisis(url, self.name, titulo, elementos, numerar=bool(principales))

    def download(self, item: DownloadItem, url: str, dest_folder: str, on_progress):
        # No debería llamarse nunca directamente: lo que encuentra el
        # análisis se descarga con direct_http, video, gdrive...
        item.status = DownloadStatus.ERROR
        item.error = "El plugin web solo analiza páginas; no descarga directamente"
        on_progress(item)
