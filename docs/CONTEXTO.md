# Contexto del proyecto: sitio, Sveltia, planilla e inventario de Ciudad Nueva Chile

Documento de referencia para entender el sistema completo: qué hace cada parte, dónde vive, cómo se conectan y
qué cálculos hace el modelo de inventario, con la relación entre lo que pasa en la bodega (variables reales), lo que
se anota en la planilla y las fórmulas del código.

> Este repositorio es **público**. Este documento no contiene contraseñas, claves, IDs de planilla ni datos reales.
> Los secretos viven en GitHub (Settings → Secrets) y en la Google Sheet privada.

---

## 1. Qué es y para quién

La Fundación Mariápolis distribuye en Chile los libros de **Editorial Ciudad Nueva** (ediciones de España y de
Argentina): patrística, espiritualidad, vidas de santos y pensamiento social cristiano. El sistema tiene dos objetivos:

1. **Vender mejor**: un sitio web con el catálogo completo (unos 720 títulos), fichas con portada, precio y sinopsis,
   búsqueda y una «solicitud de pedido» que el cliente envía por WhatsApp o correo.
2. **Comprar mejor**: un modelo de inventario que, a partir de lo que Roberto anota en una planilla, clasifica los
   libros, pronostica la demanda y sugiere cuánto importar, cuándo y desde qué país.

Personas:

| Persona | Rol en el sistema |
|---|---|
| Andrés | Diseña y mantiene el sistema; define costos y parámetros |
| Roberto | Opera: edita libros en Sveltia, anota existencias y ventas en la planilla, decide los pedidos |
| Clientes (lectores, librerías, parroquias, instituciones) | Navegan el sitio y envían solicitudes |

### Entornos

| Entorno | Repositorio | Estado |
|---|---|---|
| **Prueba / simulación** | `Ciudad-Nueva-Chile/sveltia-cms-public` (público) | Activo. Planilla de prueba con datos sintéticos |
| **Oficial** | `Ciudad-Nueva-Chile/sveltia-cms` (versión anterior del sitio) | Se migrará cuando la prueba esté completa. Dominio previsto: `ciudadnueva.cl` |

El mismo código sirve para ambos; cambian solo los secretos (planilla, contraseña) y el dominio.

---

## 2. Mapa general

```
          EDITAN PERSONAS                                         LO QUE SE VE
 ┌───────────────────────────────┐                     ┌───────────────────────────────┐
 │ SVELTIA CMS        /admin/    │                     │ SITIO WEB            /        │
 │ libros, precios, portadas,    │── commit a GitHub ─►│ catálogo, fichas, búsqueda,   │
 │ ocultar, páginas, ajustes,    │                     │ solicitud por WhatsApp/correo │
 │ parámetros del modelo         │                     └───────────────────────────────┘
 └───────────────────────────────┘           │
                                             ▼
 ┌───────────────────────────────┐   ┌─────────────────────────────┐   ┌──────────────────────────┐
 │ GOOGLE SHEET (privada)        │◄─►│ GITHUB ACTIONS              │──►│ PANEL      /inventario/  │
 │ Inventario  (existencias)     │   │ «Publicar sitio y panel»    │   │ con contraseña           │
 │ Ventas      (cada venta)      │   │ cada mañana 07:00 y con     │   │ (datos cifrados AES-256) │
 │ Pedido sugerido (envíos)      │   │ cada cambio en main:        │   └──────────────────────────┘
 └───────────────────────────────┘   │ 1. compila el sitio         │
                                     │ 2. lee la planilla          │
                                     │ 3. calcula (Python)         │
                                     │ 4. escribe en la planilla   │
                                     │ 5. cifra datos del panel    │
                                     │ 6. publica en GitHub Pages  │
                                     └─────────────────────────────┘
```

Reglas que ordenan todo:

- **El sitio (`src/libros`) es la fuente de los libros y los precios.** La planilla los toma de ahí.
- **La planilla es la fuente de los números** (existencias, ventas, costos, costo de envíos).
- **El panel solo muestra**; no guarda nada.
- **No hay servidor propio ni base de datos**: todo es estático (GitHub Pages) más un cálculo programado (Actions).

---

## 3. Direcciones

| Dirección | Qué es | Acceso |
|---|---|---|
| `https://ciudad-nueva-chile.github.io/sveltia-cms-public/` | Sitio para clientes | Público; `noindex` mientras sea prueba |
| `…/admin/` | Sveltia CMS | Cuenta de GitHub con permiso de escritura en el repositorio |
| `…/inventario/` | Panel de decisiones | Contraseña (secreto `CLAVE_PANEL`) |
| Google Sheet «Inventario …» | Planilla de operación | Cuentas de Google con quienes se compartió |
| `github.com/Ciudad-Nueva-Chile/sveltia-cms-public` | Código, historial, Actions, secretos | Miembros de la organización |

---

## 4. El sitio web (para clientes)

### 4.1 Qué ofrece

| Página | Archivo | Contenido |
|---|---|---|
| Inicio | `src/index.njk` | Portada con antetítulo, título y bajada (editables), destacados, categorías y colecciones |
| Catálogo | `src/catalogo.njk` | Todos los libros visibles con búsqueda, filtros y orden (48 por tanda, «cargar más») |
| Categoría | `src/categoria.njk` | Una página por categoría (paginación de Eleventy) |
| Patrística | `src/patristica.njk` | Colecciones de patrística (BP, FP, AT, NT…) ordenadas por número |
| Ficha de libro | `src/_includes/libro.njk` | Portada, título, sigla, autor, edición, ISBN, precio, sinopsis, relacionados, botón «Agregar a la solicitud» |
| Mi solicitud | `src/solicitud.njk` + `assets/js/solicitud.js` | Lista editable, datos de facturación y envío por WhatsApp o correo |
| Nosotros, Instituciones | `src/paginas/*.md` | Páginas de texto editables |
| 404, sitemap, robots | `src/404.njk`, `sitemap.njk`, `robots.txt` | — |

