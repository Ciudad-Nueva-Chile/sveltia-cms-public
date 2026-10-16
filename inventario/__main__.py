"""Uso:
    python -m inventario                               # datos de ejemplo → salida/
    python -m inventario --fuente sheets --planilla ID # planilla privada → escribe los resultados en ella
    python -m inventario --panel panel/datos.json      # además genera los datos del panel
    python -m inventario --fuente sheets --panel _site/inventario/datos.cifrado.json --cifrar
                                                       # datos del panel cifrados con la contraseña CLAVE_PANEL
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import pandas as pd

from . import lenguaje
from .config import RAIZ, cargar_parametros, leer_fecha_lista
from . import stock
from . import ventas as ventas_mod
from . import importaciones as importaciones_mod
from . import costos as costos_mod
from .fuentes import COLUMNAS, FuenteCSV, FuenteSheets, catalogo_desde_sitio
from .modelo import Resultado, calcular
from .planilla import COLUMNAS as COLUMNAS_INVENTARIO, EDITABLES, detectar_cambios, ultima_actualizacion

COLUMNAS_MOV = COLUMNAS["Movimientos"]

# Orden de las pestañas en la planilla. Roberto edita las columnas amarillas de «Inventario», la pestaña «Ventas»
# y el costo de cada envío en «Pedido sugerido». Las primeras VISIBLES quedan a la vista; el resto, ocultas.
ORDEN_PESTANAS = ["Inventario", "Ventas", "Importaciones", "Esta semana", "Pedido sugerido",
                  "Costos", "Movimientos", "Historial", "Lista de libros", "Análisis técnico", "Indicadores"]
VISIBLES = 5
AUTOMATICAS = ["isbn", "titulo", "autor", "origen", "categoria", "categoria_gestion", "precio_lista", "actualizado", "se_vende", "que_hacer"]

NOTAS_INVENTARIO = {
    "bodega": "Ejemplares en la bodega. Las ventas anotadas en «Ventas» se descuentan solas en el próximo cálculo (cada hora de lunes a sábado): no las restes aquí. "
              "Corrígelo para llegadas, conteos u otras salidas.",
    "consignacion": "Ejemplares entregados en consignación (con guía) que el cliente aún no paga ni devuelve.",
    "en_camino": "AUTOMÁTICA si el libro tiene filas sin fecha de llegada en «Importaciones»: es la suma de lo que está en camino "
                 "allí. Para los demás libros, anota aquí lo pedido a la editorial que todavía no llega.",
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
    "estado": "Vendido (o vacío): descuenta del stock. «No había stock»: alguien lo pidió y no había. No mueve stock, "
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


NOTAS_IMPORTACIONES = {
    "fecha_pedido": "Día en que se hizo el pedido a la editorial. Con la fecha de llegada, sirve para medir el plazo L.",
    "fecha_llegada": "Día en que llegó el embarque. Vacía = todavía en camino (cuenta como «Pedido en camino» en «Inventario»).",
    "pais": "País desde donde se compró: España o Argentina.",
    "documento": "Número de factura de la editorial o de la DIN. Opcional.",
    "id": "Escribe parte del título o del código y elige el libro de la lista.",
    "cantidad": "Ejemplares de este libro en este embarque.",
    "fob_usd": "Opcional: valor FOB total de esta línea, en dólares. Con él se mide «FOB / precio neto» de «Configuración».",
    "gastos_clp": ("Opcional: lo que costó traer el embarque, en pesos y sin IVA (flete, seguro, agente de aduana y "
                   "aranceles). Se escribe una sola vez por factura o DIN, en cualquiera de sus filas. Con él se mide "
                   "«Costo en bodega / precio neto» de «Configuración»."),
    "sumado": "Se completa sola cuando el cálculo suma la llegada a «En bodega». No hay que sumarla también en «Inventario».",
}


def preparar_importaciones(fuente: FuenteSheets, paises: list[str], filas: list | None = None) -> None:
    """Crea la pestaña «Importaciones» (solo si no existe, o al rehacer la planilla con filas de ejemplo)."""
    enc = lenguaje.ENCABEZADOS["Importaciones"]
    idx = {c: i for i, c in enumerate(importaciones_mod.COLUMNAS)}
    fuente.escribir("Importaciones", [[enc[c] for c in importaciones_mod.COLUMNAS]] + (filas or []), solo_lectura=True,
                    filtro=True, editables=[idx[c] for c in importaciones_mod.EDITABLES], filas_minimas=1000,
                    formatos={idx["fecha_pedido"]: "dd-mm-yyyy", idx["fecha_llegada"]: "dd-mm-yyyy", idx["fob_usd"]: "#,##0.00", idx["gastos_clp"]: '"$"#,##0'},
                    notas={idx[c]: t for c, t in NOTAS_IMPORTACIONES.items()},
                    listas={idx["pais"]: paises},
                    listas_rango={idx["id"]: "='Lista de libros'!A2:A"},
                    reglas={idx["fecha_pedido"]: ({"type": "DATE_IS_VALID"}, "Fecha, por ejemplo 05-10-2026"),
                            idx["fecha_llegada"]: ({"type": "DATE_IS_VALID"}, "Vacía mientras el embarque no llegue"),
                            idx["cantidad"]: ({"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]}, "Ejemplares (número entero)")},
                    anchos={idx["fecha_pedido"]: 105, idx["fecha_llegada"]: 110, idx["pais"]: 110, idx["documento"]: 140,
                            idx["id"]: 340, idx["cantidad"]: 75, idx["fob_usd"]: 110, idx["gastos_clp"]: 150, idx["notas"]: 200, idx["sumado"]: 230})


def lista_libros(catalogo: pd.DataFrame) -> pd.DataFrame:
    """Pestaña oculta con «Código · Título», ISBN y precio: la usan la lista desplegable y las fórmulas de «Ventas»."""
    df = pd.DataFrame({"libro": catalogo["id"] + " · " + catalogo["titulo"], "isbn": catalogo["isbn"],
                       "precio_lista": catalogo["precio_lista"], "_orden": catalogo["titulo"].str.lower()})
    return df.sort_values("_orden").drop(columns="_orden").rename(columns=lenguaje.ENCABEZADOS["ListaLibros"])


def datos_disponibilidad(r: Resultado) -> dict:
    """Estado de cada libro para el sitio público: solo una etiqueta, nunca cantidades ni la categoría.

        disponible   En bodega > 0
        agotado      En bodega = 0 y categoría A o B (con «llega» si hay pedido en camino)
        bajo_pedido  En bodega = 0 y categoría C, D o sin categoría
    """
    libros = {}
    for f in r.titulos.itertuples():
        if f.bodega > 0:
            libros[f.id] = {"estado": "disponible"}
        elif f.categoria_gestion in ("A", "B"):
            libros[f.id] = {"estado": "agotado", "llega": bool(f.transito > 0)}
        else:
            libros[f.id] = {"estado": "bajo_pedido"}
    return {"fecha": r.fecha_corte.date().isoformat(), "libros": libros}


def datos_panel(r: Resultado, etiqueta: str = "") -> dict:
    """Solo lo que el panel necesita. Los datos de ejemplo se pueden publicar; los reales, no."""
    def limpiar(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    t = r.titulos.copy()
    t["que_hacer"] = t["politica"].map(lenguaje.QUE_HACER)
    t["se_vende"] = t["tasa_mensual"].map(lenguaje.ritmo)
    t["como_se_vende"] = t["clase"].map(lenguaje.COMO_SE_VENDE)
    t["categoria_texto"] = t["categoria_gestion"].map(lenguaje.CATEGORIA)
    titulos = [{k: limpiar(v) for k, v in fila.items()} for fila in t.to_dict("records")]
    pedido = r.pedido.copy()
    pedido["por_que"] = pedido["motivo"].map(lenguaje.motivo_simple) if len(pedido) else []
    series = {i: [int(x) for x in fila] for i, fila in zip(r.series.index, r.series.to_numpy())}
    return {
        "fecha_corte": r.fecha_corte.date().isoformat(),
        "etiqueta": etiqueta,
        "meses": list(r.series.columns),
        "semana": lenguaje.esta_semana(r.titulos, r.pedido_resumen, r.pedido, r.fecha_corte, r.errores, r.perdidas,
                                       conteo=r.conteo, caducidad=r.caducidad, tl=r.tl),
        "ventas": r.ventas,
        "categorias": r.categorias.to_dict("records"),
        "matriz": r.matriz,
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
    df["categoria_gestion"] = df["id"].map(t["categoria_gestion"])
    df["autor"] = df["autor"].replace({"Aa.Vv.": "Varios autores", "Autor no especificado": ""})
    cant = cantidades.set_index("id") if len(cantidades) else pd.DataFrame(columns=["bodega", "consignacion", "en_camino", "notas"])
    for c in ("bodega", "consignacion", "en_camino"):
        df[c] = df["id"].map(cant[c]).fillna(0).astype(int) if c in cant else 0
    df["notas"] = df["id"].map(cant["notas"]).fillna("") if "notas" in cant else ""
    df["compra_en"] = df["compra_en"].where(df["compra_en"].astype(str).str.strip() != "", df["origen"])
    df["actualizado"] = df["id"].map(actualizado)
    df["se_vende"] = df["id"].map(t["tasa_mensual"]).map(lenguaje.ritmo)
    df["que_hacer"] = df["id"].map(t["politica"]).map(lenguaje.QUE_HACER)
    return df[COLUMNAS_INVENTARIO].sort_values("titulo", key=lambda s: s.str.lower())


NOTAS_CONFIGURACION = {
    "Tipo de cambio vigente desde": "Lo completa el cálculo con el dólar observado del Banco Central (mindicador.cl).",
    "Factores vigentes desde": "Fecha del último embarque usado para medir los factores. Se avisa si pasan más de 12 meses.",
    "Cómo se obtuvo": ("Lo completa el cálculo: si cada valor se midió (dólar del Banco Central; factores con los últimos "
                       "embarques de «Importaciones» que tienen FOB y gastos) o quedó el escrito a mano."),
}


def configuracion_automatica(fuente: FuenteSheets, imp: pd.DataFrame, catalogo: pd.DataFrame, hoy) -> pd.DataFrame:
    """Dólar del día y factores medidos (costos.py): se escriben en «Configuración» y se usan en este cálculo."""
    costos = fuente.leer("Costos")
    try:
        nuevos = costos_mod.actualizar(costos, imp, catalogo, hoy)
    except Exception as e:                       # sin datos nuevos se calcula con lo que dice la planilla
        print(f"::warning::Configuración automática: {type(e).__name__}")
        return costos
    enc = lenguaje.ENCABEZADOS["Costos"]
    cols = ["tipo_cambio", "tc_desde", "fob_sobre_precio_neto", "costo_sobre_precio_neto", "factores_desde", "como"]
    try:
        fuente.asegurar_columnas("Costos", [enc[c] for c in ("tc_desde", "factores_desde", "como")], NOTAS_CONFIGURACION,
                                 formatos={enc["tc_desde"]: "dd-mm-yyyy", enc["factores_desde"]: "dd-mm-yyyy"})
        fuente.asegurar_columnas("Importaciones", [lenguaje.ENCABEZADOS["Importaciones"]["gastos_clp"]],
                                 {lenguaje.ENCABEZADOS["Importaciones"]["gastos_clp"]: NOTAS_IMPORTACIONES["gastos_clp"]},
                                 editables=(lenguaje.ENCABEZADOS["Importaciones"]["gastos_clp"],),
                                 formatos={lenguaje.ENCABEZADOS["Importaciones"]["gastos_clp"]: '"$"#,##0'})
        fuente.escribir_filas("Costos", {int(f["fila_planilla"]): {enc[c]: f[c] for c in cols} for _, f in nuevos.iterrows()},
                              [enc[c] for c in cols])
    except Exception as e:
        print(f"::warning::No se pudo escribir «Configuración»: {type(e).__name__}")
    return nuevos


def ciclo_planilla(fuente: FuenteSheets, catalogo: pd.DataFrame, p, fecha_corte=None) -> Resultado:
    """Un paso completo con la planilla: detectar cambios en «Inventario», descontar las ventas nuevas,
    calcular y escribir resultados."""
    hoy = pd.Timestamp(fecha_corte) if fecha_corte else pd.Timestamp.now(tz="America/Santiago").tz_localize(None).normalize()
    inv = fuente.leer("Inventario")
    # Filas sin código o con el código repetido (p. ej. un libro de prueba ya borrado) no se pueden cruzar: se ignoran y
    # desaparecen al reescribir la pestaña, que se arma desde el catálogo
    inv = inv[inv["id"].astype(str).str.strip(" '\"") != ""].drop_duplicates("id")
    hist = fuente.leer("Historial")
    mov = fuente.leer("Movimientos")
    mov = mov[mov["tipo"] != "pedido_en_camino"]  # lo que viene en camino se lee de la columna del inventario
    ventas = fuente.leer("Ventas")
    imp = fuente.leer("Importaciones")
    envios = fuente.leer("Envios")
    ya_descontadas = ventas_mod.a_movimientos(ventas, solo_descontadas=True)
    ya_sumadas = importaciones_mod.a_movimientos(imp, solo_sumadas=True)
    base = stock.existencias(stock.limpiar(pd.concat([mov, ya_descontadas, ya_sumadas], ignore_index=True)),
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
    # Llegadas nuevas de «Importaciones»: se suman al stock una sola vez (salvo lo que Roberto ya subió a mano hoy)
    llegadas = importaciones_mod.llegadas(imp)
    pendientes_imp = llegadas[llegadas["sumado"] == ""]
    marcas_imp = {}
    if len(pendientes_imp):
        nuevas, nuevos, marcas_imp, cambiados_imp = importaciones_mod.aplicar(
            pendientes_imp, cantidades[["id", "bodega", "consignacion", "en_camino"]], nuevos, hoy)
        cantidades = cantidades.copy()
        cantidades["bodega"] = cantidades["id"].map(nuevas.set_index("id")["bodega"]).fillna(cantidades["bodega"]).astype(int)
        cambiados = cambiados | cambiados_imp
    # «Pedido en camino»: automático para los libros con filas abiertas en «Importaciones». A los libros sin filas
    # abiertas que recibieron hoy un embarque se les resta lo que llegó.
    viene = importaciones_mod.en_camino(imp)
    llego = pendientes_imp[~pendientes_imp["id"].isin(viene.index)].groupby("id")["cantidad"].sum()
    if len(viene) or len(llego):
        cantidades = cantidades.copy()
        antes = cantidades.set_index("id")["en_camino"].astype(int)
        con_filas = cantidades["id"].isin(viene.index)
        cantidades.loc[con_filas, "en_camino"] = cantidades.loc[con_filas, "id"].map(viene).astype(int)
        recibio = cantidades["id"].isin(llego.index)
        cantidades.loc[recibio, "en_camino"] = (cantidades.loc[recibio, "en_camino"].astype(int)
                                                - cantidades.loc[recibio, "id"].map(llego)).clip(lower=0).astype(int)
        ahora = cantidades.set_index("id")["en_camino"].astype(int)
        cambiados = cambiados | {i for i in ahora.index if antes.get(i) != ahora.get(i)}
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

    todos = pd.concat([mov, nuevos, ventas_mod.a_movimientos(ventas), importaciones_mod.a_movimientos(imp)], ignore_index=True)
    transito = cantidades[["id", "en_camino"]].rename(columns={"en_camino": "cantidad"})
    costos = configuracion_automatica(fuente, imp, catalogo, hoy)
    r = calcular(catalogo, todos, transito, costos, p, hoy,
                 envios=dict(zip(envios["origen"], envios["costo_usd"])), hoja_ventas=ventas, fecha_lista=leer_fecha_lista(), importaciones=imp)

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
                                idx["categoria"]: 190, idx["categoria_gestion"]: 110, idx["precio_lista"]: 95, idx["bodega"]: 80, idx["consignacion"]: 105,
                                idx["en_camino"]: 95, idx["actualizado"]: 105, idx["se_vende"]: 125, idx["que_hacer"]: 190, idx["notas"]: 240})
    else:
        faltan = completa[~completa["id"].isin(inv["id"])]
        if len(faltan):  # libros nuevos del sitio: se agregan al final
            fuente.agregar_filas("Inventario", faltan.rename(columns=nombres))
        fuente.actualizar_columnas("Inventario", completa.set_index("id").rename(columns=nombres),
                                   [nombres[c] for c in AUTOMATICAS], nombres["id"])
        # Solo las celdas que cambiaron por ventas o importaciones (no se pisa lo que Roberto esté editando en otras filas)
        nuevas = cantidades.set_index("id")
        fuente.actualizar_celdas("Inventario", nombres["id"], {i: {nombres["bodega"]: int(nuevas.at[i, "bodega"]),
                                                                    nombres["consignacion"]: int(nuevas.at[i, "consignacion"]),
                                                                    nombres["en_camino"]: int(nuevas.at[i, "en_camino"])}
                                                                for i in cambiados if i in nuevas.index})
        fuente.notas_encabezado("Inventario", {nombres[c]: t for c, t in NOTAS_INVENTARIO.items()})

    fuente.escribir("Lista de libros", lista_libros(catalogo), oculta=True, solo_lectura=True)
    if fuente.hoja("Ventas") is None:
        preparar_ventas(fuente)
    fuente.escribir_celdas("Ventas", lenguaje.ENCABEZADOS["Ventas"]["descontado"], marcas)
    if fuente.hoja("Importaciones") is None:
        preparar_importaciones(fuente, [o.nombre for o in p.origenes])
    fuente.escribir_celdas("Importaciones", lenguaje.ENCABEZADOS["Importaciones"]["sumado"], marcas_imp)

    semana = lenguaje.esta_semana(r.titulos, r.pedido_resumen, r.pedido, r.fecha_corte, r.errores, r.perdidas, sin_anotar,
                                  r.conteo, r.caducidad, r.tl)
    hoja_semana = lenguaje.hoja_esta_semana(semana)
    fuente.escribir("Esta semana", hoja_semana, solo_lectura=True, secciones=True, anchos={0: 380, 1: 560},
                    filas_seccion=hoja_semana.attrs["secciones"])
    hp = lenguaje.hoja_pedido(r.pedido, r.pedido_resumen.attrs["combinaciones"], r.pedido_resumen.attrs["envios"],
                              r.fecha_corte, fuente.separador, r.pedido_resumen)
    fuente.escribir("Pedido", hp["filas"], solo_lectura=True, secciones=True, celdas_editables=hp["editables"],
                    negritas=hp["negritas"], formatos_rango=hp["formatos"],
                    anchos={0: 230, 1: 300, 2: 120, 3: 320, 4: 110, 5: 110, 6: 380, 7: 90})
    fuente.escribir("Análisis técnico", r.titulos, oculta=True, solo_lectura=True)
    fuente.escribir("Indicadores", r.resumen, oculta=True, solo_lectura=True, anchos={0: 360, 1: 420})
    fuente.ordenar(ORDEN_PESTANAS, visibles=VISIBLES)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(prog="inventario", description="Categorías A a D, demanda, nivel objetivo y pedido por embarque")
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
    ap.add_argument("--disponibilidad", type=Path,
                    help="escribe el estado de cada libro para el sitio (src/_data/disponibilidad.json), sin cantidades")
    ap.add_argument("--cifrar", action="store_true", help="cifra los datos del panel con la contraseña de la variable CLAVE_PANEL")
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
        imp = fuente.leer("Importaciones")
        movimientos = pd.concat([fuente.leer("Movimientos"), ventas_mod.a_movimientos(ventas),
                                 importaciones_mod.a_movimientos(imp)], ignore_index=True)
        viene = importaciones_mod.en_camino(imp)
        transito = fuente.leer("EnTransito")
        transito = pd.concat([transito[~transito["id"].isin(viene.index)][["id", "cantidad"]],
                              viene.rename("cantidad").reset_index()], ignore_index=True)
        r = calcular(catalogo, movimientos, transito, fuente.leer("Costos"),
                     p, pd.Timestamp(a.fecha_corte) if a.fecha_corte else None,
                     envios=dict(zip(envios["origen"], envios["costo_usd"])), hoja_ventas=ventas, fecha_lista=leer_fecha_lista(), importaciones=imp)
        fuente.escribir("Resultado_Titulos", r.titulos)
        fuente.escribir("Resultado_Pedido", r.pedido)
        fuente.escribir("Comparacion_envios", pd.DataFrame(r.pedido_resumen.attrs["combinaciones"]))
        fuente.escribir("Resumen", r.resumen)
        fuente.escribir("Categorias", r.categorias)
        fuente.escribir("Esta_semana", lenguaje.hoja_esta_semana(
            lenguaje.esta_semana(r.titulos, r.pedido_resumen, r.pedido, r.fecha_corte, r.errores, r.perdidas,
                                 conteo=r.conteo, caducidad=r.caducidad, tl=r.tl)))

    if a.disponibilidad:
        a.disponibilidad.parent.mkdir(parents=True, exist_ok=True)
        a.disponibilidad.write_text(json.dumps(datos_disponibilidad(r), ensure_ascii=False), encoding="utf-8")

    if a.panel:
        a.panel.parent.mkdir(parents=True, exist_ok=True)
        etiqueta = a.etiqueta if a.etiqueta is not None else ("Datos de ejemplo (sintéticos)" if a.fuente == "ejemplo" else "")
        datos = datos_panel(r, etiqueta)
        if a.cifrar:
            from .cifrado import cifrar
            if not os.environ.get("CLAVE_PANEL"):
                raise SystemExit("Falta la contraseña del panel: define la variable CLAVE_PANEL.")
            datos = cifrar(datos, os.environ["CLAVE_PANEL"])
        elif a.fuente == "sheets" and os.environ.get("GITHUB_ACTIONS"):
            # El sitio es público: los datos reales nunca se publican sin cifrar
            raise SystemExit("Los datos de la planilla solo se publican cifrados: usa --cifrar.")
        a.panel.write_text(json.dumps(datos, ensure_ascii=False, default=str), encoding="utf-8")

    if a.fuente == "sheets":
        # Los registros de GitHub Actions de un repositorio público son públicos: no imprimir datos reales.
        print(f"Resultados escritos en la planilla (corte {r.fecha_corte.date()}). Revisa la pestaña «Esta semana».")
        return
    print(f"Fuente: {fuente.describir()} · corte {r.fecha_corte.date()}")
    for fila in r.resumen.itertuples(index=False):
        print(f"  {fila.indicador}: {fila.valor}")


if __name__ == "__main__":
    main()
