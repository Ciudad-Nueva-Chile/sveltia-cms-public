"""Pedido por embarque programado y elección de dónde comprar cada libro (memoria, sección 4.2.5).

1. Cada origen tiene un embarque cada T meses (`intervalo_embarque_meses`). El próximo es la fecha de su última
   importación más T. Sin importaciones registradas, el embarque se considera vencido (pedir ahora).
2. Las necesidades salen de la política (politica.py): títulos A y B con Sugerido > 0.
3. Un libro puede comprarse en más de un origen (columna «Se compra en»). Para cada origen hay dos valores por
   ejemplar (pestaña Configuración, según origen de compra y edición del libro):
     - costo puesto en bodega: solo para valorizar lo que se repone (trae el flete histórico, así que no se compara);
     - valor FOB: es lo que se le paga a la editorial.
4. Se comparan las combinaciones de envíos que cubren TODAS las necesidades (Todo desde España, Todo desde Argentina,
   Dividir). En cada una, cada libro va al origen con menor valor FOB entre los que envían:
       Total = Σ cantidad × valor FOB + Σ costo de cada envío que se hace
   El flete entra una sola vez: en «Envíos», no en «Libros».
   El costo de cada envío es la cotización que anota Roberto en «Pedido sugerido». Si la celda está vacía o en 0, se estima
   por peso: ejemplares × peso (el de la ficha o el promedio del origen), con la tarifa de `config/parametros.yml`, sin IVA,
   impuestos ni recargos. Se elige el menor Total (empate: menos envíos).
5. El pedido que toca se pide aunque sea chico: el costo fijo del embarque ya está en el cálculo de T (memoria 4.2.5).
6. Fecha del próximo pedido: con meses fijos (`meses_embarque`; Argentina, febrero, mayo, agosto y noviembre, el de agosto
   junto con los calendarios), el
   siguiente de esos meses; el mes en curso cuenta mientras no haya llegado su embarque. Sin meses fijos (España), la
   última llegada de «Importaciones» más T.
"""
from __future__ import annotations

import itertools
import math

import pandas as pd

from .categorias import IVA
from .config import Parametros
from .stock import llegadas_reales

SEPARADORES = (" o ", ",", "/", " y ")
EDICION_GENERAL = {"", "todas"}
NAN = math.nan
COTIZACION, ESTIMADO = "cotización anotada", "estimado por peso"
LIMITE_KG, LIMITE_FOB_USD = 50, 3000     # sobre estos valores, un envío estimado se avisa para pedir cotización
DIAS_ANTICIPACION = 30   # un embarque que vence en los próximos 30 días se pide ahora


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
    """(costo puesto en bodega, valor FOB) de un ejemplar, en dólares. NaN si falta configuración.

    Precio neto = precio con IVA / 1,19. Los factores reales («Costo en bodega / precio neto», «FOB / precio neto»)
    y el tipo de cambio viven en la planilla privada, no en el repositorio.
    """
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


def tarifa_envio(envio: dict | None, kg: float) -> float:
    """Costo de un envío de `kg` kilos, en la moneda de la tarifa. Sin IVA, impuestos ni recargos.

    Con tabla (`tarifa`), el valor del peso redondeado hacia arriba al paso; pasado el último valor, `incremento_sobre_tabla`
    por paso. Sin tabla, `fijo` + `por_kg` × kilos."""
    if not envio or kg <= 0:
        return 0.0
    if envio.get("tarifa"):
        tabla, paso = envio["tarifa"], float(envio.get("paso_kg", 0.5))
        n = math.ceil(round(kg / paso, 6))
        if n <= len(tabla):
            return float(tabla[n - 1])
        return float(tabla[-1]) + (n - len(tabla)) * float(envio.get("incremento_sobre_tabla", 0))
    return float(envio.get("fijo", 0)) + float(envio.get("por_kg", 0)) * kg


def peso_por_ejemplar(f, origen) -> float:
    """El «Peso (kg)» de la ficha o, si no tiene, el promedio del origen donde se compra."""
    peso = pd.to_numeric(getattr(f, "peso_kg", None), errors="coerce")
    return float(peso) if pd.notna(peso) and peso > 0 else float(origen.peso_medio_kg or 0)