### 4.2 Cómo funciona el pedido (no hay pago en línea)

1. El cliente agrega libros a su **solicitud**, que se guarda en su navegador (`localStorage`, clave `cn-solicitud-v1`).
2. En «Mi solicitud» completa sus datos (se recuerdan en `cn-datos-cliente-v1`).
3. El sitio arma un mensaje con libros, cantidades, ISBN, precios y datos, y abre **WhatsApp** (`wa.me/<número>`) o
   el **correo** (`mailto:`).
4. La venta se confirma a mano. Si el cliente no encuentra un libro, la búsqueda ofrece un enlace de WhatsApp
   «LIBRO NO ENCONTRADO · búsqueda: …» (demanda no atendida que conviene anotar en «Ventas» como «No había stock»).

### 4.3 Tecnología

- **Eleventy 3.1.6** (generador de sitios estáticos) con plantillas **Nunjucks**. `npm run build` → carpeta `_site/`.
- Cada libro es un archivo `src/libros/cn-XXXX-titulo.md` con un encabezado YAML:

  ```yaml
  id_catalogo: "CN-0002"          # código interno, igual en la planilla
  isbn: "9788497153188"
  titulo: "1 - 2 REYES, … (AT. 5)" # la sigla final se muestra como insignia
  autor: "Aa.Vv."                  # se muestra «Varios autores»
  origen_editorial: "Ciudad Nueva España"
  coleccion: "La Biblia comentada por los Padres — Antiguo Testamento"
  num_coleccion: "5"
  categoria: "Patrística — Padres de la Iglesia"
  precio_iva: 72600                # precio de lista con IVA (CLP); 0 = «Precio a consultar»
  precio_neto: 61008
  portada: "/assets/portadas/CN-0002.jpg"
  oculto: false                    # true: no se publica (desde Sveltia)
  destacado: false                 # true: aparece en la portada
  inventario_tipo: ""              # Estacional / Coyuntural (para el modelo)
  inventario_decision: ""          # política manual (para el modelo)
  ```

- **Campos calculados** (`src/libros/libros.11tydata.js`): `titulo_visible` (sin la sigla), `sigla` («BP 46»),
  `autor_visible`, `coleccion_visible`, `sello`, y `permalink` = falso si `oculto` (la página no se genera).
- **Colecciones** (`eleventy.config.js`): `libros`, `destacados`, `categorias`, `colecciones`; todas parten de
  `librosVisibles` (excluye los ocultos). Filtro `relacionados`: primero misma colección, luego misma categoría.
- **Datos globales** (`src/_data/`): `sitio.json` (nombre, WhatsApp, correo, portada, anuncio, fecha de la lista de
  precios), `categorias.json` (nombre, nombre corto, color), `colecciones.json` (nombre, sigla, descripción).
- **Prefijo de ruta**: en GitHub Pages el sitio vive bajo `/sveltia-cms-public/`; `PATH_PREFIX` + `HtmlBasePlugin`
  corrigen todos los enlaces. En el dominio propio será `/`.
- **Modo prueba**: con prefijo, el sitio agrega `noindex, nofollow` y un aviso al pie.
- **Portadas**: `src/assets/portadas/CN-XXXX.jpg`, de fotos propias o de los sitios de Ciudad Nueva España y
  Argentina (las de Amazon se eliminaron). Sin portada, el sitio genera una tapa con el título.
- **Diseño**: colores de marca (rojo del isotipo y carbón), logos en `src/assets/img`, adaptable a celular.
- **Scripts**: `sitio.js` (menú, carrusel, solicitud), `catalogo.js` (búsqueda sin tildes, filtros, orden),
  `solicitud.js` (lista y mensaje).

---

## 5. Sveltia CMS (`/admin/`)

- Versión **fija** `@sveltia/cms 0.220.0` (en `package.json`); `npm run admin` copia `sveltia-cms.js` y `chunks/`
  a `admin/`. Actualizar es cambiar la versión y volver a publicar.
- `admin/config.yml` define qué se edita. Backend `github` sobre este repositorio; cada guardado es un **commit**
  en `main`, que dispara la publicación.
- Inicio de sesión: hoy con un token personal de GitHub. Pendiente: OAuth App + `sveltia-cms-auth` en Cloudflare
  Workers (`base_url` en `config.yml`) para que Roberto entre con «Login with GitHub».

| Colección | Archivo(s) | Qué se edita |
|---|---|---|
| **Libros del catálogo** | `src/libros/*.md` | Título, autor, ISBN, portada, precio, categoría, **Ocultar en el sitio**, **Destacar**, edición, colección, n.º, sinopsis, tipo especial y decisión manual para el inventario. Vistas: destacados, ocultos, sin portada, patrística. En la lista, los ocultos llevan «🚫 OCULTO» |
| **Páginas del sitio** | `src/paginas/*.md` | Nosotros, Librerías e instituciones |
| **Ajustes del sitio** | `src/_data/*.json` | Contacto, WhatsApp, portada, franja de anuncio, categorías, colecciones |
| **Modelo de inventario** | `config/parametros.yml` | Parámetros del cálculo (sección 9.10) |

