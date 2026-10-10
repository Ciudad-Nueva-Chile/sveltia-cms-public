// Datos comunes a todas las fichas de libro y campos calculados para la vista.
// Los .md solo guardan lo que Roberto edita desde /admin; aquí se deriva lo demás.

const SIGLA_FINAL = /\s*\(\s*([A-Z]{2})\.?\s*(\d+)\s*\)\s*$/;
const COLECCION_VACIA = new Set(["", "Sin colección identificada en el título"]);
const AUTOR_VACIO = new Set(["", "Autor no especificado"]);

// Primera frase de la sinopsis (el cuerpo del .md), sin marcas de Markdown
const primeraFrase = (texto) => {
  const limpio = String(texto || "").replace(/[#*_>`\[\]()]/g, " ").replace(/\s+/g, " ").trim();
  if (!limpio) return "";
  const m = limpio.match(/^.{20,240}?[.!?](\s|$)/);
  return (m ? m[0] : limpio.slice(0, 200)).trim();
};

export default {
  layout: "libro.njk",
  eleventyComputed: {
    // Un libro oculto desde /admin no genera su página
    permalink: (data) => (data.oculto ? false : `/catalogo/${data.page.fileSlug}/`),
    // Título sin la sigla de colección final, p. ej. "CARTAS CRISTOLOGICAS (BP. 46)" → "CARTAS CRISTOLOGICAS"
    titulo_visible: (data) => String(data.titulo || "").replace(/\\"/g, '"').replace(SIGLA_FINAL, "").replace(/\s{2,}/g, " ").trim(),
    // "BP 46", o vacío si el título no trae sigla
    sigla: (data) => {
      const m = String(data.titulo || "").match(SIGLA_FINAL);
      return m ? `${m[1]} ${m[2]}` : "";
    },
    autor_visible: (data) => {
      const a = String(data.autor || "").trim();
      if (AUTOR_VACIO.has(a)) return "";
      if (/^aa\.?\s*vv\.?$/i.test(a)) return "Varios autores";
      return a;
    },
    coleccion_visible: (data) => (COLECCION_VACIA.has(String(data.coleccion || "").trim()) ? "" : data.coleccion),
    sello: (data) => data.origen_editorial || "Ciudad Nueva",
    // Descripción para buscadores propia de cada ficha: título, autor, colección y número, ISBN y, si hay sinopsis,
    // su primera frase. Nunca incluye existencias, costos ni precio neto.
    descripcion_seo: (data) => {
      const partes = [`${data.titulo_visible}${data.autor_visible ? `, de ${data.autor_visible}` : ""}.`];
      if (data.coleccion_visible) partes.push(`${data.coleccion_visible}${data.num_coleccion ? ` n.º ${data.num_coleccion}` : ""}.`);
      if (data.isbn) partes.push(`ISBN ${data.isbn}.`);
      const frase = primeraFrase(data.page?.rawInput);
      partes.push(frase || `Editorial ${data.sello}, disponible en Chile.`);
      return partes.join(" ");
    },
  },
};
