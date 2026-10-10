// Página «Mi solicitud»: edita la lista, valida los datos de facturación y arma el mensaje
// que el cliente envía por WhatsApp o correo. No hay checkout: el pedido se confirma a mano.
// Espera a DOMContentLoaded porque depende de window.Solicitud, definido en sitio.js.
document.addEventListener("DOMContentLoaded", function () {
  "use strict";

  var raiz = document.querySelector("[data-solicitud]");
  if (!raiz || !window.Solicitud) return;

  var S = window.Solicitud;
  var lista = raiz.querySelector("[data-items]");
  var vacio = raiz.querySelector("[data-vacio]");
  var resumen = raiz.querySelector("[data-resumen]");
  var form = raiz.querySelector("[data-formulario]");
  var error = raiz.querySelector("[data-error]");
  var CLAVE_DATOS = "cn-datos-cliente-v1";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }

  function pintar() {
    var items = S.leer();
    vacio.hidden = items.length > 0;
    resumen.hidden = items.length === 0;
    lista.innerHTML = items.map(function (i, n) {
      return '<li class="item" data-i="' + n + '">' +
        '<a class="item-portada" href="' + esc(i.url) + '">' +
          (i.portada ? '<img src="' + esc(i.portada) + '" alt="">' : '<span class="item-sin-portada"></span>') +
        "</a>" +
        '<div class="item-info"><a href="' + esc(i.url) + '">' + esc(i.titulo) + "</a>" +
          '<span class="item-meta">ISBN ' + esc(i.isbn) + " · " + (i.precio ? S.formatoCLP(i.precio) + " c/u" : "precio a consultar") + "</span></div>" +
        '<div class="cantidad cantidad-chica">' +
          '<button type="button" data-accion="menos" aria-label="Quitar uno">−</button>' +
          '<input type="number" min="1" max="999" value="' + i.cantidad + '" aria-label="Cantidad de ' + esc(i.titulo) + '" data-accion="valor">' +
          '<button type="button" data-accion="mas" aria-label="Agregar uno">+</button>' +
        "</div>" +
        '<strong class="item-subtotal">' + (i.precio ? S.formatoCLP(i.precio * i.cantidad) : "—") + "</strong>" +
        '<button type="button" class="item-quitar" data-accion="quitar" aria-label="Quitar ' + esc(i.titulo) + '">×</button>' +
      "</li>";
    }).join("");

    var unidades = items.reduce(function (s, i) { return s + i.cantidad; }, 0);
    var monto = items.reduce(function (s, i) { return s + i.precio * i.cantidad; }, 0);
    raiz.querySelector("[data-total-unidades]").textContent = unidades;
    raiz.querySelector("[data-total-monto]").textContent = S.formatoCLP(monto);
    raiz.querySelector("[data-total-items]").textContent = items.length ? "(" + items.length + ")" : "";
  }

  function cambiar(indice, fn) {
    var items = S.leer();
    if (!items[indice]) return;
    fn(items, indice);
    items = items.filter(function (i) { return i.cantidad > 0; });
    S.guardar(items);
    pintar();
  }

  lista.addEventListener("click", function (e) {
    var b = e.target.closest("[data-accion]");
    if (!b || b.tagName === "INPUT") return;
    var n = +b.closest("[data-i]").dataset.i;
    cambiar(n, function (items, i) {
      if (b.dataset.accion === "mas") items[i].cantidad = Math.min(999, items[i].cantidad + 1);
      if (b.dataset.accion === "menos") items[i].cantidad = Math.max(1, items[i].cantidad - 1);
      if (b.dataset.accion === "quitar") items[i].cantidad = 0;
    });
  });

  lista.addEventListener("change", function (e) {
    if (e.target.dataset.accion !== "valor") return;
    var n = +e.target.closest("[data-i]").dataset.i;
    cambiar(n, function (items, i) { items[i].cantidad = Math.max(1, Math.min(999, parseInt(e.target.value, 10) || 1)); });
  });

  raiz.querySelector("[data-vaciar]").addEventListener("click", function () {
    if (confirm("¿Quitar todos los títulos de la solicitud?")) { S.guardar([]); pintar(); }
  });

  // ---------- Datos del cliente ----------
  function rutValido(rut) {
    var limpio = String(rut).replace(/[.\-\s]/g, "").toUpperCase();
    if (!/^\d{7,8}[\dK]$/.test(limpio)) return false;
    var cuerpo = limpio.slice(0, -1), dv = limpio.slice(-1), suma = 0, mult = 2;
    for (var i = cuerpo.length - 1; i >= 0; i--) { suma += +cuerpo[i] * mult; mult = mult === 7 ? 2 : mult + 1; }
    var esperado = 11 - (suma % 11);
    esperado = esperado === 11 ? "0" : esperado === 10 ? "K" : String(esperado);
    return dv === esperado;
  }

  // Sin puntos: «12345678-5». Se acepta escrito con o sin puntos y con o sin guion.
  function formatearRut(rut) {
    var limpio = String(rut).replace(/[^\dkK]/g, "").toUpperCase();
    if (limpio.length < 2) return limpio;
    return limpio.slice(0, -1) + "-" + limpio.slice(-1);
  }

  var campoRut = form.querySelector("[data-rut]");
  campoRut.addEventListener("blur", function () { if (campoRut.value) campoRut.value = formatearRut(campoRut.value); });

  function tipo() { return form.querySelector('input[name="tipo"]:checked').value; }
  function rutObligatorio() { return tipo() !== "Particular"; }
  form.querySelectorAll('input[name="tipo"]').forEach(function (r) {
    r.addEventListener("change", function () { raiz.querySelector("[data-rut-obligatorio]").hidden = !rutObligatorio(); });
  });

  // Recordar datos en este navegador
  try {
    var guardados = JSON.parse(localStorage.getItem(CLAVE_DATOS) || "{}");
    Object.keys(guardados).forEach(function (k) {
      var campo = form.elements[k];
      if (!campo) return;
      if (campo.length && campo[0] && campo[0].type === "radio") {
        Array.prototype.forEach.call(campo, function (r) { r.checked = r.value === guardados[k]; });
      } else campo.value = guardados[k];
    });
    raiz.querySelector("[data-rut-obligatorio]").hidden = !rutObligatorio();
  } catch (e) {}

  function datos() {
    var d = {};
    ["tipo", "razon", "rut", "giro", "contacto", "telefono", "email", "direccion", "comuna", "region", "comentarios"].forEach(function (k) {
      d[k] = k === "tipo" ? tipo() : (form.elements[k].value || "").trim();
    });
    return d;
  }

  function validar(d) {
    form.querySelectorAll(".invalido").forEach(function (el) { el.classList.remove("invalido"); });
    var faltan = [];
    function marcar(nombre, mensaje) { form.elements[nombre].classList.add("invalido"); faltan.push(mensaje); }
    if (!S.leer().length) faltan.push("agrega al menos un título");
    if (!d.razon) marcar("razon", "nombre o razón social");
    if (!d.contacto) marcar("contacto", "persona de contacto");
    if (!d.telefono) marcar("telefono", "teléfono");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(d.email)) marcar("email", "un correo válido");
    if (d.rut ? !rutValido(d.rut) : rutObligatorio()) marcar("rut", "un RUT válido");
    if (faltan.length) {
      error.textContent = "Para enviar la solicitud falta: " + faltan.join(", ") + ".";
      error.hidden = false;
      var primero = form.querySelector(".invalido");
      if (primero) primero.focus();
      return false;
    }
    error.hidden = true;
    return true;
  }

  function mensaje(d) {
    var items = S.leer();
    var total = items.reduce(function (s, i) { return s + i.precio * i.cantidad; }, 0);
    var lineas = [
      "SOLICITUD DE PEDIDO WEB · Ciudad Nueva Chile",
      "",
      "Títulos:",
    ];
    items.forEach(function (i) {
      lineas.push("• " + i.cantidad + " × " + i.titulo + " (ISBN " + i.isbn + ")" + (i.precio ? ", " + S.formatoCLP(i.precio) + " c/u" : ""));
    });
    lineas.push("", "Total referencial a precio de lista, IVA incluido: " + S.formatoCLP(total) + " (" + items.reduce(function (s, i) { return s + i.cantidad; }, 0) + " ejemplares). El precio final se confirma al responder la solicitud.", "");
    lineas.push("Datos de facturación:");
    lineas.push("Tipo de cliente: " + d.tipo);
    lineas.push("Razón social / nombre: " + d.razon);
    if (d.rut) lineas.push("RUT: " + formatearRut(d.rut));
    if (d.giro) lineas.push("Giro: " + d.giro);
    lineas.push("Contacto: " + d.contacto + " · " + d.telefono + " · " + d.email);
    if (d.direccion || d.comuna) lineas.push("Dirección de entrega: " + [d.direccion, d.comuna, d.region].filter(Boolean).join(", "));
    if (d.comentarios) lineas.push("", "Comentarios: " + d.comentarios);
    lineas.push("", "Lista de precios vigente al " + window.SITIO.fechaLista + ".");
    return lineas.join("\n");
  }

  var canal = "whatsapp";
  form.querySelectorAll("[data-enviar]").forEach(function (b) {
    b.addEventListener("click", function () { canal = b.dataset.enviar; });
  });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var d = datos();
    if (!validar(d)) return;
    try { localStorage.setItem(CLAVE_DATOS, JSON.stringify(Object.assign({}, d, { comentarios: "" }))); } catch (err) {}
    var texto = mensaje(d);
    if (canal === "email") {
      location.href = "mailto:" + window.SITIO.email + "?subject=" + encodeURIComponent("Solicitud de pedido · " + d.razon) + "&body=" + encodeURIComponent(texto);
    } else {
      window.open("https://wa.me/" + window.SITIO.whatsapp + "?text=" + encodeURIComponent(texto), "_blank", "noopener");
    }
    S.aviso("<strong>Solicitud preparada</strong><span>Revísala y envíala desde " + (canal === "email" ? "tu correo" : "WhatsApp") + ". Te responderemos a la brevedad.</span>");
  });

  document.addEventListener("solicitud:cambio", pintar);
  pintar();
});
