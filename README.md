# Ciudad Nueva Chile: sitio e inventario

Repositorio de prueba con dos partes que se publican juntas:

- **El sitio** (`src/`, Eleventy): catálogo, fichas, solicitud de pedido por WhatsApp o correo. Se edita en `/admin/` con Sveltia CMS.
- **El inventario** (`inventario/`, Python): existencias, categorías de gestión AA, BB, CC y DD, clase de demanda, nivel objetivo y pedido por embarque y origen.
  Los datos reales viven en una Google Sheet privada; este repositorio público solo tiene código y **datos de ejemplo sintéticos**.

**Contexto completo** (cómo se conectan sitio, Sveltia, planilla, GitHub y panel, y todas las fórmulas del modelo con
un ejemplo): [`docs/CONTEXTO.md`](docs/CONTEXTO.md). Configuración paso a paso: [`docs/CONFIGURAR.md`](docs/CONFIGURAR.md).

| Dirección | Qué es |
|---|---|
| <https://ciudad-nueva-chile.github.io/sveltia-cms-public/> | El sitio (versión de prueba, no indexada en buscadores) |
| <https://ciudad-nueva-chile.github.io/sveltia-cms-public/admin/> | Un solo panel para libros, páginas, ajustes y parámetros del inventario |
| <https://ciudad-nueva-chile.github.io/sveltia-cms-public/inventario/> | Panel de inventario. Con la planilla conectada pide una contraseña (los datos se publican cifrados); sin ella muestra datos de ejemplo |

## La planilla: una tabla de libros, una de ventas y el pedido

| Pestaña | Para qué |
|---|---|
| **Inventario** | Un libro por fila: código, ISBN, título, autor, editorial, **se compra en**, categoría, precio de venta, **en bodega**, **en consignación**, **pedido en camino**, última actualización, cómo se vende, qué hacer y **notas**. Roberto solo edita las columnas amarillas; el resto se completa solo y se puede ordenar y filtrar |
| **Ventas** | Una fila por libro vendido: fecha, pedido o boleta, libro (lista desplegable), cantidad, **descuento (%)** si hubo, canal y estado («Vendido», «No había stock» o «Devolución»). ISBN, precio de lista y total cobrado se completan solos con fórmulas. Cada mañana las ventas nuevas se descuentan del stock de «Inventario» y se anota cuándo en «Descontado del stock» |
| **Esta semana** | Qué pedir y dónde conviene, qué está sin stock, qué pidieron y no había, qué contar esta semana, qué consignaciones cobrar. Solo lectura |
| **Pedido sugerido** | Arriba, **dónde conviene comprar**: Roberto anota el costo real de cada envío (celdas amarillas) y la comparación entre «Todo a España», «Todo a Argentina» y «Dividir» se recalcula al instante. El flete no se calcula por peso. Abajo, la lista de qué pedir en el próximo embarque |
| Ocultas | Configuración (costos por origen), Registro de movimientos, Historial de fotos, Lista de libros (para la lista desplegable de «Ventas»), Análisis técnico, Indicadores |

Cada mañana el cálculo compara «Inventario» con la foto anterior y deduce qué pasó: si bajó la bodega y subió la
consignación, fue una salida en consignación; si bajó la bodega, una venta; si subió, una llegada. Luego descuenta las
ventas nuevas de «Ventas». Si Roberto ya había bajado la bodega a mano ese día, no se descuenta dos veces: la venta
anotada reemplaza a la baja deducida. Las bajas sin venta anotada se avisan en «Esta semana». La historia pasada se
carga una vez desde las facturas y guías del SII, que son más exactas.

«Ventas» es la fuente de demanda con más detalle: la venta perdida («No había stock») cuenta como demanda aunque no
mueva stock, y el descuento y el canal quedan para analizar ofertas.

La demanda que usa el modelo es la **venta neta** (venta + factura de consignación − devoluciones) más la venta perdida.
La salida en guía no es venta: decide entre las categorías CC y DD.

El catálogo y los precios salen del sitio (`src/libros`): el precio se cambia en `/admin/`, no en la planilla.

## Qué calcula

