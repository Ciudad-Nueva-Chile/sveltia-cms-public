"""Traducción del resultado técnico a lenguaje simple, para la planilla y el panel.

Todo texto que ve Roberto sale de aquí, así la planilla y el panel dicen lo mismo con las mismas palabras.
"""
from __future__ import annotations

import math
import re

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
                   "compra_en": "Se compra en", "categoria": "Categoría", "categoria_gestion": "Categoría de gestión", "precio_lista": "Precio de venta", "bodega": "En bodega",
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
    "Reponer": "Reponer hasta el nivel objetivo",
    "Reponer lo vendido": "Reponer lo vendido en cada embarque",
    "Temporada": "Un pedido al año antes de septiembre",
    "No reponer": "No reponer",
    "A pedido": "Pedir solo si lo encargan",
}
COMO_SE_VENDE = {
    "Regular": "Casi todos los meses, en cantidades parejas",
    "Intermitente": "De vez en cuando, en tres o más meses",
    "Esporádica": "En uno o dos meses de la ventana",
    "Estacional": "Por temporada (septiembre a marzo)",
    "Coyuntural": "Por un acontecimiento, se atiende por reacción",
    "Sin venta neta": "Sin venta en la ventana",
}
CATEGORIA = {
    "AA": "AA, demanda recurrente",
    "BB": "BB, venta ocasional",
    "CC": "CC, sin venta y salió en guía",
    "DD": "DD, sin venta ni salida",
    "Sin categoría": "Sin categoría",
}


def miles(n) -> str:
    """12345.6 → «12.346»."""
    return f"{float(n):,.0f}".replace(",", ".")


def fecha(v) -> str:
    """2026-10-26 → «26-10-2026»."""
    return pd.Timestamp(v).strftime("%d-%m-%Y") if v not in ("", None) else ""


def ritmo(por_mes: float) -> str:
    """0,5 → «≈1 cada 2 meses», 3,2 → «≈3 al mes». Sin tasa estimada → «Sin tasa»."""
    if not por_mes or por_mes <= 0:
        return "Sin tasa"
    if por_mes >= 0.95:
        return f"≈{round(por_mes)} al mes"
    cada = 1 / por_mes
    if cada > 12:
        return "menos de 1 al año"
    return f"≈1 cada {round(cada)} meses"


def motivo_simple(motivo: str) -> str:
    """El motivo del pedido en palabras cortas, para la planilla y el panel."""
    base, _, comparacion = motivo.partition(". ")
    m = base.lower()
    if "nivel objetivo" in m:
        texto = "Se vende y queda poco"
    elif "lo vendido" in m:
        texto = "Reponer lo vendido"
    elif "temporada" in m:
        texto = "Pedido de temporada"
    else:
        texto = base
    if comparacion:
        texto += ". " + comparacion[0].upper() + comparacion[1:]
    return texto


def libros(t: pd.DataFrame) -> pd.DataFrame:
    """Una fila por libro, solo con lo necesario para decidir."""
    df = pd.DataFrame({
        "Código": t["id"],
        "Título": t["titulo"],
        "Origen": t["origen"],
        "Categoría": t["categoria_gestion"],
        "En bodega": t["bodega"],
        "En consignación": t["consignacion"],
        "Viene en camino": t["transito"],
        "Se vende": t["tasa_mensual"].map(ritmo),
        "Cómo se vende": t["clase"].map(COMO_SE_VENDE),
        "Qué hacer": t["politica"].map(QUE_HACER),
        "Nivel objetivo": t["nivel_objetivo"].where(t["politica"] == "Reponer", ""),
        "Pedir": t["sugerido"].where(t["sugerido"] > 0, ""),
        "Aviso": t["alertas"].fillna(""),
    })
    return df.sort_values(["Categoría", "Título"])


