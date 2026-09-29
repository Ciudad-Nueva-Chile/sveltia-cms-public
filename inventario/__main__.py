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

from . import lenguaje
from .config import RAIZ, cargar_parametros
from . import stock
from .fuentes import COLUMNAS, FuenteCSV, FuenteSheets, catalogo_desde_sitio
from .modelo import Resultado, calcular
from .planilla import COLUMNAS as COLUMNAS_INVENTARIO, EDITABLES, detectar_cambios, ultima_actualizacion

COLUMNAS_MOV = COLUMNAS["Movimientos"]

# Orden de las pestañas en la planilla. Roberto solo edita las columnas amarillas de «Inventario».
ORDEN_PESTANAS = ["Inventario", "Esta semana", "Pedido sugerido",
                  "Costos", "Movimientos", "Historial", "Análisis técnico", "Indicadores"]
AUTOMATICAS = ["isbn", "titulo", "autor", "origen", "categoria", "precio_lista", "actualizado", "se_vende", "que_hacer"]

NOTAS_INVENTARIO = {
    "bodega": "Ejemplares en la bodega. Corrígelo cuando cambie: una venta, una llegada, un conteo.",
    "consignacion": "Ejemplares entregados en consignación (con guía) que el cliente aún no paga ni devuelve.",
    "en_camino": "Ejemplares pedidos a la editorial que todavía no llegan. Cuando lleguen, bórralos de aquí y súmalos a «En bodega».",
    "notas": "Lo que quieras recordar de este libro.",
    "compra_en": "Dónde se puede comprar este libro. Si está en ambas editoriales, el cálculo elige la que conviene según el costo puesto en bodega y el mínimo de cada envío.",
    "actualizado": "Se completa sola: el día en que cambió por última vez alguna cantidad.",
    "precio_lista": "Viene del sitio. Para cambiarlo, edita el libro en el panel de administración (/admin).",
}

