"""Carga de parámetros del modelo (config/parametros.yml) con valores por omisión.

Los valores por omisión son los de la memoria del proyecto (sección 4.2.5). Los que son supuestos o criterios, y no
mediciones, están marcados así en config/parametros.yml y en las pistas de Sveltia.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
DIAS_POR_MES = 30  # la memoria expresa el plazo de reposición como días / 30
CATEGORIAS = ("AA", "BB", "CC", "DD")


@dataclass
class Origen:
    nombre: str
    intervalo_embarque_meses: float = 8.5   # T: meses entre embarques (análisis de lote por embarque de la memoria)
    plazo_dias: float = 7                   # L: plazo de reposición de la casa de origen, en días
    minimo_embarque_usd: float = 700        # mínimo económico del embarque, a costo FOB


def _origenes_memoria() -> list[Origen]:
    return [Origen("España", 8.5, 7, 700), Origen("Argentina", 12, 5.5, 700)]


@dataclass
class Parametros:
    historia_meses: int = 21                # ventana de observación de la memoria (dic-2024 a ago-2026)
    corte_adi: float = 1.32                 # Syntetos, Boylan y Croston (2005); solo informativo
    corte_cv2: float = 0.49
    alfa_suavizado: float = 0.15            # supuesto abierto
    nivel_servicio: float = 0.95            # criterio, no optimización
    dias_consignacion_antigua: int = 365
    conteos_por_anio: dict = field(default_factory=lambda: {"AA": 12, "BB": 2, "CC": 1, "DD": 1})
    revision_clasificacion_meses: dict = field(default_factory=lambda: {"AA": 6, "BB": 6, "CC": 12, "DD": 12})
    origenes: list[Origen] = field(default_factory=_origenes_memoria)

    def origen(self, nombre: str) -> Origen:
        """Parámetros del origen. Todo origen distinto de Argentina se trata como España (criterio de la memoria)."""
        for o in self.origenes:
            if o.nombre == nombre:
                return o
        if nombre != "Argentina":
            for o in self.origenes:
                if o.nombre == "España":
                    return o
        return Origen(nombre)

    def intervalo_meses(self, origen: str) -> float:
        """T: meses entre embarques del origen."""
        return float(self.origen(origen).intervalo_embarque_meses)

    def plazo_meses(self, origen: str) -> float:
        """L: plazo de reposición en meses (días / 30)."""
        return float(self.origen(origen).plazo_dias) / DIAS_POR_MES


def cargar_parametros(ruta: Path | None = None) -> Parametros:
    ruta = ruta or RAIZ / "config" / "parametros.yml"
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    datos = datos or {}
    campos_origen = Origen.__dataclass_fields__
    origenes = [Origen(**{k: v for k, v in o.items() if k in campos_origen}) for o in datos.pop("origenes", [])] or None
    conocidos = {k: v for k, v in datos.items() if k in Parametros.__dataclass_fields__}
    p = Parametros(**conocidos)
    if origenes:
        p.origenes = origenes
    return p
