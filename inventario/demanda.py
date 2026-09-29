"""Comportamiento de la demanda por título: serie mensual, patrón, clase y pronóstico.

Patrón (Syntetos, Boylan y Croston, 2005), con ADI = intervalo medio entre meses con demanda y
CV² = coeficiente de variación al cuadrado del tamaño de la demanda cuando la hay:
    Suave        ADI < 1,32 y CV² < 0,49
    Errática     ADI < 1,32 y CV² ≥ 0,49
    Intermitente ADI ≥ 1,32 y CV² < 0,49
    Grumosa      ADI ≥ 1,32 y CV² ≥ 0,49
    Puntual      menos de dos meses con demanda: no hay base para estimar ADI ni CV²
    Sin demanda  ningún mes con demanda en la ventana

Pronóstico: SBA (Croston con corrección de sesgo) para demanda intermitente o grumosa, suavizamiento
exponencial simple para demanda suave o errática, y promedio de la ventana para demanda puntual.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .stock import TIPOS_DEMANDA

CLASE_POR_PATRON = {
    "Suave": "Regular",
    "Errática": "Regular",
    "Intermitente": "Intermitente",
    "Grumosa": "Intermitente",
    "Puntual": "Esporádica",
    "Sin demanda": "Sin demanda",
}


def meses_ventana(fecha_corte: pd.Timestamp, meses: int) -> pd.PeriodIndex:
    fin = fecha_corte.to_period("M")
    return pd.period_range(end=fin, periods=meses, freq="M")


def series_mensuales(mov: pd.DataFrame, ids: list[str], fecha_corte: pd.Timestamp, meses: int, tipos: dict) -> pd.DataFrame:
    """Matriz títulos × meses con la suma de los movimientos de los tipos dados (con su signo)."""
    periodos = meses_ventana(fecha_corte, meses)
    m = mov[mov["tipo"].isin(tipos) & (mov["fecha"] <= fecha_corte)].copy()
    m["mes"] = m["fecha"].dt.to_period("M")
    m = m[m["mes"] >= periodos[0]]
    m["unidades"] = m["cantidad"] * m["tipo"].map(tipos)
    tabla = m.pivot_table(index="id", columns="mes", values="unidades", aggfunc="sum", fill_value=0)
    return tabla.reindex(index=ids, columns=periodos, fill_value=0).fillna(0)


def demanda_mensual(mov, ids, fecha_corte, meses) -> pd.DataFrame:
    """Salida física neta por mes. Un mes con más devoluciones que salidas cuenta como cero."""
    return series_mensuales(mov, ids, fecha_corte, meses, TIPOS_DEMANDA).clip(lower=0)


def clasificar(serie: np.ndarray, corte_adi: float = 1.32, corte_cv2: float = 0.49) -> tuple[str, float, float]:
    """Devuelve (patrón, ADI, CV²). ADI y CV² son NaN cuando no se pueden calcular."""
    positivos = serie[serie > 0]
    if len(positivos) == 0:
        return "Sin demanda", math.nan, math.nan
    if len(positivos) < 2:
        return "Puntual", math.nan, math.nan
    adi = len(serie) / len(positivos)
    media = positivos.mean()
    cv2 = float((positivos.std(ddof=0) / media) ** 2) if media > 0 else 0.0
    if adi < corte_adi:
        patron = "Suave" if cv2 < corte_cv2 else "Errática"
    else:
        patron = "Intermitente" if cv2 < corte_cv2 else "Grumosa"
    return patron, adi, cv2


def sba(serie: np.ndarray, alfa: float = 0.15) -> float:
    """Pronóstico mensual con el método de Syntetos y Boylan (Croston corregido)."""
    tamano = intervalo = None
    desde_ultima = 0
    for x in serie:
        desde_ultima += 1
        if x > 0:
            if tamano is None:
                tamano, intervalo = float(x), float(desde_ultima)
            else:
                tamano += alfa * (x - tamano)
                intervalo += alfa * (desde_ultima - intervalo)
            desde_ultima = 0
    if tamano is None:
        return 0.0
    return (1 - alfa / 2) * tamano / intervalo


def suavizamiento_simple(serie: np.ndarray, alfa: float = 0.15) -> float:
    if len(serie) == 0:
        return 0.0
    nivel = float(serie[: min(3, len(serie))].mean())
    for x in serie:
        nivel += alfa * (x - nivel)
    return nivel


def pronosticar(serie: np.ndarray, patron: str, alfa: float) -> float:
    if patron in ("Intermitente", "Grumosa"):
        return sba(serie, alfa)
    if patron in ("Suave", "Errática"):
        return suavizamiento_simple(serie, alfa)
    if patron == "Puntual":
        return float(serie.sum() / len(serie))
    return 0.0


def cuantil_proteccion(serie: np.ndarray, horizonte_meses: float, nivel: float, simulaciones: int, rng: np.random.Generator) -> float:
    """Demanda del periodo de protección que no se supera con probabilidad `nivel`.

    Se estima remuestreando meses observados (bootstrap), sin suponer una distribución: sirve para demanda
    intermitente, donde la aproximación normal no funciona. La fracción de mes se toma proporcional.
    """
    if len(serie) == 0 or serie.sum() == 0:
        return 0.0
    enteros = int(horizonte_meses)
    fraccion = horizonte_meses - enteros
    muestras = rng.choice(serie, size=(simulaciones, enteros + 1), replace=True)
    totales = muestras[:, :enteros].sum(axis=1) + fraccion * muestras[:, enteros]
    return float(np.quantile(totales, nivel))
