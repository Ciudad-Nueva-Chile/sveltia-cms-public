// Ayudas al guardar un libro en Sveltia (evento «preSave», que corre en el navegador justo antes de guardar):
//
// 1. Precio de lista y precio neto: si cambias uno, el otro se calcula solo (IVA de 19 %).
//    Para saber cuál cambiaste se guardan los valores de la última vez en dos campos ocultos.
// 2. ISBN: si el título o el autor están vacíos, se buscan por ISBN en Google Books y, si no aparece, en Open Library.
//    (bookfinder.com no tiene una API pública que se pueda consultar desde el navegador.)
//
// Las funciones de cálculo están separadas para poder probarlas sin Sveltia: node --test tests/ayudas_admin.test.mjs
(function (raiz) {
  "use strict";

  var IVA = 0.19;

  function numero(v) {
    var n = Number(v);
    return isFinite(n) && n > 0 ? Math.round(n) : 0;
  }

  // Devuelve los cambios a aplicar a los precios. `d` es el objeto con los datos del libro.
  function calcularPrecios(d) {
    var lista = numero(d.precio_iva), neto = numero(d.precio_neto);
    var cambioLista = lista !== numero(d.precio_iva_guardado);
    var cambioNeto = neto !== numero(d.precio_neto_guardado);
    if (cambioNeto && !cambioLista && neto > 0) {
      lista = Math.round(neto * (1 + IVA));          // escribiste el neto: se calcula el de lista
    } else if (lista > 0) {
      neto = Math.round(lista / (1 + IVA));          // escribiste el de lista (o los dos): manda el de lista
    } else if (neto > 0) {
      lista = Math.round(neto * (1 + IVA));          // solo hay neto
    }
    return { precio_iva: lista, precio_neto: neto, precio_iva_guardado: lista, precio_neto_guardado: neto };
  }

  function limpiarIsbn(v) {
    return String(v || "").replace(/[^0-9Xx]/g, "").toUpperCase();
  }

  // Busca título y autor por ISBN. Devuelve {titulo, autor} o null.
  async function buscarPorIsbn(isbn, fetchFn) {
    var f = fetchFn || raiz.fetch.bind(raiz);
    isbn = limpiarIsbn(isbn);
    if (isbn.length !== 10 && isbn.length !== 13) return null;
    try {
      var g = await (await f("https://www.googleapis.com/books/v1/volumes?q=isbn:" + isbn)).json();
      var v = g && g.items && g.items[0] && g.items[0].volumeInfo;
      if (v && v.title) {
        return { titulo: v.title + (v.subtitle ? ". " + v.subtitle : ""), autor: (v.authors || []).join(", ") };
      }
    } catch (e) { /* sin conexión o sin resultado: se prueba la otra fuente */ }
    try {
      var o = await (await f("https://openlibrary.org/api/books?bibkeys=ISBN:" + isbn + "&format=json&jscmd=data")).json();
      var l = o && o["ISBN:" + isbn];
      if (l && l.title) {
        return { titulo: l.title + (l.subtitle ? ". " + l.subtitle : ""), autor: (l.authors || []).map(function (a) { return a.name; }).join(", ") };
      }
    } catch (e) { /* sin resultado */ }
    return null;
  }

  // Cambios por ISBN: solo completa lo que está vacío. El título va en mayúsculas, como en la lista de precios.
  async function completarPorIsbn(d, fetchFn) {
    var faltaTitulo = !String(d.titulo || "").trim(), faltaAutor = !String(d.autor || "").trim();
    if (!faltaTitulo && !faltaAutor) return {};
    var r = await buscarPorIsbn(d.isbn, fetchFn);
    var cambios = {};
    if (r) {
      if (faltaTitulo) cambios.titulo = r.titulo.toUpperCase();
      if (faltaAutor && r.autor) cambios.autor = r.autor;
    } else if (faltaTitulo) {
      cambios.titulo = "SIN TÍTULO (ISBN " + limpiarIsbn(d.isbn) + ")";   // para que se note en la lista y se complete a mano
    }
    return cambios;
  }

  var api = { calcularPrecios: calcularPrecios, buscarPorIsbn: buscarPorIsbn, completarPorIsbn: completarPorIsbn };
  raiz.CiudadNuevaAyudas = api;

  if (raiz.CMS && raiz.CMS.registerEventListener) {
    raiz.CMS.registerEventListener({
      name: "preSave",
      handler: async function (ev) {
        var entry = ev.entry;
        if (entry.get("collection") !== "libros") return;
        var datos = entry.get("data");
        var d = datos.toJS();
        var cambios = Object.assign({}, calcularPrecios(d), await completarPorIsbn(d));
        return datos.merge(cambios);
      },
    });
  }
})(typeof window !== "undefined" ? window : globalThis);