---

## 6. GitHub

### 6.1 Flujos de Actions (`.github/workflows/`)

| Flujo | Cuándo | Qué hace |
|---|---|---|
| **Pruebas** (`pruebas.yml`) | Cada push y pull request | `pytest` (41 pruebas), el modelo de punta a punta con datos de ejemplo y la compilación del sitio con prefijo |
| **Publicar sitio y panel** (`publicar.yml`) | Cada push a `main`, **todos los días a las 10:00 UTC** (07:00 Chile en verano) y a mano | Compila el sitio y Sveltia, copia el panel, calcula con la planilla, cifra los datos del panel y publica en GitHub Pages |

Detalle del paso de cálculo de `publicar.yml`:

| Secretos presentes | Resultado |
|---|---|
| Faltan `GOOGLE_CREDENCIALES` o `ID_PLANILLA` | El panel muestra datos de ejemplo (`datos.json`) |
| Están los de la planilla, falta `CLAVE_PANEL` | Calcula y escribe en la planilla; el panel muestra datos de ejemplo |
| Están los tres | Calcula, escribe en la planilla y publica `datos.cifrado.json` |

El paso tiene `continue-on-error`: si Google falla, el sitio se publica igual y el panel avisa que no encontró datos.
Para recalcular en el momento: **Actions → Publicar sitio y panel → Run workflow**.

### 6.2 Secretos (Settings → Secrets and variables → Actions)

| Secreto | Contenido |
|---|---|
| `GOOGLE_CREDENCIALES` | JSON completo de la cuenta de servicio de Google (proyecto `inventario-ciudad-nueva`) |
| `ID_PLANILLA` | ID de la Google Sheet (lo que va entre `/d/` y `/edit` en su dirección) |
| `CLAVE_PANEL` | Contraseña del panel de inventario |

### 6.3 Publicación

GitHub Pages con **Source: GitHub Actions**. Lo publicado es solo `_site/` (sitio + `admin/` + `inventario/`).

---

## 7. La Google Sheet (privada)

La planilla es la «base de datos» operativa. La lee y escribe una **cuenta de servicio** de Google (un usuario
robot, con permiso de **Editor** solo en esa planilla). Las pestañas automáticas tienen protección de advertencia
(avisan antes de editar) y se reescriben en cada cálculo.

### 7.1 Pestañas visibles

**Inventario** — un libro por fila (todos los del sitio, incluidos los ocultos). Amarillo = lo edita Roberto.

| Columna | Interna | Quién | Significado |
|---|---|---|---|
| Código | `id` | Auto | `CN-XXXX`, el mismo del sitio |
| ISBN, Título, Autor, Editorial, Categoría | `isbn`, `titulo`, `autor`, `origen`, `categoria` | Auto | Del sitio |
| **Se compra en** | `compra_en` | Roberto | España, Argentina o «España o Argentina» (si está en ambas, el modelo elige) |
| Precio de venta | `precio_lista` | Auto | Precio con IVA del sitio (se cambia en Sveltia) |
| **En bodega** | `bodega` | Roberto | Ejemplares físicos en la bodega |
| **En consignación** | `consignacion` | Roberto | Entregados con guía, aún no pagados ni devueltos |
| **Pedido en camino** | `en_camino` | Roberto | Pedidos a la editorial que no han llegado |
| Última actualización | `actualizado` | Auto | Último día en que cambió alguna cantidad |
| Se vende | `se_vende` | Auto | Ritmo en palabras («≈1 cada 2 meses») |
| Qué hacer | `que_hacer` | Auto | Política en palabras («Mantener en bodega») |
| **Notas** | `notas` | Roberto | Libre |

**Ventas** — una fila por libro vendido o pedido no atendido.

| Columna | Interna | Quién | Significado |
|---|---|---|---|
| **Fecha** | `fecha` | Roberto | Día de la venta |
| **Pedido o boleta** | `documento` | Roberto | N.º de boleta, factura o pedido (opcional) |
| **Libro** | `id` | Roberto | Lista desplegable «CN-XXXX · TÍTULO» (de la pestaña oculta «Lista de libros») |
| **Cantidad** | `cantidad` | Roberto | Ejemplares |
| **Descuento (%)** | `descuento` | Roberto | Solo el número (15 = 15 %); vacío = precio de lista |
| **Canal** | `canal` | Roberto | Web / WhatsApp, Local, Evento o feria, Librería, Parroquia o institución, Consignación (factura) |
| **Estado** | `estado` | Roberto | Vendido (o vacío), No había stock, Devolución |
| **Notas** | `notas` | Roberto | Libre |
| ISBN, Precio de lista | `isbn`, `precio_lista` | Fórmula | `BUSCARV` sobre «Lista de libros» |
| Total cobrado | `total` | Fórmula | `cantidad × precio × (1 − descuento)`; negativo en devoluciones; vacío si «No había stock» |
| Descontado del stock | `descontado` | Auto | Cuándo el cálculo descontó la venta («Descontado el …», «Ya estaba descontado a mano …», «Anotada … (no mueve stock)», «Revisar: …») |

**Esta semana** — resumen para decidir (solo lectura): pedidos por país y cuál conviene, libros que se venden y
están sin stock, «Te los pidieron y no había», «Bajas de stock sin venta anotada», para liquidar, consignaciones de
más de un año, productos de temporada, errores de datos y cómo anotar.

