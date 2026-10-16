import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import poisson

from inventario import categorias, demanda, politica, stock
from inventario.config import Parametros
from inventario.modelo import calcular, conteo_ciclico


# ---------- Clase de demanda por meses con venta (k) ----------
def test_clase_por_k():
    s = np.zeros(21)
    assert demanda.clasificar(s)[:2] == ("Sin venta neta", 0)
    s[5] = 3
    assert demanda.clasificar(s)[:2] == ("Esporádica", 1)
    s[9] = 1
    assert demanda.clasificar(s)[:2] == ("Esporádica", 2)         # «Puntual» se funde en Esporádica
    s[15] = 2
    assert demanda.clasificar(s)[:2] == ("Intermitente", 3)


def test_regular_si_adi_y_cv2_bajo_los_cortes():
    clase, k, adi, cv2 = demanda.clasificar(np.full(21, 4.0))
    assert clase == "Regular" and k == 21 and adi == 1 and cv2 == 0
    # Casi todos los meses pero con tamaños muy distintos: CV² alto, sigue Intermitente
    assert demanda.clasificar(np.array([1, 10, 1, 12, 1, 9, 2, 11] * 2, dtype=float))[0] == "Intermitente"


def test_adi_y_cv2_son_informativos():
    s = np.array([0, 2, 0, 0, 2, 0, 0, 2, 0, 0, 2, 0], dtype=float)  # ADI 3, tamaño constante
    adi, cv2 = demanda.indicadores(s)
    assert adi == 3 and cv2 == 0
    assert demanda.cuadrante(adi, cv2) == "Intermitente"
    assert demanda.cuadrante(1.0, 0.8) == "Errática"
    assert demanda.cuadrante(*demanda.indicadores(np.array([0, 1, 0, 0, 9, 0, 0, 1, 0, 0, 12, 0], dtype=float))) == "Grumosa"
    assert math.isnan(demanda.indicadores(np.array([0, 0, 3.0]))[0])   # un solo mes: sin indicadores


# ---------- Pronóstico SBA ----------
def test_sba_demanda_regular_intermitente():
    # 2 unidades cada 3 meses → tasa 0,667; SBA la corrige por (1 - alfa/2)
    s = np.array([0, 0, 2] * 8, dtype=float)
    assert demanda.sba(s, 0.1) == pytest.approx((1 - 0.05) * 2 / 3, rel=1e-6)


def test_sba_sin_demanda_es_cero_y_esporadica_no_se_estima():
    assert demanda.sba(np.zeros(6)) == 0
    s = np.zeros(21); s[3] = 5
    assert demanda.pronosticar(s, "Esporádica", 0.15) == 0


# ---------- Nivel objetivo S: Poisson al 95 % con T y L por origen ----------
def test_nivel_objetivo_es_el_percentil_de_poisson():
    lam, T, L = 0.66, 8.5, 7 / 30
    assert demanda.nivel_objetivo(lam, T, L, 0.95) == int(poisson.ppf(0.95, lam * (T + L)))
    assert demanda.nivel_objetivo(0, T, L) == 0


def test_t_y_l_por_origen():
    p = Parametros()
    assert p.intervalo_meses("Argentina") == 12 and p.plazo_meses("Argentina") == pytest.approx(5.5 / 30)
    assert p.intervalo_meses("España") == 8.5 and p.plazo_meses("España") == pytest.approx(7 / 30)
    assert p.intervalo_meses("Uruguay") == 8.5          # todo origen distinto de Argentina se trata como España
    from inventario.config import HISTORIA_MESES
    assert p.nivel_servicio == 0.95 and HISTORIA_MESES == 21


def test_humo_s_con_lambda_t_y_l_conocidos():
    """Prueba de humo: S con λ, T y L conocidos coincide con scipy para ambos orígenes."""
    p = Parametros()
    for origen, lam in (("España", 0.5), ("Argentina", 0.5), ("España", 2.3)):
        media = lam * (p.intervalo_meses(origen) + p.plazo_meses(origen))
        assert demanda.nivel_objetivo(lam, p.intervalo_meses(origen), p.plazo_meses(origen), p.nivel_servicio) == \
            int(poisson.ppf(0.95, media))


# ---------- Categorías A, B, C y D ----------
@pytest.mark.parametrize("clase,bodega,guia,esperada", [
    ("Intermitente", 0, False, "A"), ("Regular", 3, False, "A"), ("Estacional", 0, False, "A"),
    ("Coyuntural", 5, True, "A"), ("Esporádica", 2, True, "B"),          # la demanda manda sobre la guía
    ("Sin venta neta", 4, True, "C"), ("Sin venta neta", 4, False, "D"), ("Sin venta neta", 0, True, "Sin categoría"),
])
def test_categoria(clase, bodega, guia, esperada):
    assert categorias.categoria(clase, bodega, guia) == esperada


