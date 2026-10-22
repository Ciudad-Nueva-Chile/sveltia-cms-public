"""Completa por ISBN los libros nuevos del catálogo: título, autor, portada y edición.

Corre en GitHub Actions antes de compilar el sitio (publicar.yml). Desde el navegador, Sveltia solo puede consultar
Google Books y Open Library; aquí, en el servidor, también se consultan los sitios de Ciudad Nueva, que tienen casi
todo el catálogo:

    1. ciudadnueva.com (España): cada ficha trae ISBN, título, autor y portada. Si ya hay título, se usa su buscador;
       si no, se buscan en herramientas/indice_ciudadnueva.json (cada ficha con su ISBN) y en las fichas nuevas del
       sitio, que se agregan al índice.
    2. libros.ciudadnueva.com.ar (Argentina): no publica el ISBN, así que solo sirve para la portada, buscando por
       título (debe coincidir casi exacto).
    3. Open Library y Google Books, si todavía falta algo.

Solo toca libros agregados en Sveltia (sin «id_catalogo») que no se buscaron antes, y solo completa lo vacío. El título
«SIN TÍTULO (ISBN …)» que deja Sveltia cuando no encontró nada cuenta como vacío. Cada libro buscado queda con la marca
«busqueda_isbn» (fecha y fuente) para no volver a buscarlo en cada pasada; para repetir la búsqueda, borra esa línea.

    python herramientas/completar_libros.py                 # src/libros y src/assets/portadas
    python herramientas/completar_libros.py --solo-mostrar  # dice qué libros buscaría, sin conectarse
    python herramientas/completar_libros.py --actualizar-indice   # agrega al índice las fichas nuevas de ciudadnueva.com
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import html
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
ES = "https://www.ciudadnueva.com"
AR = "https://libros.ciudadnueva.com.ar"
AGENTE = {"User-Agent": "Mozilla/5.0 (compatible; catalogo Ciudad Nueva Chile)"}
PREFIJO_AR = "978950586"        # ISBN de Ciudad Nueva Argentina
SIN_TITULO = "SIN TÍTULO"
MAX_PORTADA = 8_000_000         # bytes, antes de achicarla
ALTO_PORTADA = 1000             # px
HILOS = 4                       # consultas a la vez al recorrer ciudadnueva.com
SINOPSIS_POR_PASADA = 40        # libros del catálogo que buscan su sinopsis en cada publicación
INDICE = RAIZ / "herramientas" / "indice_ciudadnueva.json"


def bajar(url: str, intentos: int = 3) -> bytes:
    for i in range(intentos):
        try:
            pedido = urllib.request.Request(urllib.parse.quote(url, safe=":/%?=&+"), headers=AGENTE)
            return urllib.request.urlopen(pedido, timeout=30).read()
        except Exception:
            if i == intentos - 1:
                raise
            time.sleep(1.5)
    return b""


def texto(url: str, bajar_fn=bajar) -> str:
    return bajar_fn(url).decode("utf-8", "ignore")


# ---------------------------------------------------------------- ISBN y títulos
def limpiar_isbn(v) -> str:
    return re.sub(r"[^0-9Xx]", "", str(v or "")).upper()


def isbn13(v) -> str:
    """El ISBN en 13 dígitos (los de 10 se convierten), o "" si no es válido."""
    s = limpiar_isbn(v)
    if len(s) == 13 and s.isdigit():
        return s
    if len(s) == 10:
        base = "978" + s[:9]
        suma = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(base))
        return base + str((10 - suma % 10) % 10)
    return ""


def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def parecido(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


# ---------------------------------------------------------------- Archivos del catálogo
def leer(md: Path) -> dict:
    partes = md.read_text(encoding="utf-8").split("---", 2)
    return (yaml.safe_load(partes[1]) or {}) if len(partes) == 3 else {}


def escribir_campos(md: Path, cambios: dict) -> None:
    """Cambia o agrega campos del encabezado sin tocar el resto del archivo."""
    contenido = md.read_text(encoding="utf-8")
    _, cabeza, cuerpo = contenido.split("---", 2)
    lineas = cabeza.strip("\n").split("\n")
    for clave, valor in cambios.items():
        nueva = f"{clave}: {json.dumps(valor, ensure_ascii=False)}"
        i = next((n for n, l in enumerate(lineas) if re.match(rf"{re.escape(clave)}:", l)), None)
        if i is None:
            lineas.append(nueva)
        else:
            fin = i + 1
            while fin < len(lineas) and lineas[fin][:1] in (" ", "\t"):    # valor largo partido en varias líneas
                fin += 1
            lineas[i:fin] = [nueva]
    md.write_text("---\n" + "\n".join(lineas) + "\n---" + cuerpo, encoding="utf-8")


def quitar_campo(md: Path, clave: str) -> None:
    contenido = md.read_text(encoding="utf-8")
    _, cabeza, cuerpo = contenido.split("---", 2)
    lineas, fuera = [], False
    for l in cabeza.strip("\n").split("\n"):
        if re.match(rf"{re.escape(clave)}:", l):
            fuera = True
            continue
        if fuera and l[:1] in (" ", "\t"):
            continue
        fuera = False
        lineas.append(l)
    md.write_text("---\n" + "\n".join(lineas) + "\n---" + cuerpo, encoding="utf-8")


# ---------------------------------------------------------------- Duplicados
def nombre_libro(md: Path, d: dict) -> str:
    return f"{d.get('id_catalogo') or md.stem} «{str(d.get('titulo') or '').strip()[:50]}»"


def avisos_duplicados(carpeta: Path) -> dict[Path, str]:
    """{archivo: aviso} para libros con el mismo ISBN que otro, o con el mismo título y la misma edición."""
    libros = [(md, leer(md)) for md in sorted(carpeta.glob("*.md"))]
    por_isbn, por_titulo = {}, {}
    for md, d in libros:
        i = isbn13(d.get("isbn"))
        if i:
            por_isbn.setdefault(i, []).append((md, d))
        t = normalizar(d.get("titulo"))
        if t and not vacio(d, "titulo"):
            por_titulo.setdefault((t, str(d.get("origen_editorial") or "")), []).append((md, d))
    avisos: dict[Path, list[str]] = {}
    for grupo, motivo in [(g, "mismo ISBN") for g in por_isbn.values()] + [(g, "mismo título") for g in por_titulo.values()]:
        if len(grupo) < 2:
            continue
        for md, d in grupo:
            otros = ", ".join(nombre_libro(m, x) for m, x in grupo if m != md)
            avisos.setdefault(md, []).append(f"{motivo} que {otros}")
    return {md: "Posible duplicado: " + "; ".join(dict.fromkeys(v)) for md, v in avisos.items()}


def marcar_duplicados(carpeta: Path) -> list[tuple[Path, str]]:
    """Escribe el campo «aviso» en los duplicados y lo borra en los que ya no lo son. Devuelve lo que cambió."""
    nuevos = avisos_duplicados(carpeta)
    cambios = []
    for md in sorted(carpeta.glob("*.md")):
        actual = str(leer(md).get("aviso") or "")
        nuevo = nuevos.get(md, "")
        if actual == nuevo:
            continue
        if nuevo:
            escribir_campos(md, {"aviso": nuevo})
        else:
            quitar_campo(md, "aviso")
        cambios.append((md, nuevo))
    return cambios


def vacio(d: dict, campo: str) -> bool:
    v = str(d.get(campo) or "").strip()
    return not v or (campo == "titulo" and v.upper().startswith(SIN_TITULO))


def faltantes(d: dict) -> list[str]:
    return [c for c in ("titulo", "autor", "portada", "origen_editorial") if vacio(d, c)]


def pendientes(carpeta: Path) -> list[tuple[Path, dict]]:
    """Libros agregados en Sveltia (sin ID interno), con ISBN válido, sin buscar todavía y con algo por completar."""
    res = []
    for md in sorted(carpeta.glob("*.md")):
        d = leer(md)
        if d.get("id_catalogo") or d.get("busqueda_isbn") or not isbn13(d.get("isbn")):
            continue
        if faltantes(d):
            res.append((md, d))
    return res


# ---------------------------------------------------------------- Ciudad Nueva España
def ficha_es(pagina: str, url: str = "") -> dict:
    """Datos de una ficha de ciudadnueva.com."""
    isbn = re.search(r"ISBN:</strong>(?:&nbsp;|\s)*([\d\-Xx]+)", pagina)
    titulo = re.search(r'<meta property="og:title" content="([^"]*)"', pagina)
    imagen = re.search(r'<meta property="og:image" content="([^"]*)"', pagina)
    autores = [html.unescape(a).strip() for a in re.findall(r'<a href="/autor/[^"]+"[^>]*>([^<]+)</a>', pagina)]
    return {"isbn": isbn13(isbn.group(1)) if isbn else "", "titulo": html.unescape(titulo.group(1)).strip() if titulo else "",
            "autor": "; ".join(a for a in autores if a), "portada": imagen.group(1) if imagen else "", "url": url,
            "fuente": "Ciudad Nueva España"}


def enlaces_libros(pagina: str) -> list[str]:
    return sorted(set(re.findall(r'href="(https://www\.ciudadnueva\.com/libro/[^"]+)"', pagina)))


def buscar_es_por_titulo(titulo: str, isbn: str, bajar_fn=bajar) -> dict | None:
    palabras = "+".join(normalizar(re.sub(r"\(.*?\)", " ", titulo)).split()[:6])
    if not palabras:
        return None
    for url in enlaces_libros(texto(f"{ES}/libros_encontrados/{palabras}", bajar_fn))[:10]:
        f = ficha_es(texto(url, bajar_fn), url)
        if f["isbn"] == isbn:
            return f
    return None


def fichas_es(bajar_fn=bajar) -> set[str]:
    """Direcciones de todas las fichas de ciudadnueva.com, colección por colección y página por página."""
    colecciones = sorted(set(re.findall(r'href="(https://www\.ciudadnueva\.com/coleccion/[^"]+)"', texto(ES + "/", bajar_fn))))

    def de_coleccion(col):
        vistas = set()
        for pag in range(1, 40):
            try:
                nuevas = set(enlaces_libros(texto(col if pag == 1 else f"{col}/{pag}", bajar_fn))) - vistas
            except Exception:
                break
            if not nuevas:
                break
            vistas |= nuevas
        return vistas

    with ThreadPoolExecutor(HILOS) as ex:
        return set().union(*ex.map(de_coleccion, colecciones)) if colecciones else set()


def recorrer_es(buscados: set[str], bajar_fn=bajar, indice: dict | None = None) -> dict[str, dict]:
    """Busca los ISBN en las fichas de ciudadnueva.com. `indice` ({ficha: ISBN}) evita volver a leer fichas ya vistas:
    primero se miran las fichas conocidas con esos ISBN y después solo las fichas nuevas, que se agregan al índice."""
    indice = {} if indice is None else indice
    hallados = {}

    def leer_ficha(url):
        try:
            return ficha_es(texto(url, bajar_fn), url)
        except Exception:
            return None

    with ThreadPoolExecutor(HILOS) as ex:
        for f in ex.map(leer_ficha, [u for u, i in indice.items() if i in buscados]):
            if f and f["isbn"] in buscados:
                hallados[f["isbn"]] = f
        if buscados and len(hallados) == len(buscados):
            return hallados
        for f in ex.map(leer_ficha, sorted(fichas_es(bajar_fn) - set(indice))):
            if f:
                indice[f["url"]] = f["isbn"]
                if f["isbn"] in buscados:
                    hallados[f["isbn"]] = f
    return hallados


def leer_indice(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))["fichas"]
    except Exception:
        return {}


def guardar_indice(ruta: Path, fichas: dict) -> None:
    ruta.write_text(json.dumps({"nota": "Fichas de ciudadnueva.com y su ISBN (datos públicos del sitio). Lo mantiene "
                                        "completar_libros.py: solo se leen las fichas que no están aquí.",
                                "fichas": dict(sorted(fichas.items()))}, ensure_ascii=False, indent=0) + "\n",
                    encoding="utf-8")


# ---------------------------------------------------------------- Ciudad Nueva Argentina (solo portada)
def sin_sigla(t: str) -> str:
    return re.sub(r"[\(\[].*?[\)\]]", " ", t)


def mismo_libro(catalogo: str, tienda: str) -> bool:
    """Títulos casi iguales sin las siglas; si el del catálogo viene recortado («...»), basta con que el de la tienda
    empiece igual. Si los dos traen número de colección (BP. 83 / [BPa, 83]), tiene que ser el mismo."""
    a, b = normalizar(sin_sigla(catalogo)), normalizar(sin_sigla(tienda))
    num = lambda t: set(re.findall(r"\d+", " ".join(re.findall(r"[\(\[](.*?)[\)\]]", t))))
    if num(catalogo) and num(tienda) and not num(catalogo) & num(tienda):
        return False
    recortado = catalogo.rstrip(" )]").split("(")[0].strip().endswith("...")
    return parecido(a, b) >= 0.9 or (recortado and len(a.split()) >= 3 and b.startswith(a))


def portada_ar(titulo: str, bajar_fn=bajar) -> str:
    # La tienda busca la frase tal cual (un guion en el título la corta): se prueba con las primeras 3 palabras, y 2
    palabras = normalizar(sin_sigla(titulo)).split()
    for n in (3, 2):
        if len(palabras) < n:
            continue
        consulta = urllib.parse.urlencode({"search": " ".join(palabras[:n]), "per_page": 50})
        try:
            productos = json.loads(texto(f"{AR}/wp-json/wc/store/v1/products?{consulta}", bajar_fn))
        except Exception:
            return ""
        buenos = [p for p in productos if p.get("images") and mismo_libro(titulo, html.unescape(p.get("name", "")))]
        if buenos:
            return buenos[0]["images"][0]["src"] if len(buenos) == 1 else ""   # dos fichas posibles: ambiguo, no se usa
    return ""


# ---------------------------------------------------------------- Sinopsis
# Texto de la editorial: ficha de ciudadnueva.com para las ediciones españolas y tienda de Ciudad Nueva Argentina para las
# argentinas (cada libro con la de su edición: la misma colección numera distinto en cada país). Se escribe como cuerpo
# del .md («Sobre el libro» en la ficha) solo si está vacío, y la marca «busqueda_sinopsis» evita repetir la búsqueda.
RUIDO = re.compile(r"cookie|pinchar|b[uú]squeda|carrito|suscr[ií]b|newsletter|aviso legal|pol[ií]tica de", re.I)


def texto_plano(fragmento: str) -> str:
    """HTML → párrafos de texto separados por una línea en blanco."""
    t = re.sub(r"(?i)<br\s*/?>", "\n", fragmento)
    t = re.sub(r"(?i)</p>|</div>|</li>", "\n\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    parrafos = [" ".join(p.split()) for p in re.split(r"\n\s*\n", t)]
    return "\n\n".join(p for p in parrafos if p)


def sinopsis_es(pagina: str) -> str:
    """La sección «Sinopsis» de la ficha (sin «Autor» ni «Información», que vienen después)."""
    m = re.search(r">\s*Sinopsis\s*</span>", pagina)
    if not m:
        return ""
    zona = pagina[m.end():]
    fin = re.search(r'id="subhistoria_articulo|>\s*Autor\s*</span>|>\s*Informaci', zona)
    zona = zona[:fin.start()] if fin else zona
    parrafos = [texto_plano(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", zona)]
    return "\n\n".join(p for p in parrafos if len(p) > 1 and not RUIDO.search(p))


def productos_ar(bajar_fn=bajar) -> list[dict]:
    """Todo el catálogo de la tienda argentina (unas 5 consultas de 100)."""
    todos = []
    for pag in range(1, 20):
        try:
            lote = json.loads(texto(f"{AR}/wp-json/wc/store/v1/products?per_page=100&page={pag}", bajar_fn))
        except Exception:
            break
        nuevos = [x for x in lote if x.get("id", x.get("name")) not in {t.get("id", t.get("name")) for t in todos}]
        if not nuevos:
            break
        todos += nuevos
    return todos


def sinopsis_ar(titulo: str, productos: list[dict]) -> str:
    buenos = [p for p in productos if mismo_libro(titulo, html.unescape(p.get("name", "")))]
    return texto_plano(buenos[0].get("description", "")) if len(buenos) == 1 else ""


def cuerpo(md: Path) -> str:
    return md.read_text(encoding="utf-8").split("---", 2)[2].strip()


def escribir_cuerpo(md: Path, texto_: str) -> None:
    _, cabeza, _ = md.read_text(encoding="utf-8").split("---", 2)
    md.write_text("---" + cabeza + "---\n" + texto_.strip() + "\n", encoding="utf-8")


def completar_sinopsis(carpeta: Path, bajar_fn=bajar, hoy: str | None = None, indice_ruta: Path | None = INDICE,
                       solo_nuevos: bool = True, edicion: str | None = None, limite: int | None = None) -> list[tuple[Path, str]]:
    """Agrega la sinopsis a los libros sin cuerpo y sin «busqueda_sinopsis». solo_nuevos: solo libros agregados en
    Sveltia (sin ID interno); False: todo el catálogo. edicion: solo libros de esa edición (por ejemplo «Argentina»).
    limite: máximo de libros por pasada (para no cargar los sitios). Si un sitio no responde, el libro no se marca y se
    vuelve a intentar en la próxima pasada."""
    hoy = hoy or dt.date.today().strftime("%d-%m-%Y")
    lista = []
    for md in sorted(carpeta.glob("*.md")):
        d = leer(md)
        if d.get("busqueda_sinopsis") or cuerpo(md) or (solo_nuevos and d.get("id_catalogo")):
            continue
        if edicion and edicion not in str(d.get("origen_editorial") or ""):
            continue
        lista.append((md, d))
    if limite is not None:
        lista = lista[:limite]
    if not lista:
        return []
    indice = {i: u for u, i in (leer_indice(indice_ruta) if indice_ruta else {}).items() if i}
    productos = None
    es_caido = False                              # si ciudadnueva.com no responde, no se insiste en esta pasada
    hechos = []
    for md, d in lista:
        isbn, ed = isbn13(d.get("isbn")), str(d.get("origen_editorial") or "")
        texto_, fuente, fallo = "", "", False
        if "Argentina" not in ed and isbn in indice:
            if es_caido:
                continue
            try:
                texto_, fuente = sinopsis_es(texto(indice[isbn], bajar_fn)), "Ciudad Nueva España"
            except Exception:
                fallo = es_caido = True           # el sitio no respondió: se reintenta en la próxima pasada
        if not texto_ and "España" not in ed and not vacio(d, "titulo"):
            if productos is None:
                productos = productos_ar(bajar_fn)
            fallo = fallo or not productos
            texto_, fuente = sinopsis_ar(str(d["titulo"]), productos), "Ciudad Nueva Argentina"
        if texto_:
            escribir_cuerpo(md, texto_)
        elif fallo:
            continue
        escribir_campos(md, {"busqueda_sinopsis": f"{hoy} · {fuente if texto_ else 'sin resultado'}"})
        hechos.append((md, fuente if texto_ else ""))
    return hechos


# ---------------------------------------------------------------- Open Library y Google Books
def buscar_abiertas(isbn: str, bajar_fn=bajar) -> dict | None:
    try:
        o = json.loads(texto(f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data", bajar_fn))
        l = o.get(f"ISBN:{isbn}")
        if l and l.get("title"):
            return {"titulo": l["title"] + (". " + l["subtitle"] if l.get("subtitle") else ""),
                    "autor": ", ".join(a.get("name", "") for a in l.get("authors", [])),
                    "portada": (l.get("cover") or {}).get("large", ""), "fuente": "Open Library"}
    except Exception:
        pass
    try:
        g = json.loads(texto(f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}", bajar_fn))
        v = (g.get("items") or [{}])[0].get("volumeInfo") or {}
        if v.get("title"):
            return {"titulo": v["title"] + (". " + v["subtitle"] if v.get("subtitle") else ""),
                    "autor": ", ".join(v.get("authors", [])), "portada": "", "fuente": "Google Books"}
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- Completar
def achicar(datos: bytes, ext: str, alto: int = ALTO_PORTADA) -> tuple[bytes, str]:
    """Deja la imagen en JPG de hasta `alto` px de alto, como las demás portadas del sitio."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(datos)) as im:
        if im.height <= alto and ext == "jpg":
            return datos, ext
        im = im.convert("RGB")
        if im.height > alto:
            im = im.resize((round(im.width * alto / im.height), alto), Image.LANCZOS)
        salida = io.BytesIO()
        im.save(salida, "JPEG", quality=85, progressive=True, optimize=True)
        return salida.getvalue(), "jpg"


