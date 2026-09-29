import math

import numpy as np
import pandas as pd
import pytest

from inventario import clasificacion_abc, demanda, politica, stock
from inventario.config import Parametros
from inventario.modelo import calcular


# ---------- Patrones de demanda ----------
def test_sin_demanda_y_puntual():
    assert demanda.clasificar(np.zeros(24))[0] == "Sin demanda"
    s = np.zeros(24); s[5] = 3
    assert demanda.clasificar(s)[0] == "Puntual"


def test_suave_todos_los_meses_parejos():
    patron, adi, cv2 = demanda.clasificar(np.full(12, 4.0))
    assert patron == "Suave" and adi == 1 and cv2 == 0


def test_intermitente_y_grumosa():
    s = np.array([0, 2, 0, 0, 2, 0, 0, 2, 0, 0, 2, 0], dtype=float)  # ADI 3, tamaño constante
    assert demanda.clasificar(s)[0] == "Intermitente"
    s = np.array([0, 1, 0, 0, 9, 0, 0, 1, 0, 0, 12, 0], dtype=float)  # ADI 3, tamaño muy variable
    assert demanda.clasificar(s)[0] == "Grumosa"


def test_errática():
    assert demanda.clasificar(np.array([1, 10, 1, 12, 1, 9, 2, 11], dtype=float))[0] == "Errática"


# ---------- Pronóstico ----------
def test_sba_demanda_regular_intermitente():
    # 2 unidades cada 3 meses → tasa 0,667; SBA la corrige por (1 - alfa/2)
    s = np.array([0, 0, 2] * 8, dtype=float)
    assert demanda.sba(s, 0.1) == pytest.approx((1 - 0.05) * 2 / 3, rel=1e-6)


def test_sba_sin_demanda_es_cero():
    assert demanda.sba(np.zeros(6)) == 0


def test_cuantil_proteccion_crece_con_el_nivel():
    rng = np.random.default_rng(0)
    s = np.array([0, 0, 1, 0, 3, 0, 0, 1, 0, 2, 0, 0], dtype=float)
    bajo = demanda.cuantil_proteccion(s, 1.2, 0.5, 4000, rng)
    alto = demanda.cuantil_proteccion(s, 1.2, 0.95, 4000, rng)
    assert alto > bajo >= 0


# ---------- ABC ----------
def test_abc_por_valor():
    unidades = pd.Series({"a": 100, "b": 10, "c": 5, "d": 0})
    precio = pd.Series({"a": 11900, "b": 11900, "c": 11900, "d": 11900})
    r = clasificacion_abc.clasificar_abc(unidades, precio, 0.8, 0.95)
    assert r.loc["a", "abc"] == "A"
    assert r.loc["b", "abc"] == "B"
    assert r.loc["d", "abc"] == "C"


# ---------- Existencias ----------
def _mov(filas):
    df = pd.DataFrame(filas, columns=["fecha", "id", "tipo", "cantidad"])
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def test_consignacion_no_descuenta_dos_veces():
    mov = _mov([
        ("2025-01-01", "x", "importacion", 10),
        ("2025-02-01", "x", "consignacion_salida", 4),
        ("2025-06-01", "x", "consignacion_liquidada", 3),   # la factura de liquidación no toca la bodega
        ("2025-07-01", "x", "consignacion_devolucion", 1),
        ("2025-08-01", "x", "venta", 2),
    ])
    ex = stock.existencias(mov, pd.DataFrame(columns=["id", "cantidad"]), pd.Timestamp("2025-12-31")).set_index("id")
    assert ex.loc["x", "bodega"] == 10 - 4 + 1 - 2
    assert ex.loc["x", "consignacion"] == 0
    assert pd.isna(ex.loc["x", "consignacion_desde"])


def test_consignacion_abierta_mas_antigua():
    mov = _mov([
        ("2025-01-01", "x", "consignacion_salida", 2),
        ("2025-03-01", "x", "consignacion_salida", 2),
        ("2025-04-01", "x", "consignacion_liquidada", 2),  # liquida la primera (FIFO)
    ])
    ex = stock.existencias(mov, pd.DataFrame(columns=["id", "cantidad"]), pd.Timestamp("2025-12-31")).set_index("id")
    assert ex.loc["x", "consignacion_desde"] == pd.Timestamp("2025-03-01")


# ---------- Política ----------
def test_politica_manual_manda():
    assert politica.decidir("Regular", "A", 5, 1, 18, manual="liquidar o revisar") == "Liquidar o revisar"


