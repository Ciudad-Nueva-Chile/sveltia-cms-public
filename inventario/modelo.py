"""Cálculo completo (memoria, sección 4.2.5): de las tablas de entrada a los resultados por título, el pedido por
embarque, las categorías de gestión, el conteo cíclico y el resumen."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from . import clasificacion_abc as cat_mod
from . import demanda, pedido, politica, stock
from . import ventas as ventas_mod
from .config import CATEGORIAS, Parametros


@dataclass
class Resultado:
    titulos: pd.DataFrame
    pedido: pd.DataFrame
    pedido_resumen: pd.DataFrame
    resumen: pd.DataFrame
    series: pd.DataFrame
    errores: list[str]
    fecha_corte: pd.Timestamp
    ventas: dict = field(default_factory=dict)          # indicadores de la pestaña «Ventas»
    perdidas: list = field(default_factory=list)        # pedidos sin stock recientes
    categorias: pd.DataFrame = field(default_factory=pd.DataFrame)   # Tabla 4.24: por categoría
    matriz: dict = field(default_factory=dict)          # categoría × clase → títulos
    conteo: dict = field(default_factory=dict)          # qué contar esta semana, frecuencias y revisiones


def _meses_entre(desde, hasta: pd.Timestamp) -> float:
    if desde is None or pd.isna(desde):
        return math.nan
    return (hasta - desde).days / 30.44


def conteo_ciclico(t: pd.DataFrame, p: Parametros, fecha_corte: pd.Timestamp) -> dict:
    """Qué contar esta semana, con la frecuencia de conteo por categoría (memoria, Tabla 4.26).

    Los títulos con existencias de cada categoría se reparten en turnos de 52 / conteos_por_anio semanas, en orden de
    código, de modo que cada uno se cuenta con su frecuencia.
    """
    semana = int(fecha_corte.isocalendar().week)
    contar, frecuencias = [], []
    for c in CATEGORIAS:
        f = float(p.conteos_por_anio.get(c, 0) or 0)
        g = t[(t["categoria_gestion"] == c) & (t["bodega"] > 0)].sort_values("id")
        frecuencias.append({"categoria": c, "titulos": int(len(g)), "conteos_por_anio": f})
        if not f or g.empty:
            continue
        turnos = max(1, round(52 / f))
        for i, r in enumerate(g.itertuples()):
            if i % turnos == semana % turnos:
                contar.append({"id": r.id, "titulo": r.titulo, "categoria": c, "bodega": int(r.bodega),
                               "registro": "Permanente" if c == "AA" else "Con cada conteo"})
    revis = [{"categoria": c, "cada_meses": int(p.revision_clasificacion_meses.get(c, 12) or 12)} for c in CATEGORIAS]
    return {"semana": semana, "contar": contar, "frecuencias": frecuencias, "revisiones": revis}


def calcular(catalogo: pd.DataFrame, movimientos: pd.DataFrame, transito: pd.DataFrame, costos: pd.DataFrame,
             p: Parametros, fecha_corte: pd.Timestamp | None = None, envios: dict | None = None,
             hoja_ventas: pd.DataFrame | None = None) -> Resultado:
    """movimientos ya incluye los de «Ventas»; `hoja_ventas` (la pestaña) se usa para los indicadores de venta."""
    errores = stock.validar(movimientos, catalogo)
    mov = stock.limpiar(movimientos)
    if fecha_corte is None:
        fecha_corte = mov["fecha"].max() if len(mov) else pd.Timestamp.today().normalize()
    fecha_corte = pd.Timestamp(fecha_corte)

    catalogo = catalogo.drop_duplicates("id", keep="first").copy()
    ids = catalogo["id"].tolist()
    ex = stock.existencias(mov, transito, fecha_corte).set_index("id").reindex(ids)
    ex[["bodega", "consignacion", "transito"]] = ex[["bodega", "consignacion", "transito"]].fillna(0)

    ventana = demanda.meses_ventana(fecha_corte, p.historia_meses)
    inicio_ventana = ventana[0].start_time
    serie = demanda.venta_neta_mensual(mov, ids, fecha_corte, p.historia_meses)

    # Solicitudes del canal web («No había stock» con canal Web / WhatsApp): un título CC o DD que solo tiene esas
    # solicitudes no cambia solo de categoría. Queda en CC o DD con un aviso, y pasa a BB en la próxima revisión.
    pendientes = mov[(mov["tipo"] == "venta_perdida") & (mov["cliente"].astype(str) == ventas_mod.CANAL_WEB)]
    serie_sin_pend = demanda.venta_neta_mensual(mov.drop(pendientes.index), ids, fecha_corte, p.historia_meses)

    en_ventana = mov[(mov["fecha"] >= inicio_ventana) & (mov["fecha"] <= fecha_corte)]
    con_guia = set(en_ventana.loc[en_ventana["tipo"] == "consignacion_salida", "id"])
    vendido = mov[mov["tipo"].isin(stock.TIPOS_VENTA) & (mov["fecha"] <= fecha_corte)].copy()
    vendido["u"] = vendido["cantidad"] * vendido["tipo"].map(stock.TIPOS_VENTA)
    ultima_imp = mov[(mov["tipo"] == "importacion") & (mov["fecha"] <= fecha_corte)].groupby("id")["fecha"].max()
    temp_ini, temp_fin = politica.ultima_temporada(fecha_corte)
    mes_temporada = politica.es_mes_de_pedido_temporada(fecha_corte)

    filas = []
    for fila in catalogo.itertuples(index=False):
        s = serie.loc[fila.id].to_numpy(dtype=float)
        clase, k, adi, cv2 = demanda.clasificar(s, p.corte_adi, p.corte_cv2)
        e = ex.loc[fila.id]
        bodega, transito_i = float(e["bodega"]), float(e["transito"])
        reclasificar = False
        if clase != "Sin venta neta" and bodega > 0:
            clase_sin, _, _, _ = demanda.clasificar(serie_sin_pend.loc[fila.id].to_numpy(dtype=float), p.corte_adi, p.corte_cv2)
            if clase_sin == "Sin venta neta":
                clase, reclasificar = clase_sin, True
        manual = (getattr(fila, "clase_manual", "") or "").strip()
        if manual in demanda.CLASES_MANUALES:
            clase, reclasificar = manual, False
        categoria = cat_mod.categoria(clase, bodega, fila.id in con_guia)
        tasa = demanda.pronosticar(s, clase, p.alfa_suavizado)
        pol = politica.decidir(categoria, clase, getattr(fila, "politica_manual", ""))
        T, L = p.intervalo_meses(fila.origen), p.plazo_meses(fila.origen)
        S = demanda.nivel_objetivo(tasa, T, L, p.nivel_servicio) if pol == "Reponer" else 0
        posicion = max(bodega, 0) + transito_i   # un stock negativo es un error de datos (se avisa): no infla el pedido

        desde = ultima_imp.get(fila.id, inicio_ventana)
        v_id = vendido[vendido["id"] == fila.id]
        vendido_desde = float(v_id.loc[v_id["fecha"] > desde, "u"].sum())
        temporada_u = int(v_id.loc[(v_id["fecha"] >= temp_ini) & (v_id["fecha"] <= temp_fin), "u"].sum())
        if pol == "Reponer":
            sugerido = max(0, S - posicion)
        elif pol == "Reponer lo vendido":
            sugerido = politica.reponer_lo_vendido(vendido_desde, transito_i)
        elif pol == "Temporada" and mes_temporada:
            sugerido = max(0, temporada_u - posicion)
        else:
            sugerido = 0

        positivos = s[s > 0]
        ritmo = float(positivos[-1]) if len(positivos) else 0.0     # venta del último mes con venta
        cobertura = (bodega / ritmo) if ritmo > 0 else (math.inf if bodega > 0 else 0.0)
        ultima_salida = e["ultima_salida"]
        alertas = []
        if bodega < 0:
            alertas.append("Stock negativo: revisar movimientos")
        if pol == "Reponer" and bodega <= 0:
            alertas.append("Quiebre, ya viene en tránsito" if transito_i > 0 else "Quiebre")
        elif pol == "Reponer" and sugerido > 0:
            alertas.append("Bajo el nivel objetivo")
        if pol == "Temporada":
            alertas.append(f"Temporada: pedir entre junio y agosto ({temporada_u} vendidos la última temporada)")
        if reclasificar:
            alertas.append("Título CC o DD con solicitud del canal: pasa a BB en la próxima revisión")
        dias_consig = (fecha_corte - e["consignacion_desde"]).days if not pd.isna(e["consignacion_desde"]) else 0
        if dias_consig >= p.dias_consignacion_antigua:
            alertas.append(f"Consignación abierta hace {dias_consig} días")

        meses_sin = _meses_entre(ultima_salida, fecha_corte)
        filas.append({
            "id": fila.id, "isbn": fila.isbn, "titulo": fila.titulo, "origen": fila.origen,
            "compra_en": (getattr(fila, "compra_en", "") if isinstance(getattr(fila, "compra_en", ""), str) else "") or fila.origen,
            "categoria": fila.categoria, "precio_lista": fila.precio_lista,
            "bodega": int(bodega), "consignacion": int(e["consignacion"]), "transito": int(transito_i), "posicion": int(posicion),
            "categoria_gestion": categoria, "clase": clase, "meses_con_venta": k,
            "adi": round(adi, 2) if not math.isnan(adi) else "", "cv2": round(cv2, 2) if not math.isnan(cv2) else "",
            "cuadrante": demanda.cuadrante(adi, cv2, p.corte_adi, p.corte_cv2),
            "unidades_ventana": int(s.sum()), "tasa_mensual": round(tasa, 3),
            "intervalo_meses": T, "plazo_meses": round(L, 3), "nivel_objetivo": int(S),
            "politica": pol, "sugerido": int(sugerido), "vendido_desde_importacion": int(vendido_desde),
            "temporada_unidades": temporada_u, "reclasificar": reclasificar,
            "cobertura_meses": round(cobertura, 1) if math.isfinite(cobertura) else "∞",
            "ultima_salida": ultima_salida.date().isoformat() if not pd.isna(ultima_salida) else "",
            "meses_sin_salida": round(meses_sin, 1) if not math.isnan(meses_sin) else "",
            "dias_consignacion": int(dias_consig),
            "valor_bodega": int(max(bodega, 0) * fila.precio_lista),
            "alertas": " · ".join(alertas),
        })

    titulos = pd.DataFrame(filas)
    embarques = pedido.proximos_embarques(mov, catalogo, p, fecha_corte)
    lineas, por_origen = pedido.sugerir(titulos, costos, p, fecha_corte, envios, embarques)
    categorias = cat_mod.resumen_categorias(titulos)
    matriz = {f"{c}|{k}": int(n) for (c, k), n in titulos.groupby(["categoria_gestion", "clase"]).size().items()}
    conteo = conteo_ciclico(titulos, p, fecha_corte)

    ind, perdidas = {}, []
    if hoja_ventas is not None and len(ventas_mod.validas(hoja_ventas)):
        errores += ventas_mod.errores(hoja_ventas, set(ids))
        ind = ventas_mod.indicadores(hoja_ventas, fecha_corte)
        perdidas = ventas_mod.perdidas_recientes(hoja_ventas, catalogo, fecha_corte)
    resumen = _resumen(titulos, categorias, por_origen, conteo, errores, fecha_corte, p, ind)
    serie.columns = [str(c) for c in serie.columns]
    return Resultado(titulos, lineas, por_origen, resumen, serie, errores, fecha_corte, ind, perdidas,
                     categorias, matriz, conteo)


def _resumen(t: pd.DataFrame, categorias: pd.DataFrame, por_origen: pd.DataFrame, conteo: dict, errores: list[str],
             fecha_corte, p: Parametros, ventas: dict | None = None) -> pd.DataFrame:
    filas = [
        ("Fecha de corte", fecha_corte.date().isoformat()),
        ("Ventana de observación (meses)", p.historia_meses),
        ("Títulos en catálogo", len(t)),
        ("Ejemplares en bodega", int(t["bodega"].clip(lower=0).sum())),
        ("Ejemplares en consignación", int(t["consignacion"].sum())),
        ("Valor en bodega a precio de lista", int((t["bodega"].clip(lower=0) * t["precio_lista"]).sum())),
        ("Títulos en cero", int((t["bodega"] <= 0).sum())),
        ("Títulos AA / BB / CC / DD / sin categoría",
         " / ".join(str(int((t["categoria_gestion"] == c).sum())) for c in cat_mod.ORDEN)),
        ("Títulos AA sin existencias", int(((t["categoria_gestion"] == "AA") & (t["bodega"] <= 0)).sum())),
        ("Títulos con quiebre (se reponen y están en cero)", int(t["alertas"].str.contains("Quiebre").sum())),
        ("Nivel objetivo S, suma (AA que se reponen)", int(t.loc[t["politica"] == "Reponer", "nivel_objetivo"].sum())),
        ("Títulos bajo su nivel objetivo", int(((t["politica"] == "Reponer") & (t["sugerido"] > 0)).sum())),
        ("Nivel de servicio (criterio)", f"{p.nivel_servicio:.0%}"),
    ]
    for r in categorias.itertuples():
        if r.categoria != "Total":
            filas.append((f"Categoría {r.categoria}", f"{r.titulos} títulos, {r.con_existencias} con existencias, "
                                                       f"{r.ejemplares} ejemplares, {r.pct_valor:.1%} del valor"))
    for clase, n in t["clase"].value_counts().items():
        filas.append((f"Clase: {clase}", int(n)))
    for pol, n in t["politica"].value_counts().items():
        filas.append((f"Política: {pol}", int(n)))
    for o in por_origen.itertuples():
        filas.append((f"Embarque {o.origen}", f"{o.estado}, próximo el {o.proximo_embarque}: {o.unidades} unidades, "
                                              f"US$ {o.total_usd:,.0f} (mínimo US$ {o.minimo_usd:,.0f})"))
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
