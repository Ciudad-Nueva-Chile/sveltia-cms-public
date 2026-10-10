# Contexto del proyecto: sitio, Sveltia, planilla e inventario de Ciudad Nueva Chile

Documento de referencia para entender el sistema completo: qué hace cada parte, dónde vive, cómo se conectan y
qué cálculos hace el modelo de inventario, con la relación entre lo que pasa en la bodega (variables reales), lo que
se anota en la planilla y las fórmulas del código.

> Este repositorio es **público**. Este documento no contiene contraseñas, claves, IDs de planilla ni datos reales.
> Los secretos viven en GitHub (Settings → Secrets) y en la Google Sheet privada.

> **Estado de este documento (10-10-2026).** Describe el diseño objetivo que debe implementar el código, alineado con
> la memoria del proyecto de título (secciones 4.2.2, 4.2.5, 4.2.6 y 4.3.1 a 4.3.4). Hasta que se complete la
> adaptación, el código puede conservar partes del diseño anterior (clasificación ABC, remuestreo con nivel de
> servicio de 0,90, castigos de postergar y adelantar). **Si el código difiere de este documento, se corrige el
> código.** Si al implementar aparece un choque real con este diseño, se avisa a Andrés antes de reescribir el
> documento. Al terminar, se borra este aviso.

---

## 1. Qué es y para quién

La Fundación Mariápolis distribuye en Chile los libros de **Editorial Ciudad Nueva** (ediciones de España y de
Argentina): patrística, espiritualidad, vidas de santos y pensamiento social cristiano. El sistema tiene dos objetivos:

1. **Vender mejor**: un sitio web con el catálogo completo (unos 720 títulos), fichas con portada, precio y sinopsis,
   búsqueda y una «solicitud de pedido» que el cliente envía por WhatsApp o correo.
2. **Comprar mejor**: un modelo de inventario que, a partir de lo que Roberto anota en una planilla, clasifica los
   libros en las categorías AA, BB, CC y DD de la memoria, estima la demanda de los que se reponen y sugiere cuánto
   importar en cada embarque y desde qué país.

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

### 4.4 Lo que el sitio debe cumplir frente a la memoria

Estas condiciones salen de los requerimientos RF-01 a RF-08 y RNF-01 a RNF-05 de la memoria (secciones 4.2.1, 4.2.2 y
4.3.1 a 4.3.4). Lo marcado como **Pendiente** es lo que el sitio todavía no cumple.

