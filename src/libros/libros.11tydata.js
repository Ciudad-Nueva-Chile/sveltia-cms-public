// Datos comunes a todas las fichas de libro y campos calculados para la vista.
// Los .md solo guardan lo que Roberto edita desde /admin; aquí se deriva lo demás.

const SIGLA_FINAL = /\s*\(\s*([A-Z]{2})\.?\s*(\d+)\s*\)\s*$/;
const COLECCION_VACIA = new Set(["", "Sin colección identificada en el título"]);
const AUTOR_VACIO = new Set(["", "Autor no especificado"]);

export default {
  layout: "libro.njk",
  permalink: "/catalogo/{{ page.fileSlug }}/",
  eleventyComputed: {
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
  },
};
