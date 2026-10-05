"""Pedido sugerido y elección de dónde comprar cada libro.

1. Cada título con política Reponer o Stock mínimo necesita lo que le falta para llegar a su stock objetivo.
2. Un libro puede comprarse en más de un origen (columna «Se compra en»). Para cada origen hay dos valores
   por ejemplar (pestaña Configuración, según origen de compra y edición del libro):
     - costo puesto en bodega: decide dónde conviene comprar (incluye flete, seguro e impuestos);
     - valor FOB: es lo que se le paga a la editorial y lo que cuenta para el mínimo de embarque.
3. Se prueban todas las combinaciones de envíos (ninguno, solo uno, varios). En cada una, cada libro va al origen
   con menor costo puesto en bodega entre los que se envían; un envío solo vale si alcanza su mínimo FOB,
   completándolo si hace falta con demanda adelantada de títulos A y B. Lo que no cabe se posterga.
4. Se elige la combinación de menor costo total: lo que se compra ahora, más lo adelantado × costo_adelantar, más lo
   postergado a su costo más bajo con un recargo de costo_postergar × su precio neto (el costo de esperar), más el
   costo fijo de cada envío que se hace (courier, despacho, trámites; lo anota Roberto en «Pedido sugerido»).
   Con dos orígenes son cuatro combinaciones: el óptimo es exacto.

El costo fijo de los envíos no cambia qué libros van en cada combinación, solo cuál conviene. Por eso la planilla
puede recalcular la recomendación al instante con fórmulas: total = costo de la combinación + sus envíos.
"""
from __future__ import annotations

import itertools
import math

import pandas as pd

from .clasificacion_abc import IVA
from .config import SEMANAS_POR_MES, Parametros

DIAS_POR_MES = 30.44
SEPARADORES = (" o ", ",", "/", " y ")
EDICION_GENERAL = {"", "todas"}
NAN = math.nan


def opciones_compra(texto: str, editorial: str) -> list[str]:
    """«España o Argentina» → ["España", "Argentina"]. Vacío → la editorial del libro."""
    partes = [texto.strip() if isinstance(texto, str) else ""]
    for sep in SEPARADORES:
        partes = [p for trozo in partes for p in trozo.split(sep)]
    return [p.strip() for p in partes if p.strip()] or [editorial]


def fila_costos(costos: pd.DataFrame, compra: str, edicion: str):
    """Fila de Configuración para comprar en `compra` un libro de la edición `edicion`.

    Busca primero la fila de esa edición y, si no hay, la fila general del origen (edición vacía o «Todas»).
    """
    c = costos[costos["origen"] == compra]
    if "edicion" in c.columns:
        ed = c["edicion"].astype(str).str.strip()
        exacta, general = c[ed == edicion], c[ed.str.lower().isin(EDICION_GENERAL)]
        c = exacta if len(exacta) else general
    return None if c.empty else c.iloc[0]


def costos_unitarios(precio_lista: float, costos: pd.DataFrame, compra: str, edicion: str) -> tuple[float, float]:
    """(costo puesto en bodega, valor FOB) de un ejemplar, en dólares. NaN si falta configuración."""
    f = fila_costos(costos, compra, edicion)
    if f is None:
        return NAN, NAN
    tc = pd.to_numeric(f.get("tipo_cambio"), errors="coerce")
    if pd.isna(tc) or not tc:
        return NAN, NAN
    neto_usd = precio_lista / (1 + IVA) / tc
    fob = pd.to_numeric(f.get("fob_sobre_precio_neto"), errors="coerce")
    bodega = pd.to_numeric(f.get("costo_sobre_precio_neto"), errors="coerce")
    fob = NAN if pd.isna(fob) else neto_usd * fob
    bodega = fob if pd.isna(bodega) else neto_usd * bodega  # sin costo en bodega, se compara por FOB
    return bodega, fob