**Pedido sugerido** — dos bloques:

1. **Dónde conviene comprar**: fila «Costo de cada envío (US$)» con una celda amarilla por país (la edita Roberto) y
   una tabla de opciones (Todo a España, Todo a Argentina, Dividir, No pedir nada ahora) con Libros, Esperar o
   adelantar, Envíos y Total. Envíos y Total son **fórmulas** (`=B6+C6`, `=C9+D9+E9`) y la fila **CONVIENE** usa
   `INDICE(…; COINCIDIR(MIN(…); …; 0))`: la recomendación cambia **al instante** al editar un costo de envío. Si cambia
   respecto de la lista, avisa que la lista se actualiza en el próximo cálculo.
2. **Qué pedir**: Cuándo (Ahora / Próximo envío), Comprar en, Cantidad, Título, Código, US$ aprox., Por qué.

### 7.2 Pestañas ocultas (Ver → Hojas ocultas)

| Pestaña | Contenido |
|---|---|
| **Configuración** | Una fila por origen de compra y edición: «FOB / precio neto», «Costo en bodega / precio neto», «Pesos por dólar». Si un país vende libros de otra edición con otras condiciones (p. ej. españoles comprados en Argentina), va en una fila aparte con esa «Edición del libro» |
| **Registro de movimientos** | Historia de demanda: la carga inicial (facturas, guías y notas de crédito del SII) más los movimientos deducidos de los cambios en «Inventario». Solo crece |
| **Historial** | Fotos de existencias (fecha, código, bodega, consignación, en camino) cada vez que algo cambia. Solo crece |
| **Lista de libros** | «Código · Título», ISBN y precio, para la lista desplegable y las fórmulas de «Ventas» |
| **Análisis técnico** | Todas las variables del modelo por libro |
| **Indicadores** | Resumen general (existencias, ABC, patrones, políticas, pedidos, ventas) |

### 7.3 Fórmulas de la planilla y el idioma

La planilla está en español: en sus fórmulas el separador es `;` y la coma es decimal. El código escribe las
fórmulas en inglés y las traduce según el idioma de la planilla (`lenguaje.formula` y `FuenteSheets.separador`).

---

## 8. El código (`inventario/`, Python)

```
inventario/
├── __main__.py           director: ciclo con la planilla, hojas «Ventas» y «Lista de libros», datos del panel
├── fuentes.py            leer/escribir Google Sheets (gspread) o CSV; formato, protección, listas, notas
├── planilla.py           compara «Inventario» con la última foto y deduce movimientos
├── ventas.py             pestaña «Ventas»: movimientos, descuento del stock, cuadratura, indicadores
├── stock.py              efectos de cada movimiento y existencias
├── demanda.py            serie mensual, patrón (ADI, CV²), pronóstico (SES, SBA), bootstrap
├── clasificacion_abc.py  ABC por valor
├── politica.py           qué hacer con cada libro y stock objetivo
├── pedido.py             cuánto pedir y dónde: combinaciones de envíos y costo fijo
├── modelo.py             une todo: calcular() → Resultado
├── lenguaje.py           todos los textos en lenguaje simple y las hojas armadas
├── cifrado.py            AES-256-GCM para los datos del panel
└── config.py             lectura de config/parametros.yml
panel/                    index.html, panel.css, panel.js (dibuja; no calcula salvo el comparador de envíos)
herramientas/             crear_planilla.py (prepara la planilla), generar_ejemplo.py (datos sintéticos)
datos_ejemplo/            Catalogo, Movimientos, EnTransito, Costos, Ventas, Envios (CSV inventados)
tests/test_modelo.py      41 pruebas
```

Comandos:

```bash
python -m inventario --panel panel/datos.json          # datos de ejemplo → salida/ y panel
python -m inventario --fuente sheets --planilla <ID>   # ciclo completo con la planilla
python herramientas/crear_planilla.py --planilla <ID> --con-ejemplo --reemplazar
pytest -q
```

---

## 9. El modelo de inventario: cálculos, teoría y variables

### 9.0 Orden del ciclo diario (`ciclo_planilla`)

1. Leer Inventario, Historial, Registro de movimientos, Ventas, costo de envíos y Configuración.
2. **Detectar cambios** en Inventario contra la última foto → movimientos deducidos (9.1).
3. **Descontar ventas nuevas** de «Ventas» del stock de Inventario, con cuadratura (9.1).
4. Reunir todos los movimientos: registro + deducidos + todas las filas de Ventas.
5. Calcular existencias (9.2), demanda (9.3), ABC (9.4), patrón (9.5), pronóstico (9.6), objetivo y política (9.7),
   pedido y dónde comprar (9.8), avisos e indicadores (9.9).
6. Escribir: fotos nuevas en Historial, movimientos en el registro, columnas automáticas y celdas descontadas en
   Inventario, «Descontado del stock» en Ventas, Lista de libros, Esta semana, Pedido sugerido, Análisis técnico,
   Indicadores. Ordenar pestañas (4 visibles).
7. (En Actions) cifrar los datos del panel y publicar.

### 9.1 De la realidad a movimientos

Cada hecho de la bodega se convierte en un **movimiento** `(fecha, libro, tipo, cantidad)`. La cantidad es siempre
positiva; el tipo decide el efecto (`stock.EFECTOS`):

