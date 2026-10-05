"""Traducción del resultado técnico a lenguaje simple, para la planilla y el panel.

Todo texto que ve Roberto sale de aquí, así la planilla y el panel dicen lo mismo con las mismas palabras.
"""
from __future__ import annotations

import math

import pandas as pd

# ---------- Entradas: nombres legibles ↔ nombres internos ----------
TIPOS_LEGIBLES = {
    "inventario_inicial": "Conteo inicial",
    "importacion": "Llegada de importación",
    "venta": "Venta (factura)",
    "devolucion_cliente": "Devolución de un cliente",
    "consignacion_salida": "Salida en consignación (guía)",
    "consignacion_devolucion": "Devuelto de consignación",
    "consignacion_liquidada": "Factura de consignación",
    "ajuste": "Ajuste de conteo (+ o −)",
    "pedido_en_camino": "Pedido hecho (viene en camino)",
    "venta_perdida": "Venta perdida (no había stock)",
}
TIPO_INTERNO = {v.lower(): k for k, v in TIPOS_LEGIBLES.items()}

ENCABEZADOS = {
    "Inventario": {"id": "Código", "isbn": "ISBN", "titulo": "Título", "autor": "Autor", "origen": "Editorial",
                   "compra_en": "Se compra en", "categoria": "Categoría", "precio_lista": "Precio de venta", "bodega": "En bodega",
                   "consignacion": "En consignación", "en_camino": "Pedido en camino",
                   "actualizado": "Última actualización", "se_vende": "Se vende", "que_hacer": "Qué hacer", "notas": "Notas"},
    "Historial": {"fecha": "Fecha", "id": "Código", "bodega": "En bodega", "consignacion": "En consignación",
                  "en_camino": "Pedido en camino"},
    "Catalogo": {"id": "Código", "isbn": "ISBN", "titulo": "Título", "origen": "Origen", "categoria": "Categoría",
                 "precio_lista": "Precio de lista", "clase_manual": "Tipo especial", "politica_manual": "Decisión manual"},
    "Movimientos": {"fecha": "Fecha", "id": "Código", "tipo": "Tipo", "cantidad": "Cantidad",
                    "documento": "Documento", "cliente": "Cliente"},
    "EnTransito": {"id": "Código", "cantidad": "Cantidad", "origen": "Origen", "fecha_estimada": "Llega aprox."},
    "Ventas": {"fecha": "Fecha", "documento": "Pedido o boleta", "id": "Libro", "cantidad": "Cantidad",
               "descuento": "Descuento (%)", "canal": "Canal", "estado": "Estado", "notas": "Notas", "isbn": "ISBN",
               "precio_lista": "Precio de lista", "total": "Total cobrado", "descontado": "Descontado del stock"},
    "ListaLibros": {"libro": "Libro", "isbn": "ISBN", "precio_lista": "Precio de lista"},
    "Costos": {"origen": "Se compra en", "edicion": "Edición del libro", "fob_sobre_precio_neto": "FOB / precio neto",
               "costo_sobre_precio_neto": "Costo en bodega / precio neto", "tipo_cambio": "Pesos por dólar"},
}
PESTANAS = {"Catalogo": "Catálogo", "Movimientos": "Movimientos", "EnTransito": "En tránsito", "Costos": "Costos"}

# ---------- Salidas ----------
QUE_HACER = {
    "Reponer": "Mantener en bodega",
    "Stock mínimo": "Tener 1 en bodega",
    "A pedido": "Pedir solo si lo encargan",
    "Temporada": "Pedir antes de la temporada",
    "No reponer": "No volver a pedir por ahora",
    "Liquidar o revisar": "Liquidar, devolver o revisar",
}
COMO_SE_VENDE = {
    "Suave": "Todos los meses, parejo",
    "Errática": "Casi todos los meses, en cantidades muy distintas",
    "Intermitente": "De vez en cuando, de a pocos",
    "Grumosa": "De vez en cuando, a veces en cantidad",
    "Puntual": "Casi nunca",
    "Sin demanda": "No se ha vendido",
}
IMPORTANCIA = {"A": "Alta", "B": "Media", "C": "Baja"}


def miles(n) -> str:
    """12345.6 → «12.346»."""
    return f"{float(n):,.0f}".replace(",", ".")


def fecha(v) -> str:
    """2026-10-26 → «26-10-2026»."""
    return pd.Timestamp(v).strftime("%d-%m-%Y") if v not in ("", None) else ""


def ritmo(por_mes: float) -> str:
    """0,5 → «≈1 cada 2 meses»; 3,2 → «≈3 al mes»."""
    if not por_mes or por_mes <= 0:
        return "—"
    if por_mes >= 0.95:
        return f"≈{round(por_mes)} al mes"
    cada = 1 / por_mes
    if cada > 12:
        return "menos de 1 al año"
    return f"≈1 cada {round(cada)} meses"