def guardar_portada(url: str, isbn: str, carpeta: Path, bajar_fn=bajar) -> str:
    """Baja la imagen a src/assets/portadas/<isbn>.jpg|png y devuelve la ruta pública, o "" si no sirve."""
    try:
        datos = bajar_fn(url)
    except Exception:
        return ""
    if not datos or len(datos) > MAX_PORTADA:
        return ""
    ext = "jpg" if datos[:3] == b"\xff\xd8\xff" else "png" if datos[:8] == b"\x89PNG\r\n\x1a\n" else ""
    if not ext:
        return ""
    try:
        datos, ext = achicar(datos, ext)
    except Exception:          # imagen dañada
        return ""
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{isbn}.{ext}").write_bytes(datos)
    return f"/assets/portadas/{isbn}.{ext}"


def cambios_para(d: dict, hallado: dict | None, portada_publica: str, hoy: str, portada_ar_: bool = False) -> dict:
    """Solo lo vacío: título en mayúsculas (como en la lista de precios), autor, portada y edición."""
    isbn = isbn13(d.get("isbn"))
    c = {}
    if hallado:
        if vacio(d, "titulo") and hallado.get("titulo"):
            c["titulo"] = hallado["titulo"].upper()
        if vacio(d, "autor") and hallado.get("autor"):
            c["autor"] = hallado["autor"]
    if vacio(d, "portada") and portada_publica:
        c["portada"] = portada_publica
    if vacio(d, "origen_editorial"):
        if hallado and hallado.get("fuente") == "Ciudad Nueva España":
            c["origen_editorial"] = "Ciudad Nueva España"
        elif isbn.startswith(PREFIJO_AR):
            c["origen_editorial"] = "Ciudad Nueva Argentina"
    fuentes = ([hallado["fuente"]] if hallado else []) + (["portada de Ciudad Nueva Argentina"] if portada_ar_ and "portada" in c else [])
    c["busqueda_isbn"] = f"{hoy} · {', '.join(fuentes) or 'sin resultado'}"
    return c


