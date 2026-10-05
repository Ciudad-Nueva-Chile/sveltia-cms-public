"""La pestaña «Ventas»: una fila por libro vendido (o pedido que no se pudo atender).

Es la fuente de la demanda con detalle: precio, descuento, canal y ventas perdidas. Cada mañana el cálculo:

1. Convierte todas las filas en movimientos (se releen siempre: si se corrige una fila, se corrige la historia).
2. Descuenta del stock de «Inventario» las filas nuevas y anota en «Descontado del stock» cuándo lo hizo:
       Vendido                     → baja «En bodega»
       Vendido por Consignación    → baja «En consignación» (la librería pagó lo que tenía)
       Devolución                  → sube «En bodega»
       No había stock              → no mueve stock; queda como demanda perdida
3. Cuadratura: si ese mismo día Roberto ya había bajado la bodega a mano, no se descuenta otra vez. La baja que se
   dedujo de «Inventario» se reemplaza por la venta anotada, que tiene más detalle.
"""
from __future__ import annotations

import pandas as pd

COLUMNAS = ["fecha", "documento", "id", "cantidad", "descuento", "canal", "estado", "notas",
            "isbn", "precio_lista", "total", "descontado"]
EDITABLES = ["fecha", "documento", "id", "cantidad", "descuento", "canal", "estado", "notas"]

CANALES = ["Web / WhatsApp", "Local", "Evento o feria", "Librería", "Parroquia o institución", "Consignación (factura)"]
CANAL_CONSIGNACION = "Consignación (factura)"
VENDIDO, SIN_STOCK, DEVOLUCION = "Vendido", "No había stock", "Devolución"
ESTADOS = [VENDIDO, SIN_STOCK, DEVOLUCION]
HISTORICO = "Histórico (no descuenta)"


def descuento(v) -> float:
    """«10», «10%», 0,1 → 0,10. Vacío → 0."""
    if isinstance(v, str):
        v = v.replace("%", "").replace(",", ".").strip()
    n = pd.to_numeric(v, errors="coerce")
    if pd.isna(n) or n <= 0:
        return 0.0
    return float(n / 100 if n > 1 else n)


def validas(v: pd.DataFrame) -> pd.DataFrame:
    """Filas con fecha, libro y cantidad (las demás se ignoran y se avisan)."""
    return v[v["fecha"].notna() & (v["id"] != "") & (v["cantidad"] > 0)]


def tipo(fila) -> str:
    estado = str(fila.estado).strip() or VENDIDO
    if estado == SIN_STOCK:
        return "venta_perdida"
    if estado == DEVOLUCION:
        return "devolucion_cliente"
    return "consignacion_liquidada" if str(fila.canal).strip() == CANAL_CONSIGNACION else "venta"


def a_movimientos(v: pd.DataFrame, solo_descontadas: bool = False) -> pd.DataFrame:
    """Movimientos para el cálculo. solo_descontadas: las que ya se reflejaron en «Inventario»."""
    v = validas(v)
    if solo_descontadas:
        v = v[v["descontado"].astype(str).str.strip() != ""]
    m = pd.DataFrame({"fecha": v["fecha"], "id": v["id"], "tipo": [tipo(f) for f in v.itertuples()],
                      "cantidad": v["cantidad"], "documento": v["documento"].astype(str), "cliente": ""})
    return m.reset_index(drop=True)


def errores(v: pd.DataFrame, ids: set) -> list[str]:
    e = []
    llenas = v[(v["id"] != "") | v["fecha"].notna() | (v["cantidad"] > 0)]
    incompletas = len(llenas) - len(validas(llenas))
    if incompletas:
        e.append(f"{incompletas} filas de «Ventas» sin fecha, libro o cantidad (no se cuentan hasta completarlas)")
    desconocidos = sorted(set(validas(v)["id"]) - ids)
    if desconocidos:
        e.append(f"Libros en «Ventas» que no están en el catálogo: {', '.join(desconocidos[:5])}")
    return e


