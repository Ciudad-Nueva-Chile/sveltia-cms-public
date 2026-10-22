"""Prepara la Google Sheet del inventario.

Roberto edita las columnas amarillas de «Inventario» (en bodega, en consignación, pedido en camino, notas), anota
cada venta en «Ventas» y cada embarque en «Importaciones». Todo lo demás lo completa el cálculo. Esta herramienta deja
listas «Ventas» e «Importaciones» y la parte que no se ve: «Registro de movimientos» (historia de demanda, oculta) y
«Configuración» (costos por origen con su fecha de vigencia, oculta).
La pestaña «Inventario» la crea el primer cálculo, con las existencias que dan los movimientos cargados.

Uso (en tu computador, con el archivo de credenciales de la cuenta de servicio):
    export GOOGLE_CREDENCIALES_ARCHIVO=~/credenciales-inventario.json
    python herramientas/crear_planilla.py --planilla ID                             # estructura vacía
    python herramientas/crear_planilla.py --planilla ID --con-ejemplo --reemplazar  # rehace todo con datos de ejemplo
    python herramientas/crear_planilla.py --planilla ID --datos CARPETA             # carga datos reales (CSV con el
                                                    # formato de datos_ejemplo/; la carpeta vive fuera del repositorio)
    python -m inventario --fuente sheets --planilla ID                             # primer cálculo: crea «Inventario»
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from inventario.__main__ import lista_libros, preparar_importaciones, preparar_ventas  # noqa: E402
from inventario.config import cargar_parametros  # noqa: E402
from inventario import importaciones as importaciones_mod  # noqa: E402
from inventario.fuentes import COLUMNAS, FuenteSheets, catalogo_desde_sitio  # noqa: E402
from inventario.lenguaje import ENCABEZADOS, TIPOS_LEGIBLES  # noqa: E402
from inventario import ventas as ventas_mod  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
# Pestañas que se borran al rehacer la planilla (versiones anteriores y las que se recrean solas)
BORRAR = ["Historial", "Ventas", "Importaciones", "Lista de libros", "Escala de descuentos", "Libros", "Lista de libros", "Esta semana", "Pedido sugerido",
          "Análisis técnico", "Indicadores", "Catalogo", "Catálogo", "EnTransito", "En tránsito",
          "Resultado_Titulos", "Resultado_Pedido", "Resumen", "Hoja 1", "Sheet1"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--planilla", required=True)
    ap.add_argument("--con-ejemplo", action="store_true", help="carga los movimientos y costos de datos_ejemplo/")
    ap.add_argument("--datos", type=Path, help="carga Movimientos, Importaciones, Costos y Ventas (si existen) de esta carpeta")
    ap.add_argument("--reemplazar", action="store_true", help="borra todo y rehace la planilla desde cero")
    a = ap.parse_args()
    datos = a.datos or (RAIZ / "datos_ejemplo" if a.con_ejemplo else None)
    hay = lambda nombre: datos is not None and (datos / f"{nombre}.csv").exists()

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
        if hay("Movimientos"):
            mov = pd.read_csv(datos / "Movimientos.csv", dtype=str, keep_default_na=False)
            mov["tipo"] = mov["tipo"].map(TIPOS_LEGIBLES).fillna(mov["tipo"])
        else:
            mov = pd.DataFrame(columns=COLUMNAS["Movimientos"])
        f.escribir("Movimientos", mov[COLUMNAS["Movimientos"]].rename(columns=ENCABEZADOS["Movimientos"]),
                   oculta=True, solo_lectura=True, anchos={0: 100, 1: 90, 2: 230, 3: 80, 4: 150, 5: 120})
        print(f"  Registro de movimientos: listo ({len(mov)} filas, oculto)")
    else:
        print("  Registro de movimientos: ya tiene datos, se deja como está")

    # Configuración (oculta): costos por origen. Con --con-ejemplo lleva valores inventados; sin él, vacía.
    # Los factores reales (costo en bodega y FOB sobre el precio neto) y el tipo de cambio los carga Andrés en la
    # planilla privada a partir de la memoria. Nunca se escriben en el repositorio.
    hoja = f.hoja("Costos")
    if hoja is None or a.reemplazar or len(hoja.get_all_values()) <= 1:
        cfg = pd.read_csv(datos / "Costos.csv", dtype=str, keep_default_na=False) if hay("Costos") else pd.DataFrame(
            [{"origen": o, "edicion": "", "fob_sobre_precio_neto": "", "costo_sobre_precio_neto": "", "tipo_cambio": "",
              "tc_desde": "", "factores_desde": ""} for o in ("España", "Argentina")])
        cfg = cfg.reindex(columns=COLUMNAS["Costos"]).fillna("")
        f.escribir("Costos", cfg.rename(columns=ENCABEZADOS["Costos"]), oculta=True,
                   formatos={5: "dd-mm-yyyy", 6: "dd-mm-yyyy"},
                   notas={5: "Fecha desde la que vale este tipo de cambio. Se avisa si pasan más de 6 meses.",
                          6: "Fecha desde la que valen los factores de costo. Se avisa si pasan más de 12 meses.",
                          7: "Lo completa el cálculo: si cada valor se midió o quedó el escrito a mano."},
                   anchos={0: 110, 1: 150, 2: 210, 3: 230, 4: 130, 5: 200, 6: 180, 7: 420})
        print("  Configuración: lista (oculta)")

    # Ventas (visible): con --con-ejemplo, las ventas de ejemplo quedan como históricas (ya están en las existencias)
    if f.hoja("Ventas") is None:
        f.escribir("Lista de libros", lista_libros(catalogo_desde_sitio(RAIZ / "src" / "libros")), oculta=True, solo_lectura=True)
        filas = []
        if hay("Ventas"):
            v = pd.read_csv(datos / "Ventas.csv", dtype=str, keep_default_na=False)
            v["descontado"] = ventas_mod.HISTORICO
            filas = [[r[c] if c in ventas_mod.EDITABLES else "" for c in ventas_mod.COLUMNAS[:-1]] + [r["descontado"]]
                     for r in v.to_dict("records")]
        preparar_ventas(f, filas)
        print(f"  Ventas: lista ({len(filas)} filas)")

    # Importaciones (visible): con --con-ejemplo, los embarques de ejemplo quedan como históricos (ya en existencias)
    if f.hoja("Importaciones") is None:
        filas = []
        if hay("Importaciones"):
            i = pd.read_csv(datos / "Importaciones.csv", dtype=str, keep_default_na=False)
            filas = i.reindex(columns=importaciones_mod.COLUMNAS, fill_value="").values.tolist()
        preparar_importaciones(f, [o.nombre for o in cargar_parametros().origenes], filas)
        print(f"  Importaciones: lista ({len(filas)} filas)")

    print(f"Planilla «{libro.title}» preparada. Ahora corre el primer cálculo:\n"
          f"  python -m inventario --fuente sheets --planilla {a.planilla}")


if __name__ == "__main__":
    main()
