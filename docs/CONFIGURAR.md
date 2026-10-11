# Configurar la planilla privada, el cálculo diario y la contraseña del panel

Todo esto se hace una sola vez. Toma unos 30 minutos. Nada de lo que se configura aquí queda público.

## 1. Proyecto en Google Cloud y cuenta de servicio

La cuenta de servicio es un «usuario robot» que el cálculo usa para leer y escribir la planilla.

1. Entra a <https://console.cloud.google.com/> con la cuenta de Google de la Fundación (o la tuya, para probar).
2. Arriba, en el selector de proyectos, **Proyecto nuevo** → nombre `inventario-ciudad-nueva` → **Crear**.
3. Con ese proyecto seleccionado, abre <https://console.cloud.google.com/apis/library/sheets.googleapis.com> y presiona **Habilitar**.
4. Ve a **IAM y administración → Cuentas de servicio → Crear cuenta de servicio**.
   - Nombre: `inventario`. **Crear y continuar**. No le asignes roles. **Listo**.
5. Entra a la cuenta recién creada → pestaña **Claves** → **Agregar clave → Crear clave nueva → JSON**.
   Se descarga un archivo `.json`. **Guárdalo fuera de cualquier repositorio**, por ejemplo en
   `~/credenciales-inventario.json`. Es una contraseña: no lo envíes por correo ni lo subas a GitHub.
6. Copia el correo de la cuenta de servicio (termina en `@inventario-ciudad-nueva.iam.gserviceaccount.com`).

Para este uso no hay costo: la API de Sheets es gratuita dentro de sus límites.

## 2. La planilla

1. Crea una Google Sheet vacía llamada, por ejemplo, **Inventario Ciudad Nueva**.
2. **Compartir** → pega el correo de la cuenta de servicio → permiso **Editor** → desmarca «Notificar».
3. Copia el ID de la planilla: es la parte de la dirección entre `/d/` y `/edit`.
   `https://docs.google.com/spreadsheets/d/`**`1AbC…xyz`**`/edit`
4. En tu computador, dentro del repositorio:

```bash
source .venv/bin/activate
export GOOGLE_CREDENCIALES_ARCHIVO=~/credenciales-inventario.json
python herramientas/crear_planilla.py --planilla 1AbC…xyz --con-ejemplo
python -m inventario --fuente sheets --planilla 1AbC…xyz
```

La primera orden prepara **Ventas** y lo que no se ve (Registro de movimientos y Configuración, ocultas). La segunda
crea la pestaña **Inventario** con las existencias que dan los movimientos cargados, más **Esta semana** y **Pedido sugerido**.

## 3. Cargar los datos reales

- **Registro de movimientos** (oculto): la historia de demanda. Se carga una vez desde las facturas, guías y notas de
  crédito del SII, y el conteo del 21-08-2026 como «Conteo inicial». Desde ahí crece solo con los cambios de «Inventario».
- **Configuración** (oculta; menú Ver → Hojas ocultas): una fila por origen de compra con FOB / precio neto, costo
  puesto en bodega / precio neto y pesos por dólar. Si un origen vende libros de otra edición con otras condiciones
  (por ejemplo, libros españoles comprados en Argentina), se agrega una fila con esa «Edición del libro». La fila
  con la edición vacía vale para todo lo demás. Los factores reales salen de la memoria (sección 4.1.5) y el tipo de
  cambio es el vigente: se escriben solo aquí, nunca en el repositorio. Cada fila lleva «Tipo de cambio vigente desde» y
  «Factores vigentes desde»: con ellas «Esta semana» avisa cuando el tipo de cambio pasa de 6 meses o los factores de 12.
- **Inventario**: la crea el primer cálculo. Desde entonces Roberto corrige ahí las llegadas, conteos y consignaciones.
- **Importaciones** (cómo anotar un embarque, para Roberto):
  1. Al hacer el pedido a la editorial, agrega una fila por libro con la fecha de pedido, el país, el libro y la cantidad.
  2. Deja vacía la fecha de llegada: ese libro aparece solo en «Pedido en camino» de «Inventario».
  3. Cuando llegue, escribe la fecha de llegada en esas filas (y la factura o DIN si la tienes).
  4. A la mañana siguiente se suma sola a «En bodega»: no la sumes también en «Inventario».
- **Ventas**: Roberto anota cada venta (y cada pedido que no se pudo atender, como «No había stock»). Se descuenta
  sola del stock cada mañana; no hay que restarla también en «Inventario».