def _usd(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def nombre_combinacion(envia: list[str]) -> str:
    if len(envia) == 1:
        return f"Todo desde {envia[0]}"
    return "Dividir: " + " y ".join(f"desde {o}" for o in envia) + f" ({len(envia)} envíos)"


def proximo_mes_fijo(meses: list[int], fecha_corte: pd.Timestamp, ultima=None) -> pd.Timestamp:
    """Primer día del próximo mes de pedido. Si hoy es un mes de pedido y su embarque todavía no llega, es este mes."""
    inicio = pd.Timestamp(fecha_corte.year, fecha_corte.month, 1)
    if fecha_corte.month in meses and (ultima is None or pd.Timestamp(ultima) < inicio):
        return inicio
    return min(c for c in (pd.Timestamp(fecha_corte.year + a, m, 1) for a in (0, 1) for m in meses) if c > fecha_corte)


def proximos_embarques(mov: pd.DataFrame, catalogo: pd.DataFrame, p: Parametros, fecha_corte: pd.Timestamp,
                       ultimas_llegadas: dict | None = None, intervalos: dict | None = None) -> dict:
    """{origen: (fecha de la última importación o None, fecha del próximo embarque)} para los orígenes configurados.

    Si la pestaña «Importaciones» tiene llegadas de un país (`ultimas_llegadas`), se usa la última, con el país real de
    compra. Si no, la importación se atribuye al origen (editorial) del título, porque el registro no dice desde dónde
    llegó. Todo origen distinto de Argentina se trata como España. `intervalos`: T por país, si se midió.
    """
    ultimas_llegadas = ultimas_llegadas or {}
    intervalos = intervalos or {}
    origen_de = catalogo.drop_duplicates("id").set_index("id")["origen"]
    imp = llegadas_reales(mov)
    imp = imp[imp["fecha"] <= fecha_corte].copy()
    imp["origen"] = imp["id"].map(origen_de).map(lambda o: "Argentina" if o == "Argentina" else "España")
    salida = {}
    for o in p.origenes:
        pais = "Argentina" if o.nombre == "Argentina" else "España"
        if pais in ultimas_llegadas:
            ultima = pd.Timestamp(ultimas_llegadas[pais])
        else:
            fechas = imp.loc[imp["origen"] == pais, "fecha"]
            ultima = fechas.max() if len(fechas) else None
        T = intervalos.get(o.nombre, p.intervalo_meses(o.nombre))
        meses = sorted(int(m) for m in (getattr(o, "meses_embarque", None) or []))
        if meses:
            proximo = proximo_mes_fijo(meses, fecha_corte, ultima)
        elif ultima is None:
            proximo = fecha_corte
        else:
            proximo = ultima + pd.Timedelta(days=round(T * 30.44))
        salida[o.nombre] = (ultima, pd.Timestamp(proximo).normalize())
    return salida


def sugerir(titulos: pd.DataFrame, costos: pd.DataFrame, p: Parametros, fecha_corte: pd.Timestamp,
            envios: dict | None = None, embarques: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (líneas del pedido, resumen por origen).

    titulos: una fila por título con sugerido, politica, categoria_gestion, tasa_mensual, unidades_ventana, precio_lista.
    envios: cotización anotada de cada envío en dólares, por origen. Vacía o en 0, se usa el costo estimado del origen.
    embarques: salida de proximos_embarques(); sin ella, todos los embarques se consideran vencidos.
    El resumen trae en .attrs: combinaciones, envios (el costo que se usó), envios_anotados, envios_estimados,
    envios_fuente («cotización anotada» o «costo estimado») y ahorro.
    """
    anotados = {o: float(v or 0) for o, v in (envios or {}).items()}
    embarques = embarques or {o.nombre: (None, fecha_corte) for o in p.origenes}
    if not len(costos):
        costos = pd.DataFrame(columns=["origen", "edicion", "fob_sobre_precio_neto", "costo_sobre_precio_neto", "tipo_cambio"])

    # Pesos por dólar / pesos por euro de «Configuración»: para mostrar España en € y convertir su costo de envío
    def eur_por_usd(o: str) -> float:
        if "tipo_cambio_eur" not in costos:
            return NAN
        f = costos[costos["origen"] == o]
        tc = pd.to_numeric(f["tipo_cambio"], errors="coerce").dropna()
        te = pd.to_numeric(f["tipo_cambio_eur"], errors="coerce").dropna()
        return float(tc.iloc[0] / te.iloc[0]) if len(tc) and len(te) and te.iloc[0] else NAN

    def estimado_usd(o: str, kg: float) -> float:
        """Costo estimado por peso, en dólares. Los euros se convierten con «Configuración»; sin tipo de cambio, 0 (se avisa)."""
        envio = p.origen(o).envio or {}
        monto = tarifa_envio(envio, kg)
        if envio.get("moneda", "USD") != "EUR":
            return round(monto, 2)
        k = eur_por_usd(o)
        return 0.0 if math.isnan(k) or not k else round(monto / k, 2)

    configurados = [o.nombre for o in p.origenes]

    def opciones(f) -> dict:
        return {o: costos_unitarios(f.precio_lista, costos, o, f.origen)
                for o in opciones_compra(getattr(f, "compra_en", ""), f.origen)}

    necesidades = [(f, int(f.sugerido), opciones(f)) for f in titulos.itertuples() if f.sugerido > 0]
    origenes = sorted({o for _, _, ops in necesidades for o in ops} | set(configurados),
                      key=lambda o: (configurados.index(o) if o in configurados else 99, o))

    def mejor_en(ops: dict, permitidos) -> str | None:
        en = [o for o in ops if o in permitidos]
        if not en:
            return None
        con_fob = [o for o in en if not math.isnan(ops[o][1])]
        return min(con_fob, key=lambda o: ops[o][1]) if con_fob else en[0]

    def evaluar(activos: tuple) -> dict:
        lineas, libros, cubre, pesos = [], 0.0, True, {}
        for f, cant, ops in necesidades:
            o = mejor_en(ops, activos)
            if o is None:
                cubre = False
                continue
            lineas.append((f, cant, o, ops))
            libros += 0.0 if math.isnan(ops[o][1]) else ops[o][1] * cant    # solo FOB: el flete va en «Envíos»
            pesos[o] = pesos.get(o, 0.0) + cant * peso_por_ejemplar(f, p.origen(o))
        envia = [o for o in activos if any(l[2] == o for l in lineas)]
        estimados = {o: estimado_usd(o, pesos.get(o, 0.0)) for o in envia}
        envio = sum(anotados.get(o, 0.0) or estimados[o] for o in envia)
        return {"activos": activos, "envia": envia, "lineas": lineas, "cubre": cubre, "pesos": pesos, "estimados": estimados,
                "libros": libros, "envio": envio, "total": libros + envio}

    evaluadas = [evaluar(c) for n in range(1, len(origenes) + 1) for c in itertools.combinations(origenes, n)]
    unicas = {}
    for e in evaluadas:
        if not e["cubre"] or not e["envia"]:
            continue
        k = tuple(e["envia"])
        if k not in unicas or e["total"] < unicas[k]["total"]:
            unicas[k] = e
    combinaciones = sorted(unicas.values(), key=lambda e: (len(e["envia"]), [origenes.index(o) for o in e["envia"]]))
    mejor = min(combinaciones, key=lambda e: (round(e["total"], 2), len(e["envia"]))) if combinaciones else evaluar(tuple(origenes))

    def cuando(o: str) -> str:
        _, proximo = embarques.get(o, (None, fecha_corte))
        if proximo <= fecha_corte + pd.Timedelta(days=DIAS_ANTICIPACION):
            return "Ahora"
        return "Próximo embarque " + proximo.strftime("%d-%m-%Y")

    filas, ahorro = [], 0.0
    for f, cant, o, ops in mejor["lineas"]:
        motivo = {"Reponer": "Bajo el nivel objetivo S", "Reponer lo vendido": "Reponer lo vendido desde el embarque anterior",
                  "Temporada": "Pedido de temporada, debe llegar antes de septiembre"}.get(f.politica, f.politica)
        otras = {k: v for k, v in ops.items() if k != o and not math.isnan(v[1])}
        if otras and not math.isnan(ops[o][1]):
            otra = min(otras, key=lambda k: otras[k][1])
            aqui, alla = _usd(ops[o][1]), _usd(otras[otra][1])
            if ops[o][1] <= otras[otra][1]:
                motivo += f". Conviene desde {o}: US$ {aqui} FOB contra US$ {alla} desde {otra}"
            else:
                motivo += f". Desde {otra} sale más barato (US$ {alla} contra {aqui}), pero la combinación de envíos conviene así"
        propia = ops.get(f.origen, (NAN, NAN))[1]
        if o != f.origen and not math.isnan(propia) and not math.isnan(ops[o][1]):
            ahorro += (propia - ops[o][1]) * cant
        valor = ops[o][1]
        filas.append({"cuando": cuando(o), "origen": o, "id": f.id, "isbn": f.isbn, "titulo": f.titulo,
                      "categoria": f.categoria_gestion, "cantidad": cant, "motivo": motivo,
                      "costo_unitario_usd": "" if math.isnan(valor) else round(valor, 2),
                      "subtotal_usd": "" if math.isnan(valor) else round(valor * cant, 2)})

    # España factura en euros: sus montos también en €
    def eur_de(o: str) -> float:
        return eur_por_usd(o) if o == "España" else NAN

    for l in filas:
        k = eur_de(l["origen"])
        l["subtotal_eur"] = "" if math.isnan(k) or l["subtotal_usd"] == "" else round(l["subtotal_usd"] * k, 2)

    # Resumen por origen
    resumen = []
    for o in origenes:
        lineas_o = [l for l in filas if l["origen"] == o]
        if o not in configurados and not lineas_o:
            continue
        ultima, proximo = embarques.get(o, (None, fecha_corte))
        total = round(sum(l["subtotal_usd"] or 0 for l in lineas_o), 2)
        estado = "Pedir en el embarque" if lineas_o else "Sin pedido"
        peso = round(mejor["pesos"].get(o, 0.0), 1)
        anotado = anotados.get(o, 0.0)
        envio_o = anotado or mejor["estimados"].get(o, 0.0) if lineas_o else 0.0
        aviso = ""
        if lineas_o and not anotado and (peso > LIMITE_KG or total > LIMITE_FOB_USD):
            aviso = (f"El envío estimado desde {o} supera {LIMITE_KG} kg o US$ {LIMITE_FOB_USD:,} FOB".replace(",", ".")
                     + ": pide una cotización y anótala en «Pedido sugerido».")
        resumen.append({"origen": o, "estado": estado, "titulos": len(lineas_o), "unidades": sum(l["cantidad"] for l in lineas_o),
                        "total_usd": total, "peso_kg": peso, "envio_usd": round(envio_o, 2),
                        "envio_fuente": (COTIZACION if anotado else ESTIMADO) if lineas_o else "", "aviso_envio": aviso,
                        "total_eur": "" if math.isnan(eur_de(o)) else round(total * eur_de(o), 2),
                        "ultima_importacion": ultima.date().isoformat() if ultima is not None else "",
                        "proximo_embarque": proximo.date().isoformat(), "intervalo_meses": p.intervalo_meses(o),
                        "costos_configurados": bool((costos["origen"] == o).any())})
    resumen = pd.DataFrame(resumen)
    resumen.attrs["ahorro_usd"] = round(ahorro, 2)
    usados = [o for o in origenes if o in configurados or o in anotados or any(o in e["envia"] for e in combinaciones)]
    resumen.attrs["envios_anotados"] = {o: anotados.get(o, 0.0) for o in usados}
    resumen.attrs["envios_estimados"] = {o: mejor["estimados"].get(o, 0.0) for o in usados}
    resumen.attrs["envios"] = {o: anotados.get(o, 0.0) or mejor["estimados"].get(o, 0.0) for o in usados}
    resumen.attrs["envios_pesos"] = {o: round(mejor["pesos"].get(o, 0.0), 1) for o in usados}
    resumen.attrs["envios_fuente"] = {o: COTIZACION if anotados.get(o, 0.0) > 0 else ESTIMADO for o in usados}
    resumen.attrs["combinaciones"] = [{
        "nombre": nombre_combinacion(e["envia"]), "envia": e["envia"], "elegida": e is mejor, "valida": True,
        "libros_ahora": sum(l[1] for l in e["lineas"]), "libros_usd": round(e["libros"], 2),
        "estimados": e["estimados"], "pesos": {o: round(k, 1) for o, k in e["pesos"].items()},
        "envio_usd": round(e["envio"], 2), "total_usd": round(e["total"], 2),
    } for e in combinaciones]
    columnas = ["cuando", "origen", "id", "isbn", "titulo", "categoria", "cantidad", "motivo", "costo_unitario_usd", "subtotal_usd",
                "subtotal_eur"]
    return pd.DataFrame(filas, columns=columnas), resumen
