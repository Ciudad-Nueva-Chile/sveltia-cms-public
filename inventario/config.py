"""Parámetros del modelo.

Dos tipos de valores:
- Decisiones que pueden cambiar (nivel de servicio, α de SBA y, por origen, T, L y mínimo de embarque): se leen de
  config/parametros.yml, que edita a mano solo quien mantiene el sistema.
- Valores fijos de la memoria del proyecto (sección 4.2.5 y Tabla 4.26): son constantes de este archivo, con su cita.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
DIAS_POR_MES = 30  # la memoria expresa el plazo de reposición como días / 30
CATEGORIAS = ("AA", "BB", "CC", "DD")

# ---------- Constantes de la memoria ----------
# Ventana de clasificación: los últimos 21 meses hasta la fecha de cálculo (la memoria observa diciembre de 2024 a agosto
# de 2026). Sobre ella se cuentan k, ADI y CV², y se asignan la clase de demanda y la categoría AA, BB, CC o DD.
HISTORIA_MESES = 21
# Cortes de Syntetos, Boylan y Croston (2005), memoria sección 2.4.3. Solo informativos: separan Regular de Intermitente
# y ubican cada libro en el gráfico ADI–CV².
CORTE_ADI = 1.32
CORTE_CV2 = 0.49
# Frecuencia de conteo físico por categoría, memoria Tabla 4.26 (estructura de Flores y Whybark, 1987):
# AA mensual, BB cada 6 meses, CC y DD una vez al año.
CONTEOS_POR_ANIO = {"AA": 12, "BB": 2, "CC": 1, "DD": 1}
# Una consignación abierta más de un año se avisa para cobrarla, pedir la devolución o renovarla (memoria, sección 4.1.3).
DIAS_CONSIGNACION_ANTIGUA = 365

# ---------- Avisos de caducidad de datos externos ----------
MESES_TIPO_CAMBIO = 6       # el tipo de cambio de la pestaña Configuración se revisa al menos cada 6 meses
MESES_FACTORES = 12         # los factores de costo (FOB y costo puesto en bodega) se revisan cada año
MESES_LISTA_PRECIOS = 12    # la lista de precios del sitio (fecha de vigencia en src/_data/sitio.json), cada año


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
    """Las decisiones de config/parametros.yml."""
    nivel_servicio: float = 0.95            # criterio, no optimización
    alfa_suavizado: float = 0.15            # supuesto abierto
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


def leer_fecha_lista(ruta: Path | None = None):
    """Fecha de vigencia de la lista de precios del sitio (src/_data/sitio.json, «fecha_lista»). None si no hay."""
    import json
    from datetime import date
    ruta = ruta or RAIZ / "src" / "_data" / "sitio.json"
    try:
        return date.fromisoformat(str(json.loads(ruta.read_text(encoding="utf-8")).get("fecha_lista", ""))[:10])
    except (OSError, ValueError):
        return None


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
