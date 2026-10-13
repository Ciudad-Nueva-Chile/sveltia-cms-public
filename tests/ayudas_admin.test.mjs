// Pruebas de admin/ayudas.js (lo que corre en Sveltia al guardar un libro). Se corren con: node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// ayudas.js se carga como en el navegador: define globalThis.CiudadNuevaAyudas (sin CMS, no registra el evento)
new Function(readFileSync(new URL("../admin/ayudas.js", import.meta.url), "utf8"))();
const { calcularPrecios, completarPorIsbn } = globalThis.CiudadNuevaAyudas;

test("si escribo el precio de lista, se calcula el neto", () => {
  const r = calcularPrecios({ precio_iva: 23800, precio_neto: "", precio_iva_guardado: undefined, precio_neto_guardado: undefined });
  assert.equal(r.precio_neto, 20000);
  assert.equal(r.precio_iva_guardado, 23800);
});

test("si cambio solo el neto, se calcula el de lista", () => {
  const r = calcularPrecios({ precio_iva: 23800, precio_neto: 30000, precio_iva_guardado: 23800, precio_neto_guardado: 20000 });
  assert.equal(r.precio_iva, 35700);
  assert.equal(r.precio_neto, 30000);
});

test("si cambio solo el de lista, se recalcula el neto", () => {
  const r = calcularPrecios({ precio_iva: 35700, precio_neto: 20000, precio_iva_guardado: 23800, precio_neto_guardado: 20000 });
  assert.equal(r.precio_neto, 30000);
});

test("un libro antiguo sin valores guardados: manda el de lista", () => {
  const r = calcularPrecios({ precio_iva: 72600, precio_neto: 61008 });
  assert.equal(r.precio_neto, 61008);
  assert.equal(r.precio_iva, 72600);
});

test("solo neto en un libro nuevo", () => {
  assert.equal(calcularPrecios({ precio_neto: 10000 }).precio_iva, 11900);
});

const respuestas = (google, openlibrary) => async (url) => ({
  json: async () => (url.includes("googleapis") ? google : openlibrary),
});

test("ISBN completa título y autor vacíos con Google Books", async () => {
  const f = respuestas({ items: [{ volumeInfo: { title: "Cartas cristológicas", authors: ["San Cirilo de Alejandría"] } }] }, {});
  const c = await completarPorIsbn({ isbn: "978-84-9715-123-4", titulo: "", autor: "" }, f);
  assert.deepEqual(c, { titulo: "CARTAS CRISTOLÓGICAS", autor: "San Cirilo de Alejandría" });
});

test("si Google Books no lo tiene, busca en Open Library", async () => {
  const f = respuestas({ totalItems: 0 }, { "ISBN:9788497151234": { title: "Homilías", authors: [{ name: "Orígenes" }] } });
  const c = await completarPorIsbn({ isbn: "9788497151234", titulo: "", autor: "" }, f);
  assert.deepEqual(c, { titulo: "HOMILÍAS", autor: "Orígenes" });
});

test("no pisa lo que ya está escrito", async () => {
  const f = respuestas({ items: [{ volumeInfo: { title: "Otro", authors: ["Otro autor"] } }] }, {});
  assert.deepEqual(await completarPorIsbn({ isbn: "9788497151234", titulo: "MI TÍTULO", autor: "" }, f), { autor: "Otro autor" });
  assert.deepEqual(await completarPorIsbn({ isbn: "9788497151234", titulo: "MI TÍTULO", autor: "Yo" }, f), {});
});

test("sin resultado deja un título que se nota en la lista", async () => {
  const c = await completarPorIsbn({ isbn: "9788497151234", titulo: "", autor: "" }, respuestas({}, {}));
  assert.deepEqual(c, { titulo: "SIN TÍTULO (ISBN 9788497151234)" });
});