| Condición | Detalle | Estado |
|---|---|---|
| Sin existencias en pantalla | Ni la ficha, ni el catálogo, ni los datos estructurados `Book` declaran disponibilidad. Ningún dato de inventario, costo ni precio neto se escribe en el HTML público | Cumple |
| Precio de lista con fecha | Se ve en el catálogo, en cada categoría, en la ficha y en el pie de página. Un título sin precio muestra «Precio a consultar» | Cumple (verificado) |
| Solicitud sin pago en línea | Sin carro de compras, sin precio por cliente y sin documentos tributarios. Pide RUT con dígito verificador (módulo 11, obligatorio salvo para particulares), razón social, giro, contacto, teléfono y correo (obligatorios), y dirección de entrega y comuna (opcionales: la línea de entrega solo sale en el mensaje si el cliente escribió alguna). El mensaje empieza con «SOLICITUD DE PEDIDO WEB», que es la marca de origen, trae el total referencial a precio de lista con IVA y la fecha de la lista | Cumple |
| Demanda no atendida | La búsqueda sin resultados ofrece un mensaje que empieza con «LIBRO NO ENCONTRADO» | Cumple |
| Condiciones para librerías e instituciones | La página no publica los porcentajes de descuento. El párrafo «Forma de pago» lleva un comentario «POR VALIDAR CON LA CONTRAPARTE» (visible en Sveltia, no en el sitio) | Por validar |
| Mapa del sitio | Se arma desde las colecciones (`src/sitemap.njk`): 722 fichas, 16 categorías, patrística, catálogo, inicio y las 2 páginas de texto, 743 direcciones. Deja fuera `/solicitud/` y la 404. Antes usaba `collections.all`, que solo trae la primera página de una plantilla paginada | Cumple (prueba en `pruebas.yml`) |
| Descripción por ficha | Cada ficha tiene su propia descripción (`descripcion_seo` en `src/libros/libros.11tydata.js`): título, autor, colección con su número, ISBN y la primera frase de la sinopsis, o la edición si no hay sinopsis. Las 722 son distintas | Cumple (prueba en `pruebas.yml`) |
| Tipografías propias | Fraunces e Inter (Fontsource, licencia OFL, versión fija en `package.json`) se copian de `node_modules` a `/assets/fuentes/` al compilar y se declaran con `@font-face`. Sin dependencia externa | Cumple |
| `robots.txt` y panel | `src/robots.njk` bloquea `/admin/` y `/inventario/`, y solo fuera del modo prueba agrega la línea `Sitemap` con el dominio real. El panel lleva `noindex` | Cumple |
| Portadas | 597 fichas con imagen y 125 con portada tipográfica (la memoria cuenta 682 y 40: la diferencia son las portadas de Amazon eliminadas). De las 14 fichas con ISBN desplazado, 10 tienen una portada elegida por título y 4 usan la tipográfica (CN-0682, 0695, 0697 y 0704). La publicación de las imágenes requiere autorización de la editorial | Informado |
| Sinopsis | El apartado «Sobre el libro» aparece solo si la ficha tiene sinopsis. Hoy ninguna la tiene | Cumple, con contenido pendiente |
| Cifras de la portada | Número de títulos, de obras de patrística y de áreas salen de las colecciones, no se escriben a mano | Cumple |
| Modo prueba | Con prefijo de ruta o `SITIO_PRUEBA`, `noindex` y aviso. En `ciudadnueva.cl` ambos desaparecen | Cumple |
| Valores de ejemplo | WhatsApp, correo, repositorio y servicio de autenticación de Sveltia siguen siendo de ejemplo hasta que la contraparte entregue los reales | Pendiente de la contraparte |

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
| **Modelo de inventario** | `config/parametros.yml` | Parámetros del cálculo (sección 9.10). Cada parámetro dice de dónde sale en la memoria y cuáles son supuestos |

---

## 6. GitHub

### 6.1 Flujos de Actions (`.github/workflows/`)

| Flujo | Cuándo | Qué hace |
|---|---|---|
| **Pruebas** (`pruebas.yml`) | Cada push y pull request | `pytest` (56 pruebas), el modelo de punta a punta con datos de ejemplo, la compilación del sitio con prefijo y una verificación de que el mapa del sitio trae todas las categorías (16), que ninguna descripción de ficha se repite y que no se cargan tipografías externas |
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
| Categoría de gestión | `categoria_gestion` | Auto | AA, BB, CC, DD o «Sin categoría» (sección 9.4) |
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
están sin stock, «Te los pidieron y no había», «Bajas de stock sin venta anotada», **qué contar esta semana** (sección 9.9), los títulos DD y CC con su valor, consignaciones de
más de un año, productos de temporada, errores de datos y cómo anotar.

**Pedido sugerido** — dos bloques:

1. **Dónde conviene comprar**: fila «Costo de cada envío (US$)» con una celda amarilla por país, que **Roberto anota**
   con la cotización real de cada envío (el código no calcula el flete por peso, porque el catálogo no tiene el peso de
   cada título). Una tabla compara las combinaciones que cubren todo lo que hay que pedir (Todo a España, Todo a
   Argentina, Dividir) con Libros, Envíos y Total. Envíos y Total son **fórmulas** y la fila **CONVIENE** usa
   `INDICE(…; COINCIDIR(MIN(…); …; 0))`, de modo que la recomendación cambia **al instante** al editar un costo de envío.
2. **Qué pedir**: Cuándo (el próximo embarque programado del origen), Comprar en, Cantidad, Título, Código, US$ aprox.,
   Por qué. Si un envío no alcanza el mínimo FOB, la hoja avisa «El envío a [origen] no alcanza el mínimo FOB de
   US$ 700» y Roberto decide cómo completarlo.