# ---------- Política por categoría ----------
def test_politica_manual_manda():
    assert politica.decidir("D", "Sin venta neta", manual="Reponer lo vendido") == "Reponer lo vendido"
    assert politica.decidir("A", "Intermitente", manual="auto") == "Reponer"


@pytest.mark.parametrize("categoria,clase,esperada", [
    ("A", "Intermitente", "Reponer"), ("A", "Regular", "Reponer"), ("A", "Estacional", "Temporada"),
    ("A", "Coyuntural", "No reponer"), ("B", "Esporádica", "Reponer lo vendido"),
    ("C", "Sin venta neta", "No reponer"), ("D", "Sin venta neta", "No reponer"), ("Sin categoría", "Sin venta neta", "A pedido"),
])
def test_politica_por_categoria(categoria, clase, esperada):
    assert politica.decidir(categoria, clase) == esperada


def test_bb_repone_lo_vendido_menos_lo_que_viene():
    assert politica.reponer_lo_vendido(5, 2) == 3
    assert politica.reponer_lo_vendido(1, 4) == 0


# ---------- Existencias ----------
def _mov(filas):
    df = pd.DataFrame(filas, columns=["fecha", "id", "tipo", "cantidad"] + (["cliente"] if len(filas) and len(filas[0]) > 4 else []))
    if "cliente" not in df:
        df["cliente"] = ""
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


def test_venta_neta_incluye_la_venta_perdida_y_no_la_guia():
    mov = _mov([("2026-01-01", "x", "importacion", 5), ("2026-02-01", "x", "venta_perdida", 3),
                ("2026-02-15", "x", "consignacion_salida", 2), ("2026-03-01", "x", "venta", 1)])
    ex = stock.existencias(mov, pd.DataFrame(columns=["id", "cantidad"]), pd.Timestamp("2026-03-31")).set_index("id")
    assert ex.loc["x", "bodega"] == 5 - 2 - 1
    serie = demanda.venta_neta_mensual(mov, ["x"], pd.Timestamp("2026-03-31"), 3)
    assert serie.loc["x"].tolist() == [0, 3, 1]


# ---------- Cálculo completo ----------
def _catalogo(filas):
    base = {"isbn": "", "categoria": "", "clase_manual": "", "politica_manual": "", "compra_en": ""}
    return pd.DataFrame([base | f for f in filas])


def test_calculo_completo_categorias_politica_y_s():
    catalogo = _catalogo([
        {"id": "aa", "titulo": "Rota", "origen": "España", "precio_lista": 20000},
        {"id": "bb", "titulo": "Ocasional", "origen": "Argentina", "precio_lista": 20000},
        {"id": "cc", "titulo": "En guía", "origen": "España", "precio_lista": 20000},
        {"id": "dd", "titulo": "Quieto", "origen": "España", "precio_lista": 20000},
        {"id": "sc", "titulo": "Nada", "origen": "España", "precio_lista": 20000},
        {"id": "co", "titulo": "Evento", "origen": "España", "precio_lista": 20000, "clase_manual": "Coyuntural"},
    ])
    filas = [("2025-01-01", "aa", "inventario_inicial", 2), ("2025-01-01", "cc", "inventario_inicial", 6),
             ("2025-01-01", "dd", "inventario_inicial", 4), ("2025-01-01", "co", "inventario_inicial", 30),
             ("2026-02-01", "bb", "importacion", 5), ("2026-03-10", "bb", "venta", 2), ("2026-05-10", "bb", "venta", 1),
             ("2026-04-01", "cc", "consignacion_salida", 2)]
    for m in ("2025-03", "2025-06", "2025-09", "2025-12", "2026-03", "2026-06"):
        filas.append((f"{m}-10", "aa", "venta", 1))
    for m in ("2025-09", "2025-10", "2025-11"):
        filas.append((f"{m}-10", "co", "venta", 8))
    transito = pd.DataFrame([{"id": "bb", "cantidad": 1}])
    r = calcular(catalogo, _mov(filas), transito, pd.DataFrame(), Parametros(), pd.Timestamp("2026-08-31"))
    t = r.titulos.set_index("id")
    assert t["categoria_gestion"].to_dict() == {"aa": "A", "bb": "B", "cc": "C", "dd": "D", "sc": "Sin categoría", "co": "A"}
    assert t.loc["aa", "clase"] == "Intermitente" and t.loc["aa", "politica"] == "Reponer"
    lam = t.loc["aa", "tasa_mensual"]
    p = Parametros()
    esperado = int(poisson.ppf(0.95, demanda.sba(r.series.loc["aa"].to_numpy(dtype=float), 0.15) * (8.5 + 7 / 30)))
    assert lam > 0 and t.loc["aa", "nivel_objetivo"] == esperado
    assert t.loc["aa", "sugerido"] == esperado              # bodega 2 − 6 ventas = −4: se avisa y cuenta como 0
    assert "Stock negativo" in t.loc["aa", "alertas"]
    # B: vendió 3 desde la importación de febrero y viene 1 en camino → repone 2
    assert t.loc["bb", "politica"] == "Reponer lo vendido" and t.loc["bb", "sugerido"] == 2
    assert t.loc["cc", "sugerido"] == 0 and t.loc["dd", "sugerido"] == 0
    assert t.loc["co", "politica"] == "No reponer"
    # Las categorías suman el total de títulos (con «Sin categoría»)
    cats = r.categorias.set_index("categoria")
    assert cats.loc[["A", "B", "C", "D", "Sin categoría"], "titulos"].sum() == cats.loc["Total", "titulos"] == len(catalogo)
    assert "abc" not in r.titulos.columns


