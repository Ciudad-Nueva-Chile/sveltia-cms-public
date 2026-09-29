# Ciudad Nueva Chile: sitio e inventario

Repositorio de prueba con dos partes que se publican juntas:

- **El sitio** (`src/`, Eleventy): catálogo, fichas, solicitud de pedido por WhatsApp o correo. Se edita en `/admin/` con Sveltia CMS.
- **El inventario** (`inventario/`, Python): existencias, clasificación ABC, patrón de demanda, pronóstico y pedido sugerido por origen.
  Los datos reales viven en una Google Sheet privada; este repositorio público solo tiene código y **datos de ejemplo sintéticos**.

| Dirección | Qué es |
|---|---|
| <https://ciudad-nueva-chile.github.io/sveltia-cms-public/> | El sitio (versión de prueba, no indexada en buscadores) |
| <https://ciudad-nueva-chile.github.io/sveltia-cms-public/admin/> | Un solo panel para libros, páginas, ajustes y parámetros del inventario |
| <https://ciudad-nueva-chile.github.io/sveltia-cms-public/inventario/> | Panel de inventario con datos de ejemplo |

## La planilla: una tabla de libros donde Roberto corrige cantidades

| Pestaña | Para qué |
|---|---|
| **Inventario** | Un libro por fila: código, ISBN, título, autor, editorial, **se compra en**, categoría, precio de venta, **en bodega**, **en consignación**, **pedido en camino**, última actualización, cómo se vende, qué hacer y **notas**. Roberto solo edita las columnas amarillas; el resto se completa solo y se puede ordenar y filtrar |
| **Esta semana** | Qué pedir, qué está sin stock, qué liquidar, qué consignaciones cobrar. Solo lectura |
| **Pedido sugerido** | La lista para cada editorial. Solo lectura |
| Ocultas | Configuración (costos por origen), Registro de movimientos, Historial de fotos, Análisis técnico, Indicadores |

Cada mañana el cálculo compara «Inventario» con la foto anterior y deduce qué pasó: si bajó la bodega y subió la
consignación, fue una salida en consignación; si bajó la bodega, una venta; si subió, una llegada. Así se arma la
historia de demanda sin anotar movimientos, y se estampa la fecha de «Última actualización». La historia pasada se
carga una vez desde las facturas y guías del SII, que son más exactas.

El catálogo y los precios salen del sitio (`src/libros`): el precio se cambia en `/admin/`, no en la planilla.

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
| Dónde comprar y pedido por origen | Si un libro está en ambas editoriales («Se compra en»), prueba todas las combinaciones de envíos (ninguno, España, Argentina, ambos) y elige la de menor costo: cada libro va al origen con menor **costo puesto en bodega** entre los que se envían; cada envío debe alcanzar su **mínimo FOB** (US$ 700), completándolo con demanda adelantada de títulos A y B; lo que no cabe espera el próximo envío con un castigo por la espera. Con dos orígenes son cuatro combinaciones: el óptimo es exacto | `inventario/pedido.py` |

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

El sitio: `npm install && npm run serve` (abre http://localhost:8080).

Con la planilla real: ver [docs/CONFIGURAR.md](docs/CONFIGURAR.md).

## Estructura

```
src/                        el sitio (Eleventy): libros, páginas, ajustes, estilos
admin/                      Sveltia CMS: sitio + parámetros del inventario (versión fija en package.json)
config/parametros.yml       parámetros del modelo (se editan en /admin)
inventario/                 el modelo (Python); lenguaje.py tiene todos los textos que ve Roberto
panel/                      panel de inventario: «Esta semana», «Libros» y «Análisis»
herramientas/               generar_ejemplo.py (datos sintéticos) y crear_planilla.py (prepara la Google Sheet)
datos_ejemplo/              datos sintéticos: los títulos y precios son públicos; clientes, cantidades y costos son inventados
tests/                      pruebas del modelo
.github/workflows/          pruebas, publicación (sitio + /admin + /inventario), cálculo semanal con la planilla
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