- **Pedido sugerido**: Roberto anota en las celdas amarillas la cotización de cada envío (el flete no se calcula por peso).
  La recomendación de dónde comprar se recalcula al instante, y el cálculo del día siguiente arma la lista con esa opción.
  Si un embarque no alcanza el mínimo FOB, la hoja lo avisa y Roberto decide cómo completarlo.

## 4. Cálculo automático cada mañana

En GitHub: repositorio → **Settings → Secrets and variables → Actions → New repository secret**.

| Nombre | Valor |
|---|---|
| `GOOGLE_CREDENCIALES` | El contenido completo del archivo `.json` (ábrelo con un editor de texto, copia todo) |
| `ID_PLANILLA` | El ID del paso 2.3 |
| `CLAVE_PANEL` | La contraseña del panel de inventario. Larga (por ejemplo tres o cuatro palabras): el archivo cifrado es público y una contraseña corta se puede adivinar probando |

Luego **Actions → Publicar sitio y panel → Run workflow** para probarlo. Cada mañana (y con cada cambio en el
repositorio) se detectan los cambios de «Inventario», se descuentan las ventas nuevas, se actualizan los resultados
en la planilla y se publica el panel con los datos cifrados. Los secretos no se muestran nunca y el registro no imprime datos.

**Contraseña del panel.** El panel la pide una vez; con «Recordar en este dispositivo» guarda la clave derivada (no la
contraseña) y entra directo. «Salir» la olvida. Para cambiarla, edita el secreto `CLAVE_PANEL` y vuelve a publicar:
lo recordado en los dispositivos deja de servir y se pide la nueva.

## 5. Publicación (GitHub Pages)

1. **Settings → Pages → Source: GitHub Actions**.
2. Con cada push y cada mañana se publica el sitio en `https://ciudad-nueva-chile.github.io/sveltia-cms-public/`, el
   panel de administración en `/admin/` y el panel de inventario en `/inventario/` (con contraseña si están los
   secretos de la planilla y `CLAVE_PANEL`; si no, con **datos de ejemplo**).
3. Para que Roberto entre a Sveltia con su propia cuenta hace falta un autenticador
   (OAuth App de GitHub + `sveltia-cms-auth` en Cloudflare Workers) y poner su dirección en `base_url`
   de `admin/config.yml`. Para probar sin eso: `npm install && npm run admin`, servir la carpeta y elegir
   **Work with Local Repository** en Chrome.

## 6. Traspaso

Lo que depende de quien mantiene el sistema. Si esa persona cambia, hay que traspasar o rehacer cada punto:

| Qué | Dónde vive | Qué hacer al traspasar |
|---|---|---|
| Token personal de GitHub (para entrar a Sveltia) | Cuenta de GitHub de quien mantiene el sistema | Los tokens vencen (se elige la fecha al crearlos). La persona nueva crea el suyo con acceso de lectura y escritura a *Contents* del repositorio |
| Llave de la cuenta de servicio de Google | Secreto `GOOGLE_CREDENCIALES` y el archivo `.json` en su computador | Crear una llave nueva en Google Cloud, pegarla en el secreto y borrar la anterior |
| Contraseña del panel | Secreto `CLAVE_PANEL` | Cambiarla y avisar a quienes usan el panel |
| Autenticador de Sveltia | Pendiente: OAuth App de GitHub y `sveltia-cms-auth` en Cloudflare Workers | Mientras no exista, se entra con token |
| Versión de Sveltia | Fija en `package.json` (`@sveltia/cms`) | Se actualiza al aceptar una propuesta de Dependabot que pase las pruebas |
| Decisiones del modelo | `config/parametros.yml` | Se editan a mano: nivel de servicio, α, T, L y mínimo por país |

## 7. Revisión anual

Una vez al año, quien mantiene el sistema:

1. Renueva el token de GitHub antes de que venza.
2. Revisa el tipo de cambio y los factores de costo en Configuración y actualiza sus fechas «vigente desde».
3. Revisa T y L en `config/parametros.yml` (y la tasa de costo de capital de la que sale T).
4. Revisa y acepta (o descarta) las propuestas de Dependabot pendientes.
5. Comprueba en **Actions → Publicar sitio y panel** que el proceso diario corre sin errores.
6. Actualiza la fecha de vigencia de la lista de precios en Sveltia (Ajustes del sitio) si cambió.

## Qué nunca debe llegar al repositorio

- El archivo `.json` de credenciales.
- Exportaciones de la planilla real (CSV o Excel), la carpeta `salida/` o un `panel/datos.json` generado con datos reales.

El `.gitignore` ya bloquea esos nombres, pero conviene revisar `git status` antes de cada commit.
