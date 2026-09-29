"""Qué hacer con cada título: reponer, mantener un mínimo, dejar a pedido o liquidar.

Reglas (la columna politica_manual del catálogo siempre manda sobre ellas):
    Coyuntural (marcada a mano)          No reponer: fenómeno puntual, se decide caso a caso
    Estacional (marcada a mano)          Temporada: un pedido antes de la temporada
    Regular o Intermitente, ABC A o B    Reponer hasta el stock objetivo
    Regular o Intermitente, ABC C        Stock mínimo: mantener un ejemplar
    Esporádica                           A pedido: no se mantiene stock
    Sin demanda, con stock y sin salidas
      en `meses_sin_movimiento`          Liquidar o revisar
    Sin demanda, resto                   A pedido
"""
from __future__ import annotations

import math

POLITICAS = ("Reponer", "Stock mínimo", "A pedido", "Temporada", "No reponer", "Liquidar o revisar")


def decidir(clase: str, abc: str, bodega: float, meses_sin_salida: float, meses_limite: int, manual: str = "") -> str:
    manual = (manual or "").strip()
    if manual and manual.lower() != "auto":
        for p in POLITICAS:
            if p.lower() == manual.lower():
                return p
    if clase == "Coyuntural":
        return "No reponer"
    if clase == "Estacional":
        return "Temporada"
    if clase in ("Regular", "Intermitente"):
        return "Reponer" if abc in ("A", "B") else "Stock mínimo"
    if clase == "Sin demanda" and bodega > 0 and (math.isnan(meses_sin_salida) or meses_sin_salida >= meses_limite):
        return "Liquidar o revisar"
    return "A pedido"


def objetivo(politica: str, pronostico_mensual: float, horizonte_meses: float, cuantil: float) -> int:
    """Stock objetivo (nivel hasta el que se repone)."""
    if politica == "Reponer":
        return int(math.ceil(max(cuantil, pronostico_mensual * horizonte_meses)))
    if politica == "Stock mínimo":
        return 1
    return 0
