"""Lectura y escritura de tablas: CSV locales (datos de ejemplo) o una Google Sheet privada.

En la planilla, Roberto edita las columnas amarillas de «Inventario», la pestaña «Ventas» y el costo de cada envío
en «Pedido sugerido». El catálogo sale del sitio (src/libros), los costos de la pestaña oculta «Configuración» y
todo lo demás lo escribe el cálculo.

Internamente las tablas usan nombres cortos (Catalogo, Movimientos, EnTransito, Costos) y columnas en
minúscula; en la planilla se ven con nombres legibles (ver lenguaje.py). Se aceptan ambas formas.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd

from .lenguaje import ENCABEZADOS, ETIQUETA_ENVIO, TIPO_INTERNO
from . import ventas as ventas_mod

COLUMNAS = {
    "Catalogo": ["id", "isbn", "titulo", "origen", "categoria", "precio_lista", "clase_manual", "politica_manual", "compra_en"],
    "Movimientos": ["fecha", "id", "tipo", "cantidad", "documento", "cliente"],
    "EnTransito": ["id", "cantidad", "origen", "fecha_estimada"],
    "Costos": ["origen", "edicion", "fob_sobre_precio_neto", "costo_sobre_precio_neto", "tipo_cambio"],
    "Inventario": ["id", "isbn", "titulo", "autor", "origen", "compra_en", "categoria", "categoria_gestion", "precio_lista",
                   "bodega", "consignacion", "en_camino", "actualizado", "se_vende", "que_hacer", "notas"],
    "Historial": ["fecha", "id", "bodega", "consignacion", "en_camino"],
    "Ventas": ventas_mod.COLUMNAS,
    "Envios": ["origen", "costo_usd"],
    "ListaLibros": ["libro", "isbn", "precio_lista"],
}
# Nombre de la pestaña en la planilla (el primero es el que se crea; los demás se aceptan al leer)
PESTANA = {
    "Catalogo": ["Catálogo", "Catalogo"],
    "Movimientos": ["Registro de movimientos", "Movimientos"],
    "Inventario": ["Inventario"],
    "Historial": ["Historial"],
    "EnTransito": ["En tránsito", "EnTransito"],
    "Costos": ["Configuración", "Costos"],
    "Ventas": ["Ventas"],
    "ListaLibros": ["Lista de libros"],
    "Pedido": ["Pedido sugerido"],
}
SEPARADOR_LIBRO = " · "   # «CN-0016 · CARTAS CRISTOLOGICAS» en la lista desplegable


def _fechas(serie: pd.Series) -> pd.Series:
    """Acepta número de serie de Sheets, 2026-03-04 (ISO) y 04-03-2026 o 04/03/2026 (como se escribe en Chile)."""
    numeros = pd.to_numeric(serie, errors="coerce")
    serial = pd.to_datetime(numeros.where(numeros > 20000), unit="D", origin="1899-12-30", errors="coerce")
    texto = serie.astype(str).where(numeros.isna())
    iso = pd.to_datetime(texto, format="ISO8601", errors="coerce")
    chilena = pd.to_datetime(texto, dayfirst=True, format="mixed", errors="coerce")
    return serial.fillna(iso).fillna(chilena)


def _normalizar(nombre: str, df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    if nombre == "Ventas":
        df = df.reset_index(drop=True)
        df["fila_planilla"] = range(2, len(df) + 2)  # fila en la planilla, para anotar «Descontado del stock»
    legibles = {v.lower(): k for k, v in ENCABEZADOS.get(nombre, {}).items()}
    df = df.rename(columns=lambda c: legibles.get(c.lower(), c))
    for col in COLUMNAS.get(nombre, []):
        if col not in df.columns:
            df[col] = ""
    df = df.replace({None: ""}).fillna("")
    if "id" in df.columns:
        # «CN-0016 · CARTAS CRISTOLOGICAS» → «CN-0016»
        df["id"] = df["id"].astype(str).str.split(SEPARADOR_LIBRO).str[0].str.strip()
    if nombre == "Movimientos":
        df = df[(df["id"] != "") | (df["tipo"].astype(str).str.strip() != "")]  # filas vacías de la planilla
        df["fecha"] = _fechas(df["fecha"])
        df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
        tipo = df["tipo"].astype(str).str.strip()
        df["tipo"] = tipo.str.lower().map(TIPO_INTERNO).fillna(tipo.str.lower())
    if nombre in ("Inventario", "Historial"):
        for col in ("bodega", "consignacion", "en_camino"):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        df = df[df["id"] != ""]
    if nombre == "Historial":
        df["fecha"] = _fechas(df["fecha"])
    if nombre == "Ventas":
        df["fecha"] = _fechas(df["fecha"])
        df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0).astype(int)
        for col in ("canal", "estado", "descontado", "documento", "notas"):
            df[col] = df[col].astype(str).str.strip()
    if nombre == "Envios":
        df["costo_usd"] = pd.to_numeric(df["costo_usd"].astype(str).str.replace(",", "."), errors="coerce").fillna(0)
    if nombre == "EnTransito":
        df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    if nombre == "Catalogo":
        df["precio_lista"] = pd.to_numeric(df["precio_lista"], errors="coerce").fillna(0)
    if nombre == "Costos":
        df["edicion"] = df["edicion"].astype(str).str.strip()
        for col in ("fob_sobre_precio_neto", "costo_sobre_precio_neto", "tipo_cambio"):
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "."), errors="coerce")
        df = df[df["origen"].astype(str).str.strip() != ""]
    return df


def catalogo_desde_sitio(carpeta: Path) -> pd.DataFrame:
    """El catálogo del sitio (src/libros/*.md) es la fuente única de títulos, precios y decisiones manuales."""
    filas = []
    for md in sorted(Path(carpeta).glob("*.md")):
        cabecera = md.read_text(encoding="utf-8").split("\n---", 1)[0]  # solo el encabezado YAML

        def campo(k):
            m = re.search(rf'^{k}:\s*(.*?)\s*$', cabecera, re.M)
            return m.group(1).strip().strip('"').replace('\\"', '"') if m else ""

        editorial = campo("origen_editorial")
        filas.append({
            "id": campo("id_catalogo") or campo("isbn") or md.stem,
            "isbn": campo("isbn"),
            "titulo": campo("titulo"),
            "origen": "Argentina" if "Argentina" in editorial else "España" if "España" in editorial or not editorial else editorial,
            "categoria": campo("categoria"),
            "autor": campo("autor"),
            "precio_lista": pd.to_numeric(campo("precio_iva"), errors="coerce"),
            "clase_manual": campo("inventario_tipo"),
            "politica_manual": campo("inventario_decision"),
            "compra_en": "",
        })
    df = pd.DataFrame(filas, columns=COLUMNAS["Catalogo"] + ["autor"])
    df["precio_lista"] = df["precio_lista"].fillna(0)
    return df


class FuenteCSV:
    """Lee CSV desde una carpeta y escribe los resultados en otra."""

    def __init__(self, carpeta_entrada: Path, carpeta_salida: Path):
        self.entrada = Path(carpeta_entrada)
        self.salida = Path(carpeta_salida)

    def leer(self, nombre: str) -> pd.DataFrame:
        ruta = self.entrada / f"{nombre}.csv"
        df = pd.read_csv(ruta, dtype=str, keep_default_na=False) if ruta.exists() else pd.DataFrame(columns=COLUMNAS[nombre])
        return _normalizar(nombre, df)

    def escribir(self, nombre: str, df: pd.DataFrame, **formato) -> None:
        self.salida.mkdir(parents=True, exist_ok=True)
        df.to_csv(self.salida / f"{nombre.replace(' ', '_')}.csv", index=False)

    def ordenar(self, *a, **k) -> None:
        pass

    def describir(self) -> str:
        return f"CSV en {self.entrada}"


class FuenteSheets:
    """Google Sheet privada, con una cuenta de servicio.

    Credenciales: variable GOOGLE_CREDENCIALES con el JSON de la cuenta de servicio (en GitHub, un secreto)
    o GOOGLE_CREDENCIALES_ARCHIVO con la ruta al archivo JSON (en tu computador; nunca se sube al repositorio).
    """

    ALCANCES = ["https://www.googleapis.com/auth/spreadsheets"]
    COLOR_ENCABEZADO = {"red": 0.93, "green": 0.91, "blue": 0.89}

    def __init__(self, id_planilla: str):
        import gspread
        from google.oauth2.service_account import Credentials

        if os.environ.get("GOOGLE_CREDENCIALES"):
            info = json.loads(os.environ["GOOGLE_CREDENCIALES"])
            cred = Credentials.from_service_account_info(info, scopes=self.ALCANCES)
        elif os.environ.get("GOOGLE_CREDENCIALES_ARCHIVO"):
            cred = Credentials.from_service_account_file(os.path.expanduser(os.environ["GOOGLE_CREDENCIALES_ARCHIVO"]), scopes=self.ALCANCES)
        else:
            raise SystemExit("Faltan credenciales: define GOOGLE_CREDENCIALES o GOOGLE_CREDENCIALES_ARCHIVO.")
        # BackOffHTTPClient reintenta con espera si Google pide bajar el ritmo (límite de 60 lecturas por minuto)
        self.gc = gspread.authorize(cred, http_client=gspread.BackOffHTTPClient)
        self.libro = self.gc.open_by_key(id_planilla)
        self._hojas = None

    def hoja(self, nombre: str):
        if self._hojas is None:  # una sola lectura de la lista de pestañas
            self._hojas = {h.title: h for h in self.libro.worksheets()}
        for titulo in PESTANA.get(nombre, [nombre]):
            if titulo in self._hojas:
                return self._hojas[titulo]
        return None

    @property
    def separador(self) -> str:
        """Separador de argumentos en las fórmulas: «,» en inglés; «;» donde la coma es decimal (español, etc.)."""
        if not hasattr(self, "_sep"):
            locale = self.libro.fetch_sheet_metadata({"fields": "properties.locale"})["properties"].get("locale", "en_US")
            punto = locale.startswith(("en", "ja", "zh", "ko", "th", "he", "iw")) or locale in ("es_MX", "es_US", "es_419")
            self._sep = "," if punto else ";"
        return self._sep

    def _leer_envios(self) -> pd.DataFrame:
        """Costo de cada envío: la fila «Costo de cada envío (US$)» de «Pedido sugerido», bajo los nombres de origen."""
        hoja = self.hoja("Pedido")
        filas = hoja.get_all_values(value_render_option="UNFORMATTED_VALUE") if hoja is not None else []
        for i, fila in enumerate(filas):
            if i and fila and str(fila[0]).strip() == ETIQUETA_ENVIO:
                origenes = filas[i - 1]
                datos = [{"origen": str(o).strip(), "costo_usd": v} for o, v in zip(origenes[1:], fila[1:]) if str(o).strip()]
                return _normalizar("Envios", pd.DataFrame(datos, columns=COLUMNAS["Envios"]))
        return _normalizar("Envios", pd.DataFrame(columns=COLUMNAS["Envios"]))

    def leer(self, nombre: str) -> pd.DataFrame:
        if nombre == "Envios":
            return self._leer_envios()
        hoja = self.hoja(nombre)
        if hoja is None:
            return _normalizar(nombre, pd.DataFrame(columns=COLUMNAS[nombre]))
        filas = hoja.get_all_values(value_render_option="UNFORMATTED_VALUE", date_time_render_option="SERIAL_NUMBER")
        if not filas:
            return _normalizar(nombre, pd.DataFrame(columns=COLUMNAS[nombre]))
        ancho = len(filas[0])
        filas = [f + [""] * (ancho - len(f)) for f in filas]
        return _normalizar(nombre, pd.DataFrame(filas[1:], columns=filas[0]))

    @staticmethod
    def _celda(v):
        """Valor que la API de Google acepta: fechas como texto, sin tipos de numpy ni vacíos NaN."""
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return ""
        if hasattr(v, "isoformat"):
            return v.isoformat()[:10]
        if hasattr(v, "item"):
            return v.item()
        return v

    @classmethod
    def _valores(cls, df: pd.DataFrame, con_encabezado: bool = True) -> list:
        filas = [[cls._celda(v) for v in fila] for fila in df.astype(object).values.tolist()]
        return ([list(df.columns)] if con_encabezado else []) + filas

    @staticmethod
    def _letra(i: int) -> str:
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(65 + r) + s
        return s

    def escribir(self, nombre: str, df, oculta: bool = False, solo_lectura: bool = False,
                 secciones: bool = False, anchos: dict | None = None, editables: list[int] | None = None,
                 filtro: bool = False, congelar_columnas: int = 0, formatos: dict | None = None,
                 notas: dict | None = None, listas: dict | None = None, listas_rango: dict | None = None,
                 celdas_editables: list | None = None, negritas: list | None = None,
                 formatos_rango: list | None = None, filas_minimas: int = 0, reglas: dict | None = None,
                 filas_seccion: list | None = None) -> None:
        """Reemplaza el contenido de una pestaña y le da formato legible.

        df: una tabla, o una lista de filas (la primera es el encabezado).
        editables: índices de columnas que el usuario puede editar (fondo amarillo, sin protección).
        celdas_editables: celdas sueltas (fila, columna) editables, para hojas armadas por filas.
        listas_rango: listas desplegables que toman sus valores de un rango, p. ej. {2: "='Lista de libros'!A2:A"}.
        formatos_rango: [(fila_desde, fila_hasta, col_desde, col_hasta, patrón)], índices desde 0 y finales excluidos.
        reglas: otras validaciones por columna, {col: (condición de la API, texto de ayuda)}.
        filas_seccion: filas (desde 0, contando el encabezado) con formato de título de sección. Sin ella, se usa la
            primera columna en mayúsculas (sirve si ningún dato va en mayúsculas).
        """
        titulo = PESTANA.get(nombre, [nombre])[0]
        hoja = self.hoja(nombre)
        valores = self._valores(df) if isinstance(df, pd.DataFrame) else [[self._celda(v) for v in f] for f in df]
        n = max(len(f) for f in valores)
        valores = [f + [""] * (n - len(f)) for f in valores]
        filas = max(len(valores), filas_minimas)
        if hoja is None:
            hoja = self.libro.add_worksheet(title=titulo, rows=max(filas + 20, 50), cols=max(n, 4))
            self._hojas = None
        else:
            if hoja.title != titulo:  # pestaña de una versión anterior: se renombra
                hoja.update_title(titulo)
                self._hojas = None
            hoja.clear()
            if hoja.row_count < filas:
                hoja.add_rows(filas - hoja.row_count)
        hoja.update(values=valores, range_name="A1", value_input_option="USER_ENTERED")
        editables = editables or []
        celdas_editables = celdas_editables or []

        pedidos = [
            {"updateSheetProperties": {"properties": {"sheetId": hoja.id, "hidden": oculta,
                                                      "gridProperties": {"frozenRowCount": 0 if secciones else 1,
                                                                         "frozenColumnCount": congelar_columnas}},
                                       "fields": "hidden,gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
            {"repeatCell": {"range": {"sheetId": hoja.id},
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": False}, "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                                                           "wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
                            "fields": "userEnteredFormat(textFormat,backgroundColor,wrapStrategy,verticalAlignment)"}},
        ]
        amarillo = {"red": 1, "green": 0.973, "blue": 0.827}
        for col in editables:
            pedidos.append({"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
                                           "cell": {"userEnteredFormat": {"backgroundColor": amarillo}},
                                           "fields": "userEnteredFormat.backgroundColor"}})
        if secciones:
            # Filas de título de sección: texto en mayúsculas en la primera columna
            for i, fila in enumerate(valores):
                es_seccion = (i in filas_seccion) if filas_seccion is not None else (
                    fila and isinstance(fila[0], str) and fila[0] and fila[0] == fila[0].upper() and any(ch.isalpha() for ch in fila[0]))
                if es_seccion:
                    pedidos.append({"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": i, "endRowIndex": i + 1},
                                                   "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 12 if i == 0 else 11},
                                                                                  "backgroundColor": self.COLOR_ENCABEZADO}},
                                                   "fields": "userEnteredFormat(textFormat,backgroundColor)"}})
            for i in negritas or []:
                pedidos.append({"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": i, "endRowIndex": i + 1},
                                               "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                                               "fields": "userEnteredFormat.textFormat.bold"}})
            for r, c in celdas_editables:
                pedidos.append({"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": r, "endRowIndex": r + 1, "startColumnIndex": c, "endColumnIndex": c + 1},
                                               "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 0.894, "blue": 0.6},
                                                                              "textFormat": {"bold": True}}},
                                               "fields": "userEnteredFormat(backgroundColor,textFormat)"}})
        else:
            pedidos.append({"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": 0, "endRowIndex": 1},
                                           "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": self.COLOR_ENCABEZADO}},
                                           "fields": "userEnteredFormat(textFormat,backgroundColor)"}})
            for col in editables:
                pedidos.append({"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
                                               "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": {"red": 1, "green": 0.894, "blue": 0.6}}},
                                               "fields": "userEnteredFormat(textFormat,backgroundColor)"}})
        for col, patron in (formatos or {}).items():
            tipo = "DATE" if "yy" in patron else "NUMBER"
            pedidos.append({"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
                                           "cell": {"userEnteredFormat": {"numberFormat": {"type": tipo, "pattern": patron}}},
                                           "fields": "userEnteredFormat.numberFormat"}})
        for r0, r1, c0, c1, patron in formatos_rango or []:
            pedidos.append({"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": r0, "endRowIndex": r1, "startColumnIndex": c0, "endColumnIndex": c1},
                                           "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": patron}}},
                                           "fields": "userEnteredFormat.numberFormat"}})
        for col, rango in (listas_rango or {}).items():
            pedidos.append({"setDataValidation": {"range": {"sheetId": hoja.id, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
                                                  "rule": {"condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": rango}]},
                                                           "strict": True, "showCustomUi": True}}})
        for col, (condicion, ayuda) in (reglas or {}).items():
            pedidos.append({"setDataValidation": {"range": {"sheetId": hoja.id, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
                                                  "rule": {"condition": condicion, "inputMessage": ayuda, "strict": True}}})
        for col, valores_lista in (listas or {}).items():  # listas desplegables
            pedidos.append({"setDataValidation": {"range": {"sheetId": hoja.id, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
                                                  "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in valores_lista]},
                                                           "strict": True, "showCustomUi": True}}})
        for col, texto in (notas or {}).items():
            pedidos.append({"updateCells": {"range": {"sheetId": hoja.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1},
                                            "rows": [{"values": [{"note": texto}]}], "fields": "note"}})
        for col, ancho in (anchos or {}).items():
            pedidos.append({"updateDimensionProperties": {"range": {"sheetId": hoja.id, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1},
                                                          "properties": {"pixelSize": ancho}, "fields": "pixelSize"}})
        if filtro:
            pedidos.append({"setBasicFilter": {"filter": {"range": {"sheetId": hoja.id, "startRowIndex": 0, "endRowIndex": len(valores),
                                                                    "startColumnIndex": 0, "endColumnIndex": n}}}})
        # Protección de solo advertencia: evita editar por error lo que escribe el cálculo
        meta = self.libro.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,protectedRanges.protectedRangeId)"})
        for s in meta["sheets"]:
            if s["properties"]["sheetId"] == hoja.id:
                for pr in s.get("protectedRanges", []):
                    pedidos.append({"deleteProtectedRange": {"protectedRangeId": pr["protectedRangeId"]}})
        if solo_lectura:
            protegidas = [c for c in range(n) if c not in editables] if editables else None
            rangos = ([{"sheetId": hoja.id}] if protegidas is None else
                      [{"sheetId": hoja.id, "startColumnIndex": c, "endColumnIndex": c + 1} for c in protegidas])
            if celdas_editables:  # protegida entera salvo esas celdas
                rangos = [{"sheetId": hoja.id, "_sin": [{"sheetId": hoja.id, "startRowIndex": r, "endRowIndex": r + 1,
                                                         "startColumnIndex": c, "endColumnIndex": c + 1} for r, c in celdas_editables]}]
            for r in rangos:
                sin = r.pop("_sin", None)
                rango = {"range": r, "warningOnly": True,
                         "description": "La completa el cálculo: los cambios aquí se pierden en el próximo cálculo."}
                if sin:
                    rango["unprotectedRanges"] = sin
                pedidos.append({"addProtectedRange": {"protectedRange": rango}})
        self.libro.batch_update({"requests": pedidos})

    def agregar_filas(self, nombre: str, df: pd.DataFrame) -> None:
        """Agrega filas al final (para los registros que solo crecen)."""
        if df.empty:
            return
        hoja = self.hoja(nombre)
        if hoja is None:
            self.escribir(nombre, df, oculta=True, solo_lectura=True)
            return
        hoja.append_rows(self._valores(df, con_encabezado=False), value_input_option="USER_ENTERED")

    def actualizar_columnas(self, nombre: str, datos: pd.DataFrame, columnas: list[str], columna_id: str) -> None:
        """Escribe solo algunas columnas, fila por fila según el código de cada fila en la planilla.

        Respeta el orden que tenga la pestaña (Roberto puede ordenarla o filtrarla) y no toca las columnas editables.
        datos: indexado por código, con los nombres de columna tal como se ven en la planilla.
        """
        hoja = self.hoja(nombre)
        filas = hoja.get_all_values()
        encabezado = filas[0]
        ids = [f[encabezado.index(columna_id)] if len(f) > encabezado.index(columna_id) else "" for f in filas[1:]]
        rangos = []
        for col in columnas:
            j = encabezado.index(col)
            valores = [[self._celda(datos.at[i, col]) if i in datos.index else ""] for i in ids]
            letra = self._letra(j)
            rangos.append({"range": f"{letra}2:{letra}{len(ids) + 1}", "values": valores})
        if rangos:
            hoja.batch_update(rangos, value_input_option="USER_ENTERED")

    def escribir_celdas(self, nombre: str, columna: str, valores_por_fila: dict) -> None:
        """Escribe celdas sueltas de una columna (por encabezado) según el número de fila: {fila: valor}."""
        if not valores_por_fila:
            return
        hoja = self.hoja(nombre)
        encabezado = hoja.row_values(1)
        letra = self._letra(encabezado.index(columna))
        hoja.batch_update([{"range": f"{letra}{fila}", "values": [[self._celda(v)]]} for fila, v in valores_por_fila.items()],
                          value_input_option="USER_ENTERED")

    def actualizar_celdas(self, nombre: str, columna_id: str, cambios: dict) -> None:
        """Escribe solo las celdas que cambian, buscando la fila por código: {código: {columna: valor}}."""
        if not cambios:
            return
        hoja = self.hoja(nombre)
        filas = hoja.get_all_values()
        encabezado = filas[0]
        j = encabezado.index(columna_id)
        fila_de = {f[j]: i + 2 for i, f in enumerate(filas[1:]) if len(f) > j}
        rangos = [{"range": f"{self._letra(encabezado.index(col))}{fila_de[id_]}", "values": [[self._celda(v)]]}
                  for id_, cols in cambios.items() if id_ in fila_de for col, v in cols.items()]
        if rangos:
            hoja.batch_update(rangos, value_input_option="USER_ENTERED")

    def notas_encabezado(self, nombre: str, notas: dict) -> None:
        """Pone (o actualiza) la nota de algunas columnas del encabezado: {encabezado: texto}."""
        hoja = self.hoja(nombre)
        encabezado = hoja.row_values(1)
        pedidos = [{"updateCells": {"range": {"sheetId": hoja.id, "startRowIndex": 0, "endRowIndex": 1,
                                              "startColumnIndex": encabezado.index(c), "endColumnIndex": encabezado.index(c) + 1},
                                    "rows": [{"values": [{"note": t}]}], "fields": "note"}}
                   for c, t in notas.items() if c in encabezado]
        if pedidos:
            self.libro.batch_update({"requests": pedidos})

    def ordenar(self, nombres: list[str], visibles: int | None = None) -> None:
        """Deja las pestañas en este orden (las no mencionadas quedan al final).

        visibles: cuántas de las primeras quedan a la vista; las demás se ocultan.
        """
        self._hojas = None
        self.hoja("Inventario")
        hojas = self._hojas
        titulos = [PESTANA.get(n, [n])[0] for n in nombres]
        pedidos = []
        for i, t in enumerate(titulos):
            if t not in hojas:
                continue
            props, campos = {"sheetId": hojas[t].id, "index": i}, "index"
            if visibles is not None:
                props["hidden"], campos = i >= visibles, "index,hidden"
            pedidos.append({"updateSheetProperties": {"properties": props, "fields": campos}})
        if pedidos:
            self.libro.batch_update({"requests": pedidos})

    def describir(self) -> str:
        return f"Google Sheet «{self.libro.title}»"
