"""Clasificación ABC por valor de la venta facturada en la ventana.

A: títulos que, ordenados de mayor a menor valor, suman hasta el corte A (80 %) del valor total.
B: los siguientes hasta el corte B (95 %). C: el resto, incluidos los que no vendieron.
"""
from __future__ import annotations

import pandas as pd

IVA = 0.19


def clasificar_abc(unidades_vendidas: pd.Series, precio_lista: pd.Series, corte_a: float, corte_b: float) -> pd.DataFrame:
    """unidades_vendidas y precio_lista indexadas por id. Devuelve valor, participación acumulada y clase."""
    valor = (unidades_vendidas.clip(lower=0) * precio_lista / (1 + IVA)).fillna(0)
    df = pd.DataFrame({"valor_venta": valor}).sort_values("valor_venta", ascending=False, kind="stable")
    total = df["valor_venta"].sum()
    if total <= 0:
        df["participacion_acumulada"] = 0.0
        df["abc"] = "C"
        return df
    acumulado_previo = df["valor_venta"].cumsum().shift(fill_value=0) / total
    df["participacion_acumulada"] = df["valor_venta"].cumsum() / total
    # Un título entra a A si lo acumulado antes de él todavía no alcanza el corte
    df["abc"] = "C"
    df.loc[acumulado_previo < corte_b, "abc"] = "B"
    df.loc[acumulado_previo < corte_a, "abc"] = "A"
    df.loc[df["valor_venta"] <= 0, "abc"] = "C"
    return df