@pytest.mark.parametrize("clase,abc,esperado", [
    ("Regular", "A", "Reponer"), ("Intermitente", "C", "Stock mínimo"), ("Esporádica", "A", "A pedido"),
    ("Coyuntural", "A", "No reponer"), ("Estacional", "B", "Temporada"),
])
def test_politica_por_clase(clase, abc, esperado):
    assert politica.decidir(clase, abc, 3, 2, 18) == esperado


def test_sin_movimiento_con_stock_se_liquida():
    assert politica.decidir("Sin demanda", "C", 4, 20, 18) == "Liquidar o revisar"
    assert politica.decidir("Sin demanda", "C", 0, 20, 18) == "A pedido"


# ---------- Cálculo completo ----------
def test_calculo_completo_sugiere_reponer_un_titulo_que_rota():
    catalogo = pd.DataFrame([
        {"id": "r", "isbn": "", "titulo": "Rota", "origen": "España", "categoria": "", "precio_lista": 20000,
         "clase_manual": "", "politica_manual": ""},
        {"id": "q", "isbn": "", "titulo": "Quieto", "origen": "España", "categoria": "", "precio_lista": 20000,
         "clase_manual": "", "politica_manual": ""},
    ])
    filas = [("2024-10-01", "r", "inventario_inicial", 69), ("2024-10-01", "q", "inventario_inicial", 5)]
    for m in pd.period_range("2024-10", "2026-08", freq="M"):
        filas.append((str(m.start_time.date() + pd.Timedelta(days=10)), "r", "venta", 3))
    mov = _mov(filas)
    costos = pd.DataFrame([{"origen": "España", "fob_sobre_precio_neto": 0.45, "costo_sobre_precio_neto": 0.6, "tipo_cambio": 950}])
    r = calcular(catalogo, mov, pd.DataFrame(columns=["id", "cantidad"]), costos, Parametros(), pd.Timestamp("2026-08-31"))
    t = r.titulos.set_index("id")
    assert t.loc["r", "patron"] == "Suave"
    assert t.loc["r", "politica"] == "Reponer"
    assert t.loc["r", "bodega"] == 0 and t.loc["r", "sugerido"] >= 3
    assert "Quiebre" in t.loc["r", "alertas"]
    assert t.loc["q", "politica"] == "Liquidar o revisar"
    assert set(r.pedido["id"]) == {"r"}


# ---------- Lectura de fechas ----------
def test_fechas_iso_chilenas_y_numero_de_serie_de_sheets():
    from inventario.fuentes import _fechas
    r = _fechas(pd.Series(["2026-08-21", "21-08-2026", "03/04/2026", 46255, "46255", ""]))
    assert list(r[:5]) == [pd.Timestamp("2026-08-21"), pd.Timestamp("2026-08-21"), pd.Timestamp("2026-04-03"),
                           pd.Timestamp("2026-08-21"), pd.Timestamp("2026-08-21")]
    assert pd.isna(r.iloc[5])


# ---------- Lenguaje simple ----------
def test_ritmo_y_motivos():
    from inventario import lenguaje
    assert lenguaje.ritmo(3.2) == "≈3 al mes"
    assert lenguaje.ritmo(0.5) == "≈1 cada 2 meses"
    assert lenguaje.ritmo(0.05) == "menos de 1 al año"
    assert lenguaje.ritmo(0) == "—"
    assert lenguaje.motivo_simple("Bajo el stock objetivo + adelanto para completar el mínimo") == "Se vende y queda poco + Para completar el envío mínimo"
    assert lenguaje.motivo_simple("Mantener un ejemplar (stock mínimo)") == "Tener 1 en bodega"


def test_movimientos_con_nombres_legibles():
    from inventario.fuentes import _normalizar
    df = pd.DataFrame({"Fecha": ["21-08-2026", 46255], "Código": ["CN-0016 · CARTAS CRISTOLOGICAS", "CN-0016"],
                       "Tipo": ["Venta (factura)", "Pedido hecho (viene en camino)"], "Cantidad": ["2", 3],
                       "Documento": ["", ""], "Cliente": ["", ""]})
    m = _normalizar("Movimientos", df)
    assert list(m["id"]) == ["CN-0016", "CN-0016"]
    assert list(m["tipo"]) == ["venta", "pedido_en_camino"]
    assert list(m["cantidad"]) == [2, 3]


def test_pedido_en_camino_suma_a_transito_hasta_que_llega():
    mov = _mov([
        ("2026-01-01", "x", "inventario_inicial", 1),
        ("2026-02-01", "x", "pedido_en_camino", 5),
        ("2026-02-10", "x", "importacion", 3),
    ])
    ex = stock.existencias(mov, pd.DataFrame(columns=["id", "cantidad"]), pd.Timestamp("2026-03-01")).set_index("id")
    assert ex.loc["x", "bodega"] == 4
    assert ex.loc["x", "transito"] == 2
