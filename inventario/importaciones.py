"""La pestaña «Importaciones»: una fila por libro y embarque.

Columnas que edita Roberto: fecha de pedido, fecha de llegada (vacía = en camino), país de compra, factura o DIN, libro,
cantidad, FOB total y gastos de internación del embarque (opcionales; con ellos se miden los factores de costo de
«Configuración», ver costos.py) y notas. «Sumado al stock» lo completa el cálculo.

1. Una fila con fecha de llegada es una importación real (fecha y país reales). Se suma a «En bodega» una sola vez y se
   anota cuándo en «Sumado al stock». Cuadratura como en «Ventas»: si ese día Roberto ya subió la bodega a mano en
   «Inventario», no se suma de nuevo.
2. Una fila sin fecha de llegada está en camino. Para los libros con filas abiertas, «Pedido en camino» de «Inventario»
   se completa solo con la suma de esas filas. Para los demás queda lo que anote Roberto; cuando llega un embarque de un
   libro sin otras filas abiertas, lo que llegó se resta de su «Pedido en camino».
3. El próximo embarque de cada país parte de su última llegada registrada aquí.
4. T y L medidos (memoria, sección 4.2.5, para contrastar los valores del análisis de lote):
       T = mediana de los días entre fechas de llegada distintas del país, en sus últimos 5 embarques
       L = mediana de (fecha de llegada − fecha de pedido), en las filas que tienen ambas
   Son solo un aviso comparativo: el nivel objetivo S y la fecha del próximo embarque usan siempre los T y L de la
   política (config/parametros.yml). El observado se muestra cuando hay 3 o más embarques con datos del país.
"""
from __future__ import annotations

import pandas as pd

from .config import DIAS_POR_MES

COLUMNAS = ["fecha_pedido", "fecha_llegada", "pais", "documento", "id", "cantidad", "fob_usd", "fob_eur", "gastos_clp", "notas", "sumado"]
EDITABLES = ["fecha_pedido", "fecha_llegada", "pais", "documento", "id", "cantidad", "fob_usd", "fob_eur", "gastos_clp", "notas"]
HISTORICO = "Histórico (ya en existencias)"
MINIMO_EMBARQUES = 3      # embarques con datos necesarios para usar T y L medidos
ULTIMOS_EMBARQUES = 5     # T se mide sobre los últimos 5 embarques del país
DIAS_MES = 30.44          # días por mes para pasar T de días a meses


def pais(nombre) -> str:
    """Todo país distinto de Argentina se trata como España (criterio de la memoria)."""
    return "Argentina" if str(nombre).strip() == "Argentina" else "España"


def validas(i: pd.DataFrame) -> pd.DataFrame:
    if i is None or i.empty:
        return pd.DataFrame(columns=COLUMNAS + ["fila_planilla"])
    return i[(i["id"] != "") & (i["cantidad"] > 0) & (i["fecha_llegada"].notna() | i["fecha_pedido"].notna())]


def llegadas(i: pd.DataFrame) -> pd.DataFrame:
    v = validas(i)
    return v[v["fecha_llegada"].notna()]


def abiertas(i: pd.DataFrame) -> pd.DataFrame:
    v = validas(i)
    return v[v["fecha_llegada"].isna()]


def en_camino(i: pd.DataFrame) -> pd.Series:
    """Unidades en camino por libro, según las filas abiertas (sin fecha de llegada). Para esos libros «Pedido en camino»
    es automático; los demás siguen con lo que anote Roberto."""
    return abiertas(i).groupby("id")["cantidad"].sum()


def a_movimientos(i: pd.DataFrame, solo_sumadas: bool = False) -> pd.DataFrame:
    """Movimientos «importacion» con la fecha de llegada real. El país de compra queda en «cliente»."""
    v = llegadas(i)
    if solo_sumadas:
        v = v[v["sumado"].astype(str).str.strip() != ""]
    return pd.DataFrame({"fecha": v["fecha_llegada"], "id": v["id"], "tipo": "importacion", "cantidad": v["cantidad"],
                         "documento": v["documento"].astype(str), "cliente": v["pais"].map(pais)}).reset_index(drop=True)