def motivo_simple(motivo: str) -> str:
    base, _, comparacion = motivo.partition("; ")
    m = base.lower()
    partes = []
    if "objetivo" in m:
        partes.append("Se vende y queda poco")
    if "stock mínimo" in m:
        partes.append("Tener 1 en bodega")
    if "completar" in m:
        partes.append("Para completar el envío mínimo")
    texto = " + ".join(partes) or base
    if comparacion.startswith("esperar"):
        texto += ". Esperar: " + comparacion.split(": ", 1)[1]
    elif comparacion:  # «conviene Argentina: …» o «en Argentina sale más barato…, pero…»
        c = comparacion.split(" + ")[0]
        texto += ". " + c[0].upper() + c[1:]
    return texto


def _meses(v) -> str:
    if v in ("", None) or (isinstance(v, float) and math.isnan(v)):
        return "sin salidas registradas"
    return f"sin salidas hace {int(round(float(v)))} meses"


def libros(t: pd.DataFrame) -> pd.DataFrame:
    """Una fila por libro, solo con lo necesario para decidir."""
    df = pd.DataFrame({
        "Código": t["id"],
        "Título": t["titulo"],
        "Origen": t["origen"],
        "En bodega": t["bodega"],
        "En consignación": t["consignacion"],
        "Viene en camino": t["transito"],
        "Se vende": t["pronostico_mensual"].map(ritmo),
        "Cómo se vende": t["patron"].map(COMO_SE_VENDE),
        "Importancia": t["abc"].map(IMPORTANCIA),
        "Qué hacer": t["politica"].map(QUE_HACER),
        "Tener en bodega": t["stock_objetivo"].where(t["politica"].isin(["Reponer", "Stock mínimo"]), ""),
        "Pedir ahora": t["sugerido"].where(t["sugerido"] > 0, ""),
        "Aviso": t["alertas"].fillna(""),
    })
    orden = {"Mantener en bodega": 0, "Tener 1 en bodega": 1, "Liquidar, devolver o revisar": 2}
    df["_o"] = df["Qué hacer"].map(orden).fillna(3)
    return df.sort_values(["_o", "Pedir ahora", "Título"], ascending=[True, False, True], key=lambda s: s if s.name != "Pedir ahora" else pd.to_numeric(s, errors="coerce").fillna(0)).drop(columns="_o")


def pedido(lineas: pd.DataFrame) -> pd.DataFrame:
    if lineas.empty:
        return pd.DataFrame(columns=["Cuándo", "Comprar en", "Cantidad", "Título", "Código", "Por qué", "US$ aprox."])
    return pd.DataFrame({
        "Cuándo": lineas["cuando"],
        "Comprar en": lineas["origen"],
        "Cantidad": lineas["cantidad"],
        "Título": lineas["titulo"],
        "Código": lineas["id"],
        "Por qué": lineas["motivo"].map(motivo_simple),
        "US$ aprox.": lineas["subtotal_usd"],
    }).sort_values(["Cuándo", "Comprar en", "Título"])


ETIQUETA_ENVIO = "Costo de cada envío (US$)"


def formula(texto: str, sep: str = ",") -> str:
    """Fórmula escrita con comas → con el separador de la planilla (en español, «;»). Respeta los textos entre comillas."""
    if sep == ",":
        return texto
    partes = texto.split('"')
    return '"'.join(p.replace(",", sep) if i % 2 == 0 else p for i, p in enumerate(partes))


def _letra(i: int) -> str:
    return chr(65 + i)


def que_incluye(c: dict) -> str:
    if not c["envia"]:
        return f"Se espera: {c['para_despues']} libros quedan para el próximo envío"
    partes = [f"{c['libros_ahora']} libros"]
    if c["adelantados"]:
        partes.append(f"{c['adelantados']} adelantados para llegar al mínimo")
    if c["para_despues"]:
        partes.append(f"{c['para_despues']} quedan para después")
    return " · ".join(partes)


