"""Lectura y escritura de tablas: CSV locales (datos de ejemplo) o una Google Sheet privada.

Cada tabla es una pestaña de la planilla o un archivo CSV con el mismo nombre.
Entrada: Catalogo, Movimientos, EnTransito, Costos.
Salida:  Resultado_Titulos, Resultado_Pedido, Resumen.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

COLUMNAS = {
    "Catalogo": ["id", "isbn", "titulo", "origen", "categoria", "precio_lista", "clase_manual", "politica_manual"],
    "Movimientos": ["fecha", "id", "tipo", "cantidad", "documento", "cliente"],
    "EnTransito": ["id", "cantidad", "origen", "fecha_estimada"],
    "Costos": ["origen", "fob_sobre_precio_neto", "costo_sobre_precio_neto", "tipo_cambio"],
}


def _fechas(serie: pd.Series) -> pd.Series:
    """Acepta 2026-03-04 (ISO) y 04-03-2026 o 04/03/2026 (como se escribe en Chile)."""
    numeros = pd.to_numeric(serie, errors="coerce")
    # Google Sheets entrega las fechas como número de serie (días desde 1899-12-30), sin depender del idioma
    serial = pd.to_datetime(numeros.where(numeros > 20000), unit="D", origin="1899-12-30", errors="coerce")
    texto = serie.astype(str).where(numeros.isna())
    iso = pd.to_datetime(texto, format="ISO8601", errors="coerce")
    chilena = pd.to_datetime(texto, dayfirst=True, format="mixed", errors="coerce")
    return serial.fillna(iso).fillna(chilena)


def _normalizar(nombre: str, df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    for col in COLUMNAS.get(nombre, []):
        if col not in df.columns:
            df[col] = ""
    df = df.replace({None: ""}).fillna("")
    if nombre == "Movimientos":
        df["fecha"] = _fechas(df["fecha"])
        df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
        df["tipo"] = df["tipo"].astype(str).str.strip().str.lower()
    if nombre == "EnTransito":
        df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    if nombre == "Catalogo":
        df["precio_lista"] = pd.to_numeric(df["precio_lista"], errors="coerce").fillna(0)
    if nombre == "Costos":
        for col in COLUMNAS["Costos"][1:]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("id",):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
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

    def escribir(self, nombre: str, df: pd.DataFrame) -> None:
        self.salida.mkdir(parents=True, exist_ok=True)
        df.to_csv(self.salida / f"{nombre}.csv", index=False)

    def describir(self) -> str:
        return f"CSV en {self.entrada}"


class FuenteSheets:
    """Google Sheet privada, con una cuenta de servicio.

    Credenciales: variable GOOGLE_CREDENCIALES con el JSON de la cuenta de servicio (en GitHub, un secreto)
    o GOOGLE_CREDENCIALES_ARCHIVO con la ruta al archivo JSON (en tu computador; nunca se sube al repositorio).
    """

    ALCANCES = ["https://www.googleapis.com/auth/spreadsheets"]

    def __init__(self, id_planilla: str):
        import gspread
        from google.oauth2.service_account import Credentials

        if os.environ.get("GOOGLE_CREDENCIALES"):
            info = json.loads(os.environ["GOOGLE_CREDENCIALES"])
            cred = Credentials.from_service_account_info(info, scopes=self.ALCANCES)
        elif os.environ.get("GOOGLE_CREDENCIALES_ARCHIVO"):
            cred = Credentials.from_service_account_file(os.environ["GOOGLE_CREDENCIALES_ARCHIVO"], scopes=self.ALCANCES)
        else:
            raise SystemExit("Faltan credenciales: define GOOGLE_CREDENCIALES o GOOGLE_CREDENCIALES_ARCHIVO.")
        self.gc = gspread.authorize(cred)
        self.libro = self.gc.open_by_key(id_planilla)

    def leer(self, nombre: str) -> pd.DataFrame:
        import gspread

        try:
            hoja = self.libro.worksheet(nombre)
        except gspread.WorksheetNotFound:
            return _normalizar(nombre, pd.DataFrame(columns=COLUMNAS[nombre]))
        filas = hoja.get_all_values(value_render_option="UNFORMATTED_VALUE", date_time_render_option="SERIAL_NUMBER")
        if not filas:
            return _normalizar(nombre, pd.DataFrame(columns=COLUMNAS[nombre]))
        return _normalizar(nombre, pd.DataFrame(filas[1:], columns=filas[0]))

    def escribir(self, nombre: str, df: pd.DataFrame) -> None:
        import gspread

        try:
            hoja = self.libro.worksheet(nombre)
            hoja.clear()
        except gspread.WorksheetNotFound:
            hoja = self.libro.add_worksheet(title=nombre, rows=max(len(df) + 10, 50), cols=max(len(df.columns), 5))
        valores = [list(df.columns)] + df.astype(object).where(df.notna(), "").values.tolist()
        valores = [[v.isoformat()[:10] if hasattr(v, "isoformat") else v for v in fila] for fila in valores]
        hoja.update(values=valores, range_name="A1", value_input_option="USER_ENTERED")
        hoja.freeze(rows=1)

    def describir(self) -> str:
        return f"Google Sheet «{self.libro.title}»"
