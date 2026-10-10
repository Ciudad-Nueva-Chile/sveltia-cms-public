"""Pedido por embarque programado y elección de dónde comprar cada libro (memoria, sección 4.2.5).

1. Cada origen tiene un embarque cada T meses (`intervalo_embarque_meses`). El próximo es la fecha de su última
   importación más T. Sin importaciones registradas, el embarque se considera vencido (pedir ahora).
2. Las necesidades salen de la política (politica.py): títulos AA y BB con Sugerido > 0.
3. Un libro puede comprarse en más de un origen (columna «Se compra en»). Para cada origen hay dos valores por
   ejemplar (pestaña Configuración, según origen de compra y edición del libro):
     - costo puesto en bodega: decide dónde conviene comprar;
     - valor FOB: es lo que se le paga a la editorial y lo que cuenta para el mínimo de embarque.
4. Se comparan las combinaciones de envíos que cubren TODAS las necesidades (Todo a España, Todo a Argentina,
   Dividir). En cada una, cada libro va al origen con menor costo puesto en bodega entre los que envían:
       Total = Σ cantidad × costo puesto en bodega + Σ costo fijo de cada envío que se hace
   El costo fijo de cada envío lo anota Roberto en «Pedido sugerido» (cotización real). El código no calcula el flete
   por peso, porque el catálogo no tiene el peso de cada título. Se elige el menor Total (empate: menos envíos).
5. Mínimo de embarque: si un envío no llega a `minimo_embarque_usd` FOB, no se completa solo: se avisa y Roberto
   decide cómo completarlo. No hay castigos numéricos de postergar ni de adelantar.
"""
from __future__ import annotations

import itertools
import math

import pandas as pd

from .clasificacion_abc import IVA
from .config import Parametros

SEPARADORES = (" o ", ",", "/", " y ")
EDICION_GENERAL = {"", "todas"}
NAN = math.nan
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


