"""«Configuración» automática (inventario/costos.py): dólar del día y factores medidos, sin conectarse."""
import math

import pandas as pd

from inventario import costos


def dolar_fijo(valor=1000.0, hoy="2026-10-16"):
    """Dólar de mentira: la misma serie para cualquier año."""
    serie = [{"fecha": f"{hoy}T03:00:00.000Z", "valor": valor}, {"fecha": "2026-01-02T03:00:00.000Z", "valor": valor}]
    return costos.Dolar(lambda url: {"serie": serie})


def sin_conexion():
    def falla(url):
        raise OSError("sin conexión")
    return costos.Dolar(falla, espera=0)


CATALOGO = pd.DataFrame({"id": ["E1", "E2", "A1"], "origen": ["España", "España", "Argentina"],
                         "precio_lista": [11900, 23800, 11900]})                    # netos: 10.000, 20.000 y 10.000

CONFIG = pd.DataFrame({"origen": ["España", "Argentina", "Argentina"], "edicion": ["", "Argentina", "España"],
                       "fob_sobre_precio_neto": [0.45, 0.4, 0.5], "costo_sobre_precio_neto": [0.6, 0.5, 0.57],
                       "tipo_cambio": [950, 950, 950], "tc_desde": ["", "", ""], "factores_desde": ["", "", ""]})


def importacion(filas):
    cols = ["fecha_pedido", "fecha_llegada", "pais", "documento", "id", "cantidad", "fob_usd", "gastos_clp", "notas", "sumado",
            "fob_eur"]
    df = pd.DataFrame([dict(zip(cols, f)) for f in filas], columns=cols)
    for c in ("fecha_pedido", "fecha_llegada"):
        df[c] = pd.to_datetime(df[c])
    return df


def test_dolar_del_dia_y_de_una_fecha():
    d = dolar_fijo(984.09)
    assert d.hoy() == (984.09, pd.Timestamp("2026-10-16"))
    assert d.en("2026-03-08") == 984.09                     # domingo: el último día hábil anterior
    assert sin_conexion().hoy() is None and sin_conexion().en("2026-03-08") is None


def test_factores_medidos_con_fob_y_gastos():
    imp = importacion([
        # Embarque de España: 10 de E1 (neto 100.000) y 5 de E2 (neto 100.000), FOB US$ 100 → $100.000 de 200.000
        ("2026-05-01", "2026-06-01", "España", "F-1", "E1", 10, 50, 40000, "", ""),
        ("2026-05-01", "2026-06-01", "España", "F-1", "E2", 5, 50, None, "", ""),
        # Argentina, edición argentina: neto 100.000, FOB US$ 40 → 0,4; sin gastos
        ("2026-07-01", "2026-08-01", "Argentina", "D-9", "A1", 10, 40, None, "", ""),
        # En camino: no cuenta
        ("2026-09-01", None, "España", "F-2", "E1", 10, 99, 99999, "", ""),
    ])
    c = costos.actualizar(CONFIG, imp, CATALOGO, pd.Timestamp("2026-10-16"), dolar_fijo(1000), sin_conexion()).set_index(["origen", "edicion"])
    assert c.loc[("España", ""), "fob_sobre_precio_neto"] == 0.5
    assert c.loc[("España", ""), "costo_sobre_precio_neto"] == 0.7           # (100.000 + 40.000) / 200.000
    assert c.loc[("España", ""), "factores_desde"] == pd.Timestamp("2026-06-01")
    assert c.loc[("Argentina", "Argentina"), "fob_sobre_precio_neto"] == 0.4
    assert c.loc[("Argentina", "Argentina"), "costo_sobre_precio_neto"] == 0.5     # sin gastos: el escrito a mano
    assert "costo en bodega: el escrito a mano" in c.loc[("Argentina", "Argentina"), "como"]
    assert c.loc[("Argentina", "España"), "fob_sobre_precio_neto"] == 0.5          # sin embarques: el escrito a mano
    assert (c["tipo_cambio"] == 1000).all() and (c["tc_desde"] == pd.Timestamp("2026-10-16")).all()


def test_solo_los_ultimos_tres_embarques():
    filas = [(f"2026-0{m}-01", f"2026-0{m}-15", "España", f"F-{m}", "E1", 10, fob, None, "", "")
             for m, fob in ((1, 900), (2, 30), (3, 40), (4, 50))]            # el primero, muy caro, ya no cuenta
    c = costos.actualizar(CONFIG, importacion(filas), CATALOGO, pd.Timestamp("2026-10-16"), dolar_fijo(1000), sin_conexion())
    assert math.isclose(c.iloc[0]["fob_sobre_precio_neto"], 0.4)                  # 120.000 / 300.000
    assert "FOB medido con 3 embarques" in c.iloc[0]["como"]


def test_sin_conexion_y_sin_importaciones_queda_lo_escrito():
    c = costos.actualizar(CONFIG, importacion([]), CATALOGO, pd.Timestamp("2026-10-16"), sin_conexion(), sin_conexion())
    assert c["tipo_cambio"].tolist() == [950, 950, 950]
    assert c["fob_sobre_precio_neto"].tolist() == [0.45, 0.4, 0.5]
    assert c.iloc[0]["como"].startswith("Dólar: el escrito a mano")


def test_factura_en_euros_y_euro_del_dia():
    # España factura en euros: 10 de E1 (neto 100.000) por € 40 con el euro a 1.250 → $50.000 → 0,5
    imp = importacion([("2026-05-01", "2026-06-01", "España", "F-9", "E1", 10, None, None, "", "", 40)])
    c = costos.actualizar(CONFIG, imp, CATALOGO, pd.Timestamp("2026-10-16"), dolar_fijo(1000), dolar_fijo(1250))
    assert c.iloc[0]["fob_sobre_precio_neto"] == 0.5
    assert c.iloc[0]["tipo_cambio_eur"] == 1250