def _ventas_mensuales(desde, hasta, cada=3):
    """Una venta de 2 ejemplares cada `cada` meses, entre dos meses (incluidos)."""
    return [(str(m.start_time.date() + pd.Timedelta(days=9)), "x", "venta", 2)
            for i, m in enumerate(pd.period_range(desde, hasta, freq="M")) if i % cada == 0]


def test_con_21_meses_o_menos_el_pronostico_usa_la_misma_serie():
    catalogo = _catalogo([{"id": "x", "titulo": "x", "origen": "España", "precio_lista": 10000}])
    mov = _mov([("2025-04-01", "x", "inventario_inicial", 30)] + _ventas_mensuales("2025-04", "2026-08"))
    fc = pd.Timestamp("2026-08-31")
    r = calcular(catalogo, mov, pd.DataFrame(columns=["id", "cantidad"]), pd.DataFrame(), Parametros(), fc)
    t = r.titulos.set_index("id")
    ventana = demanda.venta_neta_mensual(stock.limpiar(mov), ["x"], fc, 21).loc["x"].to_numpy(dtype=float)
    assert t.loc["x", "meses_pronostico"] == 21
    assert t.loc["x", "tasa_mensual"] == round(demanda.sba(ventana, 0.15), 3)


def test_con_36_meses_el_pronostico_incorpora_los_meses_anteriores():
    catalogo = _catalogo([{"id": "x", "titulo": "x", "origen": "España", "precio_lista": 10000}])
    # Primeros 15 meses: se vendía todos los meses. Últimos 21 (la ventana): cada 3 meses.
    antes = [(str(m.start_time.date() + pd.Timedelta(days=9)), "x", "venta", 4) for m in pd.period_range("2023-09", "2024-11", freq="M")]
    mov = _mov([("2023-09-01", "x", "inventario_inicial", 200)] + antes + _ventas_mensuales("2024-12", "2026-08"))
    fc = pd.Timestamp("2026-08-31")
    r = calcular(catalogo, mov, pd.DataFrame(columns=["id", "cantidad"]), pd.DataFrame(), Parametros(), fc)
    t = r.titulos.set_index("id")
    limpio = stock.limpiar(mov)
    ventana = demanda.venta_neta_mensual(limpio, ["x"], fc, 21).loc["x"].to_numpy(dtype=float)
    completa = demanda.venta_neta_mensual(limpio, ["x"], fc, 36).loc["x"].to_numpy(dtype=float)
    assert t.loc["x", "meses_pronostico"] == 36
    assert t.loc["x", "clase"] == demanda.clasificar(ventana)[0]                 # la clase sigue usando 21 meses
    assert t.loc["x", "tasa_mensual"] == round(demanda.sba(completa, 0.15), 3)
    assert t.loc["x", "tasa_mensual"] != round(demanda.sba(ventana, 0.15), 3)    # λ cambia con la historia anterior


def test_solicitud_web_de_un_c_o_d_pasa_a_b_en_el_proximo_calculo():
    catalogo = _catalogo([{"id": "d", "titulo": "Quieto", "origen": "España", "precio_lista": 10000}])
    mov = _mov([("2025-01-01", "d", "inventario_inicial", 3, ""),
                ("2026-03-01", "d", "venta_perdida", 1, "Web / WhatsApp")])
    hoja = _ventas([("2026-03-01", "d", 1, "", "Web / WhatsApp", "No había stock", "")])
    vacio = pd.DataFrame(columns=["id", "cantidad"])
    # Recién anotada (sin marcar en «Ventas»): sigue en D, con el aviso
    r = calcular(catalogo, mov, vacio, pd.DataFrame(), Parametros(), pd.Timestamp("2026-04-30"), hoja_ventas=hoja)
    t = r.titulos.set_index("id")
    assert t.loc["d", "categoria_gestion"] == "D" and bool(t.loc["d", "reclasificar"])
    assert "pasa a B en el próximo cálculo" in t.loc["d", "alertas"]
    # En el cálculo siguiente la fila ya está marcada: cuenta como venta neta y el título queda en B
    hoja["descontado"] = "Anotada el 30-04-2026 (no mueve stock)"
    r = calcular(catalogo, mov, vacio, pd.DataFrame(), Parametros(), pd.Timestamp("2026-04-30"), hoja_ventas=hoja)
    assert r.titulos.set_index("id").loc["d", "categoria_gestion"] == "B"


