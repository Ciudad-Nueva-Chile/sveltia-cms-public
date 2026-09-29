# Configurar la planilla privada y el cálculo semanal

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

La primera orden prepara lo que no se ve (Registro de movimientos y Configuración, ocultas); la segunda crea la
pestaña **Inventario** con las existencias que dan los movimientos cargados, más **Esta semana** y **Pedido sugerido**.

## 3. Cargar los datos reales

- **Registro de movimientos** (oculto): la historia de demanda. Se carga una vez desde las facturas, guías y notas de
  crédito del SII, y el conteo del 21-08-2026 como «Conteo inicial». Desde ahí crece solo con los cambios de «Inventario».
- **Configuración** (oculta; menú Ver → Hojas ocultas): una fila por origen de compra con FOB / precio neto, costo
  puesto en bodega / precio neto y pesos por dólar. Si un origen vende libros de otra edición con otras condiciones
  (por ejemplo, libros españoles comprados en Argentina), se agrega una fila con esa «Edición del libro»; la fila
  con la edición vacía vale para todo lo demás.
- **Inventario**: la crea el primer cálculo. Desde entonces Roberto corrige ahí las cantidades.

## 4. Cálculo automático cada mañana

En GitHub: repositorio → **Settings → Secrets and variables → Actions → New repository secret**.

| Nombre | Valor |
|---|---|
| `GOOGLE_CREDENCIALES` | El contenido completo del archivo `.json` (ábrelo con un editor de texto, copia todo) |
| `ID_PLANILLA` | El ID del paso 2.3 |

Luego **Actions → Cálculo diario del inventario → Run workflow** para probarlo. Cada mañana se detectan los cambios
de «Inventario» y se actualizan los resultados. Los secretos no se muestran nunca y el registro del cálculo no imprime datos.

## 5. Publicación (GitHub Pages)

1. **Settings → Pages → Source: GitHub Actions**.
2. Con cada push se publica el sitio en `https://ciudad-nueva-chile.github.io/sveltia-cms-public/`, el panel de
   administración en `/admin/` y el panel de inventario con **datos de ejemplo** en `/inventario/`.
3. Para que Roberto edite los parámetros en línea hace falta el mismo autenticador del sitio
   (OAuth App de GitHub + `sveltia-cms-auth` en Cloudflare Workers) y poner su dirección en `base_url`
   de `admin/config.yml`. Para probar sin eso: `npm install && npm run admin`, servir la carpeta y elegir
   **Work with Local Repository** en Chrome.

## Qué nunca debe llegar al repositorio

- El archivo `.json` de credenciales.
- Exportaciones de la planilla real (CSV o Excel), la carpeta `salida/` o un `panel/datos.json` generado con datos reales.

El `.gitignore` ya bloquea esos nombres, pero conviene revisar `git status` antes de cada commit.