### 7.2 Pestañas ocultas (Ver → Hojas ocultas)

| Pestaña | Contenido |
|---|---|
| **Configuración** | Una fila por origen de compra y edición: «FOB / precio neto», «Costo en bodega / precio neto», «Pesos por dólar». Si un país vende libros de otra edición con otras condiciones (p. ej. españoles comprados en Argentina), va en una fila aparte con esa «Edición del libro» |
| **Registro de movimientos** | Historia de demanda: la carga inicial (facturas, guías y notas de crédito del SII) más los movimientos deducidos de los cambios en «Inventario». Solo crece |
| **Historial** | Fotos de existencias (fecha, código, bodega, consignación, en camino) cada vez que algo cambia. Solo crece |
| **Lista de libros** | «Código · Título», ISBN y precio, para la lista desplegable y las fórmulas de «Ventas» |
| **Análisis técnico** | Todas las variables del modelo por libro |
| **Indicadores** | Resumen general (existencias, categorías AA, BB, CC y DD, clases de demanda, políticas, pedidos, ventas, conteo) |

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
├── demanda.py            serie mensual, clase por meses con demanda, ADI y CV² informativos, pronóstico SBA
├── clasificacion_abc.py  categorías de gestión AA, BB, CC y DD (el nombre del archivo es histórico)
├── politica.py           política por categoría y nivel objetivo S (Poisson al 95 %)
├── pedido.py             pedido por embarque programado y dónde comprar: combinaciones de envíos con costo fijo
├── modelo.py             une todo: calcular() → Resultado
├── lenguaje.py           todos los textos en lenguaje simple y las hojas armadas
├── cifrado.py            AES-256-GCM para los datos del panel
└── config.py             lectura de config/parametros.yml
panel/                    index.html, panel.css, panel.js (dibuja; no calcula salvo el comparador de envíos)
herramientas/             crear_planilla.py (prepara la planilla), generar_ejemplo.py (datos sintéticos)
datos_ejemplo/            Catalogo, Movimientos, EnTransito, Costos, Ventas, Envios (CSV inventados)
tests/test_modelo.py      56 pruebas
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
5. Calcular existencias (9.2), demanda (9.3), categorías AA, BB, CC y DD (9.4), clase de demanda (9.5), pronóstico (9.6),
   política y nivel objetivo (9.7), pedido por embarque y dónde comprar (9.8), avisos, indicadores y conteo (9.9).
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

### 9.3 Serie de venta neta mensual (`demanda.venta_neta_mensual`)

Para cada libro, los últimos `historia_meses` (21) meses calendario hasta la fecha de corte. La ventana de 21 meses es la
que usa la memoria (diciembre de 2024 a agosto de 2026) y es un parámetro:
```
dₜ = máx(0,  venta + consignacion_liquidada − devolucion_cliente + venta_perdida)
```
Es la **venta neta** de la memoria (Tabla 4.8, sobre facturas), más la **venta perdida** anotada en «Ventas», que corrige
la demanda censurada. La **salida en guía no es venta**: un título que solo salió en consignación no tiene venta neta y
queda en CC (9.4); cuenta cuando la librería lo factura. Sobre esta serie se cuentan k, ADI, CV² y la tasa λ.

### 9.4 Categorías de gestión AA, BB, CC y DD (`clasificacion_abc.py`)

Adaptan la estructura de política de Flores y Whybark (1987), con una diferencia que la memoria justifica en su sección
4.2.5: en lugar de combinar valor de uso con criticidad, usan la **recurrencia de la demanda** y la **salida de bodega**,
porque la criticidad no puede evaluarse título por título con el registro disponible. **Reemplazan a la clasificación ABC
por valor**, que deja de usarse en la política, la planilla y el panel.

| Categoría | Criterio de asignación | Se repone |
|---|---|---|
| **AA** | Clase Intermitente, Regular, Estacional o Coyuntural (9.5) | Sí, según su clase (9.7) |
| **BB** | Clase Esporádica: venta neta en uno o dos meses de la ventana | Sí, lo vendido desde el embarque anterior |
| **CC** | Con existencias, sin venta neta en la ventana y con salida en guía de despacho (`consignacion_salida`) en la ventana | No |
| **DD** | Con existencias, sin venta neta ni salida en guía | No |
| Sin categoría | Sin existencias y sin demanda. Se exhibe igual en el sitio | A pedido |