def test_conteo_ciclico_por_categoria():
    t = pd.DataFrame({"id": [f"a{i}" for i in range(8)] + ["b0", "c0", "d0"],
                      "titulo": ["x"] * 11, "bodega": [1] * 11,
                      "categoria_gestion": ["A"] * 8 + ["B", "C", "D"]})
    c = conteo_ciclico(t, Parametros(), pd.Timestamp("2026-10-07"))
    frec = {h["categoria"]: h for h in c["frecuencias"]}
    assert frec["A"]["titulos"] == 8 and frec["A"]["conteos_por_anio"] == 12 and frec["D"]["conteos_por_anio"] == 1
    # A se cuenta cada 4 semanas: 8 títulos → 2 por semana
    assert sum(1 for x in c["contar"] if x["categoria"] == "A") == 2
    # Repartido en el año, cada título A se cuenta 13 veces (≈ mensual)
    veces = {}
    for semana in range(1, 53):
        fecha = pd.Timestamp.fromisocalendar(2026, semana, 3)
        for x in conteo_ciclico(t, Parametros(), fecha)["contar"]:
            veces[x["id"]] = veces.get(x["id"], 0) + 1
    assert veces["a0"] == 13 and veces["d0"] == 1


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
    assert lenguaje.ritmo(0) == "Sin tasa"
    assert lenguaje.motivo_simple("Bajo el nivel objetivo S. Conviene Argentina: US$ 5,10 puesto en bodega contra US$ 7,40 en España") == \
        "Se vende y queda poco. Conviene Argentina: US$ 5,10 puesto en bodega contra US$ 7,40 en España"
    assert lenguaje.motivo_simple("Reponer lo vendido desde el embarque anterior") == "Reponer lo vendido"


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


# ---------- Pedido por embarque y dónde comprar ----------
def _titulo(id_, origen, sugerido, precio, compra_en="", categoria="A", tasa=0.0, unidades=0):
    return {"id": id_, "isbn": "", "titulo": id_, "origen": origen, "compra_en": compra_en, "precio_lista": precio,
            "sugerido": sugerido, "politica": "Reponer" if categoria == "A" else "Reponer lo vendido",
            "categoria_gestion": categoria, "tasa_mensual": tasa, "unidades_ventana": unidades}


COSTOS = pd.DataFrame([
    {"origen": "España", "edicion": "", "fob_sobre_precio_neto": 0.45, "tipo_cambio": 1000},
    {"origen": "Argentina", "edicion": "Argentina", "fob_sobre_precio_neto": 0.40, "tipo_cambio": 1000},
    {"origen": "Argentina", "edicion": "España", "fob_sobre_precio_neto": 0.30, "tipo_cambio": 1000},  # español vía Argentina, más barato
])


def test_libro_en_ambas_va_al_mas_barato_si_la_combinacion_cubre_todo():
    from inventario import pedido
    t = pd.DataFrame([
        _titulo("esp", "España", 10, 119000),              # solo España
        _titulo("arg", "Argentina", 20, 119000),           # solo Argentina
        _titulo("x", "España", 5, 119000, "España o Argentina"),  # en España 45 c/u, vía Argentina 30 c/u
    ])
    lineas, resumen = pedido.sugerir(t, COSTOS, Parametros(), pd.Timestamp("2026-10-01"))
    combos = resumen.attrs["combinaciones"]
    assert [c["nombre"] for c in combos] == ["Dividir: España y Argentina (2 envíos)"]   # la única que cubre todo
    assert lineas.set_index("id").loc["x", "origen"] == "Argentina"
    assert resumen.attrs["ahorro_usd"] == pytest.approx(5 * 15, abs=0.1)
    assert "castigo_usd" not in combos[0]


def test_el_costo_fijo_puede_juntar_todo_en_un_solo_pais():
    from inventario import pedido
    t = pd.DataFrame([_titulo("esp", "España", 16, 119000), _titulo("x", "España", 5, 119000, "España o Argentina")])
    p = Parametros()
    _, sin_envio = pedido.sugerir(t, COSTOS, p, pd.Timestamp("2026-10-01"))
    assert next(c for c in sin_envio.attrs["combinaciones"] if c["elegida"])["envia"] == ["España", "Argentina"]
    _, con_envio = pedido.sugerir(t, COSTOS, p, pd.Timestamp("2026-10-01"), envios={"España": 100, "Argentina": 100})
    combos = con_envio.attrs["combinaciones"]
    elegida = next(c for c in combos if c["elegida"])
    assert elegida["envia"] == ["España"]
    for c in combos:   # el total es siempre libros + envíos: la planilla lo recalcula con fórmulas
        assert c["total_usd"] == pytest.approx(c["libros_usd"] + c["envio_usd"], abs=0.02)


