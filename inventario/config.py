"""Carga de parámetros del modelo (config/parametros.yml) con valores por omisión."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
SEMANAS_POR_MES = 52 / 12


@dataclass
class Origen:
    nombre: str
    plazo_semanas: float = 1
    minimo_embarque_usd: float = 700


@dataclass
class Parametros:
    historia_meses: int = 24
    abc_meses: int = 12
    abc_corte_a: float = 0.80
    abc_corte_b: float = 0.95
    corte_adi: float = 1.32
    corte_cv2: float = 0.49
    alfa_suavizado: float = 0.15
    nivel_servicio: float = 0.90
    revision_semanas: float = 4
    simulaciones: int = 2000
    meses_sin_movimiento: int = 18
    dias_consignacion_antigua: int = 365
    costo_postergar: float = 0.30   # castigo por ejemplar necesario que no se pide: fracción de su precio neto
    costo_adelantar: float = 0.10   # castigo por ejemplar comprado antes de tiempo para completar un mínimo
    origenes: list[Origen] = field(default_factory=lambda: [Origen("España"), Origen("Argentina")])

    def origen(self, nombre: str) -> Origen:
        for o in self.origenes:
            if o.nombre == nombre:
                return o
        return Origen(nombre)

    def horizonte_meses(self, origen: str) -> float:
        """Periodo de protección en meses: plazo de reposición más periodo de revisión."""
        return (self.origen(origen).plazo_semanas + self.revision_semanas) / SEMANAS_POR_MES

    def plazo_meses(self, origen: str) -> float:
        return self.origen(origen).plazo_semanas / SEMANAS_POR_MES


def cargar_parametros(ruta: Path | None = None) -> Parametros:
    ruta = ruta or RAIZ / "config" / "parametros.yml"
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    datos = datos or {}
    origenes = [Origen(**o) for o in datos.pop("origenes", [])] or None
    conocidos = {k: v for k, v in datos.items() if k in Parametros.__dataclass_fields__}
    p = Parametros(**conocidos)
    if origenes:
        p.origenes = origenes
    return p