- **Prioridad:** primero la demanda (AA y BB), después CC y DD.
- **Qué no es CC ni DD:** un título con venta, aunque sea en un solo mes, es BB. DD queda para lo que no tuvo venta ni salida.
- **Solicitudes del canal:** si un título CC o DD recibe una solicitud del canal web (fila de «Ventas» con canal Web / WhatsApp
  y estado «No había stock»), el sistema no cambia su categoría: queda en CC o DD con el aviso «Título CC o DD con solicitud
  del canal: pasa a BB en la próxima revisión». El cambio lo hace la revisión de la clasificación. Una venta concretada por el
  canal web sí es venta neta y lo deja en BB de inmediato, porque BB es justamente «venta neta en uno o dos meses».
- **Indicadores por categoría:** títulos, títulos con existencias, ejemplares, valor a precio de venta y porcentaje del valor.
- **Qué hace con CC y DD el sistema:** solo los muestra con su valor. Su destino (consignación sin liquidar en CC, fondo sin
  movimiento en DD) se decide en la memoria, no en el código.

### 9.5 Clase de demanda (`demanda.clasificar`)

Se cuenta k, el número de meses de la ventana con demanda neta positiva:

| k | Clase | Detalle |
|---|---|---|
| 0 | Sin venta neta | |
| 1 o 2 | **Esporádica** | No hay serie suficiente para estimar: se decide, no se estima (categoría BB) |
| 3 o más | **Intermitente** | Si además ADI < 1,32 y CV² < 0,49, **Regular**, con el mismo trato |

**Estacional** (calendarios y agendas) y **Coyuntural** (línea Carlo Acutis) se marcan a mano en Sveltia («Inventario: tipo
especial») y mandan sobre lo calculado. La clase «Puntual» desaparece: se funde en Esporádica.

ADI y CV² (Syntetos, Boylan y Croston, 2005) se siguen calculando como indicadores informativos, con los cortes 1,32 y
0,49 de la literatura:
```
ADI = n / k                         (intervalo medio entre meses con demanda)
CV² = (σ(x) / μ(x))²                (variabilidad del tamaño cuando hay demanda, σ poblacional)
```
y se muestran en el panel, donde permiten ver si una obra se comporta como suave, errática, intermitente o grumosa.

### 9.6 Pronóstico mensual (`demanda.pronosticar`)

Para las clases Intermitente y Regular se usa **SBA** (Croston, 1972, con la corrección de Syntetos y Boylan, 2005), con
α = `alfa_suavizado` (0,15), un valor bajo o moderado porque una venta aislada no debe mover en exceso el pronóstico.
**α es un supuesto abierto**, no un valor estimado con datos. Solo se actualiza en los meses con demanda, con q = meses
transcurridos desde la anterior:
```
z ← z + α (dₜ − z)       tamaño típico
p ← p + α (q − p)        intervalo típico
λ = (1 − α/2) · z / p    ejemplares por mes
```
Se inicia con el primer mes con demanda: z = d, p = meses hasta él. El factor (1 − α/2) corrige el sesgo positivo de
Croston. Para Esporádica no se estima tasa, y su reposición no depende de un pronóstico (9.7). El suavizamiento exponencial
simple deja de usarse en la política.

### 9.7 Política por categoría y nivel objetivo S

La política se asigna por categoría. La «decisión manual» de Sveltia manda siempre.

| Categoría y clase | Política | Cuánto |
|---|---|---|
| AA Intermitente o Regular | **Reponer** | Hasta el nivel objetivo S |
| AA Estacional | **Temporada** | Un pedido anual que debe llegar antes de septiembre. Cantidad de la última temporada completa |
| AA Coyuntural | **No reponer** | Se atiende por reacción |
| BB | **Reponer lo vendido** | Unidades netas vendidas desde el último movimiento de importación del título, menos lo que ya viene en camino. Sin stock de seguridad |
| CC y DD | **No reponer** | El sistema solo los muestra con su valor |
| Sin categoría | **A pedido** | No se mantiene stock |