def test_bajo_el_minimo_solo_avisa_sin_completar():
    from inventario import pedido, lenguaje
    t = pd.DataFrame([_titulo("arg", "Argentina", 2, 119000)])                   # 80 US$ FOB: bajo el mínimo
    lineas, resumen = pedido.sugerir(t, COSTOS, Parametros(), pd.Timestamp("2026-10-01"))
    arg = resumen.set_index("origen").loc["Argentina"]
    assert arg["estado"] == "Bajo el mínimo" and arg["falta_usd"] == pytest.approx(700 - 80, abs=0.1)
    assert list(lineas["id"]) == ["arg"]                                          # no se completó solo
    fila = next(o for o in resumen.to_dict("records") if o["origen"] == "Argentina")
    assert lenguaje.aviso_minimo(fila) == "El envío a Argentina no alcanza el mínimo FOB de US$ 700."


def test_proximo_embarque_es_la_ultima_importacion_mas_t():
    from inventario import pedido
    catalogo = _catalogo([{"id": "a", "titulo": "a", "origen": "Argentina", "precio_lista": 1}])
    mov = _mov([("2026-01-15", "a", "importacion", 3)])
    e = pedido.proximos_embarques(mov, catalogo, Parametros(), pd.Timestamp("2026-10-01"))
    ultima, proximo = e["Argentina"]
    assert ultima == pd.Timestamp("2026-01-15") and proximo.year == 2027 and proximo.month == 1
    assert e["España"][0] is None and e["España"][1] == pd.Timestamp("2026-10-01")  # sin importaciones: vencido


# ---------- Pestaña «Ventas» ----------
def _ventas(filas):
    df = pd.DataFrame(filas, columns=["fecha", "id", "cantidad", "descuento", "canal", "estado", "descontado"])
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["documento"] = df["notas"] = ""
    df["fila_planilla"] = range(2, len(df) + 2)
    return df


def test_descuento_acepta_numero_porcentaje_y_fraccion():
    from inventario.ventas import descuento
    assert descuento("10") == descuento("10%") == descuento(0.1) == pytest.approx(0.1)
    assert descuento("") == 0 and descuento(None) == 0


def test_tipos_de_venta_y_canal():
    from inventario import ventas
    v = _ventas([("2026-10-01", "a", 2, "", "Local", "", ""),
                 ("2026-10-01", "a", 1, "", "Consignación (factura)", "Vendido", ""),
                 ("2026-10-01", "a", 3, "", "Web / WhatsApp", "No había stock", ""),
                 ("2026-10-01", "a", 1, "", "Local", "Devolución", ""),
                 ("", "a", 1, "", "", "", "")])                                  # incompleta: se ignora
    m = ventas.a_movimientos(v)
    assert m["tipo"].tolist() == ["venta", "consignacion_liquidada", "venta_perdida", "devolucion_cliente"]
    assert m["cliente"].tolist()[2] == "Web / WhatsApp"


def test_aplicar_descuenta_una_vez_y_reconoce_lo_bajado_a_mano():
    from inventario import ventas
    hoy = pd.Timestamp("2026-10-05")
    v = _ventas([("2026-10-05", "a", 2, 15, "Web / WhatsApp", "Vendido", ""),
                 ("2026-10-05", "b", 1, "", "Local", "", ""),                   # Roberto ya bajó la bodega de «b»
                 ("2026-10-05", "c", 2, "", "Consignación (factura)", "Vendido", ""),
                 ("2026-10-05", "d", 3, "", "Web / WhatsApp", "No había stock", ""),
                 ("2026-10-05", "a", 9, "", "Local", "", "Descontado el 01-10-2026")])  # ya procesada
    cant = pd.DataFrame([{"id": "a", "bodega": 4, "consignacion": 0, "en_camino": 0},
                         {"id": "b", "bodega": 3, "consignacion": 0, "en_camino": 0},
                         {"id": "c", "bodega": 1, "consignacion": 4, "en_camino": 0},
                         {"id": "d", "bodega": 0, "consignacion": 0, "en_camino": 0}])
    derivados = pd.DataFrame([{"fecha": hoy, "id": "b", "tipo": "venta", "cantidad": 1, "documento": "Cambio en Inventario", "cliente": ""}])
    pend = ventas.validas(v)[ventas.validas(v)["descontado"] == ""]
    nuevas, der, marcas, cambiados = ventas.aplicar(pend, cant, derivados, hoy)
    n = nuevas.set_index("id")
    assert n.loc["a", "bodega"] == 2 and n.loc["b", "bodega"] == 3
    assert n.loc["c", "consignacion"] == 2 and n.loc["c", "bodega"] == 1
    assert n.loc["d", "bodega"] == 0
    assert der.empty                                                          # la baja de «b» la explica la venta
    assert cambiados == {"a", "c"}
    assert marcas[3].startswith("Ya estaba descontado") and "no mueve stock" in marcas[5]
    assert 6 not in marcas


