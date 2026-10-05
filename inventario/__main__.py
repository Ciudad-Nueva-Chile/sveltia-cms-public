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
from . import ventas as ventas_mod
from .fuentes import COLUMNAS, FuenteCSV, FuenteSheets, catalogo_desde_sitio
from .modelo import Resultado, calcular
from .planilla import COLUMNAS as COLUMNAS_INVENTARIO, EDITABLES, detectar_cambios, ultima_actualizacion

COLUMNAS_MOV = COLUMNAS["Movimientos"]

# Orden de las pestañas en la planilla. Roberto edita las columnas amarillas de «Inventario», la pestaña «Ventas»
# y el costo de cada envío en «Pedido sugerido». Las primeras VISIBLES quedan a la vista; el resto, ocultas.
ORDEN_PESTANAS = ["Inventario", "Ventas", "Esta semana", "Pedido sugerido",
                  "Costos", "Movimientos", "Historial", "Lista de libros", "Análisis técnico", "Indicadores"]
VISIBLES = 4
AUTOMATICAS = ["isbn", "titulo", "autor", "origen", "categoria", "precio_lista", "actualizado", "se_vende", "que_hacer"]

NOTAS_INVENTARIO = {
    "bodega": "Ejemplares en la bodega. Las ventas anotadas en «Ventas» se descuentan solas cada mañana: no las restes aquí. "
              "Corrígelo para llegadas, conteos u otras salidas.",
    "consignacion": "Ejemplares entregados en consignación (con guía) que el cliente aún no paga ni devuelve.",
    "en_camino": "Ejemplares pedidos a la editorial que todavía no llegan. Cuando lleguen, bórralos de aquí y súmalos a «En bodega».",
    "notas": "Lo que quieras recordar de este libro.",
    "compra_en": "Dónde se puede comprar este libro. Si está en ambas editoriales, el cálculo elige la que conviene según el costo puesto en bodega y el mínimo de cada envío.",
    "actualizado": "Se completa sola: el día en que cambió por última vez alguna cantidad.",
    "precio_lista": "Viene del sitio. Para cambiarlo, edita el libro en el panel de administración (/admin).",
}

NOTAS_VENTAS = {
    "fecha": "Día de la venta (o del pedido que no se pudo atender).",
    "documento": "Número de boleta, factura o pedido. Opcional, pero ayuda a encontrarla después.",
    "id": "Escribe parte del título o del código y elige el libro de la lista.",
    "cantidad": "Ejemplares de este libro en esta venta.",
    "descuento": "Solo si hubo descuento u oferta: el porcentaje, como número (10 = 10 %). Vacío = precio de lista.",
    "canal": "Por dónde se vendió. «Consignación (factura)» descuenta de «En consignación» en vez de la bodega.",
    "estado": "Vendido (o vacío): descuenta del stock. «No había stock»: alguien lo pidió y no había; no mueve stock, "
              "pero cuenta como demanda. «Devolución»: un cliente devolvió el libro.",
    "descontado": "Se completa sola cuando el cálculo descuenta la venta del stock. Si corriges una venta ya descontada, "
                  "corrige también «En bodega» en «Inventario».",
}


def hoja_ventas(sep: str, filas: list | None = None) -> list:
    """Encabezado de «Ventas» (las columnas automáticas son fórmulas en el encabezado) y filas iniciales."""
    enc = lenguaje.ENCABEZADOS["Ventas"]
    f = lambda t: lenguaje.formula(t, sep)
    cabecera = [enc[c] for c in ventas_mod.COLUMNAS]
    buscar = "IFERROR(VLOOKUP(C2:C,'Lista de libros'!A:C,{col},FALSE),\"\")"
    cabecera[8] = f('={"ISBN";ARRAYFORMULA(IF(C2:C="","",' + buscar.format(col=2) + '))}')
    cabecera[9] = f('={"Precio de lista";ARRAYFORMULA(IF(C2:C="","",' + buscar.format(col=3) + '))}')
    cabecera[10] = f('={"Total cobrado";ARRAYFORMULA(IF((C2:C="")+(D2:D="")+(G2:G="No había stock"),"",'
                     'IFERROR(ROUND(D2:D*J2:J*(1-IF(E2:E>1,E2:E/100,E2:E))*IF(G2:G="Devolución",-1,1),0),"")))}')
    return [cabecera] + (filas or [])


