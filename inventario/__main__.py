"""Uso:
    python -m inventario                               # datos de ejemplo → salida/
    python -m inventario --fuente sheets --planilla ID # planilla privada → escribe los resultados en ella
    python -m inventario --panel panel/datos.json      # además genera los datos del panel
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import pandas as pd

from .config import RAIZ, cargar_parametros
from .fuentes import FuenteCSV, FuenteSheets
from .modelo import Resultado, calcular


def datos_panel(r: Resultado, etiqueta: str = "") -> dict:
    """Solo lo que el panel necesita. Los datos de ejemplo se pueden publicar; los reales, no."""
    def limpiar(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    titulos = [{k: limpiar(v) for k, v in fila.items()} for fila in r.titulos.to_dict("records")]
    series = {i: [int(x) for x in fila] for i, fila in zip(r.series.index, r.series.to_numpy())}
    return {
        "fecha_corte": r.fecha_corte.date().isoformat(),
        "etiqueta": etiqueta,
        "meses": list(r.series.columns),
        "resumen": r.resumen.to_dict("records"),
        "pedido": r.pedido.to_dict("records"),
        "pedido_resumen": r.pedido_resumen.to_dict("records"),
        "titulos": titulos,
        "series": series,
        "errores": r.errores,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="inventario", description="ABC, demanda, pronóstico y sugerencia de importación")
    ap.add_argument("--fuente", choices=["ejemplo", "csv", "sheets"], default="ejemplo")
    ap.add_argument("--datos", type=Path, default=RAIZ / "datos_ejemplo", help="carpeta con los CSV de entrada")
    ap.add_argument("--salida", type=Path, default=RAIZ / "salida", help="carpeta para los CSV de resultados")
    ap.add_argument("--planilla", default=os.environ.get("ID_PLANILLA"), help="ID de la Google Sheet")
    ap.add_argument("--parametros", type=Path, default=RAIZ / "config" / "parametros.yml")
    ap.add_argument("--fecha-corte", help="AAAA-MM-DD; por omisión, la del último movimiento")
    ap.add_argument("--panel", type=Path, help="escribe también los datos del panel en este JSON")
    ap.add_argument("--etiqueta", default=None, help="texto de la etiqueta del panel (por omisión, según la fuente)")
    a = ap.parse_args(argv)

    if a.fuente == "sheets":
        if not a.planilla:
            raise SystemExit("Falta el ID de la planilla: usa --planilla o la variable ID_PLANILLA.")
        fuente = FuenteSheets(a.planilla)
    else:
        fuente = FuenteCSV(a.datos, a.salida)

    p = cargar_parametros(a.parametros)
    r = calcular(fuente.leer("Catalogo"), fuente.leer("Movimientos"), fuente.leer("EnTransito"), fuente.leer("Costos"),
                 p, pd.Timestamp(a.fecha_corte) if a.fecha_corte else None)

    fuente.escribir("Resultado_Titulos", r.titulos)
    fuente.escribir("Resultado_Pedido", r.pedido)
    fuente.escribir("Resumen", r.resumen)

    if a.panel:
        a.panel.parent.mkdir(parents=True, exist_ok=True)
        a.panel.write_text(json.dumps(datos_panel(r, a.etiqueta if a.etiqueta is not None else ("Datos de ejemplo (sintéticos)" if a.fuente == "ejemplo" else "")), ensure_ascii=False, default=str), encoding="utf-8")

    if a.fuente == "sheets":
        # Los registros de GitHub Actions de un repositorio público son públicos: no imprimir datos reales.
        print(f"Resultados escritos en la planilla (corte {r.fecha_corte.date()}). Revisa la pestaña Resumen.")
        return
    print(f"Fuente: {fuente.describir()} · corte {r.fecha_corte.date()}")
    for fila in r.resumen.itertuples(index=False):
        print(f"  {fila.indicador}: {fila.valor}")


if __name__ == "__main__":
    main()