def completar(carpeta: Path, portadas: Path, bajar_fn=bajar, hoy: str | None = None,
              indice_ruta: Path | None = INDICE) -> list[tuple[Path, dict]]:
    hoy = hoy or dt.date.today().strftime("%d-%m-%Y")
    lista = pendientes(carpeta)
    if not lista:
        return []
    hallados: dict[str, dict] = {}
    # 1. España por buscador, para los que ya tienen título
    for _, d in lista:
        isbn = isbn13(d.get("isbn"))
        if not vacio(d, "titulo"):
            try:
                f = buscar_es_por_titulo(d["titulo"], isbn, bajar_fn)
            except Exception:
                f = None
            if f:
                hallados[isbn] = f
    # 2. España recorriendo las colecciones, para los ISBN españoles sin título (o no hallados por el buscador)
    sin_hallar = {isbn13(d.get("isbn")) for _, d in lista if isbn13(d.get("isbn")) not in hallados}
    espanoles = {i for i in sin_hallar if i.startswith("97884")}
    if espanoles:
        indice = leer_indice(indice_ruta) if indice_ruta else {}
        antes = dict(indice)
        try:
            hallados.update(recorrer_es(espanoles, bajar_fn, indice))
        except Exception:
            pass
        if indice_ruta and indice != antes:
            guardar_indice(indice_ruta, indice)
    resultado = []
    for md, d in lista:
        isbn = isbn13(d.get("isbn"))
        hallado = hallados.get(isbn)
        # 3. Open Library y Google Books
        if not hallado:
            hallado = buscar_abiertas(isbn, bajar_fn)
        portada, de_ar = "", False
        if vacio(d, "portada"):
            url = (hallado or {}).get("portada", "")
            titulo = (hallado or {}).get("titulo") or ("" if vacio(d, "titulo") else d["titulo"])
            if not url and titulo:
                url = portada_ar(titulo, bajar_fn)
                de_ar = bool(url)
            if url:
                portada = guardar_portada(url, isbn, portadas, bajar_fn)
        c = cambios_para(d, hallado, portada, hoy, de_ar)
        escribir_campos(md, c)
        resultado.append((md, c))
    return resultado


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--carpeta", default=RAIZ / "src" / "libros", type=Path)
    ap.add_argument("--portadas", default=RAIZ / "src" / "assets" / "portadas", type=Path)
    ap.add_argument("--solo-mostrar", action="store_true", help="dice qué libros buscaría, sin conectarse ni escribir")
    ap.add_argument("--actualizar-indice", action="store_true", help="lee las fichas nuevas de ciudadnueva.com y las agrega al índice")
    ap.add_argument("--sinopsis-todos", metavar="EDICION", nargs="?", const="",
                    help="carga inicial: sinopsis para todo el catálogo (o solo una edición: España, Argentina)")
    a = ap.parse_args(argv)
    if a.solo_mostrar:
        for md, d in pendientes(a.carpeta):
            print(f"{md.name}: falta {', '.join(faltantes(d))}")
        return 0
    if a.actualizar_indice:
        indice = leer_indice(INDICE)
        n = len(indice)
        recorrer_es(set(), indice=indice)
        guardar_indice(INDICE, indice)
        print(f"Índice: {len(indice)} fichas ({len(indice) - n} nuevas).")
        return 0
    if a.sinopsis_todos is not None:
        hechos = completar_sinopsis(a.carpeta, solo_nuevos=False, edicion=a.sinopsis_todos or None)
        print(f"Sinopsis: {sum(1 for _, f in hechos if f)} de {len(hechos)} libros buscados.")
        return 0
    for md, aviso in marcar_duplicados(a.carpeta):
        print(f"{md.name}: {aviso or 'ya no es duplicado'}")
    res = completar(a.carpeta, a.portadas)
    for md, fuente in completar_sinopsis(a.carpeta):
        print(f"{md.name}: sinopsis {'de ' + fuente if fuente else 'no encontrada'}")
    # Catálogo existente sin sinopsis: de a poco, para no cargar los sitios de Ciudad Nueva
    hechos = completar_sinopsis(a.carpeta, solo_nuevos=False, limite=SINOPSIS_POR_PASADA)
    if hechos:
        print(f"Sinopsis del catálogo: {sum(1 for _, f in hechos if f)} de {len(hechos)} buscadas en esta pasada.")
    for md, c in res:
        campos = [k for k in c if k != "busqueda_isbn"]
        print(f"{md.name}: {', '.join(campos) if campos else 'nada encontrado'} ({c['busqueda_isbn']})")
    if not res:
        print("Sin libros nuevos por completar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