def datos_panel(r: Resultado, etiqueta: str = "") -> dict:
    """Solo lo que el panel necesita. Los datos de ejemplo se pueden publicar; los reales, no."""
    def limpiar(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    t = r.titulos.copy()
    t["que_hacer"] = t["politica"].map(lenguaje.QUE_HACER)
    t["se_vende"] = t["pronostico_mensual"].map(lenguaje.ritmo)
    t["como_se_vende"] = t["patron"].map(lenguaje.COMO_SE_VENDE)
    t["importancia"] = t["abc"].map(lenguaje.IMPORTANCIA)
    titulos = [{k: limpiar(v) for k, v in fila.items()} for fila in t.to_dict("records")]
    pedido = r.pedido.copy()
    pedido["por_que"] = pedido["motivo"].map(lenguaje.motivo_simple) if len(pedido) else []
    series = {i: [int(x) for x in fila] for i, fila in zip(r.series.index, r.series.to_numpy())}
    return {
        "fecha_corte": r.fecha_corte.date().isoformat(),
        "etiqueta": etiqueta,
        "meses": list(r.series.columns),
        "semana": lenguaje.esta_semana(r.titulos, r.pedido_resumen, r.pedido, r.fecha_corte, r.errores),
        "resumen": r.resumen.to_dict("records"),
        "pedido": pedido.to_dict("records"),
        "pedido_resumen": r.pedido_resumen.to_dict("records"),
        "titulos": titulos,
        "series": series,
        "errores": r.errores,
    }


def _hoja_inventario(catalogo: pd.DataFrame, cantidades: pd.DataFrame, r: Resultado, actualizado: pd.Series) -> pd.DataFrame:
    """Filas completas de «Inventario» (internas), ordenadas por título."""
    t = r.titulos.set_index("id")
    df = catalogo[["id", "isbn", "titulo", "autor", "origen", "categoria", "precio_lista", "compra_en"]].copy()
    df["autor"] = df["autor"].replace({"Aa.Vv.": "Varios autores", "Autor no especificado": ""})
    cant = cantidades.set_index("id") if len(cantidades) else pd.DataFrame(columns=["bodega", "consignacion", "en_camino", "notas"])
    for c in ("bodega", "consignacion", "en_camino"):
        df[c] = df["id"].map(cant[c]).fillna(0).astype(int) if c in cant else 0
    df["notas"] = df["id"].map(cant["notas"]).fillna("") if "notas" in cant else ""
    df["compra_en"] = df["compra_en"].where(df["compra_en"].astype(str).str.strip() != "", df["origen"])
    df["actualizado"] = df["id"].map(actualizado)
    df["se_vende"] = df["id"].map(t["pronostico_mensual"]).map(lenguaje.ritmo)
    df["que_hacer"] = df["id"].map(t["politica"]).map(lenguaje.QUE_HACER)
    return df[COLUMNAS_INVENTARIO].sort_values("titulo", key=lambda s: s.str.lower())


def ciclo_planilla(fuente: FuenteSheets, catalogo: pd.DataFrame, p, fecha_corte=None) -> Resultado:
    """Un paso completo con la planilla: detectar cambios en «Inventario», calcular y escribir resultados."""
    hoy = pd.Timestamp(fecha_corte) if fecha_corte else pd.Timestamp.now(tz="America/Santiago").tz_localize(None).normalize()
    inv = fuente.leer("Inventario")
    hist = fuente.leer("Historial")
    mov = fuente.leer("Movimientos")
    mov = mov[mov["tipo"] != "pedido_en_camino"]  # lo que viene en camino se lee de la columna del inventario
    base = stock.existencias(stock.limpiar(mov), pd.DataFrame(columns=["id", "cantidad"]), hoy)

    primera_vez = inv.empty
    # «Se compra en» vive en la planilla (lo decide Roberto); por omisión, la editorial del libro
    catalogo = catalogo.copy()
    if not primera_vez:
        catalogo["compra_en"] = catalogo["id"].map(inv.set_index("id")["compra_en"]).fillna("")
    if primera_vez:
        # La pestaña se crea con las existencias que dicen los movimientos cargados (p. ej. el historial del SII)
        cantidades = base.rename(columns={"transito": "en_camino"})[["id", "bodega", "consignacion", "en_camino"]].copy()
        cantidades[["bodega", "consignacion", "en_camino"]] = cantidades[["bodega", "consignacion", "en_camino"]].clip(lower=0).astype(int)
        # Foto inicial de todos los libros del catálogo (con ceros los que no tienen existencias)
        cantidades = catalogo[["id"]].merge(cantidades, on="id", how="left").fillna(0)
        cantidades[["bodega", "consignacion", "en_camino"]] = cantidades[["bodega", "consignacion", "en_camino"]].astype(int)
        fotos = cantidades.assign(fecha=hoy)[["fecha", "id", "bodega", "consignacion", "en_camino"]]
        nuevos = pd.DataFrame(columns=["fecha", "id", "tipo", "cantidad", "documento", "cliente"])
    else:
        cantidades = inv
        fotos, nuevos = detectar_cambios(inv, hist, base, hoy)

    todos = pd.concat([mov, nuevos], ignore_index=True)
    transito = cantidades[["id", "en_camino"]].rename(columns={"en_camino": "cantidad"})
    r = calcular(catalogo, todos, transito, fuente.leer("Costos"), p, hoy)

    historial = pd.concat([hist, fotos], ignore_index=True)
    actualizado = ultima_actualizacion(historial)

    # Registros ocultos: solo crecen
    fuente.agregar_filas("Historial", fotos.rename(columns=lenguaje.ENCABEZADOS["Historial"]))
    if len(nuevos):
        reg = nuevos.assign(tipo=nuevos["tipo"].map(lenguaje.TIPOS_LEGIBLES))
        fuente.agregar_filas("Movimientos", reg[COLUMNAS_MOV].rename(columns=lenguaje.ENCABEZADOS["Movimientos"]))

    completa = _hoja_inventario(catalogo, cantidades, r, actualizado)
    nombres = lenguaje.ENCABEZADOS["Inventario"]
    if primera_vez:
        idx = {c: i for i, c in enumerate(COLUMNAS_INVENTARIO)}
        fuente.escribir("Inventario", completa.rename(columns=nombres), solo_lectura=True, filtro=True, congelar_columnas=3,
                        editables=[idx[c] for c in EDITABLES],
                        formatos={idx["precio_lista"]: '"$"#,##0', idx["actualizado"]: "dd-mm-yyyy"},
                        notas={idx[c]: texto for c, texto in NOTAS_INVENTARIO.items()},
                        listas={idx["compra_en"]: ["España", "Argentina", "España o Argentina"]},
                        anchos={idx["id"]: 80, idx["isbn"]: 115, idx["titulo"]: 320, idx["autor"]: 170, idx["origen"]: 90, idx["compra_en"]: 150,
                                idx["categoria"]: 190, idx["precio_lista"]: 95, idx["bodega"]: 80, idx["consignacion"]: 105,
                                idx["en_camino"]: 95, idx["actualizado"]: 105, idx["se_vende"]: 125, idx["que_hacer"]: 190, idx["notas"]: 240})
    else:
        faltan = completa[~completa["id"].isin(inv["id"])]
        if len(faltan):  # libros nuevos del sitio: se agregan al final
            fuente.agregar_filas("Inventario", faltan.rename(columns=nombres))
        fuente.actualizar_columnas("Inventario", completa.set_index("id").rename(columns=nombres),
                                   [nombres[c] for c in AUTOMATICAS], nombres["id"])

    semana = lenguaje.esta_semana(r.titulos, r.pedido_resumen, r.pedido, r.fecha_corte, r.errores)
    fuente.escribir("Esta semana", lenguaje.hoja_esta_semana(semana), solo_lectura=True, secciones=True, anchos={0: 380, 1: 560})
    fuente.escribir("Pedido sugerido", lenguaje.pedido(r.pedido), solo_lectura=True,
                    anchos={0: 90, 1: 80, 2: 360, 3: 90, 4: 300, 5: 90})
    fuente.escribir("Análisis técnico", r.titulos, oculta=True, solo_lectura=True)
    fuente.escribir("Indicadores", r.resumen, oculta=True, solo_lectura=True, anchos={0: 360, 1: 420})
    fuente.ordenar(ORDEN_PESTANAS, visibles=3)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(prog="inventario", description="ABC, demanda, pronóstico y sugerencia de importación")
    ap.add_argument("--fuente", choices=["ejemplo", "csv", "sheets"], default="ejemplo")
    ap.add_argument("--datos", type=Path, default=RAIZ / "datos_ejemplo", help="carpeta con los CSV de entrada")
    ap.add_argument("--salida", type=Path, default=RAIZ / "salida", help="carpeta para los CSV de resultados")
    ap.add_argument("--planilla", default=os.environ.get("ID_PLANILLA"), help="ID de la Google Sheet")
    ap.add_argument("--catalogo", choices=["sitio", "fuente"], default=None,
                    help="de dónde sale el catálogo: los libros del sitio (por omisión con --fuente sheets) o la tabla Catalogo")
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

    desde_sitio = (a.catalogo or ("sitio" if a.fuente == "sheets" else "fuente")) == "sitio"
    catalogo = catalogo_desde_sitio(RAIZ / "src" / "libros") if desde_sitio else fuente.leer("Catalogo")

    p = cargar_parametros(a.parametros)
    if a.fuente == "sheets":
        r = ciclo_planilla(fuente, catalogo, p, a.fecha_corte)
    else:
        r = calcular(catalogo, fuente.leer("Movimientos"), fuente.leer("EnTransito"), fuente.leer("Costos"),
                     p, pd.Timestamp(a.fecha_corte) if a.fecha_corte else None)
        fuente.escribir("Resultado_Titulos", r.titulos)
        fuente.escribir("Resultado_Pedido", r.pedido)
        fuente.escribir("Resumen", r.resumen)
        fuente.escribir("Esta_semana", lenguaje.hoja_esta_semana(
            lenguaje.esta_semana(r.titulos, r.pedido_resumen, r.pedido, r.fecha_corte, r.errores)))

    if a.panel:
        a.panel.parent.mkdir(parents=True, exist_ok=True)
        etiqueta = a.etiqueta if a.etiqueta is not None else ("Datos de ejemplo (sintéticos)" if a.fuente == "ejemplo" else "")
        a.panel.write_text(json.dumps(datos_panel(r, etiqueta), ensure_ascii=False, default=str), encoding="utf-8")

    if a.fuente == "sheets":
        # Los registros de GitHub Actions de un repositorio público son públicos: no imprimir datos reales.
        print(f"Resultados escritos en la planilla (corte {r.fecha_corte.date()}). Revisa la pestaña «Esta semana».")
        return
    print(f"Fuente: {fuente.describir()} · corte {r.fecha_corte.date()}")
    for fila in r.resumen.itertuples(index=False):
        print(f"  {fila.indicador}: {fila.valor}")


if __name__ == "__main__":
    main()