| Hecho real | Tipo interno | Efecto bodega | Efecto consignación | ¿Demanda? | ¿Venta facturada? |
|---|---|---|---|---|---|
| Conteo inicial | `inventario_inicial` | + | | | |
| Llega una importación | `importacion` | + | | | |
| Venta directa | `venta` | − | | + | + |
| Un cliente devuelve | `devolucion_cliente` | + | | − | − |
| Sale en consignación (guía) | `consignacion_salida` | − | + | + | |
| Vuelve de consignación | `consignacion_devolucion` | + | − | − | |
| La librería paga lo consignado | `consignacion_liquidada` | | − | | + |
| Ajuste de conteo (±) | `ajuste` | ± | | | |
| Lo pidieron y no había | `venta_perdida` | | | + | |
| Pedido hecho, no llega | `pedido_en_camino` | (suma a «en camino») | | | |

**Deducción desde «Inventario»** (`planilla.derivar`). Con Δb = cambio en bodega y Δc = cambio en consignación
entre la foto anterior y la planilla de hoy:

```
si Δc > 0:  consignacion_salida = Δc        y  Δb ← Δb + Δc     (esa baja de bodega ya está explicada)
si Δc < 0:  volvió = min(−Δc, máx(Δb, 0))  → consignacion_devolucion = volvió ;  Δb ← Δb − volvió
            el resto (−Δc − volvió)          → consignacion_liquidada
si Δb < 0:  venta = −Δb
si Δb > 0:  importacion = Δb
```
Un libro que aparece por primera vez genera un «Conteo inicial». Limitación: solo se ve el cambio neto del día.

**Descuento de «Ventas»** (`ventas.aplicar`), solo para filas válidas con «Descontado del stock» vacío:

| Fila | Movimiento | Cambio en Inventario |
|---|---|---|
| Vendido (canal ≠ consignación) | `venta` | En bodega − cantidad |
| Vendido, canal «Consignación (factura)» | `consignacion_liquidada` | En consignación − cantidad |
| Devolución | `devolucion_cliente` | En bodega + cantidad |
| No había stock | `venta_perdida` | ninguno |

**Cuadratura**: si ese mismo día Roberto ya bajó la bodega a mano (hay una `venta` deducida para ese libro), la venta
anotada la reemplaza y no se descuenta de nuevo («Ya estaba descontado a mano»). Si la venta supera el stock, queda
en 0 y se marca «Revisar». Las filas de Ventas se releen completas en cada cálculo como movimientos (si se corrige
una fila, se corrige la historia de demanda), pero el descuento del stock ocurre una sola vez.

### 9.2 Existencias (`stock.existencias`)

```
Bodegaᵢ        = Σ efecto_bodega(tipo) × cantidad          sobre todos los movimientos del libro i
Consignaciónᵢ  = máx(0, Σ efecto_consignación(tipo) × cantidad)
En caminoᵢ     = columna «Pedido en camino» de Inventario
Posiciónᵢ      = Bodegaᵢ + En caminoᵢ
```
La consignación abierta más antigua se rastrea por **FIFO** (la primera salida es la primera que se liquida o
vuelve); su antigüedad alimenta el aviso de consignaciones de más de `dias_consignacion_antigua` días.

### 9.3 Serie de demanda mensual (`demanda.demanda_mensual`)

Para cada libro, los últimos `historia_meses` (24) meses calendario hasta la fecha de corte:
```
dₜ = máx(0,  venta + consignacion_salida + venta_perdida − devolucion_cliente − consignacion_devolucion)
```
Se mide la **salida física** (lo que hay que reponer), no la facturación: la consignación cuenta cuando sale.
La venta perdida corrige la **demanda censurada** (sin ella, un libro agotado parecería no venderse).

### 9.4 Clasificación ABC (`clasificacion_abc.py`) — principio de Pareto

```
unidades facturadasᵢ = Σ (venta + consignacion_liquidada − devolucion_cliente)   en los últimos abc_meses (12)
Valorᵢ               = unidades facturadasᵢ × precio_listaᵢ / 1,19                  (sin IVA)
```
Se ordena de mayor a menor valor. Con *acumulado previo* = participación acumulada de los libros anteriores:
A si acumulado previo < `abc_corte_a` (0,80); B si < `abc_corte_b` (0,95); C el resto y los de valor 0.

### 9.5 Patrón de demanda (`demanda.clasificar`) — Syntetos, Boylan y Croston (2005)

Sobre la serie dₜ de n = 24 meses, con k = meses con dₜ > 0 y x = tamaños de esos meses:
```
ADI = n / k                         (intervalo medio entre meses con demanda)
CV² = (σ(x) / μ(x))²                (variabilidad del tamaño cuando hay demanda; σ poblacional)
```
| | CV² < `corte_cv2` (0,49) | CV² ≥ 0,49 |
|---|---|---|
| **ADI < `corte_adi` (1,32)** | Suave | Errática |
| **ADI ≥ 1,32** | Intermitente | Grumosa |

k = 0 → «Sin demanda»; k = 1 → «Puntual». Clase: Suave y Errática → **Regular**; Intermitente y Grumosa →
**Intermitente**; Puntual → **Esporádica**. **Estacional** y **Coyuntural** se marcan a mano en Sveltia
(«Inventario: tipo especial») y mandan sobre lo calculado.

### 9.6 Pronóstico mensual (`demanda.pronosticar`), con α = `alfa_suavizado` (0,15)

- **Suave / Errática — suavizamiento exponencial simple (SES)**:
  `nivel₀ = promedio de los 3 primeros meses`; `nivel ← nivel + α (dₜ − nivel)`; pronóstico = nivel final.
