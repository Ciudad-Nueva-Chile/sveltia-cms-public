"""Prepara la Google Sheet del inventario.

Roberto edita solo las columnas amarillas de «Inventario» (en bodega, en consignación, pedido en camino, notas).
Todo lo demás lo completa el cálculo. Esta herramienta deja lista la parte que no se ve:
«Registro de movimientos» (historia de demanda, oculta) y «Configuración» (costos por origen, oculta).
La pestaña «Inventario» la crea el primer cálculo, con las existencias que dan los movimientos cargados.

Uso (en tu computador, con el archivo de credenciales de la cuenta de servicio):
    export GOOGLE_CREDENCIALES_ARCHIVO=~/credenciales-inventario.json
    python herramientas/crear_planilla.py --planilla ID                             # estructura vacía
    python herramientas/crear_planilla.py --planilla ID --con-ejemplo --reemplazar  # rehace todo con datos de ejemplo
    python -m inventario --fuente sheets --planilla ID                             # primer cálculo: crea «Inventario»
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from inventario.fuentes import COLUMNAS, FuenteSheets  # noqa: E402
from inventario.lenguaje import ENCABEZADOS, TIPOS_LEGIBLES  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
# Pestañas que se borran al rehacer la planilla (versiones anteriores y las que se recrean solas)
BORRAR = ["Historial", "Libros", "Lista de libros", "Esta semana", "Pedido sugerido",
          "Análisis técnico", "Indicadores", "Catalogo", "Catálogo", "EnTransito", "En tránsito",
          "Resultado_Titulos", "Resultado_Pedido", "Resumen", "Hoja 1", "Sheet1"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--planilla", required=True)
    ap.add_argument("--con-ejemplo", action="store_true", help="carga los movimientos y costos de datos_ejemplo/")
    ap.add_argument("--reemplazar", action="store_true", help="borra todo y rehace la planilla desde cero")
    a = ap.parse_args()

    f = FuenteSheets(a.planilla)
    libro = f.libro

    if a.reemplazar:
        # «Inventario» no se borra (Google exige al menos una pestaña visible): se vacía y el primer cálculo la rehace
        inv = f.hoja("Inventario")
        if inv is not None:
            inv.clear()
            inv.update(values=[["Se completa con el primer cálculo"]], range_name="A1")
        for nombre in BORRAR:
            try:
                hoja = libro.worksheet(nombre)
            except Exception:
                continue
            if len(libro.worksheets()) > 1:
                libro.del_worksheet(hoja)
                f._hojas = None
                print(f"  {nombre}: eliminada")

    # «Inventario» visible desde el principio (Google no permite ocultar todas las pestañas); el primer cálculo la llena
    if f.hoja("Inventario") is None:
        hoja = libro.add_worksheet(title="Inventario", rows=50, cols=14, index=0)
        hoja.update(values=[["Se completa con el primer cálculo"]], range_name="A1")
        f._hojas = None

    # Registro de movimientos (oculto): la historia de demanda. Con datos reales, aquí se cargan las facturas y guías del SII.
    hoja = f.hoja("Movimientos")
    if hoja is None or a.reemplazar or len(hoja.get_all_values()) <= 1:
        if a.con_ejemplo:
            mov = pd.read_csv(RAIZ / "datos_ejemplo" / "Movimientos.csv", dtype=str, keep_default_na=False)
            mov["tipo"] = mov["tipo"].map(TIPOS_LEGIBLES).fillna(mov["tipo"])
        else:
            mov = pd.DataFrame(columns=COLUMNAS["Movimientos"])
        f.escribir("Movimientos", mov[COLUMNAS["Movimientos"]].rename(columns=ENCABEZADOS["Movimientos"]),
                   oculta=True, solo_lectura=True, anchos={0: 100, 1: 90, 2: 230, 3: 80, 4: 150, 5: 120})
        print(f"  Registro de movimientos: listo ({len(mov)} filas, oculto)")
    else:
        print("  Registro de movimientos: ya tiene datos, se deja como está")

    # Configuración (oculta): costos por origen, los define Andrés una vez
    hoja = f.hoja("Costos")
    if hoja is None or a.reemplazar or len(hoja.get_all_values()) <= 1:
        cfg = pd.read_csv(RAIZ / "datos_ejemplo" / "Costos.csv") if a.con_ejemplo else pd.DataFrame(
            [{"origen": o, "fob_sobre_precio_neto": "", "costo_sobre_precio_neto": "", "tipo_cambio": ""} for o in ("España", "Argentina")])
        f.escribir("Costos", cfg.rename(columns=ENCABEZADOS["Costos"]), oculta=True, anchos={0: 110, 1: 150, 2: 210, 3: 130})
        print("  Configuración: lista (oculta)")

    print(f"Planilla «{libro.title}» preparada. Ahora corre el primer cálculo:\n"
          f"  python -m inventario --fuente sheets --planilla {a.planilla}")


if __name__ == "__main__":
    main()
