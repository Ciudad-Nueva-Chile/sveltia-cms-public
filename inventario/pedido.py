"""Sugerencia de importación por origen.

1. Cada título con política Reponer o Stock mínimo pide lo que le falta para llegar a su stock objetivo,
   descontando lo que hay en bodega y en tránsito.
2. Si el pedido de un origen no alcanza el mínimo económico de embarque, se propone completarlo
   adelantando la demanda del próximo periodo de revisión de los títulos A y B de ese origen.
   Si aun así no alcanza, la sugerencia es acumular y se estima cuándo conviene pedir.
"""
from __future__ import annotations

import math

import pandas as pd

from .clasificacion_abc import IVA
from .config import Parametros, SEMANAS_POR_MES

DIAS_POR_MES = 30.44


def costo_usd(precio_lista: float, costos: pd.Series) -> float:
    """Valor FOB estimado de un ejemplar, en dólares."""
    fob = costos.get("fob_sobre_precio_neto")
    tc = costos.get("tipo_cambio")
    if not fob or not tc or pd.isna(fob) or pd.isna(tc):
        return math.nan
    return precio_lista / (1 + IVA) * fob / tc


def sugerir(titulos: pd.DataFrame, costos: pd.DataFrame, p: Parametros, fecha_corte: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (líneas del pedido, resumen por origen)."""
    costos = costos.set_index("origen") if len(costos) else pd.DataFrame()
    lineas, resumen = [], []
    revision_meses = p.revision_semanas / SEMANAS_POR_MES

    for origen, grupo in titulos.groupby("origen"):
        c = costos.loc[origen] if origen in costos.index else pd.Series(dtype=float)
        minimo = p.origen(origen).minimo_embarque_usd
        base = grupo[grupo["sugerido"] > 0]
        for fila in base.itertuples():
            u = costo_usd(fila.precio_lista, c)
            motivo = "Mantener un ejemplar (stock mínimo)" if fila.politica == "Stock mínimo" else "Bajo el stock objetivo"
            lineas.append({"origen": origen, "id": fila.id, "titulo": fila.titulo, "abc": fila.abc,
                           "cantidad": int(fila.sugerido), "motivo": motivo,
                           "costo_unitario_usd": round(u, 2) if not math.isnan(u) else "",
                           "subtotal_usd": round(u * fila.sugerido, 2) if not math.isnan(u) else ""})
        total = sum(l["subtotal_usd"] or 0 for l in lineas if l["origen"] == origen)

        # Completar el mínimo adelantando demanda de títulos A y B que ya se reponen
        if 0 < total < minimo:
            candidatos = grupo[(grupo["politica"] == "Reponer") & (grupo["pronostico_mensual"] > 0)]
            candidatos = candidatos.sort_values(["abc", "valor_venta"], ascending=[True, False])
            for fila in candidatos.itertuples():
                if total >= minimo:
                    break
                extra = int(math.ceil(fila.pronostico_mensual * revision_meses))
                u = costo_usd(fila.precio_lista, c)
                if extra <= 0 or math.isnan(u):
                    continue
                existente = next((l for l in lineas if l["origen"] == origen and l["id"] == fila.id), None)
                if existente:
                    existente["cantidad"] += extra
                    existente["motivo"] += " + adelanto para completar el mínimo"
                    existente["subtotal_usd"] = round(u * existente["cantidad"], 2)
                else:
                    lineas.append({"origen": origen, "id": fila.id, "titulo": fila.titulo, "abc": fila.abc,
                                   "cantidad": extra, "motivo": "Adelanto para completar el mínimo de embarque",
                                   "costo_unitario_usd": round(u, 2), "subtotal_usd": round(u * extra, 2)})
                total += u * extra

        # Cuándo conviene pedir: el primer título que cruce su punto de pedido
        reponer = grupo[(grupo["politica"] == "Reponer") & (grupo["pronostico_mensual"] > 0)]
        dias = ((reponer["posicion"] - reponer["punto_pedido"]) / reponer["pronostico_mensual"] * DIAS_POR_MES).clip(lower=0)
        dias_min = float(dias.min()) if len(dias) else math.nan

        if total >= minimo:
            estado, fecha = "Pedir ahora", fecha_corte
        elif total > 0:
            estado = "Acumular: no alcanza el mínimo"
            fecha = fecha_corte + pd.Timedelta(weeks=p.revision_semanas)
        elif not math.isnan(dias_min):
            estado = f"Sin pedido: el primer título llega a su punto de pedido en {int(dias_min)} días"
            fecha = fecha_corte + pd.Timedelta(days=dias_min)
        else:
            estado, fecha = "Sin pedido", None
        resumen.append({
            "origen": origen,
            "estado": estado,
            "titulos": sum(1 for l in lineas if l["origen"] == origen),
            "unidades": sum(l["cantidad"] for l in lineas if l["origen"] == origen),
            "total_usd": round(total, 2),
            "minimo_usd": minimo,
            "fecha_sugerida": fecha.date().isoformat() if fecha is not None else "",
            "costos_configurados": bool(len(c)),
        })
    columnas = ["origen", "id", "titulo", "abc", "cantidad", "motivo", "costo_unitario_usd", "subtotal_usd"]
    return pd.DataFrame(lineas, columns=columnas), pd.DataFrame(resumen)
