"""Demanda por título: serie mensual de venta neta, clase de demanda, pronóstico SBA y nivel objetivo.

Sigue la memoria del proyecto (Tabla 4.8 y sección 4.2.5).

Serie: venta neta por mes (venta + factura de consignación − devoluciones) más la venta perdida anotada en «Ventas».
La salida en guía no es venta: decide entre CC y DD (clasificacion_abc.py).

Clase, por k = meses de la ventana con venta neta positiva:
    k = 0       Sin venta neta
    k = 1 o 2   Esporádica      no hay serie suficiente: se decide, no se estima
    k ≥ 3       Intermitente    (Regular si además ADI < 1,32 y CV² < 0,49, con el mismo trato)
Estacional y Coyuntural se marcan a mano en el catálogo y mandan sobre lo calculado.

ADI y CV² (Syntetos, Boylan y Croston, 2005) quedan como indicadores informativos.

Pronóstico: SBA (Croston corregido por Syntetos y Boylan), solo para Intermitente y Regular.
Nivel objetivo: percentil `nivel_servicio` de una Poisson con media λ × (T + L).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import poisson

from .stock import TIPOS_VENTA_NETA

CLASES_CON_TASA = ("Intermitente", "Regular")
CLASES_MANUALES = ("Estacional", "Coyuntural")
CLASES = ("Regular", "Intermitente", "Esporádica", "Estacional", "Coyuntural", "Sin venta neta")


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


def venta_neta_mensual(mov, ids, fecha_corte, meses) -> pd.DataFrame:
    """Venta neta (con la venta perdida) por mes. Un mes con más devoluciones que ventas cuenta como cero."""
    return series_mensuales(mov, ids, fecha_corte, meses, TIPOS_VENTA_NETA).clip(lower=0)


def indicadores(serie: np.ndarray) -> tuple[float, float]:
    """(ADI, CV²) de Syntetos, Boylan y Croston. NaN si hay menos de dos meses con demanda."""
    positivos = serie[serie > 0]
    if len(positivos) < 2:
        return math.nan, math.nan
    adi = len(serie) / len(positivos)
    media = positivos.mean()
    cv2 = float((positivos.std(ddof=0) / media) ** 2) if media > 0 else 0.0
    return adi, cv2


def cuadrante(adi: float, cv2: float, corte_adi: float = 1.32, corte_cv2: float = 0.49) -> str:
    """Cuadrante informativo del plano ADI–CV²: Suave, Errática, Intermitente o Grumosa."""
    if math.isnan(adi):
        return ""
    if adi < corte_adi:
        return "Suave" if cv2 < corte_cv2 else "Errática"
    return "Intermitente" if cv2 < corte_cv2 else "Grumosa"


def clasificar(serie: np.ndarray, corte_adi: float = 1.32, corte_cv2: float = 0.49) -> tuple[str, int, float, float]:
    """Devuelve (clase, k, ADI, CV²)."""
    k = int((serie > 0).sum())
    adi, cv2 = indicadores(serie)
    if k == 0:
        return "Sin venta neta", k, adi, cv2
    if k <= 2:
        return "Esporádica", k, adi, cv2
    regular = adi < corte_adi and cv2 < corte_cv2
    return ("Regular" if regular else "Intermitente"), k, adi, cv2


def sba(serie: np.ndarray, alfa: float = 0.15) -> float:
    """Pronóstico mensual con el método de Syntetos y Boylan (Croston corregido), ecuaciones (3) a (5) de la memoria."""
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


def pronosticar(serie: np.ndarray, clase: str, alfa: float) -> float:
    """λ, ejemplares por mes. Solo Intermitente y Regular tienen tasa; las demás clases no se estiman."""
    return sba(serie, alfa) if clase in CLASES_CON_TASA else 0.0


def nivel_objetivo(tasa_mensual: float, intervalo_meses: float, plazo_meses: float, nivel: float = 0.95) -> int:
    """S = percentil `nivel` de una Poisson con media λ × (T + L)."""
    media = tasa_mensual * (intervalo_meses + plazo_meses)
    if media <= 0:
        return 0
    return int(poisson.ppf(nivel, media))
