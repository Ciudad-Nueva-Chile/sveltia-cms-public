"""Parámetros del modelo.

Dos tipos de valores:
- Decisiones que pueden cambiar (nivel de servicio, α de SBA y, por origen, T, L y meses fijos de pedido): se leen de
  config/parametros.yml, que edita a mano solo quien mantiene el sistema.
- Valores fijos del método: son constantes de este archivo, cada una con su explicación.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
DIAS_POR_MES = 30  # el plazo de reposición se expresa en meses como días / 30
CATEGORIAS = ("A", "B", "C", "D")

# ---------- Constantes del método ----------
# Ventana de clasificación: los últimos 20 meses hasta la fecha de cálculo. Sobre ella se cuentan k, ADI y CV², y se
# asignan la clase de demanda y la categoría A, B, C o D.
HISTORIA_MESES = 20
# La demanda se cuenta desde enero de 2025, inicio de la gestión actual; los movimientos anteriores solo sirven para las
# existencias.
INICIO_DEMANDA = "2025-01-01"
# Cortes de Syntetos, Boylan y Croston (2005). Solo informativos: separan Regular de Intermitente y ubican cada libro en
# el gráfico ADI–CV².
CORTE_ADI = 1.32
CORTE_CV2 = 0.49
# Frecuencia de conteo físico por categoría (estructura de Flores y Whybark, 1987): conteo mensual para A, semestral para B
# y anual para C y D.
CONTEOS_POR_ANIO = {"A": 12, "B": 2, "C": 1, "D": 1}
# Una consignación abierta más de un año se avisa para cobrarla, pedir la devolución o renovarla.
DIAS_CONSIGNACION_ANTIGUA = 365

# ---------- Aviso de aceleración (no cambia S) ----------
# El cálculo supone que los próximos meses se parecen a la ventana observada; un título que se acelera (por ejemplo, por
# un acontecimiento) rompe ese supuesto antes de que SBA lo refleje. Se avisa si el ritmo de los últimos
# 3 meses es al menos 2 veces el de los 18 meses anteriores, con 3 o más unidades netas en esos 3 meses.
ACELERACION_MESES_RECIENTES = 3
ACELERACION_MESES_PREVIOS = 18
ACELERACION_FACTOR = 2
ACELERACION_MINIMO_UNIDADES = 3

# ---------- Aviso de evento que sigue vendiéndose (no cambia la clase, S ni la política) ----------
# La clase Coyuntural se marca a mano y no tiene nivel objetivo. El aviso salta cuando una obra coyuntural registra venta
# neta positiva en 3 o más de los últimos 6 meses. Quitar la marca en Sveltia lo decide quien administra el catálogo; el
# cálculo solo avisa.
COYUNTURAL_MESES_REVISION = 6
COYUNTURAL_MESES_CON_VENTA = 3

# ---------- Avisos de caducidad de datos externos ----------
MESES_TIPO_CAMBIO = 6       # el tipo de cambio de la pestaña Configuración se revisa al menos cada 6 meses
MESES_FACTORES = 12         # los factores de costo (FOB y costo puesto en bodega) se revisan cada año
MESES_LISTA_PRECIOS = 12    # la lista de precios del sitio (fecha de vigencia en src/_data/sitio.json), cada año


@dataclass
class Origen:
    nombre: str
    intervalo_embarque_meses: float = 6     # T: meses entre embarques
    plazo_dias: float = 39                  # L: plazo de reposición observado, en días
    meses_embarque: list | None = None      # meses fijos del pedido (p. ej. [2, 8]); vacío = última llegada + T
    peso_medio_kg: float = 0                # peso de un ejemplar si la ficha no trae «Peso (kg)»
    envio: dict | None = None               # costo estimado del envío según su peso: tarifa por tramos o fijo + por kilo
    aduana: dict | None = None              # impuestos aproximados del envío: IVA, seguro presunto, arancel, tasas, flete de aduana


def _origenes_configurados() -> list[Origen]:
    """Los orígenes de config/parametros.yml: un solo lugar para T, L y la tarifa."""
    return cargar_parametros().origenes


@dataclass
class Parametros:
    """Las decisiones de config/parametros.yml."""
    nivel_servicio: float = 0.95            # criterio, no optimización
    alfa_suavizado: float = 0.15            # supuesto abierto
    origenes: list[Origen] = field(default_factory=_origenes_configurados)

    def origen(self, nombre: str) -> Origen:
        """Parámetros del origen. Todo origen distinto de Argentina se trata como España."""
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
    return Parametros(**conocidos, origenes=origenes or [])
