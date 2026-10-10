const slug = (texto) =>
  String(texto || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();

const porTitulo = (a, b) => a.data.titulo.localeCompare(b.data.titulo, "es");
// Libros visibles en el sitio: los marcados «Ocultar en el sitio» en /admin quedan fuera de todo
const librosVisibles = (api) => api.getFilteredByGlob("src/libros/*.md").filter((l) => !l.data.oculto);

import { HtmlBasePlugin } from "@11ty/eleventy";

// En GitHub Pages el sitio de prueba vive bajo /sveltia-cms-public/; en ciudadnueva.cl, en la raíz.
// PATH_PREFIX lo fija el flujo de publicación; HtmlBasePlugin corrige todos los enlaces del HTML.
const PATH_PREFIX = process.env.PATH_PREFIX || "/";

export default function (eleventyConfig) {
  eleventyConfig.addPlugin(HtmlBasePlugin);
  // Versión de prueba: no se indexa en buscadores y muestra un aviso
  eleventyConfig.addGlobalData("entorno", { prueba: PATH_PREFIX !== "/" || Boolean(process.env.SITIO_PRUEBA) });

  eleventyConfig.addPassthroughCopy("src/assets");
  eleventyConfig.addPassthroughCopy({ admin: "admin" });
  // Tipografías servidas desde el propio sitio (Fontsource, licencia OFL), sin depender de un servicio externo
  const FUENTES = "node_modules/@fontsource-variable/";
  eleventyConfig.addPassthroughCopy({
    [FUENTES + "fraunces/files/fraunces-latin-opsz-normal.woff2"]: "assets/fuentes/fraunces-latin-opsz-normal.woff2",
    [FUENTES + "fraunces/files/fraunces-latin-opsz-italic.woff2"]: "assets/fuentes/fraunces-latin-opsz-italic.woff2",
    [FUENTES + "inter/files/inter-latin-wght-normal.woff2"]: "assets/fuentes/inter-latin-wght-normal.woff2",
  });

  // ---------- Filtros ----------
  eleventyConfig.addFilter("slug", slug);

  eleventyConfig.addFilter("clp", (valor) => {
    if (valor === undefined || valor === null || valor === "" || Number(valor) === 0) return "";
    return "$" + Number(valor).toLocaleString("es-CL");
  });

  eleventyConfig.addFilter("fecha", (valor) => {
    const d = new Date(String(valor) + "T12:00:00");
    if (isNaN(d)) return valor;
    return d.toLocaleDateString("es-CL", { day: "numeric", month: "long", year: "numeric" });
  });

  eleventyConfig.addFilter("anio", () => new Date().getFullYear());

  // Relacionados: primero la misma colección, luego la misma categoría
  eleventyConfig.addFilter("relacionados", (libros, actual, limite = 6) => {
    const otros = libros.filter((l) => l.url !== actual.page.url);
    const misma = actual.coleccion_visible ? otros.filter((l) => l.data.coleccion_visible === actual.coleccion_visible) : [];
    const cat = otros.filter((l) => l.data.categoria === actual.categoria && !misma.includes(l));
    return [...misma, ...cat].slice(0, limite);
  });

  eleventyConfig.addFilter("conPortada", (libros) => libros.filter((l) => l.data.portada));
  eleventyConfig.addFilter("deCategoria", (libros, nombre) => libros.filter((l) => l.data.categoria === nombre));
  eleventyConfig.addFilter("deColeccion", (libros, nombre) => libros.filter((l) => l.data.coleccion_visible === nombre));
  eleventyConfig.addFilter("fueraDe", (libros, colecciones) => {
    const nombres = new Set((colecciones || []).map((c) => c.nombre));
    return libros.filter((l) => !nombres.has(l.data.coleccion_visible));
  });
  eleventyConfig.addFilter("tomar", (arr, n) => (arr || []).slice(0, n));

  // Busca la ficha de configuración de una categoría (color, nombre corto)
  eleventyConfig.addFilter("infoCategoria", (nombre, categorias) => {
    const c = (categorias?.lista || []).find((x) => x.nombre === nombre);
    return c ? { ...c, slug: slug(c.corto || c.nombre) } : { nombre, corto: nombre, color: "#555", slug: slug(nombre) };
  });

  // ---------- Colecciones ----------
  eleventyConfig.addCollection("libros", (api) => librosVisibles(api).sort(porTitulo));

  // Páginas de texto (Nosotros, Librerías e instituciones), para el mapa del sitio
  eleventyConfig.addCollection("paginas", (api) => api.getFilteredByGlob("src/paginas/*.md"));

  eleventyConfig.addCollection("destacados", (api) =>
    librosVisibles(api).filter((l) => l.data.destacado).sort(porTitulo)
  );

  // Categorías en el orden de src/_data/categorias.json; si un libro trae una categoría
  // que no está en el archivo, igual aparece (al final) para que nada quede huérfano.
  eleventyConfig.addCollection("categorias", (api) => {
    const libros = librosVisibles(api).sort(porTitulo);
    const config = libros[0]?.data.categorias?.lista || [];
    const nombres = [...config.map((c) => c.nombre)];
    for (const l of libros) if (!nombres.includes(l.data.categoria)) nombres.push(l.data.categoria);
    return nombres
      .map((nombre) => {
        const c = config.find((x) => x.nombre === nombre) || { nombre, corto: nombre, descripcion: "", color: "#555" };
        const items = libros.filter((l) => l.data.categoria === nombre);
        return { ...c, slug: slug(c.corto || c.nombre), libros: items, muestra: items.filter((l) => l.data.portada).slice(0, 3) };
      })
      .filter((c) => c.libros.length);
  });

  eleventyConfig.addCollection("colecciones", (api) => {
    const libros = librosVisibles(api).sort(porTitulo);
    const config = libros[0]?.data.colecciones?.lista || [];
    return config
      .map((c) => {
        const items = libros
          .filter((l) => l.data.coleccion_visible === c.nombre)
          .sort((a, b) => (parseInt(a.data.num_coleccion) || 9999) - (parseInt(b.data.num_coleccion) || 9999) || porTitulo(a, b));
        return { ...c, slug: slug(c.nombre), libros: items, muestra: items.filter((l) => l.data.portada).slice(0, 3) };
      })
      .filter((c) => c.libros.length);
  });

  return {
    dir: { input: "src", includes: "_includes", data: "_data", output: "_site" },
    pathPrefix: PATH_PREFIX,
    markdownTemplateEngine: "njk",
    htmlTemplateEngine: "njk",
  };
}