def aplicar(pendientes: pd.DataFrame, cantidades: pd.DataFrame, derivados: pd.DataFrame, hoy: pd.Timestamp):
    """Suma al stock las llegadas nuevas. Igual que ventas.aplicar: devuelve (cantidades nuevas, derivados sin lo que
    explican las llegadas, {fila: texto para «Sumado al stock»}, ids cuyo stock cambió)."""
    cant = cantidades.set_index("id")[["bodega", "consignacion", "en_camino"]].astype(int).copy()
    der = derivados.copy()
    marcas, cambiados = {}, set()
    dia = hoy.strftime("%d-%m-%Y")
    for f in pendientes.itertuples():
        q = int(f.cantidad)
        if f.id not in cant.index:
            marcas[f.fila_planilla] = "Revisar: el libro no está en «Inventario»"
            continue
        usado = 0
        for k in der.index[(der["id"] == f.id) & (der["tipo"] == "importacion")]:
            u = min(q - usado, int(der.at[k, "cantidad"]))
            der.at[k, "cantidad"] -= u
            usado += u
            if usado == q:
                break
        if usado < q:
            cant.at[f.id, "bodega"] += q - usado
            cambiados.add(f.id)
        marcas[f.fila_planilla] = (f"Ya estaba sumado a mano ({dia})" if usado == q
                                   else f"Sumado el {dia}" + (f" ({usado} ya estaban sumados a mano)" if usado else ""))
    der = der[der["cantidad"] > 0].reset_index(drop=True)
    return cant.reset_index(), der, marcas, cambiados


def ultimas_llegadas(i: pd.DataFrame) -> dict:
    """{país: fecha de la última llegada registrada}."""
    v = llegadas(i)
    if v.empty:
        return {}
    return v.assign(p=v["pais"].map(pais), fecha_llegada=pd.to_datetime(v["fecha_llegada"])).groupby("p")["fecha_llegada"].max().to_dict()


def medir(i: pd.DataFrame, nombre_pais: str) -> dict:
    """T y L medidos de un país: valores en meses y cuántos embarques los respaldan."""
    v = llegadas(i)
    v = v[v["pais"].map(pais) == pais(nombre_pais)]
    if v.empty:
        return {"T_meses": None, "embarques_T": 0, "L_meses": None, "embarques_L": 0}
    v = v.assign(fecha_llegada=pd.to_datetime(v["fecha_llegada"]), fecha_pedido=pd.to_datetime(v["fecha_pedido"]))
    fechas = sorted(v["fecha_llegada"].dt.normalize().unique())[-ULTIMOS_EMBARQUES:]
    t = None
    if len(fechas) >= 2:
        dias = pd.Series(pd.to_datetime(fechas)).diff().dt.days.dropna()
        t = float(dias.median()) / DIAS_MES
    con_pedido = v[v["fecha_pedido"].notna()]
    plazos = (con_pedido["fecha_llegada"] - con_pedido["fecha_pedido"]).dt.days
    plazos = plazos[plazos >= 0]
    embarques_l = con_pedido.loc[plazos.index, "fecha_llegada"].dt.normalize().nunique()
    return {"T_meses": t, "embarques_T": len(fechas),
            "L_meses": float(plazos.median()) / DIAS_POR_MES if len(plazos) else None, "embarques_L": int(embarques_l)}


def _num(v: float) -> str:
    return f"{v:.1f}".replace(".", ",").replace(",0", "") if v is not None else ""


def efectivos(i: pd.DataFrame, p) -> dict:
    """Por país: los T y L de la política (los que usa el cálculo) y el texto comparativo con lo observado en
    «Importaciones», por ejemplo «Política: cada 12 meses. Observado: cada 3 meses (4 embarques)»."""
    salida = {}
    for o in p.origenes:
        m = medir(i, o.nombre)
        T, L = p.intervalo_meses(o.nombre), p.plazo_meses(o.nombre)
        hay_T = m["T_meses"] is not None and m["embarques_T"] >= MINIMO_EMBARQUES
        hay_L = m["L_meses"] is not None and m["embarques_L"] >= MINIMO_EMBARQUES
        texto_T = f"Política: cada {_num(T)} meses" + (
            f". Observado: cada {_num(m['T_meses'])} meses ({m['embarques_T']} embarques)" if hay_T else "")
        texto_L = f"plazo {_num(L * DIAS_POR_MES)} días" + (
            f". Observado: {_num(m['L_meses'] * DIAS_POR_MES)} días ({m['embarques_L']} embarques)" if hay_L else "")
        salida[o.nombre] = {"T": T, "L": L, "texto_T": texto_T, "texto_L": texto_L, "medido": m,
                            "observado_T": hay_T, "observado_L": hay_L}
    return salida
