"""Prepara una Google Sheet vacía para el inventario: pestañas, encabezados, listas desplegables y notas.

Uso (en tu computador, con el archivo de credenciales de la cuenta de servicio):
    export GOOGLE_CREDENCIALES_ARCHIVO=~/credenciales-inventario.json
    python herramientas/crear_planilla.py --planilla ID_DE_LA_PLANILLA              # solo la estructura
    python herramientas/crear_planilla.py --planilla ID_DE_LA_PLANILLA --con-ejemplo # y los datos de ejemplo

No borra pestañas que ya tengan datos, salvo que se use --reemplazar.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from inventario.fuentes import COLUMNAS, FuenteSheets  # noqa: E402
from inventario.stock import EFECTOS  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent

NOTAS = {
    "Catalogo": {
        "id": "Código único del título (el mismo del catálogo, p. ej. CN-0016).",
        "origen": "España o Argentina: debe coincidir con los orígenes de los parámetros.",
        "precio_lista": "Precio de venta al público con IVA, en pesos.",
        "clase_manual": "Opcional. Estacional (calendarios, agendas) o Coyuntural (fenómenos puntuales). Vacío = automática.",
        "politica_manual": "Opcional. Reponer, Stock mínimo, A pedido, Temporada, No reponer o Liquidar o revisar. Vacío = automática.",
    },
    "Movimientos": {
        "fecha": "Día del movimiento: 21-08-2026 o 2026-08-21.",
        "tipo": "Elegir de la lista. La cantidad siempre positiva; el tipo decide si entra o sale.",
        "cantidad": "Ejemplares. Solo «ajuste» admite negativos (diferencias de conteo).",
        "documento": "Folio de factura, guía o importación, para poder rastrearlo.",
    },
    "EnTransito": {"fecha_estimada": "Cuándo se espera que llegue a bodega."},
    "Costos": {
        "fob_sobre_precio_neto": "Valor FOB de un ejemplar dividido por su precio neto chileno (sin IVA).",
        "costo_sobre_precio_neto": "Costo puesto en bodega dividido por el precio neto chileno.",
        "tipo_cambio": "Pesos por dólar.",
    },
}

DESPLEGABLES = {
    ("Movimientos", "tipo"): sorted(EFECTOS),
    ("Catalogo", "clase_manual"): ["", "Estacional", "Coyuntural"],
    ("Catalogo", "politica_manual"): ["", "Reponer", "Stock mínimo", "A pedido", "Temporada", "No reponer", "Liquidar o revisar"],
}


def validacion(hoja_id: int, col: int, valores: list[str]) -> dict:
    return {"setDataValidation": {
        "range": {"sheetId": hoja_id, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
        "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in valores if v]},
                 "strict": True, "showCustomUi": True},
    }}


def nota(hoja_id: int, col: int, texto: str) -> dict:
    return {"updateCells": {"range": {"sheetId": hoja_id, "startRowIndex": 0, "endRowIndex": 1,
                                      "startColumnIndex": col, "endColumnIndex": col + 1},
                            "rows": [{"values": [{"note": texto}]}], "fields": "note"}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--planilla", required=True)
    ap.add_argument("--con-ejemplo", action="store_true", help="carga los datos de datos_ejemplo/")
    ap.add_argument("--reemplazar", action="store_true", help="sobrescribe pestañas que ya tienen datos")
    a = ap.parse_args()

    f = FuenteSheets(a.planilla)
    libro = f.libro
    existentes = {h.title: h for h in libro.worksheets()}
    pedidos = []
    for nombre, columnas in COLUMNAS.items():
        hoja = existentes.get(nombre)
        con_datos = hoja is not None and len(hoja.get_all_values()) > 1
        if con_datos and not a.reemplazar:
            print(f"  {nombre}: ya tiene datos, se deja como está")
            continue
        if a.con_ejemplo and (RAIZ / "datos_ejemplo" / f"{nombre}.csv").exists():
            df = pd.read_csv(RAIZ / "datos_ejemplo" / f"{nombre}.csv", dtype=str, keep_default_na=False)
        else:
            df = pd.DataFrame(columns=columnas)
        f.escribir(nombre, df[columnas] if set(columnas) <= set(df.columns) else df)
        hoja = libro.worksheet(nombre)
        for col, texto in NOTAS.get(nombre, {}).items():
            pedidos.append(nota(hoja.id, columnas.index(col), texto))
        for (tabla, col), valores in DESPLEGABLES.items():
            if tabla == nombre:
                pedidos.append(validacion(hoja.id, columnas.index(col), valores))
        print(f"  {nombre}: lista ({len(df)} filas)")

    # La hoja inicial vacía que trae toda planilla nueva
    for nombre in ("Hoja 1", "Sheet1"):
        if nombre in existentes and len(libro.worksheets()) > 1 and len(existentes[nombre].get_all_values()) == 0:
            libro.del_worksheet(existentes[nombre])
    if pedidos:
        libro.batch_update({"requests": pedidos})
    print(f"Planilla «{libro.title}» preparada. Ahora corre: python -m inventario --fuente sheets --planilla {a.planilla}")


if __name__ == "__main__":
    main()
