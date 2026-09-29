// Comportamiento común a todas las páginas: menú móvil, carrusel y la solicitud de pedido.
// La solicitud vive en localStorage; no hay servidor ni pago en línea.
(function () {
  "use strict";

  var CLAVE = "cn-solicitud-v1";

  function leer() {
    try {
      var datos = JSON.parse(localStorage.getItem(CLAVE) || "[]");
      return Array.isArray(datos) ? datos : [];
    } catch (e) {
      return [];
    }
  }

  function guardar(items) {
    try {
      localStorage.setItem(CLAVE, JSON.stringify(items));
    } catch (e) {}
    actualizarContador(items);
    document.dispatchEvent(new CustomEvent("solicitud:cambio", { detail: items }));
  }

  function agregar(libro, cantidad) {
    var items = leer();
    var existente = items.find(function (i) { return i.id === libro.id; });
    if (existente) existente.cantidad = Math.min(999, existente.cantidad + cantidad);
    else items.push(Object.assign({}, libro, { cantidad: cantidad }));
    guardar(items);
  }

  function actualizarContador(items) {
    var total = items.reduce(function (s, i) { return s + i.cantidad; }, 0);
    document.querySelectorAll("[data-contador]").forEach(function (el) {
      el.textContent = total;
      el.hidden = total === 0;
    });
  }

  function formatoCLP(n) {
    return "$" + Number(n || 0).toLocaleString("es-CL");
  }

  var temporizador;
  function aviso(html) {
    var el = document.querySelector("[data-aviso]");
    if (!el) return;
    el.innerHTML = html;
    el.hidden = false;
    requestAnimationFrame(function () { el.classList.add("visible"); });
    clearTimeout(temporizador);
    temporizador = setTimeout(function () {
      el.classList.remove("visible");
      setTimeout(function () { el.hidden = true; }, 300);
    }, 3200);
  }

  function libroDesde(boton) {
    var d = boton.dataset;
    return {
      id: d.pedidoId,
      titulo: d.pedidoTitulo,
      isbn: d.pedidoIsbn,
      precio: Number(d.pedidoPrecio) || 0,
      url: d.pedidoUrl,
      portada: d.pedidoPortada,
    };
  }

  // Botones «+» de las tarjetas y «Agregar a mi solicitud» de la ficha
  document.addEventListener("click", function (e) {
    var boton = e.target.closest("[data-pedido-id]");
    if (!boton) return;
    e.preventDefault();
    var cantidad = 1;
    if (boton.hasAttribute("data-con-cantidad")) {
      var input = document.querySelector("[data-cantidad-input]");
      cantidad = Math.max(1, Math.min(999, parseInt(input && input.value, 10) || 1));
    }
    agregar(libroDesde(boton), cantidad);
    boton.classList.add("agregado");
    setTimeout(function () { boton.classList.remove("agregado"); }, 900);
    aviso("<strong>Agregado a tu solicitud</strong><span>" + (cantidad > 1 ? cantidad + " × " : "") + boton.dataset.pedidoTitulo.replace(/</g, "&lt;") + '</span><a href="' + (window.SITIO.base || "/") + 'solicitud/">Ver solicitud</a>');
  });

  // Selector de cantidad de la ficha
  document.querySelectorAll("[data-cantidad]").forEach(function (caja) {
    var input = caja.querySelector("input");
    caja.querySelector("[data-menos]").addEventListener("click", function () { input.value = Math.max(1, (parseInt(input.value, 10) || 1) - 1); });
    caja.querySelector("[data-mas]").addEventListener("click", function () { input.value = Math.min(999, (parseInt(input.value, 10) || 0) + 1); });
  });

  // «Recomendar este libro»: menú nativo de compartir en celulares; si no, WhatsApp
  document.addEventListener("click", function (e) {
    var enlace = e.target.closest("[data-compartir]");
    if (!enlace || !navigator.share || !window.matchMedia("(pointer: coarse)").matches) return;
    e.preventDefault();
    navigator.share({ title: enlace.dataset.compartirTitulo, url: enlace.dataset.compartirUrl }).catch(function () {});
  });

  // Menú móvil
  var botonMenu = document.querySelector("[data-menu]");
  if (botonMenu) {
    botonMenu.addEventListener("click", function () {
      var abierto = botonMenu.getAttribute("aria-expanded") === "true";
      botonMenu.setAttribute("aria-expanded", String(!abierto));
      document.body.classList.toggle("menu-abierto", !abierto);
    });
  }

  // Sombra de la cabecera al hacer scroll
  var cabecera = document.querySelector("[data-cabecera]");
  if (cabecera) {
    var alScroll = function () { cabecera.classList.toggle("con-sombra", window.scrollY > 8); };
    window.addEventListener("scroll", alScroll, { passive: true });
    alScroll();
  }

  // Carruseles
  document.querySelectorAll("[data-carrusel-anterior], [data-carrusel-siguiente]").forEach(function (b) {
    b.addEventListener("click", function () {
      var id = b.dataset.carruselAnterior || b.dataset.carruselSiguiente;
      var pista = document.getElementById(id);
      if (!pista) return;
      var paso = pista.clientWidth * 0.85 * (b.dataset.carruselAnterior ? -1 : 1);
      pista.scrollBy({ left: paso, behavior: "smooth" });
    });
  });

  actualizarContador(leer());

  // API mínima para las páginas de catálogo y solicitud
  window.Solicitud = { leer: leer, guardar: guardar, formatoCLP: formatoCLP, aviso: aviso };
})();