- **Intermitente / Grumosa — SBA** (Croston, 1972, con la corrección de Syntetos y Boylan, 2005). Solo en los meses
  con demanda, con q = meses transcurridos desde la anterior:
  ```
  z ← z + α (dₜ − z)       tamaño típico
  p ← p + α (q − p)        intervalo típico
  pronóstico = (1 − α/2) · z / p
  ```
  (se inicia con el primer mes con demanda: z = d, p = meses hasta él). El factor (1 − α/2) corrige el sesgo
  positivo de Croston.
- **Puntual**: total / n. **Sin demanda**: 0.

### 9.7 Stock objetivo y política — revisión periódica (R, S) con bootstrap

Horizonte de protección (en meses), por país de origen:
```
H      = (plazo_semanas + revision_semanas) / (52/12)       p. ej. (1 + 4) / 4,33 = 1,154 meses
Hplazo = plazo_semanas / (52/12)                            p. ej. 1 / 4,33 = 0,231 meses
```
**Cuantil por bootstrap** (`demanda.cuantil_proteccion`): se sortean con reposición `simulaciones` (2.000) juegos de
⌊H⌋+1 meses de la serie observada; la demanda simulada es la suma de ⌊H⌋ meses más la fracción (H − ⌊H⌋) del
último. Q = percentil `nivel_servicio` (0,90) de esas 2.000 sumas. No supone distribución normal (que falla con
demanda intermitente).

```
Stock objetivo  S  = ⌈ máx( Q(H) , pronóstico × H ) ⌉          (solo «Reponer»)
Punto de pedido    = ⌈ Q(Hplazo) ⌉                              (para estimar cuándo pedir)
Sugeridoᵢ          = máx(0, S − Posiciónᵢ)                      (si «Reponer» o «Stock mínimo»)
```

**Política** (`politica.decidir`; la «decisión manual» de Sveltia manda siempre):

| Clase | ABC | Política | S |
|---|---|---|---|
| Coyuntural | — | No reponer | 0 |
| Estacional | — | Temporada (aviso para definir el pedido del ciclo) | 0 |
| Regular o Intermitente | A o B | **Reponer** | S calculado |
| Regular o Intermitente | C | **Stock mínimo** | 1 |
| Esporádica | — | A pedido | 0 |
| Sin demanda, con bodega > 0 y sin salidas en `meses_sin_movimiento` (18) | — | Liquidar o revisar | 0 |
| Sin demanda, resto | — | A pedido | 0 |

### 9.8 Cuánto pedir y dónde (`pedido.sugerir`) — optimización exacta por enumeración

Costos por ejemplar del libro i comprado en el país o, con la fila de Configuración (o, edición):
```
neto_USDᵢ     = precio_listaᵢ / 1,19 / tipo_cambio
FOBᵢ,o        = neto_USDᵢ × «FOB / precio neto»           → lo que se paga; cuenta para el mínimo de embarque
Costoᵢ,o      = neto_USDᵢ × «Costo en bodega / precio neto» → puesto en bodega (flete, seguro, impuestos); decide dónde
```
Necesidades: libros con Sugerido > 0. Adelantables: libros «Reponer» A o B con pronóstico > 0, en cantidad
⌈pronóstico × revisión_meses⌉, ordenados por clase y valor.

Para **cada combinación** E de países que envían (∅, {España}, {Argentina}, {España, Argentina}):
1. Cada necesidad va al país de E con menor Costoᵢ,o entre los que lo venden. Si ninguno de E lo vende, se posterga.
2. Si un envío o tiene 0 < Σ FOB < `minimo_embarque_usd` (700), se completa con adelantables hasta alcanzarlo.
   Si aun así no llega, la combinación **no es válida**.
3. Costo de la combinación:
```
Libros(E)   = Σ necesidades compradas × Costoᵢ,o  +  Σ postergadas × mín_o Costoᵢ,o
Castigo(E)  = Σ adelantadas × Costoᵢ,o × costo_adelantar (0,10)
            + Σ postergadas × neto_USDᵢ × costo_postergar (0,30)
Envíos(E)   = Σ_{o que efectivamente envía} costo fijo del envío a o     (celdas amarillas de «Pedido sugerido»)
Total(E)    = Libros + Castigo + Envíos
```
Se elige la combinación válida de menor Total (empate: menos envíos). Con 2 países son 4 combinaciones y se prueban
todas, así que es el **óptimo exacto**. Como el costo fijo no cambia qué libros van en cada combinación, Total se
puede recalcular con fórmulas (planilla) o en el navegador (panel) al cambiar ese costo.

Resultados: líneas «Ahora» (se piden) y «Próximo envío» (postergadas), con el motivo («Se vende y queda poco»,
«Para completar el envío mínimo», «conviene Argentina: US$ … contra …»); resumen por país (Pedir ahora / Acumular /
Sin pedido, con fecha estimada = días hasta que el primer libro llegue a su punto de pedido:
`(Posición − Punto de pedido) / pronóstico × 30,44`); ahorro frente a comprar cada libro en su propia editorial.

### 9.9 Avisos e indicadores

| Aviso | Condición |
|---|---|
| Quiebre | Política Reponer o Stock mínimo y Bodega ≤ 0 («ya viene en tránsito» si En camino > 0) |
| Bajo el objetivo | Sugerido > 0 |
| Stock negativo | Bodega < 0 (revisar movimientos) |
| Sin salidas | Política Liquidar o revisar |
| Consignación abierta | Antigüedad FIFO ≥ `dias_consignacion_antigua` (365) |
| Te los pidieron y no había | Filas «No había stock» de los últimos 90 días |
| Bajas sin venta anotada | Bajas de bodega deducidas hoy sin fila en «Ventas» (cuando ya se usa Ventas) |

