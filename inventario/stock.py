"""Existencias a partir de los movimientos.

Cada movimiento mueve unidades entre tres lugares: la bodega, la consignación (libros en poder de un cliente
que todavía no los factura) y fuera del sistema (vendidos o perdidos). La cantidad se anota siempre positiva;
el tipo decide el signo. Solo «ajuste» admite cantidades negativas (diferencias de conteo).
"""
from __future__ import annotations

from collections import deque

import pandas as pd

# tipo: (efecto en bodega, efecto en consignación)
EFECTOS = {
    "inventario_inicial": (+1, 0),
    "importacion": (+1, 0),
    "venta": (-1, 0),
    "devolucion_cliente": (+1, 0),
    "consignacion_salida": (-1, +1),
    "consignacion_devolucion": (+1, -1),
    "consignacion_liquidada": (0, -1),
    "ajuste": (+1, 0),
    "pedido_en_camino": (0, 0),   # no mueve la bodega: suma a «en tránsito» hasta que llega la importación
    "venta_perdida": (0, 0),      # lo pidieron y no había: no mueve stock, pero es demanda
}

# Salida física de bodega que refleja demanda (lo que hay que reponer)
# La venta perdida (pedido sin stock) también cuenta: sin ella el pronóstico subestima justo los libros que faltan.
TIPOS_DEMANDA = {"venta": +1, "consignacion_salida": +1, "consignacion_devolucion": -1, "devolucion_cliente": -1,
                 "venta_perdida": +1}
# Venta facturada (lo que genera ingreso; base de la clasificación ABC)
TIPOS_VENTA = {"venta": +1, "consignacion_liquidada": +1, "devolucion_cliente": -1}


def validar(mov: pd.DataFrame, catalogo: pd.DataFrame) -> list[str]:
    """Problemas de datos que conviene corregir en la planilla. No detienen el cálculo."""
    errores = []
    desconocidos = sorted(set(mov["tipo"]) - set(EFECTOS))
    if desconocidos:
        errores.append(f"Tipos de movimiento desconocidos (se ignoran): {', '.join(desconocidos)}")
    sin_fecha = int(mov["fecha"].isna().sum())
    if sin_fecha:
        errores.append(f"{sin_fecha} movimientos sin fecha válida (se ignoran)")
    ids = set(catalogo["id"])
    huerfanos = sorted(set(mov["id"]) - ids)
    if huerfanos:
        muestra = ", ".join(huerfanos[:5]) + ("…" if len(huerfanos) > 5 else "")
        errores.append(f"{len(huerfanos)} códigos en Movimientos que no están en el Catálogo: {muestra}")
    negativos = mov[(mov["cantidad"] < 0) & (mov["tipo"] != "ajuste")]
    if len(negativos):
        errores.append(f"{len(negativos)} movimientos con cantidad negativa fuera de «ajuste» (se toma el valor absoluto)")
    return errores


def limpiar(mov: pd.DataFrame) -> pd.DataFrame:
    mov = mov[mov["tipo"].isin(EFECTOS) & mov["fecha"].notna()].copy()
    no_ajuste = mov["tipo"] != "ajuste"
    mov.loc[no_ajuste, "cantidad"] = mov.loc[no_ajuste, "cantidad"].abs()
    return mov.sort_values(["fecha", "id"], kind="stable")


def existencias(mov: pd.DataFrame, transito: pd.DataFrame, fecha_corte: pd.Timestamp) -> pd.DataFrame:
    """Por título: bodega, en consignación, en tránsito, última salida y consignación abierta más antigua."""
    mov = mov[mov["fecha"] <= fecha_corte]
    filas = []
    for id_, grupo in mov.groupby("id", sort=False):
        bodega = consignacion = 0.0
        abiertas: deque = deque()  # (fecha, unidades) de consignaciones aún no devueltas ni liquidadas
        ultima_salida = pd.NaT
        for fecha, tipo, cant in grupo[["fecha", "tipo", "cantidad"]].itertuples(index=False):
            eb, ec = EFECTOS[tipo]
            bodega += eb * cant
            consignacion += ec * cant
            if tipo in ("venta", "consignacion_salida"):
                ultima_salida = fecha
            if tipo == "consignacion_salida":
                abiertas.append([fecha, cant])
            elif tipo in ("consignacion_devolucion", "consignacion_liquidada"):
                resto = cant
                while resto > 0 and abiertas:
                    usar = min(resto, abiertas[0][1])
                    abiertas[0][1] -= usar
                    resto -= usar
                    if abiertas[0][1] <= 0:
                        abiertas.popleft()
        filas.append({
            "id": id_,
            "bodega": bodega,
            "consignacion": max(consignacion, 0),
            "ultima_salida": ultima_salida,
            "consignacion_desde": abiertas[0][0] if abiertas else pd.NaT,
        })
    ex = pd.DataFrame(filas, columns=["id", "bodega", "consignacion", "ultima_salida", "consignacion_desde"])
    # En tránsito: lo anotado en la tabla EnTransito más los pedidos hechos que todavía no llegan
    pedidos = mov[mov["tipo"] == "pedido_en_camino"]
    desde = pedidos.groupby("id")["fecha"].min()
    llegadas = mov[(mov["tipo"] == "importacion") & mov["id"].isin(desde.index)]
    llegadas = llegadas[llegadas["fecha"] >= llegadas["id"].map(desde)]
    pendiente = (pedidos.groupby("id")["cantidad"].sum() - llegadas.groupby("id")["cantidad"].sum()).fillna(pedidos.groupby("id")["cantidad"].sum()).clip(lower=0)
    tr = pd.concat([transito[["id", "cantidad"]], pendiente.rename("cantidad").reset_index()])
    tr = tr.groupby("id", as_index=False)["cantidad"].sum().rename(columns={"cantidad": "transito"})
    ex = ex.merge(tr, on="id", how="outer")
    ex[["bodega", "consignacion", "transito"]] = ex[["bodega", "consignacion", "transito"]].fillna(0)
    return ex