def test_venta_mayor_que_el_stock_queda_en_cero_y_avisa():
    from inventario import ventas
    v = _ventas([("2026-10-05", "a", 5, "", "Local", "", "")])
    cant = pd.DataFrame([{"id": "a", "bodega": 2, "consignacion": 0, "en_camino": 0}])
    nuevas, _, marcas, _ = ventas.aplicar(v, cant, pd.DataFrame(columns=["fecha", "id", "tipo", "cantidad"]), pd.Timestamp("2026-10-05"))
    assert nuevas.set_index("id").loc["a", "bodega"] == 0 and "Revisar" in marcas[2]


def test_hoja_pedido_formulas_con_separador_de_la_planilla():
    from inventario import lenguaje
    combos = [{"nombre": "Todo a España", "envia": ["España"], "elegida": True, "valida": True, "libros_ahora": 3,
               "libros_usd": 100.0, "envio_usd": 0.0, "total_usd": 100.0},
              {"nombre": "Dividir: España y Argentina (2 envíos)", "envia": ["España", "Argentina"], "elegida": False,
               "valida": True, "libros_ahora": 3, "libros_usd": 90.0, "envio_usd": 0.0, "total_usd": 90.0}]
    h = lenguaje.hoja_pedido(pd.DataFrame(), combos, {"España": 50, "Argentina": 0}, "2026-10-05", sep=";")
    filas = h["filas"]
    assert filas[5][:3] == [lenguaje.ETIQUETA_ENVIO, 50, 0]
    assert filas[8][3] == "=B6" and filas[8][4] == "=C9+D9"
    assert filas[9][3] == "=B6+C6"
    conviene = next(f for f in filas if f[0] == "CONVIENE")[1]
    assert ";" in conviene and "," not in conviene
    assert h["editables"] == [(5, 1), (5, 2)]
    assert lenguaje.formula('=IF(A1="a, b",1,2)', ";") == '=IF(A1="a, b";1;2)'


# ---------- Datos del panel cifrados ----------
def test_cifrado_ida_y_vuelta_y_contrasena_incorrecta():
    from inventario import cifrado
    paquete = cifrado.cifrar({"hola": "ñandú", "n": 3}, "clave larga de prueba")
    assert "ñandú" not in str(paquete)
    assert cifrado.descifrar(paquete, "clave larga de prueba") == {"hola": "ñandú", "n": 3}
    with pytest.raises(Exception):
        cifrado.descifrar(paquete, "otra")


def test_secciones_de_esta_semana_no_confunden_titulos_de_libros():
    from inventario import lenguaje
    assert lenguaje.es_titulo_seccion("3. QUÉ CONTAR ESTA SEMANA (9)")
    assert lenguaje.es_titulo_seccion("CÓMO ANOTAR")
    assert not lenguaje.es_titulo_seccion("VIDA DE MARIA (BP. 8)")
    assert not lenguaje.es_titulo_seccion("1 - 2 REYES, 1 - 2 CRONICA")


def test_avisos_de_caducidad():
    from datetime import date
    from inventario.modelo import avisos_caducidad
    hoy = pd.Timestamp("2026-10-01")
    costos = pd.DataFrame([
        {"origen": "España", "edicion": "", "tc_desde": pd.Timestamp("2026-02-01"), "factores_desde": pd.Timestamp("2026-01-01")},   # TC de 8 meses
        {"origen": "Argentina", "edicion": "España", "tc_desde": pd.Timestamp("2026-09-01"), "factores_desde": pd.Timestamp("2025-06-01")},  # factores de 16
        {"origen": "Argentina", "edicion": "Argentina", "tc_desde": pd.NaT, "factores_desde": pd.Timestamp("2026-05-01")},
    ])
    a = avisos_caducidad(costos, hoy, date(2025, 8, 26))
    assert "Tipo de cambio de España sin actualizar hace 8 meses" in a
    assert "Factores de costo de Argentina (edición España) sin revisar hace 16 meses" in a
    assert "Tipo de cambio de Argentina sin fecha de vigencia" in a
    assert "Lista de precios del sitio vigente desde 26-08-2025" in a
    assert not any("Factores de costo de España" in x for x in a)               # 9 meses: bajo el umbral de 12
    assert avisos_caducidad(pd.DataFrame(), hoy, date(2026, 8, 26)) == []


