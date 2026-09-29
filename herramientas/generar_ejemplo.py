"""Genera los datos de ejemplo de datos_ejemplo/: movimientos sintéticos sobre títulos reales del catálogo.

Los títulos, ISBN y precios de lista son públicos (están en el sitio). Todo lo demás es inventado:
clientes, fechas, cantidades, existencias, importaciones y costos. La mezcla de patrones imita la
del análisis real (la mayoría de los títulos se vende de forma esporádica, unos pocos son coyunturales
o estacionales), pero ninguna cifra corresponde a la operación de la Fundación.

Uso:
    python herramientas/generar_ejemplo.py --libros ../PDT/prototipo-web/src/libros
    python herramientas/generar_ejemplo.py            # reutiliza datos_ejemplo/Catalogo.csv
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "datos_ejemplo"
INICIO = pd.Timestamp("2024-10-01")
CORTE = pd.Timestamp("2026-09-28")
PREFIJO = {"inventario_inicial": "CONTEO", "ajuste": "CONTEO", "importacion": "IMP", "consignacion_salida": "GD",
           "consignacion_devolucion": "GD", "consignacion_liquidada": "F", "venta": "F"}
CLIENTES = [f"Cliente {i:02d}" for i in range(1, 23)]


def leer_libros(carpeta: Path) -> pd.DataFrame:
    filas = []
    for md in sorted(carpeta.glob("*.md")):
        t = md.read_text(encoding="utf-8")
        campo = lambda k: (re.search(rf'^{k}:\s*"?(.*?)"?\s*$', t, re.M) or [None, ""])[1]
        filas.append({"id": campo("id_catalogo"), "isbn": campo("isbn"), "titulo": campo("titulo").replace('\\"', '"'),
                      "origen": "Argentina" if "Argentina" in campo("origen_editorial") else "España",
                      "categoria": campo("categoria"), "precio_lista": int(campo("precio_iva") or 0)})
    return pd.DataFrame(filas)


def elegir_catalogo(libros: pd.DataFrame, rng) -> pd.DataFrame:
    """Unos 160 títulos: los de Carlo Acutis (coyunturales), calendarios (estacionales) y una muestra del resto."""
    libros = libros[libros["precio_lista"] > 0]
    coy = libros[libros["titulo"].str.contains("ACUTIS", case=False)].head(5).assign(clase_manual="Coyuntural")
    est = libros[libros["titulo"].str.contains("CALENDARIO|AGENDA", case=False)].head(3).assign(clase_manual="Estacional")
    resto = libros.drop(coy.index).drop(est.index)
    pat = resto[resto["categoria"].str.startswith("Patrística")].sample(60, random_state=1)
    gen = resto[~resto["categoria"].str.startswith("Patrística")].sample(92, random_state=2)
    cat = pd.concat([coy, est, pat, gen]).fillna({"clase_manual": ""})
    cat["politica_manual"] = ""
    # Uno de cada tres libros españoles también se consigue en Argentina (para mostrar la elección de origen)
    num = cat["id"].str.extract(r"(\d+)")[0].astype(int)
    cat["compra_en"] = ""
    cat.loc[(cat["origen"] == "España") & (num % 3 == 0), "compra_en"] = "España o Argentina"
    return cat.sort_values("id").reset_index(drop=True)


def perfil(fila, rng) -> str:
    if fila.clase_manual:
        return fila.clase_manual
    return rng.choice(["regular", "intermitente", "esporadica", "sin_demanda"], p=[0.04, 0.22, 0.58, 0.16])


def demanda_mensual(tipo: str, meses: pd.PeriodIndex, rng) -> np.ndarray:
    n = len(meses)
    d = np.zeros(n, dtype=int)
    if tipo == "regular":
        d = rng.poisson(rng.uniform(2.5, 6), n)
    elif tipo == "intermitente":
        p, tam = rng.uniform(0.2, 0.45), rng.uniform(1, 2.5)
        d = np.where(rng.random(n) < p, 1 + rng.poisson(tam - 1, n), 0)
    elif tipo == "esporadica":
        for i in rng.choice(n, size=rng.integers(0, 3), replace=False):
            d[i] = 1
    elif tipo == "Coyuntural":  # un evento que dispara la demanda y se apaga
        pico = rng.integers(3, 10)
        for i in range(n):
            d[i] = rng.poisson(max(0.3, 30 * np.exp(-abs(i - pico) / 2.5)))
    elif tipo == "Estacional":  # calendarios y agendas: noviembre a enero
        for i, m in enumerate(meses):
            d[i] = rng.poisson(25) if m.month in (11, 12, 1) else 0
    return d


def generar(catalogo: pd.DataFrame, rng) -> tuple[pd.DataFrame, pd.DataFrame]:
    meses = pd.period_range(INICIO, CORTE, freq="M")
    peso_cliente = 1 / np.arange(1, len(CLIENTES) + 1) ** 1.1
    peso_cliente /= peso_cliente.sum()
    movs, transito = [], []
    folio = [1000]

    def mov(fecha, id_, tipo, cant, cliente=""):
        folio[0] += 1
        movs.append({"fecha": fecha.date().isoformat(), "id": id_, "tipo": tipo, "cantidad": int(cant),
                     "documento": f"{PREFIJO.get(tipo, 'F')}-{folio[0]}", "cliente": cliente})

    for fila in catalogo.itertuples():
        tipo = perfil(fila, rng)
        dem = demanda_mensual(tipo, meses, rng)
        nivel = {"regular": 12, "intermitente": 5, "esporadica": 2, "sin_demanda": 3, "Coyuntural": 40, "Estacional": 0}[tipo]
        stock = int(rng.integers(0, nivel + 1)) if tipo != "Coyuntural" else 10
        if stock:
            mov(INICIO, fila.id, "inventario_inicial", stock)
        for i, m in enumerate(meses):
            inicio_mes = m.start_time
            # Reposición trimestral ingenua para los títulos que rotan (así la historia tiene importaciones)
            if tipo in ("regular", "intermitente", "Coyuntural") and i % 3 == 0 and i > 0 and stock < nivel // 2:
                llega = nivel - stock
                mov(inicio_mes + pd.Timedelta(days=int(rng.integers(3, 12))), fila.id, "importacion", llega)
                stock += llega
            if tipo == "Estacional" and m.month == 10:
                mov(inicio_mes + pd.Timedelta(days=5), fila.id, "importacion", 70)
                stock += 70
            vendidas = min(int(dem[i]), max(stock, 0))  # lo que no hay en bodega es venta perdida
            while vendidas > 0:
                lote = int(min(vendidas, 1 + rng.poisson(1.5)))
                fecha = inicio_mes + pd.Timedelta(days=int(rng.integers(0, 28)))
                if fecha > CORTE:
                    break
                cliente = rng.choice(CLIENTES, p=peso_cliente)
                if rng.random() < 0.4:  # consignación: se liquida, se devuelve o queda abierta
                    mov(fecha, fila.id, "consignacion_salida", lote, cliente)
                    destino = rng.random()
                    fecha2 = fecha + pd.Timedelta(days=int(rng.integers(60, 420)))
                    if fecha2 <= CORTE and destino < 0.45:
                        mov(fecha2, fila.id, "consignacion_liquidada", lote, cliente)
                    elif fecha2 <= CORTE and destino < 0.65:
                        mov(fecha2, fila.id, "consignacion_devolucion", lote, cliente)
                        stock += lote
                else:
                    mov(fecha, fila.id, "venta", lote, cliente)
                stock -= lote
                vendidas -= lote
        if tipo in ("regular", "intermitente") and rng.random() < 0.15:
            transito.append({"id": fila.id, "cantidad": int(rng.integers(2, 6)), "origen": fila.origen,
                             "fecha_estimada": (CORTE + pd.Timedelta(days=7)).date().isoformat()})
    # Un par de ajustes de conteo
    for id_ in rng.choice(catalogo["id"], 3, replace=False):
        mov(pd.Timestamp("2026-08-21"), id_, "ajuste", int(rng.choice([-1, 1])))
    m = pd.DataFrame(movs).sort_values(["fecha", "id"]).reset_index(drop=True)
    return m, pd.DataFrame(transito, columns=["id", "cantidad", "origen", "fecha_estimada"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--libros", type=Path, help="carpeta src/libros del sitio (solo la primera vez)")
    ap.add_argument("--semilla", type=int, default=2026)
    a = ap.parse_args()
    rng = np.random.default_rng(a.semilla)
    SALIDA.mkdir(exist_ok=True)
    if a.libros:
        catalogo = elegir_catalogo(leer_libros(a.libros), rng)
        catalogo[["id", "isbn", "titulo", "origen", "categoria", "precio_lista", "clase_manual", "politica_manual", "compra_en"]] \
            .to_csv(SALIDA / "Catalogo.csv", index=False)
    catalogo = pd.read_csv(SALIDA / "Catalogo.csv", dtype=str, keep_default_na=False)
    movimientos, transito = generar(catalogo, rng)
    movimientos.to_csv(SALIDA / "Movimientos.csv", index=False)
    transito.to_csv(SALIDA / "EnTransito.csv", index=False)
    # Costos inventados. Un libro español comprado vía Argentina: FOB más alto (menos descuento) pero flete menor
    pd.DataFrame([
        {"origen": "España", "edicion": "", "fob_sobre_precio_neto": 0.45, "costo_sobre_precio_neto": 0.60, "tipo_cambio": 950},
        {"origen": "Argentina", "edicion": "Argentina", "fob_sobre_precio_neto": 0.40, "costo_sobre_precio_neto": 0.50, "tipo_cambio": 950},
        {"origen": "Argentina", "edicion": "España", "fob_sobre_precio_neto": 0.50, "costo_sobre_precio_neto": 0.57, "tipo_cambio": 950},
    ]).to_csv(SALIDA / "Costos.csv", index=False)
    print(f"{len(catalogo)} títulos, {len(movimientos)} movimientos, {len(transito)} en tránsito → {SALIDA}")


if __name__ == "__main__":
    main()
