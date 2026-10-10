"""La pestaña «Inventario»: un libro por fila, y Roberto solo corrige cantidades.

Cada vez que corre el cálculo se compara lo que dice la pestaña con la última foto guardada (pestaña oculta
«Historial»). Si un número cambió, se guarda una foto nueva con la fecha del día y se deduce qué pasó:

    baja la bodega y sube la consignación   → salida en consignación
    baja la consignación y sube la bodega   → devuelto de consignación
    baja la consignación sin volver         → factura de consignación (se vendió)
    baja la bodega (lo que queda)           → venta
    sube la bodega (lo que queda)           → llegada de importación

Así se arma el historial de demanda sin que nadie anote movimientos. Es menos fino que un registro a mano:
si el mismo día llega un envío y se vende, solo se ve la diferencia neta.
"""
from __future__ import annotations

import pandas as pd

EDITABLES = ["compra_en", "bodega", "consignacion", "en_camino", "notas"]
COLUMNAS = ["id", "isbn", "titulo", "autor", "origen", "compra_en", "categoria", "categoria_gestion", "precio_lista",
            "bodega", "consignacion", "en_camino", "actualizado", "se_vende", "que_hacer", "notas"]
CANTIDADES = ["bodega", "consignacion", "en_camino"]


def derivar(prev: dict, actual: dict) -> list[tuple[str, int]]:
    """Movimientos (tipo, cantidad) que explican el paso de una foto a la siguiente."""
    db = int(actual["bodega"] - prev["bodega"])
    dc = int(actual["consignacion"] - prev["consignacion"])
    movs = []
    if dc > 0:
        movs.append(("consignacion_salida", dc))
        db += dc  # esa baja de bodega ya está explicada
    elif dc < 0:
        volvio = min(-dc, max(db, 0))
        if volvio:
            movs.append(("consignacion_devolucion", volvio))
            db -= volvio
        if -dc - volvio:
            movs.append(("consignacion_liquidada", -dc - volvio))
    if db < 0:
        movs.append(("venta", -db))
    elif db > 0:
        movs.append(("importacion", db))
    return movs


def _numero(v) -> int:
    n = pd.to_numeric(v, errors="coerce")
    return 0 if pd.isna(n) else int(n)


def detectar_cambios(inventario: pd.DataFrame, historial: pd.DataFrame, base: pd.DataFrame, hoy: pd.Timestamp):
    """Compara la pestaña con la última foto de cada libro.

    base: existencias calculadas desde los movimientos, para libros que aún no tienen foto.
    Devuelve (fotos nuevas, movimientos deducidos).
    """
    ultima = (historial.sort_values("fecha").groupby("id").last() if len(historial) else pd.DataFrame())
    base = base.set_index("id") if len(base) else pd.DataFrame()
    fotos, movs = [], []
    for fila in inventario.itertuples(index=False):
        actual = {c: _numero(getattr(fila, c)) for c in CANTIDADES}
        if fila.id in ultima.index:
            prev = {c: _numero(ultima.loc[fila.id, c]) for c in CANTIDADES}
        elif fila.id in base.index:
            prev = {"bodega": _numero(base.loc[fila.id, "bodega"]), "consignacion": _numero(base.loc[fila.id, "consignacion"]),
                    "en_camino": _numero(base.loc[fila.id, "transito"])}
        else:
            prev = None
        if prev is None:
            # Primera vez que se ve este libro: la foto inicial es un conteo
            fotos.append({"fecha": hoy, "id": fila.id, **actual})
            if actual["bodega"]:
                movs.append({"fecha": hoy, "id": fila.id, "tipo": "inventario_inicial", "cantidad": actual["bodega"]})
            if actual["consignacion"]:
                movs.append({"fecha": hoy, "id": fila.id, "tipo": "consignacion_salida", "cantidad": actual["consignacion"]})
            continue
        if actual != prev:
            fotos.append({"fecha": hoy, "id": fila.id, **actual})
            for tipo, cant in derivar(prev, actual):
                movs.append({"fecha": hoy, "id": fila.id, "tipo": tipo, "cantidad": cant})
    fotos = pd.DataFrame(fotos, columns=["fecha", "id"] + CANTIDADES)
    movs = pd.DataFrame(movs, columns=["fecha", "id", "tipo", "cantidad"])
    movs["documento"] = "Cambio en Inventario"
    movs["cliente"] = ""
    return fotos, movs


def ultima_actualizacion(historial: pd.DataFrame) -> pd.Series:
    """Fecha de la última foto en que cambió algún número, por libro."""
    if not len(historial):
        return pd.Series(dtype="datetime64[ns]")
    return historial.groupby("id")["fecha"].max()