def hoja_pedido(lineas: pd.DataFrame, combinaciones: list[dict], envios: dict, fecha_corte, sep: str = ",") -> dict:
    """«Pedido sugerido»: arriba, dónde conviene comprar (con el costo de cada envío editable y la recomendación
    recalculada por fórmulas); abajo, la lista de qué pedir.

    Devuelve las filas y su formato: celdas editables, filas en negrita y formatos numéricos (índices desde 0).
    """
    origenes = list(envios)
    filas = [["PEDIDO SUGERIDO", f"Calculado con los datos al {fecha(fecha_corte)}"], [""],
             ["1. DÓNDE CONVIENE COMPRAR"],
             ["Anota cuánto cuesta cada envío (courier, despacho y trámites, en dólares). La recomendación de abajo se recalcula al instante."],
             [""] + origenes,
             [ETIQUETA_ENVIO] + [envios[o] for o in origenes], [""],
             ["Opción", "Qué incluye", "Libros (US$)", "Esperar o adelantar (US$)", "Envíos (US$)", "Total (US$)"]]
    fila_envio = 6  # número de fila (desde 1) del costo de cada envío
    celda = {o: f"{_letra(1 + i)}{fila_envio}" for i, o in enumerate(origenes)}
    primera = len(filas) + 1
    for c in combinaciones:
        r = len(filas) + 1
        if c["valida"]:
            envio = "=" + "+".join(celda[o] for o in c["envia"]) if c["envia"] else 0
            total = f"=C{r}+D{r}+E{r}"
        else:
            envio, total = "", "No alcanza el mínimo"
        filas.append([c["nombre"], que_incluye(c), c["libros_usd"], c["castigo_usd"], envio, total])
    ultima = len(filas)
    elegida = next((c["nombre"] for c in combinaciones if c["elegida"]), "")
    rango = f"F{primera}:F{ultima}"
    fila_conviene = len(filas) + 1
    filas.append(["CONVIENE", formula(f"=IFERROR(INDEX(A{primera}:A{ultima},MATCH(MIN({rango}),{rango},0)),\"\")", sep)])
    filas.append(["", formula(f'=IF(B{fila_conviene}="{elegida}","La lista de abajo corresponde a esta opción.",'
                              f'"Con estos costos conviene otra opción. La lista de abajo se actualiza en el próximo cálculo '
                              f'(cada mañana, o a mano en GitHub: Actions → Publicar sitio y panel → Run workflow).")', sep)])
    filas += [[""], ["2. QUÉ PEDIR"]]
    tabla = pedido(lineas)
    tabla = tabla[["Cuándo", "Comprar en", "Cantidad", "Título", "Código", "US$ aprox.", "Por qué"]]
    encabezado = len(filas)
    filas.append(list(tabla.columns))
    filas += tabla.values.tolist() or [["Nada que pedir por ahora."]]
    return {
        "filas": filas,
        "editables": [(fila_envio - 1, 1 + i) for i in range(len(origenes))],
        "negritas": [4, 7, encabezado],
        "formatos": [(fila_envio - 1, fila_envio, 1, 1 + len(origenes), "#,##0"),
                     (primera - 1, ultima, 2, 6, "#,##0")],
    }


def estado_pedido(o) -> dict:
    """Frase corta y tono (ok / esperar / nada) para un origen."""
    falta = o["minimo_usd"] - o["total_usd"]
    if str(o.get("estado", "")).startswith("Pedir"):
        return {"tono": "ok", "titulo": f"Listo para pedir a {o['origen']}",
                "detalle": f"{o['unidades']} libros, unos US$ {miles(o['total_usd'])} (el mínimo es US$ {miles(o['minimo_usd'])})"}
    if str(o.get("estado", "")).startswith("Acumular"):
        return {"tono": "esperar", "titulo": f"{o['origen']}: todavía no conviene pedir",
                "detalle": f"Hay {o['unidades']} libros por pedir (US$ {miles(o['total_usd'])}); faltan US$ {miles(falta)} para el mínimo del envío. Volver a revisar el {fecha(o['fecha_sugerida'])}."}
    return {"tono": "nada", "titulo": f"{o['origen']}: nada que pedir", "detalle": "Todos los libros que se reponen tienen stock suficiente."}


def esta_semana(t: pd.DataFrame, por_origen: pd.DataFrame, lineas: pd.DataFrame, fecha_corte, errores: list[str],
                perdidas: list | None = None, sin_anotar: list | None = None) -> dict:
    """Todo lo que hay que decidir, en listas cortas.

    perdidas: libros que pidieron y no había (pestaña «Ventas»).
    sin_anotar: bajas de bodega de hoy que no tienen una venta anotada.
    """
    quiebres = t[t["alertas"].str.contains("Quiebre", na=False)]
    liquidar = t[t["politica"] == "Liquidar o revisar"].sort_values("valor_bodega", ascending=False)
    consig = t[t["alertas"].str.contains("Consignación abierta", na=False)].sort_values("dias_consignacion", ascending=False)
    temporada = t[t["politica"] == "Temporada"]
    return {
        "fecha": pd.Timestamp(fecha_corte).date().isoformat(),
        "pedidos": [estado_pedido(o) | {"origen": o["origen"], "total_usd": o["total_usd"], "minimo_usd": o["minimo_usd"],
                                        "unidades": int(o["unidades"])} for o in por_origen.to_dict("records")],
        "sin_stock": [{"id": r.id, "titulo": r.titulo, "se_vende": ritmo(r.pronostico_mensual),
                       "en_camino": int(r.transito)} for r in quiebres.itertuples()],
        "liquidar": [{"id": r.id, "titulo": r.titulo, "bodega": int(r.bodega), "valor": int(r.valor_bodega),
                      "sin_salida": _meses(r.meses_sin_salida)} for r in liquidar.itertuples()],
        "consignaciones": [{"id": r.id, "titulo": r.titulo, "unidades": int(r.consignacion),
                            "dias": int(r.dias_consignacion)} for r in consig.itertuples()],
        "temporada": [{"id": r.id, "titulo": r.titulo, "vendio": int(pd.to_numeric(r.unidades_ventana))} for r in temporada.itertuples()],
        "valor_liquidar": int(liquidar["valor_bodega"].sum()),
        "ahorro_usd": float(por_origen.attrs.get("ahorro_usd", 0.0)),
        "combinaciones": [c | {"incluye": que_incluye(c)} for c in por_origen.attrs.get("combinaciones", [])],
        "envios": por_origen.attrs.get("envios", {}),
        "perdidas": perdidas or [],
        "sin_anotar": sin_anotar or [],
        "errores": errores,
    }