def preparar_ventas(fuente: FuenteSheets, filas: list | None = None) -> None:
    """Crea la pestaña «Ventas» (solo si no existe, o al rehacer la planilla con filas de ejemplo)."""
    idx = {c: i for i, c in enumerate(ventas_mod.COLUMNAS)}
    fuente.escribir("Ventas", hoja_ventas(fuente.separador, filas), solo_lectura=True, filtro=True,
                    editables=[idx[c] for c in ventas_mod.EDITABLES], filas_minimas=1000,
                    formatos={idx["fecha"]: "dd-mm-yyyy", idx["descuento"]: '0"%"', idx["precio_lista"]: '"$"#,##0',
                              idx["total"]: '"$"#,##0'},
                    notas={idx[c]: t for c, t in NOTAS_VENTAS.items()},
                    listas={idx["canal"]: ventas_mod.CANALES, idx["estado"]: ventas_mod.ESTADOS},
                    listas_rango={idx["id"]: "='Lista de libros'!A2:A"},
                    reglas={idx["fecha"]: ({"type": "DATE_IS_VALID"}, "Fecha, por ejemplo 05-10-2026"),
                            idx["cantidad"]: ({"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]}, "Ejemplares (número entero)"),
                            idx["descuento"]: ({"type": "NUMBER_BETWEEN", "values": [{"userEnteredValue": "0"}, {"userEnteredValue": "100"}]},
                                               "Solo el número: 10 para 10 %. Vacío si no hubo descuento.")},
                    anchos={idx["fecha"]: 95, idx["documento"]: 115, idx["id"]: 340, idx["cantidad"]: 75, idx["descuento"]: 100,
                            idx["canal"]: 170, idx["estado"]: 120, idx["notas"]: 200, idx["isbn"]: 115,
                            idx["precio_lista"]: 105, idx["total"]: 110, idx["descontado"]: 230})


def lista_libros(catalogo: pd.DataFrame) -> pd.DataFrame:
    """Pestaña oculta con «Código · Título», ISBN y precio: la usan la lista desplegable y las fórmulas de «Ventas»."""
    df = pd.DataFrame({"libro": catalogo["id"] + " · " + catalogo["titulo"], "isbn": catalogo["isbn"],
                       "precio_lista": catalogo["precio_lista"], "_orden": catalogo["titulo"].str.lower()})
    return df.sort_values("_orden").drop(columns="_orden").rename(columns=lenguaje.ENCABEZADOS["ListaLibros"])


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
        "semana": lenguaje.esta_semana(r.titulos, r.pedido_resumen, r.pedido, r.fecha_corte, r.errores, r.perdidas),
        "ventas": r.ventas,
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
    """Un paso completo con la planilla: detectar cambios en «Inventario», descontar las ventas nuevas,
    calcular y escribir resultados."""
    hoy = pd.Timestamp(fecha_corte) if fecha_corte else pd.Timestamp.now(tz="America/Santiago").tz_localize(None).normalize()
    inv = fuente.leer("Inventario")
    hist = fuente.leer("Historial")
    mov = fuente.leer("Movimientos")
    mov = mov[mov["tipo"] != "pedido_en_camino"]  # lo que viene en camino se lee de la columna del inventario
    ventas = fuente.leer("Ventas")
    envios = fuente.leer("Envios")
    ya_descontadas = ventas_mod.a_movimientos(ventas, solo_descontadas=True)
    base = stock.existencias(stock.limpiar(pd.concat([mov, ya_descontadas], ignore_index=True)),
                             pd.DataFrame(columns=["id", "cantidad"]), hoy)

    primera_vez = inv.empty
    # «Se compra en» vive en la planilla (lo decide Roberto); por omisión, la editorial del libro
    catalogo = catalogo.copy()
    if not primera_vez:
        catalogo["compra_en"] = catalogo["id"].map(inv.set_index("id")["compra_en"]).fillna("")
    nuevos = pd.DataFrame(columns=["fecha", "id", "tipo", "cantidad", "documento", "cliente"])
    if primera_vez:
        # La pestaña se crea con las existencias que dicen los movimientos cargados (p. ej. el historial del SII)
        cantidades = base.rename(columns={"transito": "en_camino"})[["id", "bodega", "consignacion", "en_camino"]].copy()
        cantidades[["bodega", "consignacion", "en_camino"]] = cantidades[["bodega", "consignacion", "en_camino"]].clip(lower=0).astype(int)
        # Todos los libros del catálogo (con ceros los que no tienen existencias)
        cantidades = catalogo[["id"]].merge(cantidades, on="id", how="left").fillna(0)
        cantidades[["bodega", "consignacion", "en_camino"]] = cantidades[["bodega", "consignacion", "en_camino"]].astype(int)
        fotos = pd.DataFrame(columns=["fecha", "id", "bodega", "consignacion", "en_camino"])
    else:
        cantidades = inv
        fotos, nuevos = detectar_cambios(inv, hist, base, hoy)

    # Ventas nuevas: se descuentan del stock (salvo lo que Roberto ya bajó a mano hoy)
    validas = ventas_mod.validas(ventas)
    pendientes = validas[validas["descontado"] == ""]
    marcas, cambiados = {}, set()
    if len(pendientes):
        nuevas, nuevos, marcas, cambiados = ventas_mod.aplicar(
            pendientes, cantidades[["id", "bodega", "consignacion", "en_camino"]], nuevos, hoy)
        nuevas = nuevas.set_index("id")
        cantidades = cantidades.copy()
        for c in ("bodega", "consignacion"):
            cantidades[c] = cantidades["id"].map(nuevas[c]).fillna(cantidades[c]).astype(int)
    if primera_vez:  # foto inicial de todo el catálogo
        fotos = cantidades.assign(fecha=hoy)[["fecha", "id", "bodega", "consignacion", "en_camino"]]
    elif cambiados:  # la foto de hoy queda con el stock ya descontado
        fotos = pd.concat([fotos[~fotos["id"].isin(cambiados)],
                           cantidades[cantidades["id"].isin(cambiados)].assign(fecha=hoy)[["fecha", "id", "bodega", "consignacion", "en_camino"]]],
                          ignore_index=True)
    # Bajas de bodega sin venta anotada (solo se avisan cuando ya se usa «Ventas»)
    titulos = catalogo.set_index("id")["titulo"]
    sin_anotar = []
    if len(validas):
        bajas = nuevos[nuevos["tipo"] == "venta"].groupby("id")["cantidad"].sum()
        sin_anotar = [{"id": i, "titulo": titulos.get(i, i), "unidades": int(n)} for i, n in bajas.items() if n > 0]

    todos = pd.concat([mov, nuevos, ventas_mod.a_movimientos(ventas)], ignore_index=True)
    transito = cantidades[["id", "en_camino"]].rename(columns={"en_camino": "cantidad"})
    r = calcular(catalogo, todos, transito, fuente.leer("Costos"), p, hoy,
                 envios=dict(zip(envios["origen"], envios["costo_usd"])), hoja_ventas=ventas)

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
        # Solo las celdas que cambiaron por ventas (no se pisa lo que Roberto esté editando en otras filas)
        nuevas = cantidades.set_index("id")
        fuente.actualizar_celdas("Inventario", nombres["id"], {i: {nombres["bodega"]: int(nuevas.at[i, "bodega"]),
                                                                    nombres["consignacion"]: int(nuevas.at[i, "consignacion"])}
                                                                for i in cambiados})
        fuente.notas_encabezado("Inventario", {nombres[c]: t for c, t in NOTAS_INVENTARIO.items()})

    fuente.escribir("Lista de libros", lista_libros(catalogo), oculta=True, solo_lectura=True)
    if fuente.hoja("Ventas") is None:
        preparar_ventas(fuente)
    fuente.escribir_celdas("Ventas", lenguaje.ENCABEZADOS["Ventas"]["descontado"], marcas)

    semana = lenguaje.esta_semana(r.titulos, r.pedido_resumen, r.pedido, r.fecha_corte, r.errores, r.perdidas, sin_anotar)
    fuente.escribir("Esta semana", lenguaje.hoja_esta_semana(semana), solo_lectura=True, secciones=True, anchos={0: 380, 1: 560})
    hp = lenguaje.hoja_pedido(r.pedido, r.pedido_resumen.attrs["combinaciones"], r.pedido_resumen.attrs["envios"],
                              r.fecha_corte, fuente.separador)
    fuente.escribir("Pedido", hp["filas"], solo_lectura=True, secciones=True, celdas_editables=hp["editables"],
                    negritas=hp["negritas"], formatos_rango=hp["formatos"],
                    anchos={0: 230, 1: 260, 2: 100, 3: 320, 4: 110, 5: 110, 6: 380})
    fuente.escribir("Análisis técnico", r.titulos, oculta=True, solo_lectura=True)
    fuente.escribir("Indicadores", r.resumen, oculta=True, solo_lectura=True, anchos={0: 360, 1: 420})
    fuente.ordenar(ORDEN_PESTANAS, visibles=VISIBLES)
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
        ventas = fuente.leer("Ventas")
        envios = fuente.leer("Envios")
        movimientos = pd.concat([fuente.leer("Movimientos"), ventas_mod.a_movimientos(ventas)], ignore_index=True)
        r = calcular(catalogo, movimientos, fuente.leer("EnTransito"), fuente.leer("Costos"),
                     p, pd.Timestamp(a.fecha_corte) if a.fecha_corte else None,
                     envios=dict(zip(envios["origen"], envios["costo_usd"])), hoja_ventas=ventas)
        fuente.escribir("Resultado_Titulos", r.titulos)
        fuente.escribir("Resultado_Pedido", r.pedido)
        fuente.escribir("Comparacion_envios", pd.DataFrame(r.pedido_resumen.attrs["combinaciones"]))
        fuente.escribir("Resumen", r.resumen)
        fuente.escribir("Esta_semana", lenguaje.hoja_esta_semana(
            lenguaje.esta_semana(r.titulos, r.pedido_resumen, r.pedido, r.fecha_corte, r.errores, r.perdidas)))

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
