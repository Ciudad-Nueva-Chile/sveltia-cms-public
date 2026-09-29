// Panel de inventario: lee datos.json (generado por `python -m inventario --panel …`) y lo dibuja.
(function () {
  "use strict";

  var D = null;
  var estado = { orden: "sugerido", dir: -1, filtroMatriz: null };
  var $ = function (s) { return document.querySelector(s); };
  var fmt = new Intl.NumberFormat("es-CL");
  var fmtUsd = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
  var COLOR_ABC = { A: "var(--serie-a)", B: "var(--serie-b)", C: "var(--serie-c)" };
  var CLASES = ["Regular", "Intermitente", "Esporádica", "Estacional", "Coyuntural", "Sin demanda"];
  var NS = "http://www.w3.org/2000/svg";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }
  function el(tag, attrs) {
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }

  // ---------- Tooltip ----------
  var tip = $("#tooltip");
  function mostrarTip(html, ev) {
    tip.innerHTML = html;
    tip.hidden = false;
    var x = ev.clientX + 14, y = ev.clientY + 14;
    var r = tip.getBoundingClientRect();
    if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 14;
    if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - 14;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  function ocultarTip() { tip.hidden = true; }

  // ---------- Resumen ----------
  function valor(indicador) {
    var f = D.resumen.find(function (r) { return r.indicador === indicador; });
    return f ? f.valor : "";
  }

  function pintarResumen() {
    var tiles = [
      ["Ejemplares en bodega", fmt.format(valor("Ejemplares en bodega"))],
      ["Valor en bodega a precio de lista", "$" + fmt.format(valor("Valor en bodega a precio de lista"))],
      ["Ejemplares en consignación", fmt.format(valor("Ejemplares en consignación"))],
      ["Títulos en cero", fmt.format(valor("Títulos en cero")) + " de " + fmt.format(valor("Títulos en catálogo"))],
      ["Quiebres en títulos que se reponen", fmt.format(valor("Títulos con quiebre (se reponen y están en cero)")), true],
      ["Para liquidar o revisar", fmt.format(valor("Títulos para liquidar o revisar")), true],
    ];
    $("#tiles").innerHTML = tiles.map(function (t) {
      return '<div class="tile' + (t[2] ? " tile-destacado" : "") + '"><div class="tile-valor">' + esc(t[1]) + '</div><div class="tile-titulo">' + esc(t[0]) + "</div></div>";
    }).join("");
    if (D.errores && D.errores.length) {
      var av = $("#avisos-datos");
      av.hidden = false;
      av.innerHTML = "<strong>Revisar en la planilla</strong><ul>" + D.errores.map(function (e) { return "<li>" + esc(e) + "</li>"; }).join("") + "</ul>";
    }
  }

  // ---------- Pedido ----------
  function pintarPedido() {
    $("#origenes").innerHTML = D.pedido_resumen.map(function (o) {
      var clase = /^Pedir/.test(o.estado) ? "estado-pedir" : /^Acumular/.test(o.estado) ? "estado-acumular" : "estado-nada";
      var pct = o.minimo_usd ? Math.min(100, (o.total_usd / o.minimo_usd) * 100) : 0;
      var escala = Math.max(o.total_usd, o.minimo_usd) || 1;
      var lineas = D.pedido.filter(function (l) { return l.origen === o.origen; });
      return '<article class="tarjeta">' +
        '<div class="origen-cabecera"><h3>' + esc(o.origen) + '</h3><span class="estado ' + clase + '">' + esc(o.estado) + "</span></div>" +
        '<div class="barra-minimo" role="img" aria-label="Pedido US$ ' + fmtUsd.format(o.total_usd) + " de un mínimo de US$ " + fmtUsd.format(o.minimo_usd) + '">' +
          '<span style="width:' + (o.total_usd / escala * 100) + '%"></span><i style="left:' + (o.minimo_usd / escala * 100) + '%"></i></div>' +
        '<div class="barra-texto"><span>US$ ' + fmtUsd.format(o.total_usd) + " · " + o.unidades + " ejemplares · " + o.titulos + " títulos</span><span>mínimo US$ " + fmtUsd.format(o.minimo_usd) + (o.fecha_sugerida ? " · " + esc(o.fecha_sugerida) : "") + "</span></div>" +
        (o.costos_configurados ? "" : '<p class="alerta">Faltan los costos de este origen en la pestaña Costos: el total en dólares no se puede calcular.</p>') +
        (lineas.length ? '<table class="lineas"><thead><tr><th>Título</th><th>ABC</th><th class="num">Cant.</th><th class="num">US$</th></tr></thead><tbody>' +
          lineas.map(function (l) {
            return "<tr><td>" + esc(l.titulo) + '<div class="motivo">' + esc(l.motivo) + '</div></td><td>' + claveAbc(l.abc) + '</td><td class="num">' + l.cantidad + '</td><td class="num">' + (l.subtotal_usd === "" ? "—" : fmtUsd.format(l.subtotal_usd)) + "</td></tr>";
          }).join("") + "</tbody></table>" : '<p class="nota">Nada que pedir en este origen.</p>') +
        "</article>";
    }).join("") || '<p class="nota">Sin datos de pedido.</p>';
  }

  function claveAbc(k) {
    return '<span class="clave-abc"><i style="background:' + (COLOR_ABC[k] || "var(--texto-3)") + '"></i>' + esc(k) + "</span>";
  }

  // ---------- Dispersión ADI / CV² ----------
  function pintarDispersion() {
    $("#leyenda-abc").innerHTML = ["A", "B", "C"].map(function (k) {
      return '<span><i style="background:' + COLOR_ABC[k] + '"></i>Clase ' + k + "</span>";
    }).join("");
    var puntos = D.titulos.filter(function (t) { return t.adi !== "" && t.adi != null; });
    var W = 640, H = 380, m = { t: 16, r: 16, b: 42, l: 46 };
    var maxAdi = Math.max(6, Math.ceil(Math.max.apply(null, puntos.map(function (p) { return +p.adi; }).concat([2]))));
    var maxCv = Math.max(1.5, Math.ceil(Math.max.apply(null, puntos.map(function (p) { return +p.cv2; }).concat([1])) * 2) / 2);
    // ADI en escala logarítmica: la frontera 1,32 queda legible y los valores altos no aplastan el gráfico
    var lx = function (v) { return Math.log(v); };
    var x = function (v) { return m.l + (lx(v) - lx(1)) / (lx(maxAdi) - lx(1)) * (W - m.l - m.r); };
    var y = function (v) { return H - m.b - v / maxCv * (H - m.t - m.b); };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Dispersión de títulos según ADI y CV²" });

    [1, 1.32, 2, 3, 5, 10, 20].filter(function (v) { return v <= maxAdi; }).forEach(function (v) {
      svg.appendChild(el("line", { x1: x(v), x2: x(v), y1: m.t, y2: H - m.b, class: v === 1.32 ? "corte" : "eje" }));
      var t = el("text", { x: x(v), y: H - m.b + 16, "text-anchor": "middle", class: "eje-texto" });
      t.textContent = String(v).replace(".", ",");
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

    // C primero, A encima: los títulos importantes quedan visibles
    puntos.sort(function (a, b) { return b.abc.localeCompare(a.abc); }).forEach(function (p) {
      var c = el("circle", { cx: x(Math.min(+p.adi, maxAdi)), cy: y(Math.min(+p.cv2, maxCv)), r: 5.5, fill: COLOR_ABC[p.abc], class: "punto", tabindex: 0 });
      c.addEventListener("mousemove", function (ev) {
        mostrarTip("<strong>" + esc(p.titulo) + "</strong>Clase " + p.abc + " · " + esc(p.patron) + "<br>ADI " + String(p.adi).replace(".", ",") + " · CV² " + String(p.cv2).replace(".", ",") + "<br>" + p.unidades_ventana + " unidades en " + p.meses_con_demanda + " meses con demanda", ev);
      });
      c.addEventListener("mouseleave", ocultarTip);
      c.addEventListener("click", function () { abrirDetalle(p.id); });
      c.addEventListener("keydown", function (ev) { if (ev.key === "Enter") abrirDetalle(p.id); });
      svg.appendChild(c);
    });
    $("#dispersion").replaceChildren(svg);
  }

  // ---------- Matriz ABC × clase ----------
  function pintarMatriz() {
    var clases = CLASES.filter(function (c) { return D.titulos.some(function (t) { return t.clase === c; }); });
    var conteo = {}, max = 1;
    D.titulos.forEach(function (t) {
      var k = t.abc + "|" + t.clase;
      conteo[k] = (conteo[k] || 0) + 1;
      max = Math.max(max, conteo[k]);
    });
    var html = '<table class="matriz"><thead><tr><th></th>' + ["A", "B", "C"].map(function (k) { return '<th scope="col">' + claveAbc(k) + "</th>"; }).join("") + "</tr></thead><tbody>";
    clases.forEach(function (c) {
      html += '<tr><th scope="row">' + esc(c) + "</th>";
      ["A", "B", "C"].forEach(function (k) {
        var n = conteo[k + "|" + c] || 0;
        var a = n ? 0.1 + 0.75 * n / max : 0;
        var claro = a > 0.5;
        html += "<td" + (n ? ' data-abc="' + k + '" data-clase="' + esc(c) + '"' : ' class="cero"') +
          ' style="background: rgba(var(--secuencial), ' + a + ");" + (claro ? "color:#fff;" : "") + '">' + n + "</td>";
      });
      html += "</tr>";
    });
    $("#matriz").innerHTML = html + "</tbody></table>";
    $("#matriz").querySelectorAll("td[data-abc]").forEach(function (td) {
      td.addEventListener("click", function () {
        $("#f-abc").value = td.dataset.abc;
        $("#f-clase").value = td.dataset.clase;
        pintarTabla();
        document.getElementById("titulos").scrollIntoView({ behavior: "smooth" });
      });
    });
  }

  // ---------- Tabla ----------
  function llenarFiltros() {
    var clases = CLASES.filter(function (c) { return D.titulos.some(function (t) { return t.clase === c; }); });
    $("#f-clase").insertAdjacentHTML("beforeend", clases.map(function (c) { return "<option>" + esc(c) + "</option>"; }).join(""));
    var pols = Array.from(new Set(D.titulos.map(function (t) { return t.politica; })));
    $("#f-politica").insertAdjacentHTML("beforeend", pols.map(function (c) { return "<option>" + esc(c) + "</option>"; }).join(""));
  }

  function normalizar(s) { return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }

  function filtrados() {
    var q = normalizar($("#buscar").value), abc = $("#f-abc").value, clase = $("#f-clase").value, pol = $("#f-politica").value, conAlerta = $("#f-alertas").checked;
    return D.titulos.filter(function (t) {
      if (abc && t.abc !== abc) return false;
      if (clase && t.clase !== clase) return false;
      if (pol && t.politica !== pol) return false;
      if (conAlerta && !t.alertas) return false;
      return !q || normalizar(t.titulo + " " + t.id).indexOf(q) !== -1;
    });
  }

  function pintarTabla() {
    var filas = filtrados().sort(function (a, b) {
      var va = a[estado.orden], vb = b[estado.orden];
      if (typeof va === "number" || typeof vb === "number") return ((+va || 0) - (+vb || 0)) * estado.dir;
      return String(va).localeCompare(String(vb), "es") * estado.dir;
    });
    $("#contador").textContent = filas.length + " de " + D.titulos.length + " títulos";
    document.querySelectorAll("#tabla th[data-orden]").forEach(function (th) {
      th.setAttribute("aria-sort", th.dataset.orden === estado.orden ? (estado.dir > 0 ? "ascending" : "descending") : "none");
    });
    $("#tabla tbody").innerHTML = filas.map(function (t) {
      var alertas = (t.alertas || "").split(" · ").filter(Boolean).map(function (a) {
        return '<span class="alerta' + (/Quiebre|negativo/.test(a) ? "" : " suave") + '">' + esc(a) + "</span>";
      }).join("<br>");
      return '<tr data-id="' + esc(t.id) + '"><td class="t-titulo">' + esc(t.titulo) + '<div class="t-id">' + esc(t.id) + " · " + esc(t.origen) + "</div></td>" +
        "<td>" + claveAbc(t.abc) + "</td><td>" + esc(t.clase) + '</td><td class="num">' + t.bodega + '</td><td class="num">' + t.consignacion + "</td>" +
        '<td class="num">' + String(t.pronostico_mensual).replace(".", ",") + '</td><td class="num">' + t.stock_objetivo + '</td><td class="num ' + (t.sugerido ? "pedir" : "") + '">' + (t.sugerido || "") + "</td>" +
        '<td class="politica">' + esc(t.politica) + "</td><td>" + alertas + "</td></tr>";
    }).join("");
  }

  document.querySelectorAll("#tabla th[data-orden]").forEach(function (th) {
    th.addEventListener("click", function () {
      if (estado.orden === th.dataset.orden) estado.dir *= -1;
      else { estado.orden = th.dataset.orden; estado.dir = th.dataset.orden === "titulo" ? 1 : -1; }
      pintarTabla();
    });
  });
  ["#buscar", "#f-abc", "#f-clase", "#f-politica", "#f-alertas"].forEach(function (s) {
    $(s).addEventListener(s === "#buscar" ? "input" : "change", pintarTabla);
  });
  $("#limpiar").addEventListener("click", function () {
    $("#buscar").value = ""; $("#f-abc").value = ""; $("#f-clase").value = ""; $("#f-politica").value = ""; $("#f-alertas").checked = false;
    pintarTabla();
  });
  $("#tabla tbody").addEventListener("click", function (ev) {
    var tr = ev.target.closest("tr[data-id]");
    if (tr) abrirDetalle(tr.dataset.id);
  });

  // ---------- Detalle de un título ----------
  function graficoSerie(serie) {
    var W = 680, H = 200, m = { t: 22, r: 8, b: 28, l: 34 };
    var n = serie.length, max = Math.max(1, Math.max.apply(null, serie));
    var paso = Math.ceil(max / 4) || 1, tope = paso * 4;
    var ancho = (W - m.l - m.r) / n, barra = Math.min(24, ancho - 2);
    var y = function (v) { return H - m.b - v / tope * (H - m.t - m.b); };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Demanda mensual de los últimos " + n + " meses" });
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
        var h = H - m.b - y(val), r = Math.min(4, h, barra / 2), x0 = cx - barra / 2, y0 = y(val);
        // Extremo de datos redondeado, base recta
        g.appendChild(el("path", { class: "barra", d: "M" + x0 + "," + (H - m.b) + "V" + (y0 + r) + "Q" + x0 + "," + y0 + " " + (x0 + r) + "," + y0 + "H" + (x0 + barra - r) + "Q" + (x0 + barra) + "," + y0 + " " + (x0 + barra) + "," + (y0 + r) + "V" + (H - m.b) + "Z" }));
      } else {
        g.appendChild(el("rect", { class: "barra", x: cx - barra / 2, y: H - m.b - 1, width: barra, height: 0 }));
      }
      if (i === iMax && val > 0) {
        var lab = el("text", { x: cx, y: y(val) - 6, "text-anchor": "middle", class: "eje-texto" });
        lab.textContent = val;
        g.appendChild(lab);
      }
      if (i % 3 === 0 || i === n - 1) {
        var mes = el("text", { x: cx, y: H - m.b + 16, "text-anchor": "middle", class: "eje-texto" });
        mes.textContent = D.meses[i].slice(2).replace("-", "/");
        g.appendChild(mes);
      }
      hit.addEventListener("mousemove", function (ev) { mostrarTip("<strong>" + D.meses[i] + "</strong>" + val + " unidades", ev); });
      hit.addEventListener("mouseleave", ocultarTip);
      svg.appendChild(g);
    });
    return svg;
  }

  function explicar(t) {
    var p = {
      "Reponer": "Se repone hasta el stock objetivo: la demanda del plazo de reposición más la revisión, al nivel de servicio configurado.",
      "Stock mínimo": "Rota poco y aporta poco valor (clase C): basta con tener un ejemplar disponible.",
      "A pedido": "La demanda es esporádica o no existe: se pide a la editorial solo cuando un cliente lo solicita.",
      "Temporada": "Producto estacional: se decide un pedido antes de cada temporada con lo vendido en la anterior.",
      "No reponer": "Demanda coyuntural (un evento que no se repite): no se repone salvo decisión expresa.",
      "Liquidar o revisar": "Tiene stock pero no sale hace mucho: conviene liquidarlo, devolverlo o revisar si el conteo está bien.",
    };
    return p[t.politica] || "";
  }

  function abrirDetalle(id) {
    var t = D.titulos.find(function (x) { return x.id === id; });
    if (!t) return;
    var datos = [
      ["Bodega", t.bodega], ["En consignación", t.consignacion], ["En tránsito", t.transito],
      ["Clase ABC", t.abc], ["Patrón", t.patron], ["Clase de demanda", t.clase],
      ["ADI", t.adi === "" || t.adi == null ? "—" : String(t.adi).replace(".", ",")], ["CV²", t.cv2 === "" || t.cv2 == null ? "—" : String(t.cv2).replace(".", ",")],
      ["Pronóstico mensual", String(t.pronostico_mensual).replace(".", ",")], ["Cobertura (meses)", String(t.cobertura_meses).replace(".", ",")],
      ["Punto de pedido", t.punto_pedido], ["Stock objetivo", t.stock_objetivo], ["Sugerido pedir", t.sugerido],
      ["Última salida", t.ultima_salida || "—"], ["Precio de lista", "$" + fmt.format(t.precio_lista)],
    ];
    $("#detalle-contenido").innerHTML =
      "<h3>" + esc(t.titulo) + '</h3><p class="sub">' + esc(t.id) + " · " + esc(t.origen) + " · " + esc(t.categoria) + " · política: <strong>" + esc(t.politica) + "</strong></p>" +
      '<figure class="grafico" style="margin:0"><figcaption><strong>Demanda mensual (salida física neta)</strong><span class="nota">' + t.unidades_ventana + " unidades en " + D.meses.length + " meses</span></figcaption><div class=\"lienzo\" id=\"serie\"></div></figure>" +
      '<dl class="datos">' + datos.map(function (d) { return "<div><dt>" + esc(d[0]) + "</dt><dd>" + esc(d[1]) + "</dd></div>"; }).join("") + "</dl>" +
      (t.alertas ? '<p class="alerta">' + esc(t.alertas) + "</p>" : "") +
      '<p class="explicacion">' + esc(explicar(t)) + "</p>";
    $("#serie").appendChild(graficoSerie(D.series[id] || []));
    $("#detalle").showModal();
  }

  // ---------- Carga ----------
  fetch("datos.json", { cache: "no-store" })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (datos) {
      D = datos;
      $("#fecha-corte").textContent = D.fecha_corte;
      $("#etiqueta-datos").textContent = D.etiqueta || "";
      $("#etiqueta-datos").hidden = !D.etiqueta;
      pintarResumen();
      pintarPedido();
      pintarDispersion();
      pintarMatriz();
      llenarFiltros();
      pintarTabla();
    })
    .catch(function () {
      var e = $("#error-carga");
      e.hidden = false;
      e.textContent = "No se encontró datos.json. Genéralo con: python -m inventario --panel panel/datos.json";
    });
})();