def hoja_esta_semana(s: dict) -> pd.DataFrame:
    """La misma información de esta_semana() como una tabla de dos columnas para la planilla."""
    filas = [("", "")]
    filas.append(("1. PEDIDOS A LAS EDITORIALES", ""))
    for p in s["pedidos"]:
        filas.append((p["titulo"], p["detalle"]))
    elegida = next((c for c in s.get("combinaciones", []) if c["elegida"]), None)
    if elegida and len(s["combinaciones"]) > 1:
        filas.append(("Conviene", f"{elegida['nombre']}: unos US$ {miles(elegida['total_usd'])} contando la espera y los envíos. La comparación está en «Pedido sugerido»."))
    if s.get("ahorro_usd", 0) > 0:
        filas.append(("Dónde comprar", f"Comprar cada libro en la editorial que conviene ahorra unos US$ {miles(s['ahorro_usd'])} frente a comprarlo en su propia editorial."))
    filas.append(("", "El detalle de qué pedir está en la pestaña «Pedido sugerido»."))
    filas += [("", ""), (f"2. SE VENDEN Y ESTÁN SIN STOCK ({len(s['sin_stock'])})", "")]
    for r in s["sin_stock"][:25]:
        filas.append((r["titulo"], f"Se vende {r['se_vende']}" + (f" · vienen {r['en_camino']} en camino" if r["en_camino"] else "")))
    if s.get("perdidas"):
        filas += [("", ""), (f"TE LOS PIDIERON Y NO HABÍA ({len(s['perdidas'])})", "Anotados en «Ventas» como «No había stock», últimos 90 días")]
        for r in s["perdidas"][:25]:
            filas.append((r["titulo"], f"{r['unidades']} ejemplares en {r['veces']} pedidos · último el {fecha(r['ultima'])}"))
    if s.get("sin_anotar"):
        filas += [("", ""), (f"BAJAS DE STOCK SIN VENTA ANOTADA ({len(s['sin_anotar'])})", "Si fue una venta, anótala en «Ventas» con su precio y canal")]
        for r in s["sin_anotar"][:25]:
            filas.append((r["titulo"], f"bajó {r['unidades']} en bodega"))
    filas += [("", ""), (f"3. PARA LIQUIDAR, DEVOLVER O REVISAR ({len(s['liquidar'])})",
                         f"${miles(s['valor_liquidar'])} a precio de lista inmovilizados")]
    for r in s["liquidar"][:25]:
        filas.append((r["titulo"], f"{r['bodega']} en bodega (${miles(r['valor'])}) · {r['sin_salida']}"))
    filas += [("", ""), (f"4. CONSIGNACIONES DE MÁS DE UN AÑO ({len(s['consignaciones'])})", "Cobrar, pedir devolución o renovar")]
    for r in s["consignaciones"][:25]:
        filas.append((r["titulo"], f"{r['unidades']} ejemplares hace {r['dias']} días"))
    if s["temporada"]:
        filas += [("", ""), ("5. PRODUCTOS DE TEMPORADA", "Definir el pedido del próximo ciclo")]
        for r in s["temporada"]:
            filas.append((r["titulo"], f"vendió {r['vendio']} en los últimos 2 años"))
    if s["errores"]:
        filas += [("", ""), ("REVISAR EN LA PLANILLA", "")]
        filas += [("", e) for e in s["errores"]]
    filas += [("", ""), ("CÓMO ANOTAR", "Cada venta, en «Ventas» (se descuenta sola del stock cada mañana). "
                                        "En «Inventario», corrige las columnas amarillas para llegadas, conteos y consignaciones. "
                                        "El resto se completa solo.")]
    return pd.DataFrame(filas, columns=["QUÉ HACER ESTA SEMANA", f"Calculado con los datos al {fecha(s['fecha'])}"])