def aplicar(pendientes: pd.DataFrame, cantidades: pd.DataFrame, derivados: pd.DataFrame, hoy: pd.Timestamp):
    """Descuenta del stock las ventas nuevas.

    pendientes: filas válidas sin «Descontado del stock» (con su número de fila en «fila_planilla»).
    cantidades: «Inventario» (id, bodega, consignacion, en_camino), tal como lo dejó Roberto.
    derivados: movimientos deducidos hoy de los cambios en «Inventario».
    Devuelve (cantidades nuevas, derivados sin lo que explican las ventas, {fila: texto para «Descontado del stock»},
    ids cuyo stock cambió).
    """
    cant = cantidades.set_index("id")[["bodega", "consignacion", "en_camino"]].astype(int).copy()
    der = derivados.copy()
    marcas, cambiados = {}, set()
    dia = hoy.strftime("%d-%m-%Y")

    def consumir(id_, tipo_derivado, q) -> int:
        """Resta q de lo deducido hoy para ese libro; devuelve cuánto quedó explicado así."""
        usado = 0
        for i in der.index[(der["id"] == id_) & (der["tipo"] == tipo_derivado)]:
            u = min(q - usado, int(der.at[i, "cantidad"]))
            der.at[i, "cantidad"] -= u
            usado += u
            if usado == q:
                break
        return usado

    for f in pendientes.itertuples():
        t, q = tipo(f), int(f.cantidad)
        if f.id not in cant.index:
            marcas[f.fila_planilla] = "Revisar: el libro no está en «Inventario»"
            continue
        if t == "venta_perdida":
            marcas[f.fila_planilla] = f"Anotada el {dia} (no mueve stock)"
            continue
        columna, signo, deducido = {"venta": ("bodega", -1, "venta"),
                                    "consignacion_liquidada": ("consignacion", -1, "consignacion_liquidada"),
                                    "devolucion_cliente": ("bodega", +1, "importacion")}[t]
        ya = consumir(f.id, deducido, q)
        resto = q - ya
        aviso = ""
        if resto:
            nuevo = cant.at[f.id, columna] + signo * resto
            if nuevo < 0:
                aviso = f" · Revisar: no alcanzaba {'la consignación' if columna == 'consignacion' else 'el stock'}, quedó en 0"
                nuevo = 0
            cant.at[f.id, columna] = nuevo
            cambiados.add(f.id)
        if ya == q:
            marcas[f.fila_planilla] = f"Ya estaba descontado a mano ({dia})"
        elif ya:
            marcas[f.fila_planilla] = f"Descontado el {dia} ({ya} ya estaban descontados a mano){aviso}"
        else:
            marcas[f.fila_planilla] = f"Descontado el {dia}{aviso}"
    der = der[der["cantidad"] > 0].reset_index(drop=True)
    return cant.reset_index(), der, marcas, cambiados


def indicadores(v: pd.DataFrame, fecha_corte: pd.Timestamp, meses: int = 12) -> dict:
    """Resumen de lo anotado en «Ventas» en los últimos meses."""
    v = validas(v)
    v = v[v["fecha"] > fecha_corte - pd.DateOffset(months=meses)]
    vendidas = v[[tipo(f) in ("venta", "consignacion_liquidada") for f in v.itertuples()]]
    perdidas = v[[tipo(f) == "venta_perdida" for f in v.itertuples()]]
    d = vendidas["descuento"].map(descuento) if len(vendidas) else pd.Series(dtype=float)
    con = vendidas[d > 0]
    unidades = int(vendidas["cantidad"].sum())
    return {
        "filas": int(len(v)),
        "unidades_vendidas": unidades,
        "unidades_con_descuento": int(con["cantidad"].sum()),
        "pct_con_descuento": round(float(con["cantidad"].sum()) / unidades, 3) if unidades else 0.0,
        "descuento_promedio": round(float((d[d > 0] * con["cantidad"]).sum() / con["cantidad"].sum()), 3) if len(con) else 0.0,
        "unidades_perdidas": int(perdidas["cantidad"].sum()),
        "por_canal": {str(k): int(n) for k, n in vendidas.groupby(vendidas["canal"].replace("", "Sin canal"))["cantidad"].sum().items()},
    }


def perdidas_recientes(v: pd.DataFrame, catalogo: pd.DataFrame, fecha_corte: pd.Timestamp, dias: int = 90) -> list[dict]:
    """Libros que pidieron y no había, en los últimos días: candidatos a pedir aunque el pronóstico sea bajo."""
    v = validas(v)
    v = v[(v["fecha"] > fecha_corte - pd.Timedelta(days=dias)) & (v["estado"].astype(str).str.strip() == SIN_STOCK)]
    if v.empty:
        return []
    titulos = catalogo.drop_duplicates("id").set_index("id")["titulo"]
    g = v.groupby("id").agg(unidades=("cantidad", "sum"), veces=("cantidad", "size"), ultima=("fecha", "max"))
    g = g.sort_values(["unidades", "ultima"], ascending=False)
    return [{"id": i, "titulo": titulos.get(i, i), "unidades": int(r.unidades), "veces": int(r.veces),
             "ultima": r.ultima.date().isoformat()} for i, r in g.iterrows()]
