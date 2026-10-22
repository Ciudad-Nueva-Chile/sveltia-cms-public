"""Revisión de la planilla: filas incompletas, incongruentes o repetidas, con su número de fila.

No corrige nada ni detiene el cálculo: arma la lista «Revisar en la planilla» de «Esta semana» y del panel. Las filas
con problemas se ignoran donde no se pueden usar (por ejemplo, una venta sin cantidad) y se cuentan cuando se corrigen.
"""
from __future__ import annotations

import pandas as pd

NOMBRES = {"bodega": "En bodega", "consignacion": "En consignación", "en_camino": "Pedido en camino"}
MAXIMO = 40          # avisos que se muestran; el resto se resume en una línea
FACTOR_MIN, FACTOR_MAX = 0.1, 1.5


def _f(fila) -> str:
    return str(int(fila)) if pd.notna(fila) and str(fila).strip() != "" else "?"


def _lleno(v) -> bool:
    return not (v is None or (not isinstance(v, str) and pd.isna(v)) or str(v).strip() in ("", "0"))


def _repetidas(df: pd.DataFrame, claves: list[str], hoja: str, que: str) -> list[str]:
    r = []
    d = df[df[claves].astype(str).apply(lambda c: c.str.strip() != "").all(axis=1)]
    for _, g in d.groupby(claves):
        if len(g) > 1:
            r.append(f"{hoja}, filas {', '.join(_f(x) for x in g['fila_planilla'])}: {que} repetida (¿se anotó dos veces?)")
    return r


def ventas(v: pd.DataFrame, ids: set, hoy: pd.Timestamp) -> list[str]:
    if v is None or v.empty:
        return []
    r = []
    for x in v.itertuples():
        datos = [_lleno(x.id), pd.notna(x.fecha), _lleno(x.cantidad), _lleno(x.documento)]
        if not any(datos):
            continue
        fila = f"Ventas, fila {_f(x.fila_planilla)}"
        faltan = [n for n, ok in zip(("el libro", "la fecha", "la cantidad"), datos[:3]) if not ok]
        if faltan:
            r.append(f"{fila}: falta {', '.join(faltan)} (no se cuenta hasta completarla)")
        if _lleno(x.id) and x.id not in ids:
            r.append(f"{fila}: el libro «{x.id}» no está en el catálogo")
        if pd.notna(x.fecha) and x.fecha > hoy + pd.Timedelta(days=1):
            r.append(f"{fila}: la fecha {x.fecha:%d-%m-%Y} es futura")
        if _lleno(x.cantidad) and x.cantidad < 0:
            r.append(f"{fila}: cantidad negativa (una devolución se anota con «Estado»)")
        d = pd.to_numeric(str(getattr(x, "descuento", "")).replace("%", "").replace(",", "."), errors="coerce")
        if pd.notna(d) and not 0 <= d <= 100:
            r.append(f"{fila}: descuento de {d:g} % (debe estar entre 0 y 100)")
    return r + _repetidas(v, ["fecha", "documento", "id", "cantidad"], "Ventas", "venta")


def importaciones(i: pd.DataFrame, ids: set, hoy: pd.Timestamp) -> list[str]:
    if i is None or i.empty:
        return []
    r = []
    for x in i.itertuples():
        if not any([_lleno(x.id), pd.notna(x.fecha_pedido), pd.notna(x.fecha_llegada), _lleno(x.cantidad)]):
            continue
        fila = f"Importaciones, fila {_f(x.fila_planilla)}"
        faltan = [n for n, ok in (("el libro", _lleno(x.id)), ("la cantidad", _lleno(x.cantidad)),
                                  ("el país", _lleno(x.pais)),
                                  ("la fecha de pedido o de llegada", pd.notna(x.fecha_pedido) or pd.notna(x.fecha_llegada)))
                  if not ok]
        if faltan:
            r.append(f"{fila}: falta {', '.join(faltan)}")
        if _lleno(x.id) and x.id not in ids:
            r.append(f"{fila}: el libro «{x.id}» no está en el catálogo")
        if _lleno(x.pais) and str(x.pais).strip() not in ("España", "Argentina"):
            r.append(f"{fila}: país «{x.pais}» (se toma como España; debe ser España o Argentina)")
        if pd.notna(x.fecha_pedido) and pd.notna(x.fecha_llegada) and x.fecha_llegada < x.fecha_pedido:
            r.append(f"{fila}: la llegada ({x.fecha_llegada:%d-%m-%Y}) es anterior al pedido ({x.fecha_pedido:%d-%m-%Y})")
        if pd.notna(x.fecha_llegada) and x.fecha_llegada > hoy + pd.Timedelta(days=1):
            r.append(f"{fila}: la fecha de llegada {x.fecha_llegada:%d-%m-%Y} es futura (si no ha llegado, déjala vacía)")
        usd, eur = getattr(x, "fob_usd", None), getattr(x, "fob_eur", None)
        if _lleno(usd) and _lleno(eur):
            r.append(f"{fila}: tiene FOB en US$ y en €; deja solo el de la factura")
        if _lleno(x.cantidad) and x.cantidad < 0:
            r.append(f"{fila}: cantidad negativa")
    return r + _repetidas(i, ["documento", "id", "fecha_llegada"], "Importaciones", "línea de embarque")