La regla de BB es la lectura del diseño de «lo vendido desde el embarque anterior» y **queda por confirmar con Andrés**. Las
políticas «Stock mínimo» y «Liquidar o revisar» ya no se asignan automáticamente.

**Nivel objetivo S** (solo AA Intermitente o Regular): el nivel hasta el que se repone en cada embarque. Es el **percentil
95 de una distribución de Poisson** cuya media es la tasa mensual λ por el intervalo entre embarques del origen más el
plazo de reposición:
```
S         = ppf_Poisson( nivel_servicio, λ × (T + L) )           con nivel_servicio = 0,95
Sugeridoᵢ = máx(0, S − Posiciónᵢ)                                Posición = máx(Bodega, 0) + En camino
```
Un stock negativo es un error de datos: se avisa («Stock negativo») y cuenta como 0, para no inflar el pedido.

**Reglas por confirmar con Andrés** (marcadas así en `politica.py`):
- BB sin ninguna importación registrada: cuenta lo vendido desde el inicio de la ventana.
- Estacional: «Pedir» entre junio y agosto, hasta la venta neta de la última temporada completa (septiembre a marzo), menos
  la posición. El resto del año solo se avisa.
- **T** es el intervalo entre embarques del origen, en meses (`intervalo_embarque_meses`): Argentina 12 y España 8,5. Todo origen
  distinto de Argentina se trata como España. Estos valores salen del análisis de tamaño de lote por embarque de la memoria
  (sección 4.2.5), con tasa de costo de capital de 15 % anual dentro de un rango de 10 % a 20 %. Si esa tasa cambia, hay
  que recalcularlos fuera del código.
- **L** es el plazo de reposición, en días (`plazo_dias`): Argentina 5,5 y España 7.
- **El nivel de servicio de 95 % es un criterio y no el resultado de una optimización**, porque el costo del quiebre no
  puede estimarse con el registro. **Poisson es un supuesto de simplicidad**, razonable para demanda de unidades sueltas
  pero no contrastado con los datos.

### 9.8 Pedido por embarque y dónde comprar (`pedido.sugerir`)

Los pedidos se hacen en **embarques programados** por origen, no cada vez que un título baja de un punto. El próximo
embarque de un origen es la fecha de su última importación más T meses.

Costos por ejemplar del libro i comprado en el país o, con la fila de Configuración (o, edición):
```
neto_USDᵢ     = precio_listaᵢ / 1,19 / tipo_cambio
FOBᵢ,o        = neto_USDᵢ × «FOB / precio neto»            → lo que se paga, cuenta para el mínimo de embarque
Costoᵢ,o      = neto_USDᵢ × «Costo en bodega / precio neto» → puesto en bodega, decide dónde comprar
```
La memoria mide estos factores por origen en su sección 4.1.5 (economía del negocio) y los usa en 4.2.5 para valorizar
la reposición. **Sus valores reales y el tipo de cambio no se escriben en este repositorio**: Andrés los carga en la fila de
cada origen de la pestaña Configuración de la planilla privada. Precio neto = precio con IVA / 1,19.

La importación se atribuye al origen del título (su editorial), porque el registro no dice desde dónde llegó, y todo origen
distinto de Argentina se cuenta como España. Sin importaciones registradas, el embarque se considera vencido. Un embarque
que vence en los próximos 30 días se pide «Ahora».

**Necesidades de un embarque:** las líneas de la política (9.7) con Sugerido > 0, en AA y BB.

**Dónde comprar.** Cada título que se vende en ambos orígenes va al origen con menor Costoᵢ,o entre los que envían. Se
comparan las combinaciones de envíos que **cubren todas las necesidades** (Todo a España, Todo a Argentina, Dividir):
```
Total(E) = Σ necesidades × Costoᵢ,o  +  Σ_{o que envía} costo fijo del envío a o
```
El costo fijo de cada envío es la celda amarilla de «Pedido sugerido» que **anota Roberto** con la cotización real. El código
**no calcula el flete por peso**: el catálogo no tiene el peso de cada título. Como el costo fijo no cambia qué libros van en
cada combinación, la planilla y el panel recalculan el Total al instante al cambiarlo. Se elige la combinación de menor
Total (empate: menos envíos).

