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
    assert set(r.pedido["cuando"]) == {"Próximo envío"}   # unos pocos dólares: no alcanza el mínimo de US$ 700


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
    assert lenguaje.motivo_simple("Bajo el stock objetivo; conviene Argentina: US$ 5,10 puesto en bodega contra US$ 7,40 en España") == \
        "Se vende y queda poco. Conviene Argentina: US$ 5,10 puesto en bodega contra US$ 7,40 en España"
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


# ---------- Pestaña Inventario: deducir movimientos de los cambios ----------
from inventario.planilla import derivar, detectar_cambios  # noqa: E402


def _d(b, c, t=0):
    return {"bodega": b, "consignacion": c, "en_camino": t}


@pytest.mark.parametrize("antes,despues,esperado", [
    (_d(10, 0), _d(8, 0), [("venta", 2)]),
    (_d(10, 0), _d(7, 3), [("consignacion_salida", 3)]),
    (_d(7, 3), _d(9, 1), [("consignacion_devolucion", 2)]),
    (_d(7, 3), _d(7, 1), [("consignacion_liquidada", 2)]),
    (_d(7, 3), _d(8, 0), [("consignacion_devolucion", 1), ("consignacion_liquidada", 2)]),
    (_d(2, 0), _d(12, 0), [("importacion", 10)]),
    (_d(5, 0), _d(5, 0, 4), []),                       # solo cambia «en camino»: no es demanda
    (_d(10, 0), _d(6, 2), [("consignacion_salida", 2), ("venta", 2)]),
])
def test_derivar(antes, despues, esperado):
    assert derivar(antes, despues) == esperado


def test_detectar_cambios_solo_registra_lo_que_cambio():
    hoy = pd.Timestamp("2026-10-01")
    inv = pd.DataFrame([{"id": "a", "bodega": 3, "consignacion": 0, "en_camino": 0},
                        {"id": "b", "bodega": 5, "consignacion": 1, "en_camino": 0},
                        {"id": "c", "bodega": 2, "consignacion": 0, "en_camino": 0}])
    hist = pd.DataFrame([{"fecha": pd.Timestamp("2026-09-01"), "id": "a", "bodega": 3, "consignacion": 0, "en_camino": 0},
                         {"fecha": pd.Timestamp("2026-09-01"), "id": "b", "bodega": 6, "consignacion": 1, "en_camino": 0}])
    fotos, movs = detectar_cambios(inv, hist, pd.DataFrame(columns=["id", "bodega", "consignacion", "transito"]), hoy)
    assert set(fotos["id"]) == {"b", "c"}                      # «a» no cambió
    assert movs[movs["id"] == "b"][["tipo", "cantidad"]].values.tolist() == [["venta", 1]]
    assert movs[movs["id"] == "c"]["tipo"].tolist() == ["inventario_inicial"]  # libro nuevo: conteo


# ---------- Dónde comprar: optimización entre editoriales ----------
def _titulo(id_, origen, sugerido, precio, compra_en="", abc="A"):
    return {"id": id_, "isbn": "", "titulo": id_, "origen": origen, "compra_en": compra_en, "precio_lista": precio,
            "sugerido": sugerido, "politica": "Reponer", "abc": abc, "pronostico_mensual": 0.0, "valor_venta": 0,
            "posicion": 0, "punto_pedido": 0}


COSTOS = pd.DataFrame([
    {"origen": "España", "edicion": "", "fob_sobre_precio_neto": 0.45, "tipo_cambio": 1000},
    {"origen": "Argentina", "edicion": "Argentina", "fob_sobre_precio_neto": 0.40, "tipo_cambio": 1000},
    {"origen": "Argentina", "edicion": "España", "fob_sobre_precio_neto": 0.30, "tipo_cambio": 1000},  # español vía Argentina, más barato
])


def test_libro_en_ambas_va_donde_es_mas_barato_si_ese_envio_se_hace():
    from inventario import pedido
    t = pd.DataFrame([
        _titulo("esp", "España", 10, 119000),              # España: 10 × 45 = 450 US$
        _titulo("arg", "Argentina", 20, 119000),           # Argentina: 20 × 40 = 800 US$ → ese envío se hace
        _titulo("x", "España", 5, 119000, "España o Argentina"),  # en España 45 c/u, vía Argentina 30 c/u
    ])
    lineas, resumen = pedido.sugerir(t, COSTOS, Parametros(), pd.Timestamp("2026-10-01"))
    ahora = lineas[lineas["cuando"] == "Ahora"].set_index("id")
    assert ahora.loc["x", "origen"] == "Argentina"
    assert resumen.attrs["ahorro_usd"] == pytest.approx(5 * 15, abs=0.1)
    # España sola no llega a 700 → sus libros esperan el próximo envío
    assert lineas.set_index("id").loc["esp", "cuando"] == "Próximo envío"


def test_si_argentina_no_alcanza_el_minimo_el_libro_se_compra_en_espana():
    from inventario import pedido
    t = pd.DataFrame([
        _titulo("esp", "España", 16, 119000),              # España: 16 × 45 = 720 US$ → ese envío se hace
        _titulo("arg", "Argentina", 2, 119000),            # Argentina: 80 US$ → no alcanza
        _titulo("x", "España", 5, 119000, "España o Argentina"),
    ])
    lineas, _ = pedido.sugerir(t, COSTOS, Parametros(), pd.Timestamp("2026-10-01"))
    l = lineas.set_index("id")
    assert l.loc["x", "origen"] == "España" and l.loc["x", "cuando"] == "Ahora"
    assert l.loc["arg", "cuando"] == "Próximo envío"
