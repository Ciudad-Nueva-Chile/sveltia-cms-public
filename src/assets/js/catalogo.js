// Búsqueda, filtros y orden del catálogo. Todo en el navegador sobre las tarjetas ya publicadas,
// así cada libro sigue siendo HTML estático indexable por buscadores.
(function () {
  "use strict";

  var POR_PAGINA = 48;
  var raiz = document.querySelector("[data-catalogo]");
  if (!raiz) return;

  var grilla = document.getElementById("grilla");
  var texto = document.getElementById("filtro-texto");
  var orden = document.getElementById("orden");
  var contador = document.getElementById("contador");
  var botonMas = document.getElementById("cargar-mas");
  var sinResultados = document.getElementById("sin-resultados");
  var enlaceConsulta = document.querySelector("[data-consulta-busqueda]");
  var tarjetas = Array.prototype.slice.call(grilla.querySelectorAll(".tarjeta"));
  var visibles = POR_PAGINA;

  function normalizar(s) {
    return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  tarjetas.forEach(function (t) { t._texto = normalizar(t.dataset.texto); });

  function valorRadio(nombre) {
    var r = raiz.querySelector('input[name="' + nombre + '"]:checked');
    return r ? r.value : "";
  }

  function marcarRadio(nombre, valor) {
    raiz.querySelectorAll('input[name="' + nombre + '"]').forEach(function (r) { r.checked = r.value === valor; });
  }

  // Estado inicial desde la URL (?q=, ?categoria=, ?coleccion=)
  var params = new URLSearchParams(location.search);
  if (params.get("q")) texto.value = params.get("q");
  if (params.get("categoria")) {
    var slug = params.get("categoria");
    var r = raiz.querySelector('input[name="categoria"][data-slug="' + slug + '"]') || raiz.querySelector('input[name="categoria"][value="' + slug + '"]');
    if (r) r.checked = true;
  }
  if (params.get("coleccion")) marcarRadio("coleccion", params.get("coleccion"));

  function ordenar(lista) {
    var modo = orden.value;
    return lista.sort(function (a, b) {
      if (modo === "precio-asc") return (+a.dataset.precio || 1e9) - (+b.dataset.precio || 1e9);
      if (modo === "precio-desc") return (+b.dataset.precio || 0) - (+a.dataset.precio || 0);
      return a.dataset.titulo.localeCompare(b.dataset.titulo, "es");
    });
  }

  function aplicar(reiniciar) {
    if (reiniciar) visibles = POR_PAGINA;
    var palabras = normalizar(texto.value).split(/\s+/).filter(Boolean);
    var categoria = valorRadio("categoria");
    var coleccion = valorRadio("coleccion");
    var sello = valorRadio("sello");

    var coinciden = tarjetas.filter(function (t) {
      if (categoria && t.dataset.categoria !== categoria) return false;
      if (coleccion && t.dataset.coleccion !== coleccion) return false;
      if (sello && t.dataset.sello !== sello) return false;
      return palabras.every(function (p) { return t._texto.indexOf(p) !== -1; });
    });

    ordenar(coinciden);
    var fragmento = document.createDocumentFragment();
    coinciden.forEach(function (t, i) {
      t.hidden = i >= visibles;
      fragmento.appendChild(t);
    });
    tarjetas.forEach(function (t) { if (coinciden.indexOf(t) === -1) { t.hidden = true; fragmento.appendChild(t); } });
    grilla.appendChild(fragmento);

    var n = coinciden.length;
    contador.textContent = n === tarjetas.length ? n + " títulos" : n + " de " + tarjetas.length + " títulos";
    botonMas.hidden = n <= visibles;
    if (!botonMas.hidden) botonMas.textContent = "Mostrar más títulos (" + (n - visibles) + " restantes)";
    sinResultados.hidden = n !== 0;
    if (enlaceConsulta && n === 0) {
      enlaceConsulta.href = "https://wa.me/" + window.SITIO.whatsapp + "?text=" + encodeURIComponent("LIBRO NO ENCONTRADO · búsqueda: «" + texto.value.trim() + "»\nHola, busco un libro que no encontré en el catálogo web.");
    }

    // La colección solo tiene sentido dentro de patrística
    var grupoCol = raiz.querySelector("[data-grupo-coleccion]");
    if (grupoCol) grupoCol.hidden = !!categoria && categoria.indexOf("Patrística") !== 0;

    // Mantener la URL compartible
    var p = new URLSearchParams();
    if (texto.value.trim()) p.set("q", texto.value.trim());
    var radioCat = raiz.querySelector('input[name="categoria"]:checked');
    if (categoria && radioCat) p.set("categoria", radioCat.dataset.slug || categoria);
    if (coleccion) p.set("coleccion", coleccion);
    history.replaceState(null, "", location.pathname + (p.toString() ? "?" + p : ""));
  }

  var espera;
  texto.addEventListener("input", function () { clearTimeout(espera); espera = setTimeout(function () { aplicar(true); }, 120); });
  orden.addEventListener("change", function () { aplicar(true); });
  raiz.querySelectorAll(".filtros input").forEach(function (i) {
    i.addEventListener("change", function () {
      aplicar(true);
      if (window.innerWidth < 900) document.body.classList.remove("filtros-abiertos");
    });
  });
  botonMas.addEventListener("click", function () { visibles += POR_PAGINA; aplicar(false); });

  raiz.querySelector("[data-limpiar]").addEventListener("click", function () {
    texto.value = "";
    ["categoria", "coleccion", "sello"].forEach(function (n) { marcarRadio(n, ""); });
    aplicar(true);
  });

  var abrir = raiz.querySelector("[data-abrir-filtros]");
  if (abrir) abrir.addEventListener("click", function () { document.body.classList.toggle("filtros-abiertos"); });

  aplicar(true);
})();