**Mínimo de embarque.** Si Σ FOB de un origen es menor que `minimo_embarque_usd` (700), el envío no se arma solo: la hoja
avisa «El envío a [origen] no alcanza el mínimo FOB de US$ 700». **Cómo completarlo, o si esperar al siguiente embarque, lo
decide Roberto.** Ya no hay castigos
numéricos de postergar ni de adelantar, porque la memoria no los respalda.

Resultados: líneas «Ahora» (se piden en el embarque) y «Próximo embarque» (lo que espera), con el motivo («Se vende y queda
poco», «Reponer lo vendido», «Temporada», «conviene Argentina: US$ … contra …»), y el resumen por país (Pedir ahora / Acumular /
Sin pedido) con la fecha del próximo embarque.

### 9.9 Avisos, indicadores y conteo

| Aviso | Condición |
|---|---|
| Quiebre | AA con política Reponer y Bodega ≤ 0 («ya viene en tránsito» si En camino > 0) |
| Bajo el objetivo | Sugerido > 0 |
| Stock negativo | Bodega < 0 (revisar movimientos) |
| Consignación abierta | Antigüedad FIFO ≥ `dias_consignacion_antigua` (365) |
| Te los pidieron y no había | Filas «No había stock» de los últimos 90 días |
| Bajas sin venta anotada | Bajas de bodega deducidas hoy sin fila en «Ventas» (cuando ya se usa Ventas) |
| Solicitud del canal | Título CC o DD con una solicitud del canal web: pasa a BB en la próxima revisión |
| Mínimo de embarque | Un origen con Σ FOB bajo el mínimo en el próximo embarque |

Otros indicadores: `cobertura = Bodega / ritmo mensual` (meses), `valor_bodega = Bodega × precio_lista`, y por categoría los
títulos, ejemplares y valor a precio de venta. De «Ventas», últimos 12 meses: unidades vendidas, porcentaje de unidades con
descuento, descuento promedio ponderado, unidades perdidas y unidades por canal.

**Conteo cíclico (`Qué contar esta semana`).** La frecuencia de conteo físico se asigna por categoría, siguiendo a Flores y
Whybark (1987):

| Categoría (con existencias) | Conteo | Registro de existencias |
|---|---|---|
| AA | Mensual | Permanente, con cada embarque, guía y factura |
| BB | Cada 6 meses | Con cada conteo |
| CC y DD | Una vez al año | Con cada conteo |

La clasificación se revisa cada 6 meses en AA y BB y una vez al año en CC y DD. La hoja lista los títulos que toca contar en
la semana y la frecuencia de cada categoría: los títulos con existencias de una categoría se reparten en turnos de
52 / conteos_por_anio semanas, de modo que cada uno se cuenta con su frecuencia.

### 9.10 Parámetros (`config/parametros.yml`, editables en Sveltia → Modelo de inventario)

| Parámetro | Valor | Usado en | Origen en la memoria |
|---|---|---|---|
| `historia_meses` | 21 | 9.3 | Ventana de observación de la memoria |
| `corte_adi` / `corte_cv2` | 1,32 / 0,49 | 9.5 | Cortes de la literatura (Syntetos, Boylan y Croston, 2005). No conviene moverlos |
| `alfa_suavizado` | 0,15 | 9.6 | **Supuesto abierto** |
| `nivel_servicio` | 0,95 | 9.7 | **Criterio**, no optimización |
| `origenes[].intervalo_embarque_meses` | Argentina 12 y España 8,5 | 9.7, 9.8 | Análisis de lote por embarque (tasa 15 %, rango 10 % a 20 %) |
| `origenes[].plazo_dias` | Argentina 5,5 y España 7 | 9.7 | Plazo de reposición de la casa de origen |
| `origenes[].minimo_embarque_usd` | 700 | 9.8 | Mínimo económico del embarque |
| `dias_consignacion_antigua` | 365 | 9.9 | Criterio de operación |
| `conteos_por_anio` | AA 12, BB 2, CC 1 y DD 1 | 9.9 | Frecuencias de Flores y Whybark |
| `revision_clasificacion_meses` | AA y BB 6, CC y DD 12 | 9.4 | Criterio de la memoria |