| Paso | Método | Archivo |
|---|---|---|
| Existencias | Bodega, consignación y tránsito a partir de los movimientos. La factura de una consignación no vuelve a descontar la bodega; la consignación abierta más antigua se rastrea por orden de salida | `inventario/stock.py` |
| Categorías de gestión | AA (clase Intermitente, Regular, Estacional o Coyuntural), BB (clase Esporádica), CC (con existencias, sin venta y con salida en guía), DD (con existencias, sin venta ni salida en guía) y «Sin categoría». Adaptan a Flores y Whybark (1987) y reemplazan al ABC por valor | `inventario/clasificacion_abc.py` (nombre histórico) |
| Clase de demanda | Por meses con demanda en la ventana de 21 meses: 0 «Sin venta neta», 1 o 2 «Esporádica», 3 o más «Intermitente» (o «Regular» si ADI < 1,32 y CV² < 0,49). Estacional y Coyuntural se marcan a mano en el catálogo. ADI y CV² (Syntetos, Boylan y Croston, 2005) quedan como indicadores | `inventario/demanda.py` |
| Pronóstico mensual | SBA (Croston con corrección de sesgo, α = 0,15, supuesto abierto) para Intermitente y Regular | `inventario/demanda.py` |
| Nivel objetivo S | Percentil 95 de una distribución de Poisson con media λ × (T + L), donde λ es el pronóstico SBA, T el intervalo entre embarques del origen (Argentina 12 meses, España 8,5) y L el plazo de reposición. El 95 % es un criterio y Poisson es un supuesto de simplicidad | `inventario/politica.py` |
| Política por categoría | AA Intermitente o Regular repone hasta S, AA Estacional pide una vez al año antes de la temporada, AA Coyuntural se atiende por reacción, BB repone lo vendido desde el embarque anterior, CC y DD no se reponen, «Sin categoría» va a pedido. La planilla puede fijarla a mano | `inventario/politica.py` |
| Conteo cíclico | «Qué contar esta semana», con la frecuencia por categoría: AA mensual, BB cada 6 meses, CC y DD una vez al año | `inventario/modelo.py` |
| Pedido por embarque y dónde comprar | Embarques programados por origen. Si un libro está en ambas editoriales («Se compra en»), compara las combinaciones que cubren todo (España, Argentina, ambos) y elige la de menor costo: cada libro va al origen con menor **costo puesto en bodega** entre los que se envían, cada envío debe alcanzar su **mínimo FOB** (US$ 700) y suma su **costo fijo**, que anota Roberto. Si un envío no alcanza el mínimo, la hoja lo avisa y Roberto decide cómo completarlo. No hay castigos numéricos de postergar ni adelantar | `inventario/pedido.py` |
| Ventas | Convierte cada fila de «Ventas» en un movimiento (venta, factura de consignación, devolución o venta perdida), descuenta del stock solo las nuevas y resume ventas con descuento, descuento promedio y ventas perdidas | `inventario/ventas.py` |

Límites que conviene tener presentes:
- **La demanda observada está censurada:** cuando no hubo stock, la venta perdida solo queda registrada si se anota en
  «Ventas» como «No había stock». Conviene anotar también las consultas de WhatsApp por libros no disponibles.
- Las ventas con descuento se cuentan como demanda normal. Si una oferta dispara las ventas, el pronóstico sube un
  tiempo; el porcentaje queda anotado para separarlas más adelante.
- El modelo supone que los próximos meses se parecen a los de la ventana. Un evento como una canonización cambia
  eso: por eso existe la clase Coyuntural.
- Las cifras en dólares dependen de los factores de la pestaña oculta Configuración, que son una estimación por origen. Los valores reales los carga Andrés en la planilla privada y no se suben al repositorio.
- El flete no se calcula por peso, porque el catálogo no tiene el peso de cada título.
- El nivel de servicio de 95 %, el supuesto de Poisson, α = 0,15 y las reglas de BB y de Estacional son supuestos o criterios y no mediciones. Las dos reglas están marcadas «por confirmar» en `inventario/politica.py`.

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
tests/                      pruebas del modelo (56)
.github/workflows/          pruebas; publicación diaria y con cada cambio (sitio + /admin + /inventario + cálculo con la planilla)
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