def _usd(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def _neto_usd(precio_lista: float, costos: pd.DataFrame) -> float:
    tc = pd.to_numeric(costos["tipo_cambio"], errors="coerce").dropna() if len(costos) else pd.Series(dtype=float)
    return precio_lista / (1 + IVA) / (float(tc.iloc[0]) if len(tc) else 950.0)


def nombre_combinacion(envia: list[str]) -> str:
    if not envia:
        return "No pedir nada ahora"
    if len(envia) == 1:
        return f"Todo a {envia[0]}"
    return "Dividir: " + " y ".join(envia) + f" ({len(envia)} envíos)"


def sugerir(titulos: pd.DataFrame, costos: pd.DataFrame, p: Parametros, fecha_corte: pd.Timestamp,
            envios: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (líneas del pedido, resumen por origen).

    envios: costo fijo de cada envío en dólares, por origen (vacío = 0).
    El resumen trae en .attrs el ahorro, los postergados y la comparación de combinaciones («combinaciones»).
    """
    envios = {o: float(v or 0) for o, v in (envios or {}).items()}
    if not len(costos):
        costos = pd.DataFrame(columns=["origen", "edicion", "fob_sobre_precio_neto", "costo_sobre_precio_neto", "tipo_cambio"])
    configurados = [o.nombre for o in p.origenes]
    revision_meses = p.revision_semanas / SEMANAS_POR_MES

    def opciones(f) -> dict:
        return {o: costos_unitarios(f.precio_lista, costos, o, f.origen)
                for o in opciones_compra(getattr(f, "compra_en", ""), f.origen)}

    necesidades = [(f, int(f.sugerido), opciones(f)) for f in titulos.itertuples() if f.sugerido > 0]
    adelantables = sorted(
        [(f, int(math.ceil(f.pronostico_mensual * revision_meses)), opciones(f)) for f in titulos.itertuples()
         if f.politica == "Reponer" and f.abc in ("A", "B") and f.pronostico_mensual > 0],
        key=lambda x: (x[0].abc, -x[0].valor_venta))
    origenes = sorted({o for _, _, ops in necesidades for o in ops} | set(configurados),
                      key=lambda o: (configurados.index(o) if o in configurados else 99, o))
    opciones_de = {f.id: ops for f, _, ops in necesidades}

    def mas_barato(ops: dict, permitidos=None):
        validas = {o: v for o, v in ops.items() if not math.isnan(v[0]) and (permitidos is None or o in permitidos)}
        return min(validas, key=lambda o: validas[o][0]) if validas else None

    def evaluar(activos: tuple) -> dict:
        lineas, postergados = [], []
        fob = {o: 0.0 for o in activos}
        costo = castigo = 0.0
        for f, cant, ops in necesidades:
            o = mas_barato(ops, activos)
            sin_costo = [k for k in ops if k in activos and math.isnan(ops[k][0])]
            if o:
                lineas.append((f, cant, o, ops, "necesidad"))
                fob[o] += (ops[o][1] if not math.isnan(ops[o][1]) else 0) * cant
                costo += ops[o][0] * cant
            elif sin_costo:  # origen activo pero sin costos configurados: se pide igual, sin valorizar
                lineas.append((f, cant, sin_costo[0], ops, "necesidad"))
            else:
                postergados.append((f, cant))
        for o in activos:
            minimo = p.origen(o).minimo_embarque_usd
            for f, extra, ops in adelantables:
                if fob[o] >= minimo or fob[o] == 0:
                    break
                bodega, valor = ops.get(o, (NAN, NAN))
                if extra <= 0 or math.isnan(valor):
                    continue
                lineas.append((f, extra, o, ops, "adelanto"))
                fob[o] += valor * extra
                castigo += bodega * extra * p.costo_adelantar
        valido = all(fob[o] == 0 or fob[o] >= p.origen(o).minimo_embarque_usd for o in activos)
        # Lo postergado igual se comprará después: cuesta lo más barato posible más el castigo por la espera
        for f, cant in postergados:
            o = mas_barato(opciones_de[f.id])
            costo += (opciones_de[f.id][o][0] if o else 0.0) * cant
            castigo += _neto_usd(f.precio_lista, costos) * cant * p.costo_postergar
        envia = [o for o in activos if any(l[2] == o for l in lineas)]
        return {"activos": activos, "envia": envia, "lineas": lineas, "postergados": postergados, "valido": valido,
                "libros": costo, "castigo": castigo, "envio": sum(envios.get(o, 0.0) for o in envia),
                "costo": costo + castigo + sum(envios.get(o, 0.0) for o in envia)}

    escenarios = [evaluar(c) for n in range(len(origenes) + 1) for c in itertools.combinations(origenes, n)]
    # Combinaciones que terminan enviando a los mismos orígenes son la misma opción: queda la más barata
    unicas = {}
    for e in escenarios:
        k = tuple(e["envia"])
        if k not in unicas or (round(e["costo"], 2), len(e["activos"])) < (round(unicas[k]["costo"], 2), len(unicas[k]["activos"])):
            unicas[k] = e
    escenarios = sorted(unicas.values(), key=lambda e: (len(e["envia"]) == 0, len(e["envia"]),
                                                         [origenes.index(o) for o in e["envia"]]))
    mejor = min((e for e in escenarios if e["valido"]), key=lambda e: (round(e["costo"], 2), len(e["activos"])))

    def linea(cuando, o, f, cant, motivo, ops):
        valor = ops.get(o, (NAN, NAN))[1]
        return {"cuando": cuando, "origen": o, "id": f.id, "isbn": f.isbn, "titulo": f.titulo, "abc": f.abc,
                "cantidad": cant, "motivo": motivo, "costo_unitario_usd": "" if math.isnan(valor) else round(valor, 2),
                "subtotal_usd": "" if math.isnan(valor) else round(valor * cant, 2)}

    filas, ahorro = [], 0.0
    for f, cant, o, ops, tipo in mejor["lineas"]:
        if tipo == "adelanto":
            motivo = "Adelanto para completar el mínimo de embarque"
        else:
            motivo = "Mantener un ejemplar (stock mínimo)" if f.politica == "Stock mínimo" else "Bajo el stock objetivo"
            otras = {k: v for k, v in ops.items() if k != o and not math.isnan(v[0])}
            if otras and not math.isnan(ops[o][0]):
                otra = min(otras, key=lambda k: otras[k][0])
                aqui, alla = _usd(ops[o][0]), _usd(otras[otra][0])
                if ops[o][0] <= otras[otra][0]:
                    motivo += f"; conviene {o}: US$ {aqui} puesto en bodega contra US$ {alla} en {otra}"
                else:
                    motivo += (f"; en {otra} sale más barato (US$ {alla} contra {aqui} puesto en bodega), "
                               f"pero ese envío no alcanza el mínimo y conviene sumarlo al de {o}")
            propia = ops.get(f.origen, (NAN, NAN))[0]
            if o != f.origen and not math.isnan(propia) and not math.isnan(ops[o][0]):
                ahorro += (propia - ops[o][0]) * cant
        previa = next((l for l in filas if l["origen"] == o and l["id"] == f.id), None)
        if previa:
            previa["cantidad"] += cant
            previa["motivo"] += " + adelanto para completar el mínimo"
            valor = ops.get(o, (NAN, NAN))[1]
            previa["subtotal_usd"] = "" if math.isnan(valor) else round(valor * previa["cantidad"], 2)
        else:
            filas.append(linea("Ahora", o, f, cant, motivo, ops))

    # Lo postergado, en el origen donde sería más barato (explica por qué se espera)
    necesario, unidades_nec = {}, {}
    for f, cant in mejor["postergados"]:
        ops = opciones_de[f.id]
        o = mas_barato(ops) or f.origen
        base = "Mantener un ejemplar (stock mínimo)" if f.politica == "Stock mínimo" else "Bajo el stock objetivo"
        filas.append(linea("Próximo envío", o, f, cant, base + f"; esperar: el envío a {o} todavía no alcanza el mínimo", ops))
        valor = ops.get(o, (NAN, NAN))[1]
        necesario[o] = necesario.get(o, 0) + (0 if math.isnan(valor) else valor * cant)
        unidades_nec[o] = unidades_nec.get(o, 0) + cant

    resumen = []
    for o in origenes:
        grupo = titulos[titulos["origen"] == o]
        reponer = grupo[(grupo["politica"] == "Reponer") & (grupo["pronostico_mensual"] > 0)]
        dias = ((reponer["posicion"] - reponer["punto_pedido"]) / reponer["pronostico_mensual"] * DIAS_POR_MES).clip(lower=0)
        dias_min = float(dias.min()) if len(dias) else NAN
        ahora = [l for l in filas if l["origen"] == o and l["cuando"] == "Ahora"]
        if o not in configurados and not ahora and o not in unidades_nec:
            continue
        if ahora:
            estado, fecha = "Pedir ahora", fecha_corte
            total, unidades = sum(l["subtotal_usd"] or 0 for l in ahora), sum(l["cantidad"] for l in ahora)
        elif o in unidades_nec:
            estado = "Acumular: no alcanza el mínimo"
            fecha = fecha_corte + pd.Timedelta(weeks=p.revision_semanas)
            total, unidades = necesario[o], unidades_nec[o]
        elif not math.isnan(dias_min):
            estado = f"Sin pedido: el primer título llega a su punto de pedido en {int(dias_min)} días"
            fecha, total, unidades = fecha_corte + pd.Timedelta(days=dias_min), 0.0, 0
        else:
            estado, fecha, total, unidades = "Sin pedido", None, 0.0, 0
        resumen.append({"origen": o, "estado": estado, "titulos": len(ahora), "unidades": unidades,
                        "total_usd": round(total, 2), "minimo_usd": p.origen(o).minimo_embarque_usd,
                        "fecha_sugerida": fecha.date().isoformat() if fecha is not None else "",
                        "costos_configurados": bool((costos["origen"] == o).any())})
    resumen = pd.DataFrame(resumen)
    resumen.attrs["ahorro_usd"] = round(ahorro, 2)
    resumen.attrs["postergados"] = [(f.id, f.titulo, c) for f, c in mejor["postergados"]]
    resumen.attrs["envios"] = {o: envios.get(o, 0.0) for o in origenes if o in configurados or o in envios
                               or any(o in e["envia"] for e in escenarios)}
    resumen.attrs["combinaciones"] = [{
        "nombre": nombre_combinacion(e["envia"]),
        "envia": e["envia"],
        "elegida": e is mejor,
        "valida": e["valido"],
        "libros_ahora": sum(l[1] for l in e["lineas"]),
        "adelantados": sum(l[1] for l in e["lineas"] if l[4] == "adelanto"),
        "para_despues": sum(c for _, c in e["postergados"]),
        "libros_usd": round(e["libros"], 2),
        "castigo_usd": round(e["castigo"], 2),
        "envio_usd": round(e["envio"], 2),
        "total_usd": round(e["costo"], 2),
    } for e in escenarios]
    columnas = ["cuando", "origen", "id", "isbn", "titulo", "abc", "cantidad", "motivo", "costo_unitario_usd", "subtotal_usd"]
    return pd.DataFrame(filas, columns=columnas), resumen