Desaparecen `abc_meses`, `abc_corte_a`, `abc_corte_b`, `simulaciones`, `revision_semanas`, `meses_sin_movimiento`,
`costo_postergar` y `costo_adelantar`.

En la planilla (no en Sveltia, porque son sensibles o cambian seguido): factores de costo y tipo de cambio (Configuración) y
costo fijo de cada envío (Pedido sugerido). **Los valores reales no se escriben en este repositorio**: los carga Andrés en la
planilla privada a partir de las mediciones de la memoria.

### 9.11 Ejemplo completo con un libro (datos sintéticos)

Un libro español, AA, que también se consigue vía Argentina. Precio de lista $23.800 y tipo de cambio 950 (valores de
ejemplo, no los reales). Demanda de los últimos 21 meses:
`0 1 0 3 0 0 2 0 1 0 0 2 0 1 0 0 3 0 1 0 2` (16 ejemplares en 9 meses).

| Paso | Cálculo | Resultado |
|---|---|---|
| Clase | k = 9 meses con demanda, que son 3 o más | **Intermitente** (ADI = 21/9 = 2,33 y CV² = 0,195 solo informativos) |
| Categoría | Clase Intermitente | **AA** |
| Pronóstico | SBA con α = 0,15 | **λ = 0,66 ejemplares/mes** |
| Horizonte | T = 8,5 meses (España) más L = 7/30 de mes | 8,73 meses |
| Media de Poisson | 0,66 × 8,73 | 5,75 |
| Nivel objetivo | percentil 95 de Poisson de media 5,75 | **S = 10** |
| Pedido | Bodega 3, En camino 0, Sugerido = 10 − 3 | **pedir 7 en el próximo embarque** |
| Costos | neto = 23.800 / 1,19 = $20.000, que son US$ 21,05 | |
| España | FOB 0,45 es US$ 9,47. Costo en bodega 0,60 es **US$ 12,63** | |
| Vía Argentina | FOB 0,50 es US$ 10,53. Costo en bodega 0,57 es **US$ 12,00** | Más barato puesto en bodega |
| Con T de Argentina | T = 12 meses más 5,5/30: media 0,66 × 12,18 = 8,03, es decir S = 13 | El origen cambia el nivel objetivo |
| Decisión | Si el embarque a Argentina ocurre y la combinación cubre todo, el título va ahí. Si no, va a España | Depende de la combinación de menor Total |

---

## 10. El panel de inventario (`/inventario/`)

- **Acceso**: pide la contraseña. Los datos se publican como `datos.cifrado.json`:
  `clave = PBKDF2-SHA256(contraseña, sal fija del sitio, 600.000 iteraciones)` → `AES-256-GCM`. Se descifran en el
  navegador con Web Crypto. «Recordar en este dispositivo» guarda la **clave derivada** (no la contraseña) en
  `localStorage`; «Salir» la borra. Si cambia la contraseña, lo recordado deja de servir y se pide de nuevo.
  Sin `datos.cifrado.json`, muestra `datos.json` (ejemplo).
- **Esta semana**: «Dónde conviene comprar» (casillas de costo de envío que recalculan en vivo y no se guardan, porque el
  costo real lo anota Roberto en la planilla), una tarjeta por embarque con la fecha del próximo, la barra hacia el mínimo,
  la lista con la categoría de cada título y, si no alcanza el mínimo, el aviso «El envío a [origen] no alcanza el mínimo FOB»
  (botón «Copiar lista para la editorial»), «Qué contar esta semana» con la frecuencia por categoría, y las listas de avisos
  (sin stock, pedidos sin stock, pasan a BB en la próxima revisión, fondo CC y DD con su valor, consignaciones, temporada).