def _usd(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def nombre_combinacion(envia: list[str]) -> str:
    if len(envia) == 1:
        return f"Todo a {envia[0]}"
    return "Dividir: " + " y ".join(envia) + f" ({len(envia)} envíos)"


def proximos_embarques(mov: pd.DataFrame, catalogo: pd.DataFrame, p: Parametros, fecha_corte: pd.Timestamp) -> dict:
    """{origen: (fecha de la última importación o None, fecha del próximo embarque)} para los orígenes configurados.

    La importación se atribuye al origen (editorial) del título, porque el registro no dice desde dónde llegó.
    Todo origen distinto de Argentina se trata como España.
    """
    origen_de = catalogo.drop_duplicates("id").set_index("id")["origen"]
    imp = mov[(mov["tipo"] == "importacion") & (mov["fecha"] <= fecha_corte)].copy()
    imp["origen"] = imp["id"].map(origen_de).map(lambda o: "Argentina" if o == "Argentina" else "España")
    salida = {}
    for o in p.origenes:
        fechas = imp.loc[imp["origen"] == ("Argentina" if o.nombre == "Argentina" else "España"), "fecha"]
        ultima = fechas.max() if len(fechas) else None
        if ultima is None:
            proximo = fecha_corte
        else:
            proximo = ultima + pd.Timedelta(days=round(p.intervalo_meses(o.nombre) * 30.44))
        salida[o.nombre] = (ultima, pd.Timestamp(proximo).normalize())
    return salida


def sugerir(titulos: pd.DataFrame, costos: pd.DataFrame, p: Parametros, fecha_corte: pd.Timestamp,
            envios: dict | None = None, embarques: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (líneas del pedido, resumen por origen).

    titulos: una fila por título con sugerido, politica, categoria_gestion, tasa_mensual, unidades_ventana, precio_lista.
    envios: costo fijo de cada envío en dólares, por origen (vacío = 0).
    embarques: salida de proximos_embarques(); sin ella, todos los embarques se consideran vencidos.
    El resumen trae en .attrs: combinaciones, envios y ahorro.
    """
    envios = {o: float(v or 0) for o, v in (envios or {}).items()}
    embarques = embarques or {o.nombre: (None, fecha_corte) for o in p.origenes}
    if not len(costos):
        costos = pd.DataFrame(columns=["origen", "edicion", "fob_sobre_precio_neto", "costo_sobre_precio_neto", "tipo_cambio"])
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
        con_costo = [o for o in en if not math.isnan(ops[o][0])]
        return min(con_costo, key=lambda o: ops[o][0]) if con_costo else en[0]

    def evaluar(activos: tuple) -> dict:
        lineas, libros, cubre = [], 0.0, True
        for f, cant, ops in necesidades:
            o = mejor_en(ops, activos)
            if o is None:
                cubre = False
                continue
            lineas.append((f, cant, o, ops))
            libros += 0.0 if math.isnan(ops[o][0]) else ops[o][0] * cant
        envia = [o for o in activos if any(l[2] == o for l in lineas)]
        envio = sum(envios.get(o, 0.0) for o in envia)
        return {"activos": activos, "envia": envia, "lineas": lineas, "cubre": cubre,
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
        otras = {k: v for k, v in ops.items() if k != o and not math.isnan(v[0])}
        if otras and not math.isnan(ops[o][0]):
            otra = min(otras, key=lambda k: otras[k][0])
            aqui, alla = _usd(ops[o][0]), _usd(otras[otra][0])
            if ops[o][0] <= otras[otra][0]:
                motivo += f". Conviene {o}: US$ {aqui} puesto en bodega contra US$ {alla} en {otra}"
            else:
                motivo += f". En {otra} sale más barato (US$ {alla} contra {aqui}), pero la combinación de envíos conviene así"
        propia = ops.get(f.origen, (NAN, NAN))[0]
        if o != f.origen and not math.isnan(propia) and not math.isnan(ops[o][0]):
            ahorro += (propia - ops[o][0]) * cant
        valor = ops[o][1]
        filas.append({"cuando": cuando(o), "origen": o, "id": f.id, "isbn": f.isbn, "titulo": f.titulo,
                      "categoria": f.categoria_gestion, "cantidad": cant, "motivo": motivo,
                      "costo_unitario_usd": "" if math.isnan(valor) else round(valor, 2),
                      "subtotal_usd": "" if math.isnan(valor) else round(valor * cant, 2)})

    # Resumen por origen, con aviso de mínimo
    resumen = []
    for o in origenes:
        lineas_o = [l for l in filas if l["origen"] == o]
        if o not in configurados and not lineas_o:
            continue
        ultima, proximo = embarques.get(o, (None, fecha_corte))
        minimo = p.origen(o).minimo_embarque_usd
        total = round(sum(l["subtotal_usd"] or 0 for l in lineas_o), 2)
        if not lineas_o:
            estado = "Sin pedido"
        elif total >= minimo:
            estado = "Pedir en el embarque"
        else:
            estado = "Bajo el mínimo"
        resumen.append({"origen": o, "estado": estado, "titulos": len(lineas_o), "unidades": sum(l["cantidad"] for l in lineas_o),
                        "total_usd": total, "minimo_usd": minimo,
                        "falta_usd": round(max(0.0, minimo - total), 2) if lineas_o else 0.0,
                        "ultima_importacion": ultima.date().isoformat() if ultima is not None else "",
                        "proximo_embarque": proximo.date().isoformat(), "intervalo_meses": p.intervalo_meses(o),
                        "costos_configurados": bool((costos["origen"] == o).any())})
    resumen = pd.DataFrame(resumen)
    resumen.attrs["ahorro_usd"] = round(ahorro, 2)
    resumen.attrs["envios"] = {o: envios.get(o, 0.0) for o in origenes if o in configurados or o in envios
                               or any(o in e["envia"] for e in combinaciones)}
    resumen.attrs["combinaciones"] = [{
        "nombre": nombre_combinacion(e["envia"]), "envia": e["envia"], "elegida": e is mejor, "valida": True,
        "libros_ahora": sum(l[1] for l in e["lineas"]), "libros_usd": round(e["libros"], 2),
        "envio_usd": round(e["envio"], 2), "total_usd": round(e["total"], 2),
    } for e in combinaciones]
    columnas = ["cuando", "origen", "id", "isbn", "titulo", "categoria", "cantidad", "motivo", "costo_unitario_usd", "subtotal_usd"]
    return pd.DataFrame(filas, columns=columnas), resumen