def inventario(inv: pd.DataFrame, ids: set) -> list[str]:
    if inv is None or inv.empty or "fila_planilla" not in inv:
        return []
    r = []
    codigo = inv["id"].astype(str).str.strip(" '\"")
    for x, cod in zip(inv.itertuples(), codigo):
        fila = f"Inventario, fila {_f(x.fila_planilla)}"
        cantidades = {c: getattr(x, c, 0) for c in ("bodega", "consignacion", "en_camino")}
        if not cod:
            if any(_lleno(v) for v in cantidades.values()):
                r.append(f"{fila}: tiene cantidades pero no código (se ignora)")
            elif str(x.id).strip():
                r.append(f"{fila}: código vacío o inválido «{x.id}» (se puede borrar la fila)")
            continue
        if cod not in ids:
            r.append(f"{fila}: «{cod}» ya no está en el catálogo del sitio (si el libro se eliminó, revisa si quedaba stock)")
        for c, v in cantidades.items():
            if pd.notna(v) and v < 0:
                r.append(f"{fila}: «{NOMBRES[c]}» negativo ({int(v)})")
    rep = inv.assign(cod=codigo)
    rep = rep[rep["cod"] != ""]
    for cod, g in rep.groupby("cod"):
        if len(g) > 1:
            r.append(f"Inventario, filas {', '.join(_f(x) for x in g['fila_planilla'])}: el código {cod} está repetido (se usa la primera)")
    return r


def configuracion(costos: pd.DataFrame, origenes: list[str]) -> list[str]:
    if costos is None:
        return []
    r = []
    for o in origenes:
        if costos.empty or not (costos["origen"] == o).any():
            r.append(f"Configuración: falta la fila de {o} (sin ella no se calculan sus costos)")
    for x in costos.itertuples():
        nombre = f"Configuración, {x.origen}" + (f" (edición {x.edicion})" if str(x.edicion).strip() else "")
        for col, texto in (("fob_sobre_precio_neto", "FOB / precio neto"), ("costo_sobre_precio_neto", "Costo en bodega / precio neto")):
            v = pd.to_numeric(getattr(x, col), errors="coerce")
            if pd.isna(v):
                r.append(f"{nombre}: falta «{texto}» (anota FOB y gastos en «Importaciones» para medirlo, o escríbelo)")
            elif not FACTOR_MIN <= v <= FACTOR_MAX:
                r.append(f"{nombre}: «{texto}» = {v:g} parece fuera de rango (suele estar entre 0,3 y 0,8)")
        if pd.isna(pd.to_numeric(getattr(x, "tipo_cambio"), errors="coerce")):
            r.append(f"{nombre}: falta «Pesos por dólar»")
    return r


def revisar(ventas_: pd.DataFrame, imp: pd.DataFrame, inv: pd.DataFrame, costos: pd.DataFrame, catalogo: pd.DataFrame,
            origenes: list[str], hoy: pd.Timestamp) -> list[str]:
    ids = set(catalogo["id"])
    avisos = (ventas(ventas_, ids, hoy) + importaciones(imp, ids, hoy) + inventario(inv, ids)
              + configuracion(costos, origenes))
    if len(avisos) > MAXIMO:
        avisos = avisos[:MAXIMO] + [f"… y {len(avisos) - MAXIMO} avisos más del mismo tipo"]
    return avisos
