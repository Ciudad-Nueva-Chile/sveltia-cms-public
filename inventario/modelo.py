"""Cálculo completo: de las tablas de entrada a los resultados por título, el pedido y el resumen."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import clasificacion_abc as abc_mod
from . import demanda, pedido, politica, stock
from . import ventas as ventas_mod
from .config import Parametros


@dataclass
class Resultado:
    titulos: pd.DataFrame
    pedido: pd.DataFrame
    pedido_resumen: pd.DataFrame
    resumen: pd.DataFrame
    series: pd.DataFrame
    errores: list[str]
    fecha_corte: pd.Timestamp
    ventas: dict = field(default_factory=dict)        # indicadores de la pestaña «Ventas»
    perdidas: list = field(default_factory=list)      # pedidos sin stock recientes


def _meses_entre(desde: pd.Timestamp, hasta: pd.Timestamp) -> float:
    if pd.isna(desde):
        return math.nan
    return (hasta - desde).days / 30.44


def calcular(catalogo: pd.DataFrame, movimientos: pd.DataFrame, transito: pd.DataFrame, costos: pd.DataFrame,
             p: Parametros, fecha_corte: pd.Timestamp | None = None, semilla: int = 7,
             envios: dict | None = None, hoja_ventas: pd.DataFrame | None = None) -> Resultado:
    """movimientos ya incluye los de «Ventas»; `hoja_ventas` (la pestaña) solo se usa para los indicadores de venta."""
    errores = stock.validar(movimientos, catalogo)
    mov = stock.limpiar(movimientos)
    if fecha_corte is None:
        fecha_corte = mov["fecha"].max() if len(mov) else pd.Timestamp.today().normalize()
    fecha_corte = pd.Timestamp(fecha_corte)

    catalogo = catalogo.drop_duplicates("id", keep="first").copy()
    ids = catalogo["id"].tolist()
    ex = stock.existencias(mov, transito, fecha_corte).set_index("id").reindex(ids)
    ex[["bodega", "consignacion", "transito"]] = ex[["bodega", "consignacion", "transito"]].fillna(0)

    serie = demanda.demanda_mensual(mov, ids, fecha_corte, p.historia_meses)
    ventas = demanda.series_mensuales(mov, ids, fecha_corte, p.abc_meses, stock.TIPOS_VENTA).sum(axis=1)
    abc = abc_mod.clasificar_abc(ventas, catalogo.set_index("id")["precio_lista"], p.abc_corte_a, p.abc_corte_b)

    rng = np.random.default_rng(semilla)
    filas = []
    for fila in catalogo.itertuples(index=False):
        s = serie.loc[fila.id].to_numpy(dtype=float)
        patron, adi, cv2 = demanda.clasificar(s, p.corte_adi, p.corte_cv2)
        clase = (fila.clase_manual or "").strip() or demanda.CLASE_POR_PATRON[patron]
        pron = demanda.pronosticar(s, patron, p.alfa_suavizado)
        e = ex.loc[fila.id]
        meses_sin_salida = _meses_entre(e["ultima_salida"], fecha_corte)
        clase_abc = abc.loc[fila.id, "abc"]
        pol = politica.decidir(clase, clase_abc, e["bodega"], meses_sin_salida, p.meses_sin_movimiento, fila.politica_manual)

        h = p.horizonte_meses(fila.origen)
        cuantil = demanda.cuantil_proteccion(s, h, p.nivel_servicio, p.simulaciones, rng) if pol == "Reponer" else 0.0
        obj = politica.objetivo(pol, pron, h, cuantil)
        # Punto de pedido: demanda del plazo de reposición con el mismo nivel de servicio
        pp = demanda.cuantil_proteccion(s, p.plazo_meses(fila.origen), p.nivel_servicio, p.simulaciones, rng) if pol == "Reponer" else 0.0
        posicion = e["bodega"] + e["transito"]
        sugerido = max(0, obj - posicion) if pol in ("Reponer", "Stock mínimo") else 0

        alertas = []
        if e["bodega"] < 0:
            alertas.append("Stock negativo: revisar movimientos")
        if pol in ("Reponer", "Stock mínimo") and e["bodega"] <= 0:
            alertas.append("Quiebre, ya viene en tránsito" if e["transito"] > 0 else "Quiebre")
        elif sugerido > 0:
            alertas.append("Bajo el objetivo")
        if pol == "Temporada":
            ultimo_ciclo = int(s[-12:].sum())
            alertas.append(f"Temporada: definir el pedido del próximo ciclo (este vendió {ultimo_ciclo} en 12 meses)")
        if pol == "Liquidar o revisar":
            alertas.append(f"Sin salidas en {p.meses_sin_movimiento}+ meses")
        dias_consig = (fecha_corte - e["consignacion_desde"]).days if not pd.isna(e["consignacion_desde"]) else 0
        if dias_consig >= p.dias_consignacion_antigua:
            alertas.append(f"Consignación abierta hace {dias_consig} días")

        cobertura = (e["bodega"] / pron) if pron > 0 else (math.inf if e["bodega"] > 0 else 0)
        filas.append({
            "id": fila.id, "isbn": fila.isbn, "titulo": fila.titulo, "origen": fila.origen,
            "compra_en": (getattr(fila, "compra_en", "") if isinstance(getattr(fila, "compra_en", ""), str) else "") or fila.origen, "categoria": fila.categoria,
            "precio_lista": fila.precio_lista,
            "bodega": int(e["bodega"]), "consignacion": int(e["consignacion"]), "transito": int(e["transito"]),
            "posicion": int(posicion),
            "abc": clase_abc, "valor_venta": round(float(abc.loc[fila.id, "valor_venta"])),
            "patron": patron, "adi": round(adi, 2) if not math.isnan(adi) else "",
            "cv2": round(cv2, 2) if not math.isnan(cv2) else "", "clase": clase,
            "meses_con_demanda": int((s > 0).sum()), "unidades_ventana": int(s.sum()),
            "pronostico_mensual": round(pron, 3),
            "cobertura_meses": round(cobertura, 1) if math.isfinite(cobertura) else "∞",
            "politica": pol, "punto_pedido": int(math.ceil(pp)), "stock_objetivo": obj, "sugerido": int(sugerido),
            "ultima_salida": e["ultima_salida"].date().isoformat() if not pd.isna(e["ultima_salida"]) else "",
            "meses_sin_salida": round(meses_sin_salida, 1) if not math.isnan(meses_sin_salida) else "",
            "dias_consignacion": int(dias_consig),
            "valor_bodega": int(max(e["bodega"], 0) * fila.precio_lista),
            "alertas": " · ".join(alertas),
        })

    titulos = pd.DataFrame(filas)
    lineas, por_origen = pedido.sugerir(titulos, costos, p, fecha_corte, envios)
    ind, perdidas = {}, []
    if hoja_ventas is not None and len(ventas_mod.validas(hoja_ventas)):
        errores += ventas_mod.errores(hoja_ventas, set(ids))
        ind = ventas_mod.indicadores(hoja_ventas, fecha_corte)
        perdidas = ventas_mod.perdidas_recientes(hoja_ventas, catalogo, fecha_corte)
    resumen = _resumen(titulos, por_origen, errores, fecha_corte, p, ind)
    serie.columns = [str(c) for c in serie.columns]
    return Resultado(titulos, lineas, por_origen, resumen, serie, errores, fecha_corte, ind, perdidas)


def _resumen(t: pd.DataFrame, por_origen: pd.DataFrame, errores: list[str], fecha_corte, p: Parametros, ventas: dict | None = None) -> pd.DataFrame:
    filas = [
        ("Fecha de corte", fecha_corte.date().isoformat()),
        ("Títulos en catálogo", len(t)),
        ("Ejemplares en bodega", int(t["bodega"].clip(lower=0).sum())),
        ("Ejemplares en consignación", int(t["consignacion"].sum())),
        ("Valor en bodega a precio de lista", int((t["bodega"].clip(lower=0) * t["precio_lista"]).sum())),
        ("Títulos en cero", int((t["bodega"] <= 0).sum())),
        ("Títulos A / B / C", " / ".join(str(int((t["abc"] == k).sum())) for k in "ABC")),
        ("Títulos con quiebre (se reponen y están en cero)", int(t["alertas"].str.contains("Quiebre").sum())),
        ("  de ellos, con pedido en tránsito", int(t["alertas"].str.contains("ya viene en tránsito").sum())),
        ("Títulos para liquidar o revisar", int((t["politica"] == "Liquidar o revisar").sum())),
        ("Nivel de servicio objetivo", f"{p.nivel_servicio:.0%}"),
    ]
    for pat, n in t["patron"].value_counts().items():
        filas.append((f"Patrón: {pat}", int(n)))
    for pol, n in t["politica"].value_counts().items():
        filas.append((f"Política: {pol}", int(n)))
    for o in por_origen.itertuples():
        filas.append((f"Pedido {o.origen}", f"{o.estado} — {o.unidades} unidades, US$ {o.total_usd:,.0f} (mínimo US$ {o.minimo_usd:,.0f})"))
    if ventas:
        filas += [
            ("Ventas anotadas: unidades (12 meses)", ventas["unidades_vendidas"]),
            ("Ventas anotadas: con descuento", f"{ventas['pct_con_descuento']:.0%}"),
            ("Ventas anotadas: descuento promedio", f"{ventas['descuento_promedio']:.0%}"),
            ("Ventas perdidas por falta de stock (unidades, 12 meses)", ventas["unidades_perdidas"]),
        ]
    for e in errores:
        filas.append(("Revisar datos", e))
    return pd.DataFrame(filas, columns=["indicador", "valor"])
