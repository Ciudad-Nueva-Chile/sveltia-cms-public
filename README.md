# Inventario Ciudad Nueva Chile

Modelo de inventario para una distribuidora de libros con demanda intermitente: existencias, clasificación ABC,
patrón de demanda, pronóstico y sugerencia de importación por origen. Los datos viven en una Google Sheet
privada; este repositorio público contiene solo el código, los parámetros y **datos de ejemplo sintéticos**.

**Panel de demostración:** <https://ciudad-nueva-chile.github.io/sveltia-cms-public/> (datos de ejemplo)

```
Google Sheet privada                GitHub Actions (cada lunes)              Google Sheet privada
Catalogo · Movimientos      ──▶     python -m inventario --fuente sheets ──▶ Resumen · Resultado_Titulos
EnTransito · Costos                 lee config/parametros.yml                Resultado_Pedido
                                         ▲
                     /admin (Sveltia CMS) edita los parámetros
```

## Qué calcula

| Paso | Método | Archivo |
|---|---|---|
| Existencias | Bodega, consignación y tránsito a partir de los movimientos. La factura de una consignación no vuelve a descontar la bodega; la consignación abierta más antigua se rastrea por orden de salida | `inventario/stock.py` |
| Clasificación ABC | Valor de la venta facturada en los últimos 12 meses; cortes 80 % y 95 % | `inventario/clasificacion_abc.py` |
| Patrón de demanda | ADI y CV² con los cortes 1,32 y 0,49 de Syntetos, Boylan y Croston (2005): suave, errática, intermitente, grumosa; puntual si hubo menos de dos meses con demanda | `inventario/demanda.py` |
| Clase de demanda | Regular, Intermitente, Esporádica o Sin demanda según el patrón; Estacional y Coyuntural se marcan a mano en el catálogo | `inventario/demanda.py` |
| Pronóstico mensual | SBA (Croston con corrección de sesgo) para intermitente y grumosa; suavizamiento exponencial para suave y errática | `inventario/demanda.py` |
| Stock objetivo | Demanda del plazo de reposición más la revisión, al nivel de servicio elegido, estimada remuestreando meses observados (sin suponer una distribución normal, que no sirve con demanda intermitente) | `inventario/demanda.py` |
| Política por título | Reponer (A y B), stock mínimo de un ejemplar (C), a pedido (esporádica), temporada, no reponer (coyuntural), liquidar o revisar (con stock y sin salidas en 18 meses). La planilla puede fijarla a mano | `inventario/politica.py` |
| Pedido por origen | Lo que falta para el objetivo; si no alcanza el mínimo de embarque (US$ 700), propone adelantar demanda de títulos A y B; si aun así no alcanza, acumular | `inventario/pedido.py` |

Límites que conviene tener presentes:
- **La demanda observada está censurada:** cuando no hubo stock, la venta perdida no queda registrada. Las consultas por
  libros no disponibles (por ejemplo, las etiquetadas «No encontrado» en WhatsApp) son la forma de corregirlo.
- El remuestreo supone que los próximos meses se parecen a los de la ventana. Un evento como una canonización cambia
  eso: por eso existe la clase Coyuntural.
- Las cifras en dólares dependen de los factores de la pestaña Costos, que son una estimación por origen.

## Usarlo en tu computador

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m inventario --panel panel/datos.json     # calcula con datos_ejemplo/ y escribe salida/
python -m http.server -d panel 8000               # abre http://localhost:8000
pytest -q                                         # pruebas
```

Con la planilla real: ver [docs/CONFIGURAR.md](docs/CONFIGURAR.md).

## Estructura

```
config/parametros.yml       parámetros del modelo (se editan en /admin)
inventario/                 el modelo (Python)
panel/                      panel web estático que lee datos.json
admin/                      Sveltia CMS para editar los parámetros (versión fija en package.json)
herramientas/               generar_ejemplo.py (datos sintéticos) y crear_planilla.py (prepara la Google Sheet)
datos_ejemplo/              datos sintéticos: los títulos y precios son públicos; clientes, cantidades y costos son inventados
tests/                      pruebas del modelo
.github/workflows/          pruebas, publicación del panel de demostración, cálculo semanal con la planilla
```

## Privacidad

Este repositorio es público. **Los datos reales nunca se suben**: viven en la planilla privada, el cálculo
semanal escribe los resultados en ella y no imprime cifras en el registro de GitHub Actions (que también es
público). Las credenciales de Google se guardan como secreto del repositorio. El `.gitignore` bloquea las
credenciales, la carpeta `salida/` y `panel/datos.json`.

## Actualizaciones

Dependabot propone una vez al mes las versiones nuevas de Sveltia CMS, de las librerías de Python y de las
acciones de GitHub. Cada propuesta pasa por las pruebas antes de aceptarla; si nadie la acepta, todo sigue
funcionando con la versión probada.
