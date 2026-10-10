"""Qué hacer con cada título según su categoría de gestión (memoria, sección 4.2.5, Tabla 4.26).

La «decisión manual» del catálogo (Sveltia) siempre manda sobre estas reglas:

    AA Intermitente o Regular   Reponer             hasta el nivel objetivo S (Poisson al 95 %)
    AA Estacional               Temporada           un pedido anual que debe llegar antes de septiembre
    AA Coyuntural               No reponer          se atiende por reacción (aviso de cobertura baja)
    BB                          Reponer lo vendido  lo vendido desde el embarque anterior, sin stock de seguridad
    CC y DD                     No reponer          solo se muestran con su valor (destino: secciones 5.2 y 5.3)
    Sin categoría               A pedido            no se mantiene stock

POR CONFIRMAR CON ANDRÉS:
- BB: cantidad = unidades vendidas desde la última importación del título (o desde el inicio de la ventana si no hay
  ninguna registrada), menos lo que ya viene en camino.
- Estacional: se pide entre junio y agosto, hasta la venta neta de la última temporada completa (septiembre a marzo).
"""
from __future__ import annotations

import pandas as pd

POLITICAS = ("Reponer", "Reponer lo vendido", "Temporada", "No reponer", "A pedido")
MESES_PEDIDO_TEMPORADA = (6, 7, 8)     # para que llegue antes de septiembre
MESES_TEMPORADA = (9, 10, 11, 12, 1, 2, 3)


def decidir(categoria: str, clase: str, manual: str = "") -> str:
    manual = (manual or "").strip()
    if manual and manual.lower() != "auto":
        for p in POLITICAS:
            if p.lower() == manual.lower():
                return p
    if categoria == "AA":
        if clase == "Estacional":
            return "Temporada"
        if clase == "Coyuntural":
            return "No reponer"
        return "Reponer"
    if categoria == "BB":
        return "Reponer lo vendido"
    if categoria in ("CC", "DD"):
        return "No reponer"
    return "A pedido"


def reponer_lo_vendido(vendido_desde_importacion: float, en_camino: float) -> int:
    """BB: lo vendido desde el embarque anterior, menos lo que ya viene en camino."""
    return int(max(0, round(vendido_desde_importacion - en_camino)))


def ultima_temporada(fecha_corte: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Inicio y fin de la última temporada completa (septiembre a marzo) antes de la fecha de corte."""
    anio = fecha_corte.year if fecha_corte.month >= 4 else fecha_corte.year - 1
    return pd.Timestamp(anio - 1, 9, 1), pd.Timestamp(anio, 3, 31, 23, 59)


def es_mes_de_pedido_temporada(fecha_corte: pd.Timestamp) -> bool:
    return fecha_corte.month in MESES_PEDIDO_TEMPORADA
