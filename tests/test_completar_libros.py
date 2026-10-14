"""Completar por ISBN los libros nuevos (herramientas/completar_libros.py), sin conectarse: las páginas son de mentira."""
import io
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "herramientas"))
import completar_libros as cl  # noqa: E402


def jpg(alto=1500):
    b = io.BytesIO()
    Image.new("RGB", (alto * 2 // 3, alto), "red").save(b, "JPEG")
    return b.getvalue()


FICHA = """<meta property="og:title" content="Francisco y el sultán" />
<meta property="og:image" content="https://www.ciudadnueva.com/imagenes/libros/fys.jpg" />
<a href="/autor/herrero" style="x">Herrero, Mardia </a>
<p><strong>ISBN:</strong>&nbsp;&nbsp;978-84-9715-590-8</p>"""


def web(paginas):
    """bajar() de mentira: devuelve la página cuyo trozo de dirección aparece en la URL."""
    def bajar(url):
        for trozo, contenido in paginas.items():
            if trozo in url:
                return contenido if isinstance(contenido, bytes) else contenido.encode()
        raise OSError("sin conexión: " + url)
    return bajar


def libro(carpeta, nombre, texto):
    (carpeta / nombre).write_text(texto, encoding="utf-8")
    return carpeta / nombre


def test_isbn10_a_13_y_normalizar():
    assert cl.isbn13("0140449132") == "9780140449136"
    assert cl.isbn13("123") == ""
    assert cl.normalizar("  Exhortación – a un HIJO ") == "exhortacion a un hijo"


def test_ficha_espanola():
    f = cl.ficha_es(FICHA, "u")
    assert f["isbn"] == "9788497155908" and f["titulo"] == "Francisco y el sultán"
    assert f["autor"] == "Herrero, Mardia" and f["portada"].endswith("fys.jpg")


def test_solo_libros_nuevos_sin_buscar(tmp_path):
    libro(tmp_path, "viejo.md", '---\nid_catalogo: "CN-0001"\nisbn: "9788497150033"\ntitulo: ""\n---\n')
    libro(tmp_path, "buscado.md", '---\nisbn: "9788497150033"\ntitulo: ""\nbusqueda_isbn: "01-10-2026 · sin resultado"\n---\n')
    libro(tmp_path, "sin_isbn.md", '---\nisbn: ""\ntitulo: ""\n---\n')
    libro(tmp_path, "completo.md", '---\nisbn: "9788497150033"\ntitulo: "X"\nautor: "Y"\nportada: "/a.jpg"\n'
                                    'origen_editorial: "Otra"\n---\n')
    libro(tmp_path, "nuevo.md", '---\nisbn: "9788497150033"\ntitulo: "SIN TÍTULO (ISBN 9788497150033)"\n---\n')
    assert [p.name for p, _ in cl.pendientes(tmp_path)] == ["nuevo.md"]


def test_completa_desde_espana_por_titulo_sin_pisar_nada(tmp_path):
    md = libro(tmp_path, "9788497155908.md", '---\nisbn: "9788497155908"\ntitulo: "FRANCISCO Y EL SULTÁN"\n'
                                             'autor: ""\nprecio_iva: 10000\n---\nSinopsis.\n')
    bajar = web({"libros_encontrados/francisco+y+el+sultan": 'href="https://www.ciudadnueva.com/libro/fys"',
                 "ciudadnueva.com/libro/fys": FICHA, "fys.jpg": jpg()})
    cl.completar(tmp_path, tmp_path / "portadas", bajar, hoy="13-10-2026", indice_ruta=tmp_path / "i.json")
    d = cl.leer(md)
    assert d["titulo"] == "FRANCISCO Y EL SULTÁN" and d["autor"] == "Herrero, Mardia" and d["precio_iva"] == 10000
    assert d["portada"] == "/assets/portadas/9788497155908.jpg" and d["origen_editorial"] == "Ciudad Nueva España"
    assert d["busqueda_isbn"] == "13-10-2026 · Ciudad Nueva España"
    assert md.read_text(encoding="utf-8").endswith("---\nSinopsis.\n")
    with Image.open(tmp_path / "portadas" / "9788497155908.jpg") as im:
        assert im.height == 1000                       # achicada como las demás portadas


def test_sin_titulo_busca_en_las_fichas_y_guarda_el_indice(tmp_path):
    md = libro(tmp_path, "a.md", '---\nisbn: "9788497155908"\ntitulo: "SIN TÍTULO (ISBN 9788497155908)"\n---\n')
    bajar = web({"coleccion/una/2": "nada", "coleccion/una": 'href="https://www.ciudadnueva.com/libro/fys"',
                 "ciudadnueva.com/libro/fys": FICHA, "fys.jpg": jpg(800),
                 "ciudadnueva.com/": 'href="https://www.ciudadnueva.com/coleccion/una"'})
    indice = tmp_path / "indice.json"
    cl.completar(tmp_path, tmp_path / "p", bajar, hoy="13-10-2026", indice_ruta=indice)
    assert cl.leer(md)["titulo"] == "FRANCISCO Y EL SULTÁN"
    assert cl.leer_indice(indice) == {"https://www.ciudadnueva.com/libro/fys": "9788497155908"}

    # Con el índice, un segundo libro con el mismo ISBN se encuentra sin recorrer las colecciones
    md2 = libro(tmp_path, "b.md", '---\nisbn: "9788497155908"\ntitulo: ""\n---\n')
    solo_ficha = web({"ciudadnueva.com/libro/fys": FICHA, "fys.jpg": jpg(800)})
    cl.completar(tmp_path, tmp_path / "p", solo_ficha, hoy="13-10-2026", indice_ruta=indice)
    assert cl.leer(md2)["autor"] == "Herrero, Mardia"


def test_portada_argentina_por_titulo_recortado(tmp_path):
    md = libro(tmp_path, "a.md", '---\nisbn: "9789505863242"\ntitulo: "A LOS JOVENES EXHORTACION A UN HIJO... (BP. 83)"\n'
                                 'autor: "San Basilio"\n---\n')
    productos = [{"name": "A los jóvenes &#8211; Exhortación a un hijo espiritual [BPa, 83]",
                  "images": [{"src": "https://ar/jov.jpg"}]},
                 {"name": "Otro libro", "images": [{"src": "https://ar/otro.jpg"}]}]
    bajar = web({"wc/store": json.dumps(productos), "ar/jov.jpg": jpg(300), "openlibrary": "{}", "googleapis": "{}"})
    cl.completar(tmp_path, tmp_path / "p", bajar, hoy="13-10-2026", indice_ruta=None)
    d = cl.leer(md)
    assert d["portada"] == "/assets/portadas/9789505863242.jpg" and d["origen_editorial"] == "Ciudad Nueva Argentina"
    assert d["busqueda_isbn"] == "13-10-2026 · portada de Ciudad Nueva Argentina"


def test_otro_numero_de_coleccion_no_es_el_mismo_libro():
    assert cl.mismo_libro("CONSTITUCIONES APOSTOLICAS (BP. 82)", "Constituciones apostólicas [BPa, 82]")
    assert not cl.mismo_libro("CONSTITUCIONES APOSTOLICAS (BP. 82)", "Constituciones apostólicas [BPa, 83]")
    assert not cl.mismo_libro("LA FE", "La fe que mueve montañas")


def test_open_library_y_marca_si_no_hay_nada(tmp_path):
    a = libro(tmp_path, "a.md", '---\nisbn: "9780140449136"\ntitulo: ""\n---\n')
    ol = {"ISBN:9780140449136": {"title": "Crime and punishment", "authors": [{"name": "Dostoievski"}]}}
    cl.completar(tmp_path, tmp_path / "p", web({"openlibrary": json.dumps(ol), "wc/store": "[]"}), hoy="13-10-2026", indice_ruta=None)
    assert cl.leer(a)["titulo"] == "CRIME AND PUNISHMENT" and cl.leer(a)["autor"] == "Dostoievski"

    b = libro(tmp_path, "b.md", '---\nisbn: "9780000000002"\ntitulo: "SIN TÍTULO (ISBN 9780000000002)"\n---\n')
    cl.completar(tmp_path, tmp_path / "p", web({}), hoy="13-10-2026", indice_ruta=None)     # sin conexión: no falla
    d = cl.leer(b)
    assert d["titulo"].startswith("SIN TÍTULO") and d["busqueda_isbn"] == "13-10-2026 · sin resultado"
    assert cl.pendientes(tmp_path) == []                                  # no se vuelve a buscar