# ---------- Pestaña «Importaciones» ----------
def _imp(filas):
    """filas: (fecha_pedido, fecha_llegada, país, libro, cantidad, sumado)."""
    df = pd.DataFrame(filas, columns=["fecha_pedido", "fecha_llegada", "pais", "id", "cantidad", "sumado"])
    for c in ("fecha_pedido", "fecha_llegada"):
        df[c] = pd.to_datetime(df[c].replace("", None))
    df["documento"] = df["notas"] = ""
    df["fob_usd"] = float("nan")
    df["fila_planilla"] = range(2, len(df) + 2)
    return df


def test_llegada_suma_al_stock_una_vez_con_cuadratura():
    from inventario import importaciones
    hoy = pd.Timestamp("2026-10-05")
    i = _imp([("2026-09-28", "2026-10-05", "España", "a", 5, ""),
              ("2026-09-28", "2026-10-05", "España", "b", 4, ""),                 # Roberto ya subió la bodega de «b»
              ("2026-06-01", "2026-06-08", "España", "a", 9, "Sumado el 08-06-2026")])  # ya sumada antes
    cant = pd.DataFrame([{"id": "a", "bodega": 1, "consignacion": 0, "en_camino": 5},
                         {"id": "b", "bodega": 6, "consignacion": 0, "en_camino": 0}])
    derivados = pd.DataFrame([{"fecha": hoy, "id": "b", "tipo": "importacion", "cantidad": 4, "documento": "", "cliente": ""}])
    pend = importaciones.llegadas(i)[importaciones.llegadas(i)["sumado"] == ""]
    nuevas, der, marcas, cambiados = importaciones.aplicar(pend, cant, derivados, hoy)
    n = nuevas.set_index("id")
    assert n.loc["a", "bodega"] == 6 and n.loc["b", "bodega"] == 6
    assert der.empty and cambiados == {"a"}
    assert marcas[2].startswith("Sumado el") and marcas[3].startswith("Ya estaba sumado") and 4 not in marcas
    m = importaciones.a_movimientos(i)
    assert m["tipo"].eq("importacion").all() and m["fecha"].tolist()[0] == pd.Timestamp("2026-10-05")


def test_filas_sin_llegada_cuentan_como_pedido_en_camino():
    from inventario import importaciones
    i = _imp([("2026-09-20", "", "España", "a", 3, ""), ("2026-09-25", "", "Argentina", "a", 2, ""),
              ("2026-06-01", "2026-06-08", "España", "b", 4, "Sumado")])
    viene = importaciones.en_camino(i)
    assert viene.to_dict() == {"a": 5}                 # «b» no tiene filas abiertas: queda lo que anote Roberto


def _embarques(pais, llegadas, plazo=7):
    return _imp([(str((pd.Timestamp(f) - pd.Timedelta(days=plazo)).date()), f, pais, "x", 2, "Sumado") for f in llegadas])


def test_t_y_l_observados_con_2_3_y_5_embarques_solo_comparan():
    from inventario import importaciones
    p = Parametros()
    dos = importaciones.efectivos(_embarques("España", ["2026-01-10", "2026-04-10"]), p)["España"]
    assert dos["T"] == 8.5 and dos["texto_T"] == "Política: cada 8,5 meses"            # con 2 embarques no se muestra
    tres = importaciones.efectivos(_embarques("España", ["2026-01-10", "2026-04-10", "2026-07-10"], plazo=9), p)["España"]
    assert tres["T"] == 8.5 and tres["L"] == pytest.approx(7 / 30)                     # el cálculo usa la política
    assert tres["texto_T"] == "Política: cada 8,5 meses. Observado: cada 3 meses (3 embarques)"
    assert tres["texto_L"] == "plazo 7 días. Observado: 9 días (3 embarques)"
    assert tres["medido"]["T_meses"] == pytest.approx(90.5 / 30.44, abs=0.01)           # mediana de 90 y 91 días
    # Con 6 embarques, T observado usa solo los últimos 5 (4 intervalos de unos 60 días; el primero, de 200, queda fuera)
    seis = _embarques("Argentina", ["2025-01-01", "2025-07-20", "2025-09-18", "2025-11-17", "2026-01-16", "2026-03-17"])
    m = importaciones.medir(seis, "Argentina")
    assert m["embarques_T"] == 5 and m["T_meses"] == pytest.approx(60 / 30.44, abs=0.01)
    arg = importaciones.efectivos(seis, p)["Argentina"]
    assert arg["T"] == 12 and "Observado: cada 2 meses (5 embarques)" in arg["texto_T"]


