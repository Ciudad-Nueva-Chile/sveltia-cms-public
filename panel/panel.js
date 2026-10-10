// Panel de inventario: lee datos.json (python -m inventario --panel …).
// «Esta semana» y «Libros» usan los textos en lenguaje simple que calcula inventario/lenguaje.py,
// los mismos de la planilla. «Análisis» muestra el detalle técnico.
(function () {
  "use strict";

  var D = null;
  var estado = { orden: "sugerido", dir: -1, queHacer: "" };
  var $ = function (s) { return document.querySelector(s); };
  var fmt = new Intl.NumberFormat("es-CL");
  var COLOR_CAT = { AA: "var(--serie-a)", BB: "var(--serie-b)", CC: "var(--serie-c)", DD: "var(--serie-d)" };
  var CATEGORIAS = ["AA", "BB", "CC", "DD"];
  var CLASES = ["Regular", "Intermitente", "Esporádica", "Estacional", "Coyuntural", "Sin venta neta"];
  var ORDEN_QUE_HACER = ["Reponer hasta el nivel objetivo", "Reponer lo vendido en cada embarque", "Un pedido al año antes de septiembre",
    "No reponer", "Pedir solo si lo encargan"];
  var NS = "http://www.w3.org/2000/svg";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }
  function el(tag, attrs) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }
  function coma(v) { return String(v).replace(".", ","); }
  function fechaCl(iso) { return iso ? iso.split("-").reverse().join("-") : ""; }

  // ---------- Pestañas ----------
  function mostrarVista() {
    var v = (location.hash || "#semana").slice(1);
    if (!document.getElementById("vista-" + v)) v = "semana";
    document.querySelectorAll(".vista").forEach(function (s) { s.hidden = s.dataset.vista !== v; });
    document.querySelectorAll(".pestanas a").forEach(function (a) { a.setAttribute("aria-selected", String(a.dataset.vista === v)); });
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", mostrarVista);

  // ---------- Tooltip ----------
  var tip = $("#tooltip");
  function mostrarTip(html, ev) {
    tip.innerHTML = html;
    tip.hidden = false;
    var x = ev.clientX + 14, y = ev.clientY + 14, r = tip.getBoundingClientRect();
    if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - 14;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  function ocultarTip() { tip.hidden = true; }

  // =====================================================================
  // ESTA SEMANA
  // =====================================================================
  function pintarPedidos() {
    var S = D.semana;
    $("#pedidos").innerHTML = S.pedidos.map(function (p) {
      var lineas = D.pedido.filter(function (l) { return l.origen === p.origen; });
      var escala = Math.max(p.total_usd, p.minimo_usd) || 1;
      var icono = { ok: "✓", esperar: "…", nada: "–" }[p.tono];
      return '<article class="pedido pedido-' + p.tono + '">' +
        '<div class="pedido-cabecera"><span class="pedido-icono" aria-hidden="true">' + icono + '</span><div>' +
          "<h2>" + esc(p.titulo) + "</h2><p>" + esc(p.detalle) + "</p></div></div>" +
        (p.minimo_usd && lineas.length ? '<div class="barra-minimo" role="img" aria-label="US$ ' + fmt.format(Math.round(p.total_usd)) + " de un mínimo de US$ " + fmt.format(p.minimo_usd) + '">' +
          '<span style="width:' + (p.total_usd / escala * 100) + '%"></span><i style="left:' + (p.minimo_usd / escala * 100) + '%"></i></div>' +
          '<div class="barra-texto"><span>US$ ' + fmt.format(Math.round(p.total_usd)) + ' FOB</span><span>mínimo US$ ' + fmt.format(p.minimo_usd) + "</span></div>" : "") +
        (lineas.length ?
          '<ul class="lista-pedido">' + lineas.map(function (l) {
            var espera = l.cuando && l.cuando !== "Ahora";
            return '<li' + (espera ? ' class="espera"' : "") + '><span class="cant">' + l.cantidad + '</span><span class="lp-titulo">' + esc(l.titulo) +
              ' <em class="tag-cat">' + esc(l.categoria) + "</em>" + (espera ? ' <em class="tag-espera">' + esc(l.cuando.toLowerCase()) + "</em>" : "") +
              "<small>" + esc(l.por_que) + "</small></span></li>";
          }).join("") + "</ul>" : "") +
        (lineas.length ? '<button type="button" class="boton-sec" data-copiar="' + esc(p.origen) + '">Copiar lista para la editorial</button>' : "") +
        "</article>";
    }).join("") || '<p class="nota">Sin datos de pedido.</p>';
    if (S.ahorro_usd > 0) {
      $("#pedidos").insertAdjacentHTML("beforeend", '<p class="ahorro">Comprar cada libro en la editorial que conviene ahorra unos <b>US$ ' +
        fmt.format(Math.round(S.ahorro_usd)) + "</b> frente a comprarlo en su propia editorial.</p>");
    }

    document.querySelectorAll("[data-copiar]").forEach(function (b) {
      b.addEventListener("click", function () {
        var o = b.dataset.copiar;
        var texto = "Pedido " + o + " · Ciudad Nueva Chile\n\n" + D.pedido.filter(function (l) { return l.origen === o; })
          .map(function (l) { return l.cantidad + " × " + l.titulo + (l.isbn ? " (ISBN " + l.isbn + ")" : ""); }).join("\n");
        navigator.clipboard.writeText(texto).then(function () {
          var a = $("#aviso-copiado");
          a.hidden = false;
          setTimeout(function () { a.hidden = true; }, 1800);
        });
      });
    });
  }

  // ---------- Dónde conviene comprar ----------
  // Cada combinación cubre todo lo que hay que pedir y trae el costo de los libros puestos en bodega. El costo fijo de
  // cada envío no cambia qué libros van en cada una, así que la recomendación se puede recalcular aquí al instante.
  function usd(v) { return "US$ " + fmt.format(Math.round(v)); }

  function pintarComparacion() {
    var S = D.semana, C = S.combinaciones || [];
    if (!C.length) { $("#comparacion").innerHTML = ""; return; }
    var origenes = Object.keys(S.envios || {});
    $("#comparacion").innerHTML = '<article class="tarjeta comparacion"><header><h2>Dónde conviene comprar</h2>' +
      "<p>Anota la cotización de cada envío (courier, despacho y trámites) y la recomendación se recalcula al instante. El flete no se calcula por peso.</p></header>" +
      '<div class="envios">' + origenes.map(function (o) {
        return "<label>Envío a " + esc(o) + ' <span>US$</span><input type="number" min="0" step="10" inputmode="decimal" data-origen="' + esc(o) + '" value="' + (+S.envios[o] || 0) + '"></label>';
      }).join("") + "</div>" +
      '<div class="tabla-envoltura" style="border:0"><table class="tabla-comp"><thead><tr><th>Opción</th><th>Qué incluye</th><th class="num">Libros</th><th class="num">Envíos</th><th class="num">Total</th></tr></thead><tbody></tbody></table></div>' +
      '<p class="veredicto" aria-live="polite"></p>' +
      '<p class="nota">En US$. «Libros» es el costo puesto en bodega de todo lo que hay que pedir. Solo se comparan las combinaciones que cubren todo. ' +
      (C.length === 1 ? "Hoy hay una sola, porque varios títulos se compran en un solo país. " : "") +
      "Los costos que anotes aquí no se guardan: para que el cálculo los use, anótalos en la planilla (pestaña «Pedido sugerido»).</p></article>";
    var inputs = $("#comparacion").querySelectorAll("input[data-origen]");
    function recalcular() {
      var costo = {};
      inputs.forEach(function (i) { costo[i.dataset.origen] = Math.max(0, parseFloat(i.value) || 0); });
      var filas = C.map(function (c) {
        var envio = c.envia.reduce(function (s, o) { return s + (costo[o] || 0); }, 0);
        return { c: c, envio: envio, total: c.libros_usd + envio };
      });
      var validas = filas.filter(function (f) { return f.c.valida; });
      var mejor = validas.reduce(function (a, b) { return !a || b.total < a.total - 0.005 ? b : a; }, null);
      $("#comparacion tbody").innerHTML = filas.map(function (f) {
        var cls = f === mejor ? "mejor" : (f.c.valida ? "" : "invalida");
        return '<tr class="' + cls + '"><td>' + esc(f.c.nombre) + (f === mejor ? "<small>Conviene</small>" : "") + "</td><td>" + esc(f.c.incluye) + "</td>" +
          '<td class="num">' + usd(f.c.libros_usd) + "</td>" +
          '<td class="num">' + usd(f.envio) + '</td><td class="num"><b>' + usd(f.total) + "</b></td></tr>";
      }).join("");
      var elegida = C.find(function (c) { return c.elegida; });
      var v = $("#comparacion .veredicto");
      if (!mejor) { v.textContent = ""; return; }
      var segunda = validas.filter(function (f) { return f !== mejor; }).sort(function (a, b) { return a.total - b.total; })[0];
      v.innerHTML = "Conviene <b>" + esc(mejor.c.nombre.charAt(0).toLowerCase() + mejor.c.nombre.slice(1)) + "</b>: " + usd(mejor.total) +
        (segunda ? ", " + usd(segunda.total - mejor.total) + " menos que la siguiente opción." : ".") +
        (elegida && elegida.nombre !== mejor.c.nombre ? "<em>La lista de arriba se calculó para «" + esc(elegida.nombre) + "». Con estos costos cambia: anótalos en la planilla y se actualiza en el próximo cálculo.</em>" : "");
    }
    inputs.forEach(function (i) { i.addEventListener("input", recalcular); });
    recalcular();
  }

  function tarjetaLista(opt) {
    var MAX = 6;
    if (!opt.items.length) return "";
    var filas = opt.items.map(function (r, i) {
      return '<li' + (i >= MAX ? " hidden" : "") + ' data-id="' + esc(r.id) + '"><span class="li-titulo">' + esc(r.titulo) + '</span><span class="li-dato">' + opt.dato(r) + "</span></li>";
    }).join("");
    return '<article class="lista lista-' + opt.tono + '">' +
      '<header><h2>' + esc(opt.titulo) + ' <span class="cuenta">' + opt.items.length + "</span></h2>" +
      (opt.bajada ? "<p>" + opt.bajada + "</p>" : "") + "</header>" +
      "<ul>" + filas + "</ul>" +
      (opt.items.length > MAX ? '<button type="button" class="ver-todos">Ver los ' + opt.items.length + "</button>" : "") +
      "</article>";
  }

  function pintarListas() {
    var S = D.semana;
    $("#listas").innerHTML = [
      tarjetaLista({ titulo: "Se venden y están sin stock", tono: "urgente", items: S.sin_stock,
        bajada: "Títulos AA que se reponen. Van en el próximo embarque, salvo los que vienen en camino.",
        dato: function (r) { return "se vende " + esc(r.se_vende) + (r.en_camino ? ' · <b class="ok">vienen ' + r.en_camino + "</b>" : ""); } }),
      tarjetaLista({ titulo: "Te los pidieron y no había", tono: "urgente", items: S.perdidas || [],
        bajada: "Anotados en «Ventas» como «No había stock» en los últimos 90 días. Ya cuentan como demanda.",
        dato: function (r) { return r.unidades + " ejemplares · " + r.veces + (r.veces === 1 ? " pedido" : " pedidos") + " · último el " + fechaCl(r.ultima); } }),
      tarjetaLista({ titulo: "Qué contar esta semana", tono: "info", items: S.contar || [],
        bajada: "AA cada mes (registro permanente), BB cada 6 meses, CC y DD una vez al año.",
        dato: function (r) { return esc(r.categoria) + " · " + r.bodega + " en bodega"; } }),
      tarjetaLista({ titulo: "Bajas de stock sin venta anotada", tono: "info", items: S.sin_anotar || [],
        bajada: "Bajó «En bodega» pero no hay una venta en «Ventas». Si fue una venta, anótala con su precio y canal.",
        dato: function (r) { return "bajó " + r.unidades + " en bodega"; } }),
      tarjetaLista({ titulo: "Pasan a BB en la próxima revisión", tono: "info", items: S.reclasificar || [],
        bajada: "Títulos CC o DD que pidieron por el canal web.",
        dato: function (r) { return "hoy " + esc(r.categoria); } }),
      tarjetaLista({ titulo: "Fondo sin venta: CC y DD", tono: "atencion", items: S.fondo || [],
        bajada: "No se reponen. CC $" + fmt.format(S.valor_cc || 0) + " y DD $" + fmt.format(S.valor_dd || 0) + " a precio de lista. Su destino se decide fuera del sistema.",
        dato: function (r) { return esc(r.categoria) + " · " + r.bodega + " en bodega · $" + fmt.format(r.valor); } }),
      tarjetaLista({ titulo: "Consignaciones de más de un año", tono: "atencion", items: S.consignaciones,
        bajada: "Cobrar, pedir la devolución o renovar el acuerdo.",
        dato: function (r) { return r.unidades + " ejemplares · " + r.dias + " días"; } }),
      tarjetaLista({ titulo: "Productos de temporada", tono: "info", items: S.temporada,
        bajada: "Un pedido al año que debe llegar antes de septiembre, con la cantidad de la última temporada.",
        dato: function (r) { return "vendió " + r.vendio + " la última temporada" + (r.pedir ? " · pedir " + r.pedir : ""); } }),
    ].join("") + (S.errores.length ? '<article class="lista lista-atencion"><header><h2>Revisar en la planilla</h2></header><ul>' +
      S.errores.map(function (e) { return '<li><span class="li-titulo">' + esc(e) + "</span></li>"; }).join("") + "</ul></article>" : "");

    $("#listas").querySelectorAll(".ver-todos").forEach(function (b) {
      b.addEventListener("click", function () {
        b.parentElement.querySelectorAll("li[hidden]").forEach(function (li) { li.hidden = false; });
        b.remove();
      });
    });
    $("#listas").querySelectorAll("li[data-id]").forEach(function (li) {
      li.addEventListener("click", function () { abrirDetalle(li.dataset.id); });
    });
  }

  // =====================================================================
  // LIBROS
  // =====================================================================
  function pintarChips() {
    var cuenta = {};
    D.titulos.forEach(function (t) { cuenta[t.que_hacer] = (cuenta[t.que_hacer] || 0) + 1; });
    var opciones = [["", "Todos", D.titulos.length]].concat(ORDEN_QUE_HACER.filter(function (q) { return cuenta[q]; })
      .map(function (q) { return [q, q, cuenta[q]]; }));
    $("#chips").innerHTML = opciones.map(function (o) {
      return '<button type="button" class="chip" aria-pressed="' + (estado.queHacer === o[0]) + '" data-q="' + esc(o[0]) + '">' + esc(o[1]) + " <span>" + o[2] + "</span></button>";
    }).join("");
    $("#chips").querySelectorAll(".chip").forEach(function (c) {
      c.addEventListener("click", function () { estado.queHacer = c.dataset.q; pintarChips(); pintarLibros(); });
    });
  }

  function normalizar(s) { return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

  function pintarLibros() {
    var q = normalizar($("#buscar").value), soloAviso = $("#f-avisos").checked;
    var filas = D.titulos.filter(function (t) {
      if (estado.queHacer && t.que_hacer !== estado.queHacer) return false;
      if (soloAviso && !t.alertas) return false;
      return !q || normalizar(t.titulo + " " + t.id).indexOf(q) !== -1;
    }).sort(function (a, b) {
      var va = a[estado.orden], vb = b[estado.orden];
      if (typeof va === "number" || typeof vb === "number") return ((+va || 0) - (+vb || 0)) * estado.dir;
      return String(va).localeCompare(String(vb), "es") * estado.dir;
    });
    $("#contador").textContent = filas.length + " de " + D.titulos.length + " libros";
    document.querySelectorAll("#tabla-libros th[data-orden]").forEach(function (th) {
      th.setAttribute("aria-sort", th.dataset.orden === estado.orden ? (estado.dir > 0 ? "ascending" : "descending") : "none");
    });
    $("#tabla-libros tbody").innerHTML = filas.map(function (t) {
      var aviso = (t.alertas || "").split(" · ").filter(Boolean).map(function (a) {
        return '<span class="alerta' + (/Quiebre|negativo/.test(a) ? "" : " suave") + '">' + esc(a) + "</span>";
      }).join("<br>");
      return '<tr data-id="' + esc(t.id) + '"><td class="t-titulo">' + esc(t.titulo) + '<div class="t-id">' + esc(t.id) + " · " + esc(t.origen) + "</div></td>" +
        "<td>" + claveCat(t.categoria_gestion) + "</td>" +
        '<td class="num">' + t.bodega + '</td><td class="num">' + (t.consignacion || "") + "</td><td>" + esc(t.se_vende) + "</td>" +
        '<td><span class="que que-' + normalizar(t.que_hacer).replace(/[^a-z]+/g, "-") + '">' + esc(t.que_hacer) + '</span></td>' +
        '<td class="num pedir">' + (t.sugerido || "") + "</td><td>" + aviso + "</td></tr>";
    }).join("");
  }

  document.querySelectorAll("#tabla-libros th[data-orden]").forEach(function (th) {
    th.addEventListener("click", function () {
      if (estado.orden === th.dataset.orden) estado.dir *= -1;
      else { estado.orden = th.dataset.orden; estado.dir = th.dataset.orden === "titulo" || th.dataset.orden === "que_hacer" ? 1 : -1; }
      pintarLibros();
    });
  });
  $("#buscar").addEventListener("input", pintarLibros);
  $("#f-avisos").addEventListener("change", pintarLibros);
  $("#tabla-libros tbody").addEventListener("click", function (ev) {
    var tr = ev.target.closest("tr[data-id]");
    if (tr) abrirDetalle(tr.dataset.id);
  });

  // ---------- Detalle de un libro ----------
  function graficoSerie(serie) {
    var W = 680, H = 190, m = { t: 22, r: 8, b: 28, l: 34 };
    var n = serie.length, max = Math.max(1, Math.max.apply(null, serie));
    var paso = Math.ceil(max / 4) || 1, tope = paso * 4;
    var ancho = (W - m.l - m.r) / n, barra = Math.min(24, ancho - 2);
    var y = function (v) { return H - m.b - v / tope * (H - m.t - m.b); };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Venta neta por mes de los últimos " + n + " meses" });
    for (var v = 0; v <= tope; v += paso) {
      svg.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "eje" }));
      var t = el("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end", class: "eje-texto" });
      t.textContent = v;
      svg.appendChild(t);
    }
    var iMax = serie.indexOf(max);
    serie.forEach(function (val, i) {
      var cx = m.l + ancho * i + ancho / 2;
      var g = el("g", {});
      var hit = el("rect", { x: m.l + ancho * i, y: m.t, width: ancho, height: H - m.t - m.b, class: "barra-hit" });
      g.appendChild(hit);
      if (val > 0) {
        var r = Math.min(4, H - m.b - y(val), barra / 2), x0 = cx - barra / 2, y0 = y(val);
        g.appendChild(el("path", { class: "barra", d: "M" + x0 + "," + (H - m.b) + "V" + (y0 + r) + "Q" + x0 + "," + y0 + " " + (x0 + r) + "," + y0 + "H" + (x0 + barra - r) + "Q" + (x0 + barra) + "," + y0 + " " + (x0 + barra) + "," + (y0 + r) + "V" + (H - m.b) + "Z" }));
        if (i === iMax) {
          var lab = el("text", { x: cx, y: y0 - 6, "text-anchor": "middle", class: "eje-texto" });
          lab.textContent = val;
          g.appendChild(lab);
        }
      }
      if (i % 3 === 0 || i === n - 1) {
        var mes = el("text", { x: cx, y: H - m.b + 16, "text-anchor": "middle", class: "eje-texto" });
        mes.textContent = D.meses[i].slice(2).replace("-", "/");
        g.appendChild(mes);
      }
      hit.addEventListener("mousemove", function (ev) { mostrarTip("<strong>" + D.meses[i] + "</strong>" + val + " ejemplares", ev); });
      hit.addEventListener("mouseleave", ocultarTip);
      svg.appendChild(g);
    });
    return svg;
  }

  function frase(t) {
    var partes = [];
    partes.push("Categoría <b>" + esc(t.categoria_texto || t.categoria_gestion) + "</b>. Clase <b>" + esc(t.clase.toLowerCase()) + "</b> (" + esc((t.como_se_vende || "").toLowerCase()) + ").");
    if (t.tasa_mensual > 0) partes.push("Se vende <b>" + esc(t.se_vende) + "</b> según SBA.");
    var r = "Qué hacer: <b>" + esc(t.que_hacer.toLowerCase()) + "</b>";
    if (t.politica === "Reponer") {
      r += ". Nivel objetivo S = <b>" + t.nivel_objetivo + "</b> (Poisson al 95 % para " + coma(t.intervalo_meses) + " meses entre embarques más el plazo). Hoy hay " +
        t.bodega + (t.transito ? " y vienen " + t.transito : "") + ".";
    } else if (t.politica === "Reponer lo vendido") {
      r += ". Vendió " + t.vendido_desde_importacion + " desde el último embarque" + (t.transito ? " y vienen " + t.transito : "") + ".";
    } else r += ".";
    if (t.sugerido) r += " <b>Pedir " + t.sugerido + " en el próximo embarque.</b>";
    partes.push(r);
    return partes.join(" ");
  }

  function abrirDetalle(id) {
    var t = D.titulos.find(function (x) { return x.id === id; });
    if (!t) return;
    var tecnico = [
      ["Categoría", t.categoria_gestion], ["Clase", t.clase], ["Meses con venta (k)", t.meses_con_venta],
      ["ADI (informativo)", t.adi === "" || t.adi == null ? "Sin dato" : coma(t.adi)],
      ["CV² (informativo)", t.cv2 === "" || t.cv2 == null ? "Sin dato" : coma(t.cv2)],
      ["λ SBA (por mes)", coma(t.tasa_mensual)], ["T + L (meses)", coma(Math.round((t.intervalo_meses + t.plazo_meses) * 100) / 100)],
      ["Nivel objetivo S", t.politica === "Reponer" ? t.nivel_objetivo : "No aplica"], ["Política", t.politica],
    ];
    $("#detalle-contenido").innerHTML =
      "<h3>" + esc(t.titulo) + '</h3><p class="sub">' + esc(t.id) + " · " + esc(t.origen) + " · $" + fmt.format(t.precio_lista) + "</p>" +
      '<dl class="cifras"><div><dt>En bodega</dt><dd>' + t.bodega + "</dd></div><div><dt>En consignación</dt><dd>" + t.consignacion +
        "</dd></div><div><dt>Viene en camino</dt><dd>" + t.transito + "</dd></div><div><dt>Última salida</dt><dd>" + (fechaCl(t.ultima_salida) || "Sin salidas") + "</dd></div></dl>" +
      '<p class="frase">' + frase(t) + "</p>" +
      (t.alertas ? '<p class="alerta">' + esc(t.alertas) + "</p>" : "") +
      '<figure class="grafico" style="margin:14px 0 0"><figcaption><strong>Venta neta por mes</strong><span class="nota">' + t.unidades_ventana + " en " + D.meses.length + ' meses</span></figcaption><div class="lienzo" id="serie"></div></figure>' +
      '<details class="tecnico"><summary>Datos técnicos</summary><dl class="datos">' +
        tecnico.map(function (d) { return "<div><dt>" + esc(d[0]) + "</dt><dd>" + esc(d[1]) + "</dd></div>"; }).join("") + "</dl></details>";
    $("#serie").appendChild(graficoSerie(D.series[id] || []));
    $("#detalle").showModal();
  }

  // =====================================================================
  // ANÁLISIS
  // =====================================================================
  function valor(indicador) {
    var f = D.resumen.find(function (r) { return r.indicador === indicador; });
    return f ? f.valor : "";
  }

  function claveCat(k) {
    return '<span class="clave-abc"><i style="background:' + (COLOR_CAT[k] || "var(--texto-3)") + '"></i>' + esc(k) + "</span>";
  }

  // Tabla 4.24 de la memoria: por categoría, títulos, con existencias, ejemplares, valor y % del valor
  function pintarCategorias() {
    var filas = D.categorias || [];
    $("#tabla-categorias").innerHTML = '<table class="tabla"><thead><tr><th>Categoría</th><th>Criterio</th><th class="num">Títulos</th>' +
      '<th class="num">Con existencias</th><th class="num">Ejemplares</th><th class="num">Valor a precio de venta</th><th class="num">% del valor</th></tr></thead><tbody>' +
      filas.map(function (c) {
        return "<tr" + (c.categoria === "Total" ? ' class="fila-total"' : "") + "><td>" + (COLOR_CAT[c.categoria] ? claveCat(c.categoria) : esc(c.categoria)) + "</td><td>" + esc(c.criterio) +
          '</td><td class="num">' + fmt.format(c.titulos) + '</td><td class="num">' + fmt.format(c.con_existencias) + '</td><td class="num">' + fmt.format(c.ejemplares) +
          '</td><td class="num">$' + fmt.format(c.valor_pvp) + '</td><td class="num">' + (c.pct_valor * 100).toFixed(1).replace(".", ",") + " %</td></tr>";
      }).join("") + "</tbody></table>";
  }

  function pintarTiles() {
    var tiles = [
      ["Ejemplares en bodega", fmt.format(valor("Ejemplares en bodega"))],
      ["Valor en bodega a precio de lista", "$" + fmt.format(valor("Valor en bodega a precio de lista"))],
      ["Ejemplares en consignación", fmt.format(valor("Ejemplares en consignación"))],
      ["Títulos en cero", fmt.format(valor("Títulos en cero")) + " de " + fmt.format(valor("Títulos en catálogo"))],
      ["Títulos AA / BB / CC / DD / sin categoría", valor("Títulos AA / BB / CC / DD / sin categoría")],
      ["Títulos AA sin existencias", fmt.format(valor("Títulos AA sin existencias"))],
      ["Nivel objetivo S, suma", fmt.format(valor("Nivel objetivo S, suma (AA que se reponen)"))],
      ["Nivel de servicio (criterio)", valor("Nivel de servicio (criterio)")],
    ];
    var V = D.ventas || {};
    if (V.filas) {
      tiles.push(["Ventas anotadas con descuento (12 meses)", Math.round(V.pct_con_descuento * 100) + " %"]);
      tiles.push(["Descuento promedio cuando hay", Math.round(V.descuento_promedio * 100) + " %"]);
      tiles.push(["Ejemplares pedidos que no había (12 meses)", fmt.format(V.unidades_perdidas)]);
    }
    $("#tiles").innerHTML = tiles.map(function (t) {
      return '<div class="tile"><div class="tile-valor">' + esc(t[1]) + '</div><div class="tile-titulo">' + esc(t[0]) + "</div></div>";
    }).join("");
  }

  function pintarDispersion() {
    $("#leyenda-abc").innerHTML = CATEGORIAS.map(function (k) {
      return '<span><i style="background:' + COLOR_CAT[k] + '"></i>' + k + "</span>";
    }).join("");
    var puntos = D.titulos.filter(function (t) { return t.adi !== "" && t.adi != null; });
    var W = 640, H = 360, m = { t: 16, r: 16, b: 42, l: 46 };
    var maxAdi = Math.max(6, Math.ceil(Math.max.apply(null, puntos.map(function (p) { return +p.adi; }).concat([2]))));
    var maxCv = Math.max(1.5, Math.ceil(Math.max.apply(null, puntos.map(function (p) { return +p.cv2; }).concat([1])) * 2) / 2);
    var lx = Math.log;
    var x = function (v) { return m.l + (lx(v) - lx(1)) / (lx(maxAdi) - lx(1)) * (W - m.l - m.r); };
    var y = function (v) { return H - m.b - v / maxCv * (H - m.t - m.b); };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Dispersión de títulos según ADI y CV²" });
    [1, 1.32, 2, 3, 5, 10, 20].filter(function (v) { return v <= maxAdi; }).forEach(function (v) {
      svg.appendChild(el("line", { x1: x(v), x2: x(v), y1: m.t, y2: H - m.b, class: v === 1.32 ? "corte" : "eje" }));
      var t = el("text", { x: x(v), y: H - m.b + 16, "text-anchor": "middle", class: "eje-texto" });
      t.textContent = coma(v);
      svg.appendChild(t);
    });
    for (var v = 0; v <= maxCv + 1e-9; v += 0.5) {
      svg.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "eje" }));
      var ty = el("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end", class: "eje-texto" });
      ty.textContent = v.toFixed(1).replace(".", ",");
      svg.appendChild(ty);
    }
    svg.appendChild(el("line", { x1: m.l, x2: W - m.r, y1: y(0.49), y2: y(0.49), class: "corte" }));
    var ex = el("text", { x: (m.l + W - m.r) / 2, y: H - 6, "text-anchor": "middle", class: "eje-texto" });
    ex.textContent = "ADI: meses entre demandas (escala logarítmica)";
    svg.appendChild(ex);
    var ey = el("text", { x: 12, y: (m.t + H - m.b) / 2, "text-anchor": "middle", class: "eje-texto", transform: "rotate(-90 12 " + (m.t + H - m.b) / 2 + ")" });
    ey.textContent = "CV²: variabilidad del tamaño";
    svg.appendChild(ey);
    [["SUAVE", x(1) + 6, y(0) - 8, "start"], ["ERRÁTICA", x(1) + 6, m.t + 12, "start"],
     ["INTERMITENTE", W - m.r - 6, y(0) - 8, "end"], ["GRUMOSA", W - m.r - 6, m.t + 12, "end"]].forEach(function (c) {
      var t = el("text", { x: c[1], y: c[2], "text-anchor": c[3], class: "cuadrante" });
      t.textContent = c[0];
      svg.appendChild(t);
    });
    puntos.sort(function (a, b) { return b.categoria_gestion.localeCompare(a.categoria_gestion); }).forEach(function (p) {
      var c = el("circle", { cx: x(Math.min(+p.adi, maxAdi)), cy: y(Math.min(+p.cv2, maxCv)), r: 5.5, fill: COLOR_CAT[p.categoria_gestion] || "var(--texto-3)", class: "punto", tabindex: 0 });
      c.addEventListener("mousemove", function (ev) {
        mostrarTip("<strong>" + esc(p.titulo) + "</strong>" + esc(p.categoria_gestion) + " · " + esc(p.clase) + "<br>ADI " + coma(p.adi) + " · CV² " + coma(p.cv2), ev);
      });
      c.addEventListener("mouseleave", ocultarTip);
      c.addEventListener("click", function () { abrirDetalle(p.id); });
      c.addEventListener("keydown", function (ev) { if (ev.key === "Enter") abrirDetalle(p.id); });
      svg.appendChild(c);
    });
    $("#dispersion").replaceChildren(svg);
  }

  function pintarMatriz() {
    var clases = CLASES.filter(function (c) { return D.titulos.some(function (t) { return t.clase === c; }); });
    var cats = CATEGORIAS.concat(["Sin categoría"]);
    var conteo = D.matriz || {}, max = 1;
    Object.keys(conteo).forEach(function (k) { max = Math.max(max, conteo[k]); });
    var html = '<table class="matriz"><thead><tr><th></th>' + cats.map(function (k) { return '<th scope="col">' + (COLOR_CAT[k] ? claveCat(k) : esc(k)) + "</th>"; }).join("") + "</tr></thead><tbody>";
    clases.forEach(function (c) {
      html += '<tr><th scope="row">' + esc(c) + "</th>";
      cats.forEach(function (k) {
        var n = conteo[k + "|" + c] || 0, a = n ? 0.1 + 0.75 * n / max : 0;
        html += "<td" + (n ? ' data-cat="' + esc(k) + '" data-clase="' + esc(c) + '"' : ' class="cero"') +
          ' style="background: rgba(var(--secuencial), ' + a + ");" + (a > 0.5 ? "color:#fff;" : "") + '">' + n + "</td>";
      });
      html += "</tr>";
    });
    $("#matriz").innerHTML = html + "</tbody></table>";
    $("#matriz").querySelectorAll("td[data-cat]").forEach(function (td) {
      td.addEventListener("click", function () {
        var lista = D.titulos.filter(function (t) { return t.categoria_gestion === td.dataset.cat && t.clase === td.dataset.clase; });
        $("#detalle-contenido").innerHTML = "<h3>" + esc(td.dataset.cat) + " · " + esc(td.dataset.clase) + '</h3><p class="sub">' + lista.length + ' títulos</p><ul class="lista-simple">' +
          lista.map(function (t) { return '<li data-id="' + esc(t.id) + '">' + esc(t.titulo) + " <small>" + esc(t.que_hacer) + "</small></li>"; }).join("") + "</ul>";
        $("#detalle-contenido").querySelectorAll("li[data-id]").forEach(function (li) {
          li.addEventListener("click", function () { $("#detalle").close(); abrirDetalle(li.dataset.id); });
        });
        $("#detalle").showModal();
      });
    });
  }

  function pintarTecnica() {
    var orden = { AA: 0, BB: 1, CC: 2, DD: 3 };
    $("#tabla-tecnica tbody").innerHTML = D.titulos.slice().sort(function (a, b) {
      return ((orden[a.categoria_gestion] == null ? 9 : orden[a.categoria_gestion]) - (orden[b.categoria_gestion] == null ? 9 : orden[b.categoria_gestion])) || b.tasa_mensual - a.tasa_mensual;
    }).map(function (t) {
      return '<tr data-id="' + esc(t.id) + '"><td>' + esc(t.titulo) + "</td><td>" + claveCat(t.categoria_gestion) + "</td><td>" + esc(t.clase) + '</td><td class="num">' + t.meses_con_venta +
        '</td><td class="num">' + (t.adi === "" || t.adi == null ? "" : coma(t.adi)) + '</td><td class="num">' + (t.cv2 === "" || t.cv2 == null ? "" : coma(t.cv2)) +
        '</td><td class="num">' + coma(t.tasa_mensual) + '</td><td class="num">' + (t.politica === "Reponer" ? t.nivel_objetivo : "") + "</td><td>" + esc(t.politica) + "</td></tr>";
    }).join("");
    $("#tabla-tecnica tbody").addEventListener("click", function (ev) {
      var tr = ev.target.closest("tr[data-id]");
      if (tr) abrirDetalle(tr.dataset.id);
    });
  }

  // ---------- Carga ----------
  // Con datos reales se publica datos.cifrado.json (AES-GCM con una clave derivada de la contraseña, ver
  // inventario/cifrado.py) y se pide la contraseña. Sin él, se muestran los datos de ejemplo de datos.json.
  var CLAVE_RECORDADA = "inventario-panel.clave";

  function iniciar(datos) {
    D = datos;
    document.body.classList.remove("bloqueado");
    $("#acceso").hidden = true;
    $("#fecha-corte").textContent = fechaCl(D.fecha_corte);
    $("#etiqueta-datos").textContent = D.etiqueta || "";
    $("#etiqueta-datos").hidden = !D.etiqueta;
    pintarComparacion();
    pintarPedidos();
    pintarListas();
    pintarChips();
    pintarLibros();
    pintarTiles();
    pintarCategorias();
    pintarDispersion();
    pintarMatriz();
    pintarTecnica();
  }

  function errorCarga(texto) {
    var e = $("#error-carga");
    e.hidden = false;
    e.textContent = texto;
  }

  function bytes(b64) { return Uint8Array.from(atob(b64), function (c) { return c.charCodeAt(0); }); }
  function base64(arr) { return btoa(String.fromCharCode.apply(null, arr)); }
  function leerRecordada() { try { return localStorage.getItem(CLAVE_RECORDADA); } catch (e) { return null; } }
  function guardarRecordada(v) { try { v ? localStorage.setItem(CLAVE_RECORDADA, v) : localStorage.removeItem(CLAVE_RECORDADA); } catch (e) { /* sin almacenamiento */ } }

  function derivar(contrasena, paquete) {
    return crypto.subtle.importKey("raw", new TextEncoder().encode(contrasena), "PBKDF2", false, ["deriveBits"])
      .then(function (base) {
        return crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt: bytes(paquete.sal), iterations: paquete.iteraciones }, base, 256);
      })
      .then(function (bits) { return new Uint8Array(bits); });
  }

  function descifrar(paquete, clave) {
    return crypto.subtle.importKey("raw", clave, "AES-GCM", false, ["decrypt"])
      .then(function (k) { return crypto.subtle.decrypt({ name: "AES-GCM", iv: bytes(paquete.iv) }, k, bytes(paquete.datos)); })
      .then(function (texto) { return JSON.parse(new TextDecoder().decode(texto)); });
  }

  function pedirContrasena(paquete) {
    document.body.classList.add("bloqueado");
    $("#acceso").hidden = false;
    $("#contrasena").focus();
    $("#form-acceso").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var boton = $("#entrar");
      boton.disabled = true;
      boton.textContent = "Abriendo…";
      $("#acceso-error").hidden = true;
      var clave;
      derivar($("#contrasena").value, paquete)
        .then(function (c) { clave = c; return descifrar(paquete, c); })
        .then(function (datos) {
          if ($("#recordar").checked) guardarRecordada(base64(clave));
          $("#contrasena").value = "";
          iniciar(datos);
        })
        .catch(function () {
          $("#acceso-error").hidden = false;
          $("#contrasena").select();
        })
        .then(function () { boton.disabled = false; boton.textContent = "Entrar"; });
    });
  }

  $("#salir").addEventListener("click", function () {
    guardarRecordada(null);
    location.reload();
  });

  mostrarVista();
  fetch("datos.cifrado.json", { cache: "no-store" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; })
    .then(function (paquete) {
      if (!paquete) {  // sin datos reales: los de ejemplo
        return fetch("datos.json", { cache: "no-store" })
          .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
          .then(iniciar)
          .catch(function () { errorCarga("No se encontraron los datos del panel. Revisa el último «Publicar sitio y panel» en GitHub Actions."); });
      }
      $("#salir").hidden = false;
      var recordada = leerRecordada();
      if (!recordada) return pedirContrasena(paquete);
      return descifrar(paquete, bytes(recordada)).then(iniciar).catch(function () {
        guardarRecordada(null);  // cambió la contraseña
        pedirContrasena(paquete);
      });
    });
})();
