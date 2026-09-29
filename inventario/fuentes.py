"""Lectura y escritura de tablas: CSV locales (datos de ejemplo) o una Google Sheet privada.

En la planilla, Roberto edita una sola pestaña: «Movimientos». El catálogo sale del sitio (src/libros),
los costos de la pestaña oculta «Configuración» y todo lo demás lo escribe el cálculo.

Internamente las tablas usan nombres cortos (Catalogo, Movimientos, EnTransito, Costos) y columnas en
minúscula; en la planilla se ven con nombres legibles (ver lenguaje.py). Se aceptan ambas formas.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd

from .lenguaje import ENCABEZADOS, TIPO_INTERNO

COLUMNAS = {
    "Catalogo": ["id", "isbn", "titulo", "origen", "categoria", "precio_lista", "clase_manual", "politica_manual"],
    "Movimientos": ["fecha", "id", "tipo", "cantidad", "documento", "cliente"],
    "EnTransito": ["id", "cantidad", "origen", "fecha_estimada"],
    "Costos": ["origen", "fob_sobre_precio_neto", "costo_sobre_precio_neto", "tipo_cambio"],
}
# Nombre de la pestaña en la planilla (el primero es el que se crea; los demás se aceptan al leer)
PESTANA = {
    "Catalogo": ["Catálogo", "Catalogo"],
    "Movimientos": ["Movimientos"],
    "EnTransito": ["En tránsito", "EnTransito"],
    "Costos": ["Configuración", "Costos"],
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
    if nombre == "EnTransito":
        df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    if nombre == "Catalogo":
        df["precio_lista"] = pd.to_numeric(df["precio_lista"], errors="coerce").fillna(0)
    if nombre == "Costos":
        for col in COLUMNAS["Costos"][1:]:
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
            "precio_lista": pd.to_numeric(campo("precio_iva"), errors="coerce"),
            "clase_manual": campo("inventario_tipo"),
            "politica_manual": campo("inventario_decision"),
        })
    df = pd.DataFrame(filas, columns=COLUMNAS["Catalogo"])
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
        self.gc = gspread.authorize(cred)
        self.libro = self.gc.open_by_key(id_planilla)

    def hoja(self, nombre: str):
        import gspread

        for titulo in PESTANA.get(nombre, [nombre]):
            try:
                return self.libro.worksheet(titulo)
            except gspread.WorksheetNotFound:
                continue
        return None

    def leer(self, nombre: str) -> pd.DataFrame:
        hoja = self.hoja(nombre)
        if hoja is None:
            return _normalizar(nombre, pd.DataFrame(columns=COLUMNAS[nombre]))
        filas = hoja.get_all_values(value_render_option="UNFORMATTED_VALUE", date_time_render_option="SERIAL_NUMBER")
        if not filas:
            return _normalizar(nombre, pd.DataFrame(columns=COLUMNAS[nombre]))
        ancho = len(filas[0])
        filas = [f + [""] * (ancho - len(f)) for f in filas]
        return _normalizar(nombre, pd.DataFrame(filas[1:], columns=filas[0]))

    def escribir(self, nombre: str, df: pd.DataFrame, oculta: bool = False, solo_lectura: bool = False,
                 secciones: bool = False, anchos: dict | None = None) -> None:
        """Reemplaza el contenido de una pestaña y le da formato legible."""
        titulo = PESTANA.get(nombre, [nombre])[0]
        hoja = self.hoja(nombre)
        if hoja is None:
            hoja = self.libro.add_worksheet(title=titulo, rows=max(len(df) + 20, 50), cols=max(len(df.columns), 4))
        else:
            if hoja.title != titulo:  # pestaña de una versión anterior: se renombra
                hoja.update_title(titulo)
            hoja.clear()
            if hoja.row_count < len(df) + 1:
                hoja.add_rows(len(df) + 1 - hoja.row_count)
        valores = [list(df.columns)] + df.astype(object).where(df.notna(), "").values.tolist()
        valores = [[v.isoformat()[:10] if hasattr(v, "isoformat") else v for v in fila] for fila in valores]
        hoja.update(values=valores, range_name="A1", value_input_option="USER_ENTERED")

        pedidos = [
            {"updateSheetProperties": {"properties": {"sheetId": hoja.id, "hidden": oculta,
                                                      "gridProperties": {"frozenRowCount": 0 if secciones else 1}},
                                       "fields": "hidden,gridProperties.frozenRowCount"}},
            {"repeatCell": {"range": {"sheetId": hoja.id},
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": False}, "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                                                           "wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
                            "fields": "userEnteredFormat(textFormat,backgroundColor,wrapStrategy,verticalAlignment)"}},
        ]
        if secciones:
            # Filas de título de sección: texto en mayúsculas en la primera columna
            for i, fila in enumerate(valores):
                if fila and isinstance(fila[0], str) and fila[0] and fila[0] == fila[0].upper() and any(ch.isalpha() for ch in fila[0]):
                    pedidos.append({"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": i, "endRowIndex": i + 1},
                                                   "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 12 if i == 0 else 11},
                                                                                  "backgroundColor": self.COLOR_ENCABEZADO}},
                                                   "fields": "userEnteredFormat(textFormat,backgroundColor)"}})
        else:
            pedidos.append({"repeatCell": {"range": {"sheetId": hoja.id, "startRowIndex": 0, "endRowIndex": 1},
                                           "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": self.COLOR_ENCABEZADO}},
                                           "fields": "userEnteredFormat(textFormat,backgroundColor)"}})
        for col, ancho in (anchos or {}).items():
            pedidos.append({"updateDimensionProperties": {"range": {"sheetId": hoja.id, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1},
                                                          "properties": {"pixelSize": ancho}, "fields": "pixelSize"}})
        # Protección de solo advertencia: evita editar por error las pestañas que escribe el cálculo
        meta = self.libro.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,protectedRanges.protectedRangeId)"})
        for s in meta["sheets"]:
            if s["properties"]["sheetId"] == hoja.id:
                for pr in s.get("protectedRanges", []):
                    pedidos.append({"deleteProtectedRange": {"protectedRangeId": pr["protectedRangeId"]}})
        if solo_lectura:
            pedidos.append({"addProtectedRange": {"protectedRange": {
                "range": {"sheetId": hoja.id}, "warningOnly": True,
                "description": "La escribe el cálculo semanal: los cambios se pierden el próximo lunes."}}})
        self.libro.batch_update({"requests": pedidos})

    def ordenar(self, nombres: list[str]) -> None:
        """Deja las pestañas en este orden (las no mencionadas quedan al final)."""
        hojas = {h.title: h for h in self.libro.worksheets()}
        titulos = [PESTANA.get(n, [n])[0] for n in nombres]
        pedidos = [{"updateSheetProperties": {"properties": {"sheetId": hojas[t].id, "index": i}, "fields": "index"}}
                   for i, t in enumerate(titulos) if t in hojas]
        if pedidos:
            self.libro.batch_update({"requests": pedidos})

    def describir(self) -> str:
        return f"Google Sheet «{self.libro.title}»"
