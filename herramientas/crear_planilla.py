"""Prepara la Google Sheet del inventario: Roberto edita solo «Movimientos»; el resto lo escribe el cálculo.

Uso (en tu computador, con el archivo de credenciales de la cuenta de servicio):
    export GOOGLE_CREDENCIALES_ARCHIVO=~/credenciales-inventario.json
    python herramientas/crear_planilla.py --planilla ID                 # estructura vacía
    python herramientas/crear_planilla.py --planilla ID --con-ejemplo   # con los movimientos de ejemplo
    python herramientas/crear_planilla.py --planilla ID --con-ejemplo --reemplazar   # rehace todo

Sin --reemplazar no toca «Movimientos» ni «Configuración» si ya tienen datos.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from inventario.fuentes import COLUMNAS, SEPARADOR_LIBRO, FuenteSheets, catalogo_desde_sitio  # noqa: E402
from inventario.lenguaje import ENCABEZADOS, TIPOS_LEGIBLES  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
# Pestañas de versiones anteriores de la planilla que ya no se usan
ANTIGUAS = ["Catalogo", "Catálogo", "EnTransito", "En tránsito", "Costos", "Resultado_Titulos", "Resultado_Pedido", "Resumen", "Hoja 1", "Sheet1"]

NOTAS_MOVIMIENTOS = {
    "fecha": "Día del movimiento. Ej.: 21-08-2026.",
    "id": "Elige el libro de la lista (puedes escribir parte del título o el código para buscarlo).",
    "tipo": ("Venta (factura): se vendió y salió de bodega.\n"
             "Salida en consignación (guía): salió de bodega pero aún no se factura.\n"
             "Factura de consignación: se facturó algo que estaba en consignación (no mueve la bodega).\n"
             "Devuelto de consignación: volvió a bodega.\n"
             "Pedido hecho (viene en camino): se pidió a la editorial.\n"
             "Llegada de importación: llegó a bodega.\n"
             "Devolución de un cliente, Conteo inicial, Ajuste de conteo (+ o −)."),
    "cantidad": "Número de ejemplares, siempre positivo. Solo en «Ajuste de conteo» puede ser negativo.",
    "documento": "Folio de la factura, guía o importación (opcional, sirve para rastrear).",
    "cliente": "Opcional.",
}
TIPOS = TIPOS_LEGIBLES


def movimientos_ejemplo(catalogo: pd.DataFrame) -> pd.DataFrame:
    mov = pd.read_csv(RAIZ / "datos_ejemplo" / "Movimientos.csv", dtype=str, keep_default_na=False)
    tr = pd.read_csv(RAIZ / "datos_ejemplo" / "EnTransito.csv", dtype=str, keep_default_na=False)
    corte = pd.to_datetime(mov["fecha"]).max()
    pedidos = pd.DataFrame({"fecha": (corte - pd.Timedelta(days=3)).date().isoformat(), "id": tr["id"],
                            "tipo": "pedido_en_camino", "cantidad": tr["cantidad"], "documento": "PEDIDO", "cliente": ""})
    mov = pd.concat([mov, pedidos]).sort_values(["fecha", "id"])
    nombres = dict(zip(catalogo["id"], catalogo["id"] + SEPARADOR_LIBRO + catalogo["titulo"]))
    mov["id"] = mov["id"].map(nombres).fillna(mov["id"])
    mov["tipo"] = mov["tipo"].map(TIPOS).fillna(mov["tipo"])
    # Fechas como las escribiría Roberto
    mov["fecha"] = pd.to_datetime(mov["fecha"]).dt.strftime("%d-%m-%Y")
    return mov


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--planilla", required=True)
    ap.add_argument("--con-ejemplo", action="store_true", help="carga los movimientos y costos de datos_ejemplo/")
    ap.add_argument("--reemplazar", action="store_true", help="rehace Movimientos y Configuración y borra pestañas antiguas")
    a = ap.parse_args()

    f = FuenteSheets(a.planilla)
    libro = f.libro
    catalogo = catalogo_desde_sitio(RAIZ / "src" / "libros")

    # Lista de libros (oculta) para el desplegable de «Código»
    lista = (catalogo["id"] + SEPARADOR_LIBRO + catalogo["titulo"]).sort_values()
    f.escribir("Lista de libros", pd.DataFrame({"Libro": lista}), oculta=True, solo_lectura=True)

    # Movimientos: la única pestaña que edita Roberto
    hoja = f.hoja("Movimientos")
    con_datos = hoja is not None and len(hoja.get_all_values()) > 1
    if con_datos and not a.reemplazar:
        print("  Movimientos: ya tiene datos, se deja como está")
    else:
        mov = movimientos_ejemplo(catalogo) if a.con_ejemplo else pd.DataFrame(columns=COLUMNAS["Movimientos"])
        mov = mov[COLUMNAS["Movimientos"]].rename(columns=ENCABEZADOS["Movimientos"])
        f.escribir("Movimientos", mov, anchos={0: 100, 1: 380, 2: 230, 3: 80, 4: 110, 5: 140})
        print(f"  Movimientos: lista ({len(mov)} filas)")

    # Configuración (oculta): costos por origen, los define Andrés una vez
    hoja_cfg = f.hoja("Costos")
    if hoja_cfg is None or a.reemplazar or len(hoja_cfg.get_all_values()) <= 1:
        cfg = pd.read_csv(RAIZ / "datos_ejemplo" / "Costos.csv") if a.con_ejemplo else pd.DataFrame(
            [{"origen": o, "fob_sobre_precio_neto": "", "costo_sobre_precio_neto": "", "tipo_cambio": ""} for o in ("España", "Argentina")])
        f.escribir("Costos", cfg.rename(columns=ENCABEZADOS["Costos"]), oculta=True, anchos={0: 110, 1: 150, 2: 210, 3: 130})
        print("  Configuración: lista (oculta)")

    # Listas desplegables y notas de ayuda en «Movimientos»
    hoja = f.hoja("Movimientos")
    lista_id = f.hoja("Lista de libros").id
    col = {c: i for i, c in enumerate(COLUMNAS["Movimientos"])}
    pedidos = [
        {"setDataValidation": {"range": {"sheetId": hoja.id, "startRowIndex": 1, "startColumnIndex": col["id"], "endColumnIndex": col["id"] + 1},
                               "rule": {"condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "='Lista de libros'!A2:A"}]},
                                        "strict": True, "showCustomUi": True}}},
        {"setDataValidation": {"range": {"sheetId": hoja.id, "startRowIndex": 1, "startColumnIndex": col["tipo"], "endColumnIndex": col["tipo"] + 1},
                               "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in TIPOS.values()]},
                                        "strict": True, "showCustomUi": True}}},
        {"setDataValidation": {"range": {"sheetId": hoja.id, "startRowIndex": 1, "startColumnIndex": col["fecha"], "endColumnIndex": col["fecha"] + 1},
                               "rule": {"condition": {"type": "DATE_IS_VALID"}, "strict": True}}},
        {"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": 1, "startColumnIndex": col["fecha"], "endColumnIndex": col["fecha"] + 1},
                        "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd-mm-yyyy"}}},
                        "fields": "userEnteredFormat.numberFormat"}},
    ]
    for c, texto in NOTAS_MOVIMIENTOS.items():
        pedidos.append({"updateCells": {"range": {"sheetId": hoja.id, "startRowIndex": 0, "endRowIndex": 1,
                                                  "startColumnIndex": col[c], "endColumnIndex": col[c] + 1},
                                        "rows": [{"values": [{"note": texto}]}], "fields": "note"}})
    libro.batch_update({"requests": pedidos})

    if a.reemplazar:
        vigentes = {h.title for h in libro.worksheets()}
        for nombre in ANTIGUAS:
            if nombre in vigentes and nombre not in ("Configuración",) and len(libro.worksheets()) > 1:
                libro.del_worksheet(libro.worksheet(nombre))
                print(f"  {nombre}: eliminada (versión anterior)")
    print(f"Planilla «{libro.title}» preparada. Ahora corre: python -m inventario --fuente sheets --planilla {a.planilla}")


if __name__ == "__main__":
    main()