def pedido(lineas: pd.DataFrame) -> pd.DataFrame:
    if lineas.empty:
        return pd.DataFrame(columns=["Cuándo", "Comprar en", "Cantidad", "Título", "Código", "Categoría", "Por qué", "US$ aprox."])
    return pd.DataFrame({
        "Cuándo": lineas["cuando"],
        "Comprar en": lineas["origen"],
        "Cantidad": lineas["cantidad"],
        "Título": lineas["titulo"],
        "Código": lineas["id"],
        "Categoría": lineas["categoria"],
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
    return f"{c['libros_ahora']} libros, " + (f"un envío a {c['envia'][0]}" if len(c["envia"]) == 1 else f"{len(c['envia'])} envíos")


def hoja_pedido(lineas: pd.DataFrame, combinaciones: list[dict], envios: dict, fecha_corte, sep: str = ",",
                por_origen: pd.DataFrame | None = None) -> dict:
    """«Pedido sugerido»: arriba, dónde conviene comprar (con el costo de cada envío editable y la recomendación
    recalculada por fórmulas); al medio, el estado de cada embarque con el aviso de mínimo;
    abajo, la lista de qué pedir.

    Devuelve las filas y su formato: celdas editables, filas en negrita y formatos numéricos (índices desde 0).
    """
    origenes = list(envios)
    filas = [["PEDIDO SUGERIDO", f"Calculado con los datos al {fecha(fecha_corte)}"], [""],
             ["1. DÓNDE CONVIENE COMPRAR"],
             ["Anota la cotización de cada envío (courier, despacho y trámites, en dólares). El flete no se calcula por peso. La recomendación de abajo se recalcula al instante."],
             [""] + origenes,
             [ETIQUETA_ENVIO] + [envios[o] for o in origenes], [""],
             ["Opción", "Qué incluye", "Libros (US$)", "Envíos (US$)", "Total (US$)"]]
    fila_envio = 6  # número de fila (desde 1) del costo de cada envío
    celda = {o: f"{_letra(1 + i)}{fila_envio}" for i, o in enumerate(origenes)}
    primera = len(filas) + 1
    for c in combinaciones:
        r = len(filas) + 1
        envio = "=" + "+".join(celda[o] for o in c["envia"]) if c["envia"] else 0
        filas.append([c["nombre"], que_incluye(c), c["libros_usd"], envio, f"=C{r}+D{r}"])
    ultima = len(filas)
    elegida = next((c["nombre"] for c in combinaciones if c["elegida"]), "")
    if combinaciones:
        rango = f"E{primera}:E{ultima}"
        fila_conviene = len(filas) + 1
        filas.append(["CONVIENE", formula(f"=IFERROR(INDEX(A{primera}:A{ultima},MATCH(MIN({rango}),{rango},0)),\"\")", sep)])
        filas.append(["", formula(f'=IF(B{fila_conviene}="{elegida}","La lista de abajo corresponde a esta opción.",'
                                  f'"Con estos costos conviene otra opción. La lista de abajo se actualiza en el próximo cálculo '
                                  f'(cada mañana, o a mano en GitHub: Actions, Publicar sitio y panel, Run workflow).")', sep)])
        if len(combinaciones) == 1:
            filas.append(["", "Solo hay una combinación que cubre todo lo que hay que pedir: varios títulos se compran en un solo país."])
    else:
        filas.append(["", "No hay nada que pedir en los próximos embarques."])
    filas += [[""], ["2. EMBARQUES"], ["Origen", "Estado", "Próximo embarque", "US$ FOB", "Mínimo US$", "Falta US$"]]
    negritas_extra = [len(filas) - 1]
    for o in (por_origen.to_dict("records") if por_origen is not None and len(por_origen) else []):
        filas.append([o["origen"], o["estado"], fecha(o["proximo_embarque"]), o["total_usd"], o["minimo_usd"], o["falta_usd"]])
        if o["estado"] == "Bajo el mínimo":
            filas.append(["", aviso_minimo(o)])
    filas += [[""], ["3. QUÉ PEDIR"]]
    tabla = pedido(lineas)
    tabla = tabla[["Cuándo", "Comprar en", "Cantidad", "Título", "Código", "US$ aprox.", "Por qué", "Categoría"]]
    encabezado = len(filas)
    filas.append(list(tabla.columns))
    filas += tabla.values.tolist() or [["Nada que pedir por ahora."]]
    return {
        "filas": filas,
        "editables": [(fila_envio - 1, 1 + i) for i in range(len(origenes))],
        "negritas": [4, 7, encabezado] + negritas_extra,
        "formatos": [(fila_envio - 1, fila_envio, 1, 1 + len(origenes), "#,##0"),
                     (primera - 1, ultima, 2, 5, "#,##0")],
    }


def aviso_minimo(o) -> str:
    return f"El envío a {o['origen']} no alcanza el mínimo FOB de US$ {miles(o['minimo_usd'])}."


def estado_pedido(o) -> dict:
    """Frase corta y tono (ok / esperar / nada) para un origen."""
    proximo = fecha(o.get("proximo_embarque", ""))
    if str(o.get("estado", "")).startswith("Pedir"):
        return {"tono": "ok", "titulo": f"Embarque a {o['origen']}: listo para pedir",
                "detalle": f"{o['unidades']} libros, unos US$ {miles(o['total_usd'])} FOB (el mínimo es US$ {miles(o['minimo_usd'])}). Próximo embarque: {proximo}."}
    if str(o.get("estado", "")).startswith("Bajo"):
        return {"tono": "esperar", "titulo": f"Embarque a {o['origen']}: no alcanza el mínimo",
                "detalle": f"{aviso_minimo(o)} Hay {o['unidades']} libros por pedir (US$ {miles(o['total_usd'])} FOB). "
                           f"Roberto decide cómo completarlo. Próximo embarque: {proximo}."}
    return {"tono": "nada", "titulo": f"Embarque a {o['origen']}: nada que pedir",
            "detalle": f"Los títulos que se reponen están sobre su nivel. Próximo embarque: {proximo}."}


def esta_semana(t: pd.DataFrame, por_origen: pd.DataFrame, lineas: pd.DataFrame, fecha_corte, errores: list[str],
                perdidas: list | None = None, sin_anotar: list | None = None, conteo: dict | None = None) -> dict:
    """Todo lo que hay que decidir, en listas cortas.

    perdidas: libros que pidieron y no había (pestaña «Ventas»).
    sin_anotar: bajas de bodega de hoy que no tienen una venta anotada.
    conteo: qué contar esta semana (modelo.conteo_ciclico).
    """
    quiebres = t[t["alertas"].str.contains("Quiebre", na=False)]
    consig = t[t["alertas"].str.contains("Consignación abierta", na=False)].sort_values("dias_consignacion", ascending=False)
    temporada = t[t["politica"] == "Temporada"]
    reclasificar = t[t["reclasificar"].astype(bool)]
    fondo = t[t["categoria_gestion"].isin(["CC", "DD"])].sort_values("valor_bodega", ascending=False)
    conteo = conteo or {}
    return {
        "fecha": pd.Timestamp(fecha_corte).date().isoformat(),
        "pedidos": [estado_pedido(o) | {"origen": o["origen"], "total_usd": o["total_usd"], "minimo_usd": o["minimo_usd"],
                                        "unidades": int(o["unidades"]), "proximo_embarque": o["proximo_embarque"],
                                        "falta_usd": o["falta_usd"]} for o in por_origen.to_dict("records")],
        "sin_stock": [{"id": r.id, "titulo": r.titulo, "se_vende": ritmo(r.tasa_mensual),
                       "en_camino": int(r.transito)} for r in quiebres.itertuples()],
        "fondo": [{"id": r.id, "titulo": r.titulo, "categoria": r.categoria_gestion, "bodega": int(r.bodega),
                   "valor": int(r.valor_bodega)} for r in fondo.itertuples()],
        "valor_cc": int(fondo.loc[fondo["categoria_gestion"] == "CC", "valor_bodega"].sum()),
        "valor_dd": int(fondo.loc[fondo["categoria_gestion"] == "DD", "valor_bodega"].sum()),
        "consignaciones": [{"id": r.id, "titulo": r.titulo, "unidades": int(r.consignacion),
                            "dias": int(r.dias_consignacion)} for r in consig.itertuples()],
        "temporada": [{"id": r.id, "titulo": r.titulo, "vendio": int(r.temporada_unidades), "pedir": int(r.sugerido)}
                      for r in temporada.itertuples()],
        "reclasificar": [{"id": r.id, "titulo": r.titulo, "categoria": r.categoria_gestion} for r in reclasificar.itertuples()],
        "semana": conteo.get("semana", ""),
        "contar": conteo.get("contar", []),
        "frecuencias": conteo.get("frecuencias", []),
        "revisiones": conteo.get("revisiones", []),
        "ahorro_usd": float(por_origen.attrs.get("ahorro_usd", 0.0)),
        "combinaciones": [c | {"incluye": que_incluye(c)} for c in por_origen.attrs.get("combinaciones", [])],
        "envios": por_origen.attrs.get("envios", {}),
        "perdidas": perdidas or [],
        "sin_anotar": sin_anotar or [],
        "errores": errores,
    }


SECCIONES_FIJAS = ("TE LOS PIDIERON", "BAJAS DE STOCK", "PASAN A BB", "REVISAR EN LA PLANILLA", "CÓMO ANOTAR")


def es_titulo_seccion(texto: str) -> bool:
    """«3. QUÉ CONTAR ESTA SEMANA (9)» o uno de los títulos fijos de «Esta semana»."""
    texto = str(texto or "")
    return bool(re.match(r"^\d+\. [A-ZÁÉÍÓÚÑ]", texto)) or texto.startswith(SECCIONES_FIJAS)


def hoja_esta_semana(s: dict) -> pd.DataFrame:
    """La misma información de esta_semana() como una tabla de dos columnas para la planilla."""
    filas = [("", "")]
    filas.append(("1. EMBARQUES A LAS EDITORIALES", ""))
    for p in s["pedidos"]:
        filas.append((p["titulo"], p["detalle"]))
    elegida = next((c for c in s.get("combinaciones", []) if c["elegida"]), None)
    if elegida and len(s["combinaciones"]) > 1:
        filas.append(("Conviene", f"{elegida['nombre']}: unos US$ {miles(elegida['total_usd'])} contando los envíos. La comparación está en «Pedido sugerido»."))
    if s.get("ahorro_usd", 0) > 0:
        filas.append(("Dónde comprar", f"Comprar cada libro en la editorial que conviene ahorra unos US$ {miles(s['ahorro_usd'])} frente a comprarlo en su propia editorial."))
    filas.append(("", "El detalle de qué pedir está en «Pedido sugerido»."))
    filas += [("", ""), (f"2. SE VENDEN Y ESTÁN SIN STOCK ({len(s['sin_stock'])})", "Títulos AA que se reponen y están en cero")]
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
    filas += [("", ""), (f"3. QUÉ CONTAR ESTA SEMANA ({len(s.get('contar', []))})",
                         f"Semana {s.get('semana', '')} del año. AA cada mes, BB cada 6 meses, CC y DD una vez al año")]
    for r in s.get("contar", [])[:60]:
        filas.append((r["titulo"], f"{r['categoria']} · {r['bodega']} en bodega · registro {r['registro'].lower()}"))
    for h in s.get("frecuencias", []):
        filas.append((f"Categoría {h['categoria']}", f"{h['titulos']} títulos con existencias, {int(h['conteos_por_anio'])} conteos al año"))
    for r in s.get("revisiones", []):
        filas.append((f"Revisión de la clasificación {r['categoria']}", f"cada {r['cada_meses']} meses"))
    if s.get("reclasificar"):
        filas += [("", ""), (f"PASAN A BB EN LA PRÓXIMA REVISIÓN ({len(s['reclasificar'])})", "Títulos CC o DD que pidieron por el canal web")]
        for r in s["reclasificar"][:25]:
            filas.append((r["titulo"], f"hoy {r['categoria']}"))
    filas += [("", ""), (f"4. FONDO SIN VENTA: CC Y DD ({len(s['fondo'])})",
                         f"No se reponen. CC ${miles(s['valor_cc'])} y DD ${miles(s['valor_dd'])} a precio de lista. Su destino se decide fuera del sistema")]
    for r in s["fondo"][:25]:
        filas.append((r["titulo"], f"{r['categoria']} · {r['bodega']} en bodega (${miles(r['valor'])})"))
    filas += [("", ""), (f"5. CONSIGNACIONES DE MÁS DE UN AÑO ({len(s['consignaciones'])})", "Cobrar, pedir devolución o renovar")]
    for r in s["consignaciones"][:25]:
        filas.append((r["titulo"], f"{r['unidades']} ejemplares hace {r['dias']} días"))
    if s["temporada"]:
        filas += [("", ""), ("6. PRODUCTOS DE TEMPORADA", "Un pedido al año que debe llegar antes de septiembre")]
        for r in s["temporada"]:
            filas.append((r["titulo"], f"vendió {r['vendio']} la última temporada" + (f" · pedir {r['pedir']}" if r["pedir"] else "")))
    if s["errores"]:
        filas += [("", ""), ("REVISAR EN LA PLANILLA", "")]
        filas += [("", e) for e in s["errores"]]
    filas += [("", ""), ("CÓMO ANOTAR", "Cada venta, en «Ventas» (se descuenta sola del stock cada mañana). "
                                        "En «Inventario», corrige las columnas amarillas para llegadas, conteos y consignaciones. "
                                        "El resto se completa solo.")]
    df = pd.DataFrame(filas, columns=["QUÉ HACER ESTA SEMANA", f"Calculado con los datos al {fecha(s['fecha'])}"])
    # Filas de título de sección. Los títulos de libros también van en mayúsculas, así que no basta mirar la primera columna
    df.attrs["secciones"] = [0] + [i + 1 for i, (a, _) in enumerate(filas) if es_titulo_seccion(a)]
    return df