Otros: `cobertura = Bodega / pronóstico` (meses); `valor_bodega = Bodega × precio_lista`. De «Ventas», últimos 12
meses: unidades vendidas, % de unidades con descuento, descuento promedio ponderado por unidades, unidades perdidas
y unidades por canal.

### 9.10 Parámetros (`config/parametros.yml`, editables en Sveltia → Modelo de inventario)

| Parámetro | Valor | Usado en | Efecto al subirlo |
|---|---|---|---|
| `historia_meses` | 24 | 9.3 | Serie más larga: pronóstico más estable y más lento |
| `abc_meses` | 12 | 9.4 | Ventana del ABC |
| `abc_corte_a` / `abc_corte_b` | 0,80 / 0,95 | 9.4 | Más libros en A / B |
| `corte_adi` / `corte_cv2` | 1,32 / 0,49 | 9.5 | Cortes de la literatura; no conviene moverlos |
| `alfa_suavizado` | 0,15 | 9.6 | El pronóstico reacciona más rápido a lo reciente |
| `nivel_servicio` | 0,90 | 9.7 | Más stock, menos quiebres |
| `revision_semanas` | 4 | 9.7, 9.8 | Pedidos menos frecuentes y más grandes |
| `simulaciones` | 2000 | 9.7 | Cuantil más estable (más lento) |
| `meses_sin_movimiento` | 18 | 9.7 | Menos libros para liquidar |
| `dias_consignacion_antigua` | 365 | 9.9 | Menos avisos |
| `costo_postergar` | 0,30 | 9.8 | Más tendencia a pedir ya |
| `costo_adelantar` | 0,10 | 9.8 | Más tendencia a esperar |
| `origenes[].plazo_semanas` | 1 | 9.7 | Más stock de protección |
| `origenes[].minimo_embarque_usd` | 700 | 9.8 | Más adelantos o esperas |

En la planilla (no en Sveltia, porque son sensibles o cambian seguido): factores de costo y tipo de cambio
(Configuración) y costo fijo de cada envío (Pedido sugerido).

### 9.11 Ejemplo completo con un libro

Un libro español, A, que también se consigue vía Argentina. Precio de lista $23.800; tipo de cambio 950.
Demanda de los últimos 24 meses:
`0 2 0 0 1 0 3 0 0 2 0 1 | 0 0 2 0 1 0 0 3 0 1 0 2` (18 ejemplares en 10 meses).

| Paso | Cálculo | Resultado |
|---|---|---|
| Patrón | ADI = 24/10 = 2,4; tamaños {2,1,3,2,1,2,1,3,1,2}: μ = 1,8, σ = 0,748, CV² = (0,748/1,8)² = 0,173 | ADI ≥ 1,32 y CV² < 0,49 → **Intermitente** |
| Pronóstico | SBA con α = 0,15 | **0,74 ejemplares/mes** («≈1 cada 1 mes») |
| Horizonte | H = (1 + 4) / 4,33 | 1,154 meses |
| Bootstrap | percentil 90 de 2.000 sumas simuladas | Q = 2,46 |
| Stock objetivo | S = ⌈máx(2,46 ; 0,74 × 1,154)⌉ | **3** |
| Punto de pedido | ⌈Q(0,231 meses)⌉ | 1 |
| Pedido | Bodega 0, En camino 0 → Sugerido = 3 − 0 | **pedir 3** |
| Costos | neto = 23.800/1,19 = $20.000 → US$ 21,05 | |
| España | FOB 0,45 → US$ 9,47; costo 0,60 → **US$ 12,63** | |
| Vía Argentina | FOB 0,50 → US$ 10,53; costo 0,57 → **US$ 12,00** | Más barato puesto en bodega |
| Castigos | postergar 0,30 × 21,05 = US$ 6,32 c/u; adelantar 0,10 × 12,63 = US$ 1,26 c/u | |
| Decisión | Si se hace envío a Argentina, va ahí (ahorra 0,63 c/u); si solo conviene el de España (por mínimo o costo fijo), va a España; si ningún envío conviene, «Próximo envío» | Depende de la combinación ganadora |

---

## 10. El panel de inventario (`/inventario/`)

- **Acceso**: pide la contraseña. Los datos se publican como `datos.cifrado.json`:
  `clave = PBKDF2-SHA256(contraseña, sal fija del sitio, 600.000 iteraciones)` → `AES-256-GCM`. Se descifran en el
  navegador con Web Crypto. «Recordar en este dispositivo» guarda la **clave derivada** (no la contraseña) en
  `localStorage`; «Salir» la borra. Si cambia la contraseña, lo recordado deja de servir y se pide de nuevo.
  Sin `datos.cifrado.json`, muestra `datos.json` (ejemplo).
- **Esta semana**: «Dónde conviene comprar» (casillas de costo de envío que recalculan en vivo; no se guardan),
  tarjeta por país con barra hacia el mínimo y lista (botón «Copiar lista para la editorial»), y listas de avisos.
- **Libros**: tabla filtrable por «Qué hacer», búsqueda, orden, solo con aviso; ficha de cada libro con gráfico de
  salidas por mes y datos técnicos.