- **Libros**: tabla con la categoría de gestión, filtrable por «Qué hacer», búsqueda, orden, solo con aviso; ficha de cada libro
  con gráfico de venta neta por mes, la política en palabras (S y T + L cuando corresponde) y datos técnicos (k, ADI, CV², λ).
- **Análisis**: indicadores (incluidos los de ventas), la tabla por categoría con la estructura de la
  Tabla 4.24 de la memoria (títulos, con existencias, ejemplares, valor y % del valor), dispersión ADI–CV² coloreada por
  categoría con los cortes, matriz clase × categoría y tabla técnica.
- Colores de datos validados para daltonismo; modo oscuro; adaptable a celular. El panel lleva `noindex` y su ruta está
  bloqueada en `robots.txt`.

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
- El modelo supone que el futuro se parece a los últimos 21 meses (para los eventos existe la clase Coyuntural).
- Los dólares dependen de factores de costo estimados por origen.
- El flete no se calcula por peso: el catálogo no tiene el peso de cada título, así que el costo de cada envío lo anota Roberto.
- Varios valores son supuestos o criterios y no mediciones: el nivel de servicio de 95 %, el supuesto de Poisson, α = 0,15,
  y las reglas de reposición de BB y de Estacional. Cada uno está marcado como tal en 9.7 a 9.10.
- El intervalo entre embarques depende de una tasa de costo de capital de 15 % que es de criterio y no medida.
- Una sola contraseña para el panel: quitar el acceso a una persona exige cambiarla para todos.
- El próximo embarque se estima con la última importación de los títulos de ese origen, porque el registro no dice desde
  dónde llegó cada importación.

## 14. Pendientes

- Autenticador OAuth (Cloudflare Worker) para que Roberto entre a Sveltia con su cuenta.
- Cargar los datos reales (historial del SII y conteo) desde la carpeta privada, nunca desde este repositorio.
- Contraseña larga y planilla de la Fundación al pasar al oficial; migrar a la cuenta de la Fundación y a `ciudadnueva.cl`.
- Fotos de los 125 libros con portada tipográfica.
- Reescribir el historial de git para eliminar las portadas antiguas de Amazon.
- Confirmar con Andrés las reglas de BB y de Estacional (9.7).
- Cargar en la planilla privada los factores de costo y el tipo de cambio.
- Validar con la contraparte el párrafo «Forma de pago».
- Más adelante: WhatsApp Business (catálogo, respuestas), separar ventas en oferta en el pronóstico, medir el error
  del pronóstico con datos reales.

## 15. Glosario

| Término | Significado |
|---|---|
| AA, BB, CC, DD | Categorías de gestión de la memoria: recurrencia de la demanda y salida de bodega (sección 9.4). Reemplazan al ABC por valor |
| ADI | Average Demand Interval: meses promedio entre meses con venta |
| CV² | Coeficiente de variación al cuadrado del tamaño de la demanda |
| SBA | Syntetos–Boylan Approximation: Croston corregido para demanda intermitente |
| Poisson | Distribución de conteos de eventos independientes. Con ella se calcula el nivel objetivo S (percentil 95) |
| Nivel de servicio | Probabilidad de no quedarse sin stock durante el horizonte de protección |
| S (nivel objetivo) | Nivel de existencias hasta el que se repone en cada embarque |
| Embarque programado | Importación que se hace cada T meses por origen (12 Argentina y 8,5 España) |
| FOB | Valor de la mercadería en origen, sin flete ni impuestos |
| Costo puesto en bodega | FOB + flete + seguro + impuestos, por ejemplar |
| Demanda censurada | Demanda no observada porque no había stock |
| Consignación | Libros entregados a un cliente que paga solo lo que vende |
| Cuenta de servicio | Usuario técnico de Google con el que el cálculo accede a la planilla |
| Eleventy | Generador de sitios estáticos que arma el sitio desde los archivos `.md` |
| Sveltia CMS | Panel de edición que guarda cambios como commits en GitHub |
| GitHub Actions / Pages | Ejecución automática de tareas / alojamiento del sitio estático |
