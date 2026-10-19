import base64
import json
import random
import re
import struct
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util import Counter

from ..descarga_http import descargar_http
from ..plugin_base import Analisis, DownloadPlugin, Elemento, limpiar_nombre, tipo_por_nombre

API = "https://g.api.mega.co.nz/cs"

ERRORES = {
    -2: "petición incorrecta",
    -9: "el archivo o la carpeta no existe (o la clave del enlace es incorrecta)",
    -11: "acceso denegado",
    -16: "el usuario que lo compartió está bloqueado",
    -17: "se superó la cuota de transferencia",
    -18: "MEGA no está disponible temporalmente, prueba más tarde",
    509: "se superó la cuota de transferencia gratuita de MEGA; espera unas horas",
}


def _b64(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/").replace(",", "")
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _clave_archivo(k32: bytes) -> Tuple[bytes, bytes]:
    """Las claves de archivo de MEGA son 256 bits: la clave AES real es
    la primera mitad XOR la segunda, y el nonce de CTR va en la segunda."""
    k = struct.unpack(">8I", k32)
    clave = struct.pack(">4I", k[0] ^ k[4], k[1] ^ k[5], k[2] ^ k[6], k[3] ^ k[7])
    nonce = struct.pack(">2I", k[4], k[5])
    return clave, nonce


def _atributos(at: str, clave: bytes) -> Optional[dict]:
    datos = AES.new(clave, AES.MODE_CBC, b"\0" * 16).decrypt(_b64(at)).rstrip(b"\0")
    if not datos.startswith(b"MEGA{"):
        return None
    try:
        return json.loads(datos[4:].decode("utf-8", "replace"))
    except ValueError:
        return None


def _api(peticion: dict, carpeta: Optional[str] = None):
    params = {"id": random.randint(0, 2 ** 31)}
    if carpeta:
        params["n"] = carpeta
    r = requests.post(API, params=params, json=[peticion], timeout=30)
    if r.status_code == 509:
        raise RuntimeError("MEGA: " + ERRORES[509])
    r.raise_for_status()
    datos = r.json()
    resultado = datos if isinstance(datos, int) else datos[0]
    if isinstance(resultado, int):
        raise RuntimeError(f"MEGA: {ERRORES.get(resultado, f'error {resultado}')}")
    return resultado


def _parsear(url: str) -> dict:
    """Formatos admitidos:
    mega.nz/file/ID#CLAVE           mega.nz/#!ID!CLAVE
    mega.nz/folder/ID#CLAVE         mega.nz/#F!ID!CLAVE
    mega.nz/folder/ID#CLAVE/file/SUB    mega.nz/folder/ID#CLAVE/folder/SUB
    mega.nz/#F!ID!CLAVE!SUB"""
    p = urlparse(url)
    frag = p.fragment
    m = re.match(r"/file/([\w-]+)", p.path)
    if m and frag:
        return {"tipo": "archivo", "id": m.group(1), "clave": frag}
    m = re.match(r"/folder/([\w-]+)", p.path)
    if m and frag:
        partes = frag.split("/")
        sub = partes[2] if len(partes) >= 3 and partes[1] in ("file", "folder") else None
        return {"tipo": "carpeta", "id": m.group(1), "clave": partes[0], "sub": sub}
    m = re.match(r"!([\w-]+)!([\w-]+)", frag)
    if m:
        return {"tipo": "archivo", "id": m.group(1), "clave": m.group(2)}
    m = re.match(r"F!([\w-]+)!([\w-]+)(?:!([\w-]+))?", frag)
    if m:
        return {"tipo": "carpeta", "id": m.group(1), "clave": m.group(2), "sub": m.group(3)}
    raise ValueError("Enlace de MEGA no reconocido (¿falta la clave después de '#'?)")


class MegaPlugin(DownloadPlugin):
    """
    Archivos y carpetas públicas de MEGA (mega.nz).

    MEGA cifra todo en el navegador: el enlace lleva la clave después de
    '#'. Aquí se pide la información a su API pública, se descifran los
    nombres y el contenido se descifra al vuelo (AES-CTR) mientras se
    descarga, así que la pausa/reanudación funciona igual que en una
    descarga normal.
    """

    name = "mega"

    def can_handle(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host.endswith(("mega.nz", "mega.co.nz", "mega.io")) and "#" in url

    def analyze(self, url: str) -> Analisis:
        enlace = _parsear(url)
        if enlace["tipo"] == "archivo":
            clave, _ = _clave_archivo(_b64(enlace["clave"]))
            info = _api({"a": "g", "p": enlace["id"]})
            attrs = _atributos(info["at"], clave)
            if attrs is None:
                raise RuntimeError("MEGA: la clave del enlace es incorrecta")
            nombre = attrs.get("n", enlace["id"])
            return Analisis(url, self.name, nombre, [Elemento(
                url, nombre, tipo_por_nombre(nombre), plugin=self.name, tamano=info.get("s"),
                opciones={"mega": {"p": enlace["id"], "k": enlace["clave"]}},
            )])
        return self._analizar_carpeta(url, enlace)

    def _analizar_carpeta(self, url: str, enlace: dict) -> Analisis:
        clave_carpeta = _b64(enlace["clave"])
        nodos = _api({"a": "f", "c": 1, "r": 1, "ca": 1}, carpeta=enlace["id"])["f"]
        aes = AES.new(clave_carpeta, AES.MODE_ECB)

        info: Dict[str, dict] = {}
        for n in nodos:
            # 'k' puede traer varias claves "propietario:clave" separadas
            # por '/'; vale la que consigue descifrar los atributos.
            for parte in (n.get("k") or "").split("/"):
                if ":" not in parte:
                    continue
                cifrada = _b64(parte.split(":", 1)[1])
                if len(cifrada) > 32:
                    continue  # cifrada con RSA: solo la puede abrir el dueño
                k = aes.decrypt(cifrada)
                clave = _clave_archivo(k)[0] if n["t"] == 0 else k
                attrs = _atributos(n.get("a", ""), clave)
                if attrs is not None:
                    info[n["h"]] = {"nodo": n, "nombre": attrs.get("n", n["h"]), "k": k}
                    break

        if not info:
            raise RuntimeError("MEGA: no se pudo descifrar la carpeta (¿clave incorrecta?)")

        def ruta(h: str) -> List[str]:
            partes = []
            while h in info:
                partes.append(info[h]["nombre"])
                h = info[h]["nodo"]["p"]
            return partes[::-1]

        raiz = next(h for h, d in info.items() if d["nodo"]["p"] not in info)
        titulo = info[raiz]["nombre"]
        sub = enlace.get("sub")
        base = ruta(sub) if sub in info and info[sub]["nodo"]["t"] == 1 else ruta(raiz)

        elementos = []
        for h, d in info.items():
            n = d["nodo"]
            if n["t"] != 0:
                continue
            partes = ruta(h)
            if partes[:len(base)] != base:
                continue  # fuera de la subcarpeta pedida
            elementos.append(Elemento(
                url=f"https://mega.nz/folder/{enlace['id']}#{enlace['clave']}/file/{h}",
                nombre=d["nombre"],
                tipo=tipo_por_nombre(d["nombre"]),
                plugin=self.name,
                ruta="/".join(limpiar_nombre(p) for p in partes[len(base):-1]),
                tamano=n.get("s"),
                # Si el enlace apuntaba a un archivo concreto de la
                # carpeta, solo ese viene marcado.
                seleccionado=(sub is None or sub == h or info.get(sub, {}).get("nodo", {}).get("t") == 1),
                opciones={"mega": {"n": h, "carpeta": enlace["id"], "k": _b64e(d["k"])}},
            ))
        elementos.sort(key=lambda e: (e.ruta, e.nombre.lower()))
        return Analisis(url, self.name, base[-1] if base else titulo, elementos)

    def download(self, item, url, dest_folder, on_progress):
        datos = item.opciones.get("mega")
        if not datos:
            enlace = _parsear(url)
            if enlace["tipo"] != "archivo":
                raise RuntimeError("Las carpetas de MEGA se descargan archivo a archivo")
            datos = {"p": enlace["id"], "k": enlace["clave"]}

        if "p" in datos:
            info = _api({"a": "g", "g": 1, "ssl": 2, "p": datos["p"]})
        else:
            info = _api({"a": "g", "g": 1, "ssl": 2, "n": datos["n"]}, carpeta=datos["carpeta"])

        if not info.get("g"):
            raise RuntimeError("MEGA no dio enlace de descarga (¿cuota superada?)")

        clave, nonce = _clave_archivo(_b64(datos["k"]))
        if not item.filename:
            attrs = _atributos(info["at"], clave) or {}
            item.filename = limpiar_nombre(attrs.get("n", "mega.bin"))

        def descifrador(offset: int):
            ctr = Counter.new(64, prefix=nonce, initial_value=offset // 16)
            cifra = AES.new(clave, AES.MODE_CTR, counter=ctr)
            # Si se reanuda a mitad de un bloque de 16 bytes, hay que
            # "gastar" la parte de keystream que ya se usó.
            cifra.decrypt(b"\0" * (offset % 16))
            return cifra

        descargar_http(item, info["g"], dest_folder, on_progress,
                       descifrador=descifrador, tamano=info.get("s"))