def test_proximo_embarque_usa_la_ultima_llegada_real():
    from inventario import pedido
    catalogo = _catalogo([{"id": "a", "titulo": "a", "origen": "España", "precio_lista": 1}])
    mov = _mov([("2025-12-01", "a", "importacion", 3)])
    e = pedido.proximos_embarques(mov, catalogo, Parametros(), pd.Timestamp("2026-10-01"),
                                  ultimas_llegadas={"España": pd.Timestamp("2026-06-01")}, intervalos={"España": 3.0})
    assert e["España"][0] == pd.Timestamp("2026-06-01") and e["España"][1] == pd.Timestamp("2026-08-31")



# ---------- Aviso de aceleración ----------
def test_aceleracion_avisa_si_los_ultimos_3_meses_van_al_doble():
    acelera = np.array([0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 2, 1, 2], dtype=float)   # 5 en 3 meses vs 5 en 18
    assert demanda.acelera(acelera)
    pareja = np.array([1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 1, 0], dtype=float)    # 2 en 3 meses: menos de 3
    assert not demanda.acelera(pareja)
    alta_pero_igual = np.array([2] * 21, dtype=float)                                                  # mismo ritmo: no acelera
    assert not demanda.acelera(alta_pero_igual)


def test_aviso_de_aceleracion_en_el_calculo():
    catalogo = _catalogo([{"id": "x", "titulo": "x", "origen": "España", "precio_lista": 10000}])
    filas = [("2024-12-01", "x", "inventario_inicial", 40)]
    filas += [(f"{m}-10", "x", "venta", 1) for m in ("2025-01", "2025-05", "2025-09", "2026-01")]
    filas += [(f"{m}-10", "x", "venta", 2) for m in ("2026-06", "2026-07", "2026-08")]
    r = calcular(catalogo, _mov(filas), pd.DataFrame(columns=["id", "cantidad"]), pd.DataFrame(), Parametros(), pd.Timestamp("2026-08-31"))
    t = r.titulos.set_index("id")
    assert bool(t.loc["x", "acelera"]) and "Se vende más rápido que antes" in t.loc["x", "alertas"]
    assert t.loc["x", "nivel_objetivo"] == demanda.nivel_objetivo(t.loc["x", "tasa_mensual"], 8.5, 7 / 30)   # S no cambia


# ---------- Disponibilidad en el sitio ----------
def test_disponibilidad_solo_estado_sin_cantidades():
    from types import SimpleNamespace
    from inventario.__main__ import datos_disponibilidad
    t = pd.DataFrame([
        {"id": "a", "bodega": 3, "transito": 0, "categoria_gestion": "A"},
        {"id": "b", "bodega": 0, "transito": 4, "categoria_gestion": "B"},
        {"id": "c", "bodega": 0, "transito": 0, "categoria_gestion": "A"},
        {"id": "d", "bodega": 0, "transito": 2, "categoria_gestion": "D"},
        {"id": "s", "bodega": 0, "transito": 0, "categoria_gestion": "Sin categoría"},
    ])
    d = datos_disponibilidad(SimpleNamespace(titulos=t, fecha_corte=pd.Timestamp("2026-10-13")))
    assert d["fecha"] == "2026-10-13"
    assert d["libros"] == {"a": {"estado": "disponible"}, "b": {"estado": "agotado", "llega": True},
                           "c": {"estado": "agotado", "llega": False}, "d": {"estado": "bajo_pedido"}, "s": {"estado": "bajo_pedido"}}
    for v in d["libros"].values():                       # nunca cantidades ni la categoría
        assert set(v) <= {"estado", "llega"} and not any(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v.values())


# ---------- Catálogo desde el sitio: formatos de Sveltia y del catálogo original ----------
def test_catalogo_lee_el_formato_de_sveltia(tmp_path):
    from inventario.fuentes import catalogo_desde_sitio

    (tmp_path / "a.md").write_text('---\nid_catalogo: "CN-0001"\nisbn: "9788497150033"\ntitulo: "CARTAS \\"X\\""\n'
                                   'origen_editorial: "Ciudad Nueva España"\nprecio_iva: 70900\n---\n', encoding="utf-8")
    (tmp_path / "b.md").write_text("---\ntitulo: LIBRO NUEVO\nautor: ''\nisbn: '9789505864089'\nprecio_iva: 0\n"
                                   "origen_editorial: Ciudad Nueva Argentina\nid_catalogo: ''\n---\nSinopsis: con dos puntos.\n",
                                   encoding="utf-8")
    c = catalogo_desde_sitio(tmp_path).set_index("id")
    assert list(c.index) == ["CN-0001", "9789505864089"]          # sin ID interno: el ISBN, nunca «''»
    assert c.loc["CN-0001", "titulo"] == 'CARTAS "X"' and c.loc["CN-0001", "precio_lista"] == 70900
    assert c.loc["9789505864089", "isbn"] == "9789505864089" and c.loc["9789505864089", "autor"] == ""
    assert c.loc["9789505864089", "origen"] == "Argentina"
