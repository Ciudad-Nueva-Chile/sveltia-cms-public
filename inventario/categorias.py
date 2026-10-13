"""Categorías de gestión A, B, C y D de la memoria (sección 4.2.5, Tabla 4.24).

Adaptan las categorías AA, BB, CC y DD de Flores y Whybark (1987). Como la criticidad no puede evaluarse título por
título con el registro disponible, la memoria usa la recurrencia de la demanda y la salida de bodega:

    A   clase Intermitente, Regular, Estacional o Coyuntural
    B   clase Esporádica (venta neta en uno o dos meses de la ventana)
    C   con existencias, sin venta neta y con salida en guía de despacho en la ventana
    D   con existencias, sin venta neta ni salida en guía
    Sin categoría   sin existencias y sin demanda (se exhibe igual en el sitio)

Prioridad: primero la demanda (A y B), después C y D. La categoría se recalcula en cada ejecución con los últimos 21
meses: no hay una revisión aparte.
"""
from __future__ import annotations

import pandas as pd

IVA = 0.19
SIN_CATEGORIA = "Sin categoría"
ORDEN = ("A", "B", "C", "D", SIN_CATEGORIA)
DESCRIPCION = {
    "A": "Demanda recurrente o previsible",
    "B": "Venta ocasional (uno o dos meses)",
    "C": "Salió en guía sin facturar",
    "D": "Sin venta ni salida en guía",
    SIN_CATEGORIA: "Sin existencias y sin demanda",
}


def categoria(clase: str, bodega: float, salida_guia: bool) -> str:
    if clase in ("Intermitente", "Regular", "Estacional", "Coyuntural"):
        return "A"
    if clase == "Esporádica":
        return "B"
    if bodega > 0:
        return "C" if salida_guia else "D"
    return SIN_CATEGORIA


def resumen_categorias(t: pd.DataFrame) -> pd.DataFrame:
    """Por categoría: títulos, títulos con existencias, ejemplares, valor a precio de venta y % del valor
    (estructura de la Tabla 4.24 de la memoria)."""
    t = t.assign(_bodega=t["bodega"].clip(lower=0))
    t = t.assign(_valor=t["_bodega"] * t["precio_lista"])
    total = float(t["_valor"].sum()) or 1.0
    filas = []
    for c in ORDEN:
        g = t[t["categoria_gestion"] == c]
        filas.append({"categoria": c, "criterio": DESCRIPCION[c], "titulos": int(len(g)),
                      "con_existencias": int((g["_bodega"] > 0).sum()), "ejemplares": int(g["_bodega"].sum()),
                      "valor_pvp": int(g["_valor"].sum()), "pct_valor": round(float(g["_valor"].sum()) / total, 4)})
    filas.append({"categoria": "Total", "criterio": "", "titulos": int(len(t)), "con_existencias": int((t["_bodega"] > 0).sum()),
                  "ejemplares": int(t["_bodega"].sum()), "valor_pvp": int(t["_valor"].sum()), "pct_valor": 1.0 if len(t) else 0.0})
    return pd.DataFrame(filas)
