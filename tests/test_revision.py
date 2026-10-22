"""Revisión de la planilla (inventario/revision.py): filas incompletas, incongruentes o repetidas."""
import pandas as pd

from inventario import revision
from inventario.fuentes import _normalizar

HOY = pd.Timestamp("2026-10-22")
CAT = pd.DataFrame({"id": ["CN-0001", "CN-0002"]})


def tabla(nombre, filas, columnas):
    return _normalizar(nombre, pd.DataFrame(filas, columns=columnas))


def test_ventas_incompletas_desconocidas_futuras_y_repetidas():
    v = tabla("Ventas", [
        ["05-10-2026", "B-1", "CN-0001 · UNO", "2", "", "", "", "", ""],      # bien
        ["05-10-2026", "B-1", "CN-0001 · UNO", "2", "", "", "", "", ""],      # repetida
        ["", "B-2", "CN-0002 · DOS", "", "", "", "", "", ""],                 # sin fecha ni cantidad
        ["05-12-2026", "B-3", "CN-9999 · X", "1", "120", "", "", "", ""],     # futura, libro y descuento malos
        ["", "", "", "", "", "", "", "", ""],                                 # vacía: no se reclama
    ], ["Fecha", "Pedido o boleta", "Libro", "Cantidad", "Descuento (%)", "Canal", "Estado", "Notas", "Descontado del stock"])
    a = revision.ventas(v, set(CAT["id"]), HOY)
    assert "Ventas, fila 4: falta la fecha, la cantidad (no se cuenta hasta completarla)" in a, a
    assert "Ventas, fila 5: el libro «CN-9999» no está en el catálogo" in a
    assert any("fila 5: la fecha 05-12-2026 es futura" in x for x in a)
    assert any("fila 5: descuento de 120 %" in x for x in a)
    assert any("filas 2, 3: venta repetida" in x for x in a)
    assert not any("fila 6" in x for x in a)


def test_importaciones_fechas_al_reves_pais_y_doble_moneda():
    i = tabla("Importaciones", [
        ["10-06-2026", "01-06-2026", "Uruguay", "F-1", "CN-0001 · UNO", "3", "10", "8", "", "", ""],
        ["", "", "", "", "CN-0002 · DOS", "", "", "", "", "", ""],
    ], ["Fecha de pedido", "Fecha de llegada", "País de compra", "N° de factura o DIN", "Libro", "Cantidad",
        "FOB total US$", "FOB total €", "Gastos de internación $", "Notas", "Sumado al stock"])
    a = revision.importaciones(i, set(CAT["id"]), HOY)
    assert any("fila 2: la llegada (01-06-2026) es anterior al pedido (10-06-2026)" in x for x in a)
    assert any("fila 2: país «Uruguay»" in x for x in a)
    assert any("fila 2: tiene FOB en US$ y en €" in x for x in a)
    assert any("fila 3: falta la cantidad, el país, la fecha de pedido o de llegada" in x for x in a)


def test_inventario_codigos_raros_negativos_y_repetidos():
    inv = tabla("Inventario", [
        ["CN-0001", "", "UNO", "", "", "", "", "", "", "5", "0", "0", "", "", "", ""],
        ["CN-0001", "", "UNO", "", "", "", "", "", "", "1", "0", "0", "", "", "", ""],
        ["'", "", "", "", "", "", "", "", "", "0", "0", "0", "", "", "", ""],
        ["CN-0777", "", "VIEJO", "", "", "", "", "", "", "-2", "0", "0", "", "", "", ""],
    ], ["Código", "ISBN", "Título", "Autor", "Editorial", "Se compra en", "Categoría", "Categoría de gestión",
        "Precio de venta", "En bodega", "En consignación", "Pedido en camino", "Última actualización", "Se vende",
        "Qué hacer", "Notas"])
    a = revision.inventario(inv, set(CAT["id"]))
    assert any("filas 2, 3: el código CN-0001 está repetido" in x for x in a)
    assert any("fila 4: código vacío o inválido" in x for x in a)
    assert any("fila 5: «CN-0777» se eliminó del sitio pero tiene cantidades" in x for x in a)
    assert any("fila 5: «En bodega» negativo (-2)" in x for x in a)


def test_configuracion_faltante_y_fuera_de_rango():
    c = pd.DataFrame({"origen": ["España"], "edicion": [""], "fob_sobre_precio_neto": [""],
                      "costo_sobre_precio_neto": [25.1], "tipo_cambio": [""]})
    a = revision.configuracion(c, ["España", "Argentina"])
    assert "Configuración: falta la fila de Argentina (sin ella no se calculan sus costos)" in a
    assert any("falta «FOB / precio neto»" in x for x in a)
    assert any("= 25.1 parece fuera de rango" in x for x in a)
    assert any("falta «Pesos por dólar»" in x for x in a)
