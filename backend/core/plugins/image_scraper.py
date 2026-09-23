from urllib.parse import urlparse

from ..plugin_base import DownloadPlugin
from ..models import DownloadItem, DownloadStatus


class ImageScraperPlugin(DownloadPlugin):
    """
    Plugin "de último recurso": para cualquier página web, la renderiza
    con Playwright (así funciona también con sitios de carga dinámica
    por JavaScript) y detecta todas las imágenes visibles.

    resolve() devuelve la lista de URLs de imagen encontradas; el
    motor de descargas las vuelve a encolar como items independientes,
    que el plugin direct_http se encarga de bajar de verdad.

    IMPORTANTE: debe registrarse SIEMPRE el último en el DownloadManager,
    porque can_handle() acepta cualquier URL http(s) como fallback.
    """

    name = "image_scraper"

    def can_handle(self, url: str) -> bool:
        return urlparse(url).scheme in ("http", "https")

    def resolve(self, url: str):
        from playwright.sync_api import sync_playwright

        # Atributos donde los sitios con lazy-load suelen guardar la URL
        # real de la imagen antes de que entre en el viewport.
        LAZY_ATTRS = ("src", "data-src", "data-original", "data-lazy-src", "data-lazy", "data-echo")

        image_urls = set()

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()

            def on_response(response):
                if response.request.resource_type == "image":
                    image_urls.add(response.url)

            page.on("response", on_response)
            # "domcontentloaded" en vez de "networkidle": muchos sitios
            # nunca llegan a estar "idle" de verdad (anuncios, analítica...)
            # y networkidle acaba agotando el timeout sin motivo.
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)

            # Los lectores de manga/cómic cargan cada página según entra
            # en pantalla, así que hay que forzar el scroll hasta el final
            # para que el JS del sitio dispare esas cargas.
            self._autoscroll(page)

            # margen extra para que terminen de llegar las últimas imágenes
            page.wait_for_timeout(2000)

            # Se leen los <img> DESPUÉS de hacer scroll: muchos sitios
            # solo rellenan src/data-src (o añaden el <img> al DOM) en
            # ese momento, no al cargar la página.
            for handle in page.query_selector_all("img"):
                for attr in LAZY_ATTRS:
                    valor = handle.get_attribute(attr)
                    if valor:
                        absolute = page.evaluate(
                            "(u) => new URL(u, document.baseURI).href", valor
                        )
                        image_urls.add(absolute)
                        break

            browser.close()

        return list(image_urls)

    def _autoscroll(self, page):
        """Baja por la página en pasos pequeños, con una pausa entre cada
        uno, para que TODAS las imágenes intermedias lleguen a pasar por
        el viewport de verdad (no solo la de arriba y la de abajo).

        Antes saltábamos directo al final de la página cuando dejaba de
        crecer, pero en sitios que cargan cada imagen según entra en
        pantalla, ese salto se salta las páginas intermedias: nunca
        llegan a "aparecer", así que se quedan con el placeholder roto
        en vez de la imagen real."""
        page.evaluate(
            """
            async () => {
                let posicion = 0;
                let pasos = 0;
                const distancia = 700;
                const espera = 350;
                while (pasos < 400) {
                    const alturaActual = document.body.scrollHeight;
                    if (posicion >= alturaActual) break;
                    window.scrollTo(0, posicion);
                    await new Promise((r) => setTimeout(r, espera));
                    posicion += distancia;
                    pasos++;
                }
                // Última pasada ya en el fondo real, por si la altura
                // creció en el último tramo del bucle.
                window.scrollTo(0, document.body.scrollHeight);
            }
            """
        )

    def download(self, item: DownloadItem, url: str, dest_folder: str, on_progress):
        # No debería llamarse nunca directamente: cuando resolve()
        # devuelve varias URLs distintas de la de entrada, el
        # DownloadManager las reencola por separado (ver engine.py).
        item.status = DownloadStatus.ERROR
        item.error = "image_scraper no descarga directamente, solo resuelve enlaces"
        on_progress(item)