- **Análisis**: indicadores (incluidos los de ventas), dispersión ADI–CV² coloreada por ABC con los cortes, matriz
  ABC × clase de demanda, tabla técnica.
- Colores de datos A/B/C validados para daltonismo; modo oscuro; adaptable a celular.

---

## 11. Seguridad y privacidad

| Riesgo | Medida |
|---|---|
| Repositorio y registros de Actions públicos | Nunca datos reales en el repositorio; el cálculo no imprime datos; `salida/`, `panel/datos*.json` y credenciales en `.gitignore`; solo datos sintéticos en `datos_ejemplo/` |
| Datos del panel en un sitio público | Cifrados con AES-256-GCM; Actions se niega a publicar datos de la planilla sin cifrar |
| Contraseña débil | El archivo cifrado es público: en producción usar una contraseña larga (3–4 palabras) |
| Credenciales de Google | Cuenta de servicio con acceso solo a la planilla; el JSON vive como secreto y en el computador fuera del repositorio |
| Edición del sitio | Solo cuentas de GitHub con permiso de escritura (Sveltia) |
| Quien puede editar el repositorio podría cambiar los flujos y leer secretos | Limitar colaboradores; proteger `main` |
| Datos de clientes | La solicitud vive en el navegador del cliente y se envía por WhatsApp/correo; la planilla no guarda nombres ni RUT |
| Indexación del sitio de prueba | `noindex, nofollow` y aviso de prototipo |

---

## 12. Operación: quién hace qué

| Para… | Dónde |
|---|---|
| Cambiar precio, sinopsis o portada; ocultar o destacar un libro; agregar un libro | Sveltia → Libros |
| Marcar un libro como estacional/coyuntural o fijar su política | Sveltia → Libros → campos «Inventario» |
| Cambiar textos, WhatsApp, anuncio, categorías | Sveltia → Ajustes / Páginas |
| Ajustar el modelo | Sveltia → Modelo de inventario |
| Anotar una venta, una devolución o un pedido que no se pudo atender | Planilla → Ventas |
| Anotar una llegada, un conteo, una consignación o lo que viene en camino | Planilla → Inventario (amarillo) |
| Indicar si un libro se compra en ambos países | Planilla → Inventario → «Se compra en» |
| Anotar el costo de un envío | Planilla → Pedido sugerido (amarillo) |
| Cambiar factores de costo o tipo de cambio | Planilla → Configuración (oculta) |
| Ver qué hacer | Panel → Esta semana, o planilla → Esta semana |
| Recalcular ya | GitHub → Actions → Publicar sitio y panel → Run workflow |
| Cambiar diseño o lógica | Código (repositorio) |

Los resultados se actualizan cada mañana y con cada cambio publicado; las fórmulas de «Ventas» y del comparador de
envíos responden al instante.

---

## 13. Limitaciones conocidas

- Desde «Inventario» solo se ve el cambio neto del día; por eso conviene anotar las ventas en «Ventas».
- La cuadratura «ya lo bajé a mano» solo funciona el mismo día del cálculo. Corregir una venta ya descontada exige
  corregir también «En bodega».
- Las ventas con descuento cuentan como demanda normal: una oferta grande sube el pronóstico por un tiempo.
- El modelo supone que el futuro se parece a los últimos 24 meses (para los eventos existe la clase Coyuntural).
- Los dólares dependen de factores de costo estimados por origen.
- Una sola contraseña para el panel: quitar el acceso a una persona exige cambiarla para todos.

## 14. Pendientes

- Autenticador OAuth (Cloudflare Worker) para que Roberto entre a Sveltia con su cuenta.
- Cargar los datos reales (historial del SII y conteo) desde la carpeta privada, nunca desde este repositorio.
- Contraseña larga y planilla de la Fundación al pasar al oficial; migrar a la cuenta de la Fundación y a `ciudadnueva.cl`.
- Fotos de los ~123 libros sin portada propia.
- Reescribir el historial de git para eliminar las portadas antiguas de Amazon.
- Más adelante: WhatsApp Business (catálogo, respuestas), separar ventas en oferta en el pronóstico, medir el error
  del pronóstico con datos reales.

## 15. Glosario

| Término | Significado |
|---|---|
| ABC | Clasificación por aporte al valor vendido (A: el 80 % del valor) |
| ADI | Average Demand Interval: meses promedio entre meses con venta |
| CV² | Coeficiente de variación al cuadrado del tamaño de la demanda |
| SES | Suavizamiento exponencial simple |
| SBA | Syntetos–Boylan Approximation: Croston corregido para demanda intermitente |
| Bootstrap | Simulación remuestreando datos observados, sin suponer una distribución |
| Nivel de servicio | Probabilidad de no quedarse sin stock durante el horizonte de protección |
| (R, S) | Política de revisión periódica: cada R se repone hasta el nivel S |
| FOB | Valor de la mercadería en origen, sin flete ni impuestos |
| Costo puesto en bodega | FOB + flete + seguro + impuestos, por ejemplar |
| Demanda censurada | Demanda no observada porque no había stock |
| Consignación | Libros entregados a un cliente que paga solo lo que vende |
| Cuenta de servicio | Usuario técnico de Google con el que el cálculo accede a la planilla |
| Eleventy | Generador de sitios estáticos que arma el sitio desde los archivos `.md` |
| Sveltia CMS | Panel de edición que guarda cambios como commits en GitHub |
| GitHub Actions / Pages | Ejecución automática de tareas / alojamiento del sitio estático |
