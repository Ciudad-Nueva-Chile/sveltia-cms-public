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


def test_escribe_sobre_el_formato_de_sveltia(tmp_path):
    md = libro(tmp_path, "a.md", "---\ntitulo: SIN TÍTULO (ISBN\n  9788497155908)\nautor: ''\nisbn: '9788497155908'\n"
                                 "oculto: false\n---\n")
    cl.escribir_campos(md, {"titulo": "FRANCISCO Y EL SULTÁN", "autor": "Herrero"})
    assert cl.leer(md) == {"titulo": "FRANCISCO Y EL SULTÁN", "autor": "Herrero", "isbn": "9788497155908", "oculto": False}


def test_marca_y_desmarca_duplicados(tmp_path):
    a = libro(tmp_path, "a.md", '---\nid_catalogo: "CN-1"\nisbn: "9788497153188"\ntitulo: "REYES"\n---\n')
    b = libro(tmp_path, "b.md", "---\nisbn: '978-84-9715-318-8'\ntitulo: OTRO\n---\n")
    libro(tmp_path, "c.md", '---\nisbn: "9780140449136"\ntitulo: "SOLO"\n---\n')
    cl.marcar_duplicados(tmp_path)
    assert "mismo ISBN que b «OTRO»" in cl.leer(a)["aviso"] and "CN-1 «REYES»" in cl.leer(b)["aviso"]
    b.unlink()                                                  # se eliminó el duplicado: el aviso se borra solo
    cl.marcar_duplicados(tmp_path)
    assert "aviso" not in cl.leer(a)


def test_sinopsis_de_cada_edicion(tmp_path):
    ar = libro(tmp_path, "ar.md", '---\nisbn: "9789505863242"\ntitulo: "A LOS JOVENES EXHORTACION A UN HIJO... (BP. 83)"\n'
                                  'origen_editorial: "Ciudad Nueva Argentina"\n---\n')
    es = libro(tmp_path, "es.md", '---\nisbn: "9788497155908"\ntitulo: "FRANCISCO Y EL SULTÁN"\n'
                                  'origen_editorial: "Ciudad Nueva España"\n---\n')
    con = libro(tmp_path, "con.md", '---\nisbn: "9780140449136"\ntitulo: "X"\n---\nYa tenía sinopsis.\n')
    productos = [{"name": "A los jóvenes &#8211; Exhortación a un hijo espiritual [BPa, 83]",
                  "description": "<p>Basilio escribe a los <b>jóvenes</b>.</p><p>Segundo párrafo.</p>"}]
    ficha = FICHA.replace("<p><strong>ISBN", '<span style="x">Sinopsis</span><br/><p>Un encuentro entre Francisco de Asís '
                                              'y el sultán en plena cruzada.</p><div id="subhistoria_articulo2"><span>Autor'
                                              '</span><p>Madrid, 1981. Escritora.</p></div><p><strong>ISBN')
    indice = tmp_path / "i.json"
    cl.guardar_indice(indice, {"https://www.ciudadnueva.com/libro/fys": "9788497155908"})
    bajar = web({"wc/store": json.dumps(productos), "ciudadnueva.com/libro/fys": ficha})
    hechos = cl.completar_sinopsis(tmp_path, bajar, hoy="22-10-2026", indice_ruta=indice, solo_nuevos=False)
    assert cl.cuerpo(ar).startswith("Basilio escribe a los") and cl.cuerpo(ar).endswith("\n\nSegundo párrafo.")
    assert cl.cuerpo(es) == "Un encuentro entre Francisco de Asís y el sultán en plena cruzada."      # sin la biografía
    assert cl.cuerpo(con) == "Ya tenía sinopsis."
    assert cl.leer(es)["busqueda_sinopsis"] == "22-10-2026 · Ciudad Nueva España"
    assert len(hechos) == 2


def test_si_el_sitio_espanol_no_responde_no_marca_ni_insiste(tmp_path):
    for n in range(3):
        libro(tmp_path, f"es{n}.md", f'---\nisbn: "978849715590{n}"\ntitulo: "T{n}"\norigen_editorial: "Ciudad Nueva España"\n---\n')
    indice = tmp_path / "i.json"
    cl.guardar_indice(indice, {f"https://www.ciudadnueva.com/libro/x{n}": cl.isbn13(f"978849715590{n}") for n in range(3)})
    pedidos = []

    def caido(url):
        pedidos.append(url)
        raise OSError("sin respuesta")
    hechos = cl.completar_sinopsis(tmp_path, caido, hoy="22-10-2026", indice_ruta=indice, solo_nuevos=False)
    assert hechos == [] and len(pedidos) == 1                  # una sola consulta fallida; nada marcado
    assert all("busqueda_sinopsis" not in cl.leer(m) for m in tmp_path.glob("es*.md"))
