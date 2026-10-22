"""«Configuración» automática: el dólar del día y los factores de costo medidos con «Importaciones».

1. Pesos por dólar y pesos por euro: los observados del Banco Central del último día hábil (mindicador.cl, sin
   clave). Si no responde, queda el valor de la planilla. España factura en euros: con los dos se muestran sus montos
   en € y en US$ (para comparar con Argentina).
2. FOB / precio neto, para cada fila de «Configuración» (país de compra y edición del libro), con los últimos
   EMBARQUES embarques llegados que tienen FOB anotado:
       Σ (FOB × dólar o euro del día de llegada)  /  Σ (precio de lista / 1,19 × cantidad)
   (el FOB se anota en «FOB total US$» o, para facturas en euros, en «FOB total €»)
3. Costo en bodega / precio neto: lo mismo sumando al FOB los gastos de internación del embarque (flete, seguro,
   agente de aduana y aranceles, sin el IVA, que se recupera), solo con embarques que los tienen anotados.

Un embarque es una factura o DIN; sin número, el país y la fecha de llegada. Los gastos se anotan una vez por embarque
(en cualquiera de sus filas) y, si trae libros de dos ediciones, se reparten según el FOB.
La fila general de un país (edición vacía o «Todas») usa los libros de las ediciones que no tienen fila propia.
Sin datos medidos queda el valor escrito a mano, y la columna «Cómo se obtuvo» lo dice.
"""
from __future__ import annotations

import json
import math
import time
import urllib.request

import pandas as pd

from .categorias import IVA
from .importaciones import llegadas, pais

EMBARQUES = 3                  # factores: promedio ponderado de los últimos 3 embarques con datos
EDICION_GENERAL = ("", "todas")
API_DOLAR = "https://mindicador.cl/api/dolar"
API_EURO = "https://mindicador.cl/api/euro"


def _bajar_json(url: str):
    pedido = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; inventario Ciudad Nueva Chile)"})
    return json.loads(urllib.request.urlopen(pedido, timeout=60).read().decode("utf-8"))


class Dolar:
    """Dólar (o euro, con api=API_EURO) observado por fecha. Baja la serie de cada año una sola vez; sin conexión
    devuelve None."""

    def __init__(self, bajar_json=_bajar_json, espera: float = 2, api: str = API_DOLAR):
        self.api = api
        self.bajar_json = bajar_json
        self.espera = espera
        self._anios: dict[int, pd.Series] = {}

    def _serie(self, url: str, intentos: int = 3) -> pd.Series:
        for i in range(intentos):           # mindicador.cl a veces tarda: se reintenta antes de dejar el valor anterior
            try:
                datos = self.bajar_json(url).get("serie", [])
                break
            except Exception:
                if i == intentos - 1:
                    return pd.Series(dtype=float)
                time.sleep(self.espera)
        s = pd.Series({pd.Timestamp(d["fecha"][:10]): float(d["valor"]) for d in datos if d.get("valor")})
        return s.sort_index()

    def hoy(self) -> tuple[float, pd.Timestamp] | None:
        s = self._serie(self.api)
        return (float(s.iloc[-1]), s.index[-1]) if len(s) else None

    def en(self, fecha) -> float | None:
        """El del día, o el del último día hábil anterior."""
        fecha = pd.Timestamp(fecha).normalize()
        for anio in (fecha.year, fecha.year - 1):
            if anio not in self._anios:
                self._anios[anio] = self._serie(f"{self.api}/{anio}")
            s = self._anios[anio]
            if s.empty:
                continue
            s = s[s.index <= fecha]
            if len(s):
                return float(s.iloc[-1])
        return None


def lineas_medibles(imp: pd.DataFrame, catalogo: pd.DataFrame, dolar: Dolar, euro: Dolar | None = None) -> pd.DataFrame:
    """Filas llegadas con FOB, con su embarque, edición, precio neto, FOB en pesos y gastos repartidos."""
    ll = llegadas(imp).copy()
    if ll.empty:
        return pd.DataFrame(columns=["pais", "edicion", "embarque", "fecha", "neto", "fob_clp", "gastos"])
    cat = catalogo.drop_duplicates("id").set_index("id")
    ll["pais"] = ll["pais"].map(pais)
    ll["edicion"] = ll["id"].map(cat["origen"]).fillna("")
    precio = pd.to_numeric(ll["id"].map(cat["precio_lista"]), errors="coerce")
    ll["neto"] = precio / (1 + IVA) * ll["cantidad"]
    ll["fecha"] = pd.to_datetime(ll["fecha_llegada"])
    doc = ll["documento"].astype(str).str.strip()
    ll["embarque"] = ll["pais"] + " · " + doc.where(doc != "", ll["fecha"].dt.strftime("%Y-%m-%d"))
    ll["fob_usd"] = pd.to_numeric(ll["fob_usd"], errors="coerce")
    ll["gastos_clp"] = pd.to_numeric(ll.get("gastos_clp", 0), errors="coerce").fillna(0)
    tc = {f: dolar.en(f) for f in ll["fecha"].dropna().unique()}
    ll["fob_clp"] = ll["fob_usd"] * ll["fecha"].map(tc)
    # Facturas en euros (España): «FOB total €» con el euro del día de llegada, donde no hay FOB en dólares
    ll["fob_eur"] = pd.to_numeric(ll.get("fob_eur", pd.Series(index=ll.index, dtype=float)), errors="coerce")
    en_euros = ll["fob_clp"].isna() & ll["fob_eur"].notna() & (ll["fob_eur"] > 0)
    if en_euros.any() and euro is not None:
        tc_eur = {f: euro.en(f) for f in ll.loc[en_euros, "fecha"].dropna().unique()}
        ll.loc[en_euros, "fob_clp"] = ll.loc[en_euros, "fob_eur"] * ll.loc[en_euros, "fecha"].map(tc_eur)
    # Gastos: se anotan una vez por embarque; se reparten entre sus filas según el FOB
    gastos_emb = ll.groupby("embarque")["gastos_clp"].sum()
    fob_emb = ll.groupby("embarque")["fob_clp"].sum(min_count=1)
    ll["gastos"] = ll["embarque"].map(gastos_emb) * ll["fob_clp"] / ll["embarque"].map(fob_emb)
    ll = ll[ll["fob_clp"].notna() & (ll["fob_clp"] > 0) & ll["neto"].notna() & (ll["neto"] > 0)]
    return ll[["pais", "edicion", "embarque", "fecha", "neto", "fob_clp", "gastos"]]


def medir(lineas: pd.DataFrame, origen: str, edicion: str, ediciones_propias: set[str]) -> dict:
    """Factores medidos para una fila de Configuración: {fob, costo, n_fob, n_costo, hasta}."""
    l = lineas[lineas["pais"] == pais(origen)]
    if str(edicion).strip().lower() in EDICION_GENERAL:
        l = l[~l["edicion"].isin(ediciones_propias)]
    else:
        l = l[l["edicion"] == str(edicion).strip()]
    por_emb = l.groupby("embarque").agg(fecha=("fecha", "max"), neto=("neto", "sum"), fob=("fob_clp", "sum"),
                                        gastos=("gastos", "sum")).sort_values("fecha")
    res = {"fob": math.nan, "costo": math.nan, "n_fob": 0, "n_costo": 0, "hasta": None}
    if por_emb.empty:
        return res
    ult = por_emb.tail(EMBARQUES)
    res.update(fob=ult["fob"].sum() / ult["neto"].sum(), n_fob=len(ult), hasta=ult["fecha"].max())
    con_gastos = por_emb[por_emb["gastos"] > 0].tail(EMBARQUES)
    if len(con_gastos):
        res.update(costo=(con_gastos["fob"].sum() + con_gastos["gastos"].sum()) / con_gastos["neto"].sum(),
                   n_costo=len(con_gastos), hasta=max(res["hasta"], con_gastos["fecha"].max()))
    return res


def _fecha(f) -> str:
    return pd.Timestamp(f).strftime("%d-%m-%Y")


def actualizar(costos: pd.DataFrame, imp: pd.DataFrame, catalogo: pd.DataFrame, hoy: pd.Timestamp,
               dolar: Dolar | None = None, euro: Dolar | None = None) -> pd.DataFrame:
    """Devuelve «Configuración» con el dólar y el euro del día y los factores medidos donde hay datos, más «como»."""
    dolar = dolar or Dolar()
    euro = euro or Dolar(api=API_EURO)
    c = costos.copy()
    if c.empty:
        return c
    if "tipo_cambio_eur" not in c:
        c["tipo_cambio_eur"] = ""
    for col in ("fob_sobre_precio_neto", "costo_sobre_precio_neto", "tipo_cambio", "tipo_cambio_eur"):
        c[col] = pd.to_numeric(c[col], errors="coerce")
    c["como"] = ""
    notas = [[] for _ in range(len(c))]

    actual = dolar.hoy()
    if actual:
        c["tipo_cambio"] = round(actual[0], 2)
        c["tc_desde"] = actual[1]
        for n in notas:
            n.append(f"Dólar del Banco Central del {_fecha(actual[1])}")
    else:
        for n in notas:
            n.append("Dólar: el escrito a mano (mindicador.cl no respondió)")
    actual_eur = euro.hoy()
    if actual_eur:
        c["tipo_cambio_eur"] = round(actual_eur[0], 2)

    lineas = lineas_medibles(imp, catalogo, dolar, euro)
    propias = {o: {str(e).strip() for e in c.loc[c["origen"] == o, "edicion"] if str(e).strip().lower() not in EDICION_GENERAL}
               for o in c["origen"].unique()}
    for i, (idx, fila) in enumerate(c.iterrows()):
        m = medir(lineas, fila["origen"], fila["edicion"], propias.get(fila["origen"], set()))
        if m["n_fob"]:
            c.at[idx, "fob_sobre_precio_neto"] = round(m["fob"], 3)
            notas[i].append(f"FOB medido con {m['n_fob']} embarque{'s' if m['n_fob'] > 1 else ''}")
        else:
            notas[i].append("FOB: el escrito a mano (no hay importaciones llegadas con FOB)")
        if m["n_costo"]:
            c.at[idx, "costo_sobre_precio_neto"] = round(m["costo"], 3)
            notas[i].append(f"costo en bodega medido con {m['n_costo']} embarque{'s' if m['n_costo'] > 1 else ''}")
        else:
            notas[i].append("costo en bodega: el escrito a mano (no hay embarques con gastos de internación)")
        if m["hasta"] is not None:
            c.at[idx, "factores_desde"] = m["hasta"]
    c["como"] = ["; ".join(n) + "." for n in notas]
    return c
