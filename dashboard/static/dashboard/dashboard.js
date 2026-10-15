// dashboard/static/dashboard.js
// Helpers compartidos por todas las paginas del dashboard.

// Construye un query string a partir de un objeto; los valores que son
// arrays se repiten como parametros multiples (?tienda=A&tienda=B), que es
// como FastAPI espera listas en query params.
function qs(params) {
  const partes = [];
  for (const [clave, valor] of Object.entries(params)) {
    if (valor === undefined || valor === null || valor === "") continue;
    if (Array.isArray(valor)) {
      valor.forEach((v) => partes.push(`${encodeURIComponent(clave)}=${encodeURIComponent(v)}`));
    } else {
      partes.push(`${encodeURIComponent(clave)}=${encodeURIComponent(valor)}`);
    }
  }
  return partes.length ? `?${partes.join("&")}` : "";
}

async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) {
    console.error("Error al consultar", url, resp.status);
    return [];
  }
  return resp.json();
}

// Devuelve los valores seleccionados de un <select multiple>.
function valoresSeleccionados(selectEl) {
  return Array.from(selectEl.selectedOptions).map((o) => o.value);
}

// Filtro de lista desplegable (09-oct-2026): reemplaza los <select multiple size="4">,
// que se veian como cajas fijas y pedian Ctrl+clic. Muestra una opcion "Todas" y una
// casilla por valor. El <select multiple> original queda oculto como fuente de verdad,
// asi valoresSeleccionados() sigue igual: "Todas" = nada seleccionado = sin filtro.
// Se arma con createElement (no innerHTML) porque los valores vienen de la BD.
function crearFiltroLista(selectId, valores, etiquetaTodas = "Todas") {
  const select = document.getElementById(selectId);
  select.hidden = true;
  select.replaceChildren(...valores.map((v) => new Option(v, v)));

  select.parentElement.querySelector(".filtro-lista")?.remove();
  const cont = document.createElement("div");
  cont.className = "dropdown filtro-lista";

  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "form-select text-start";
  boton.setAttribute("data-bs-toggle", "dropdown");
  boton.setAttribute("data-bs-auto-close", "outside");
  boton.setAttribute("aria-expanded", "false");

  const menu = document.createElement("div");
  menu.className = "dropdown-menu filtro-lista-menu";

  const casilla = (texto, valor) => {
    const label = document.createElement("label");
    label.className = "dropdown-item filtro-lista-item";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.className = "form-check-input me-2";
    if (valor !== null) input.value = valor;
    label.append(input, document.createTextNode(texto));
    menu.append(label);
    return input;
  };

  // Con muchas opciones, un buscador arriba de la lista
  if (valores.length > 10) {
    const buscador = document.createElement("input");
    buscador.type = "search";
    buscador.className = "form-control form-control-sm filtro-lista-buscar";
    buscador.placeholder = "Buscar...";
    buscador.addEventListener("input", () => {
      const q = buscador.value.toLowerCase();
      menu.querySelectorAll(".filtro-lista-item[data-valor]").forEach((el) => {
        el.hidden = !el.dataset.valor.toLowerCase().includes(q);
      });
    });
    menu.append(buscador);
  }

  const todas = casilla(etiquetaTodas, null);
  todas.checked = true;
  const sep = document.createElement("hr");
  sep.className = "dropdown-divider";
  menu.append(sep);
  const casillas = valores.map((v) => {
    const input = casilla(v, v);
    input.parentElement.dataset.valor = v;
    return input;
  });

  const sincronizar = () => {
    const elegidos = casillas.filter((c) => c.checked).map((c) => c.value);
    Array.from(select.options).forEach((o) => { o.selected = elegidos.includes(o.value); });
    todas.checked = elegidos.length === 0;
    boton.textContent =
      elegidos.length === 0 ? etiquetaTodas :
      elegidos.length === 1 ? elegidos[0] :
      `${elegidos.length} seleccionadas`;
    boton.title = elegidos.join(", ");
    select.dispatchEvent(new Event("change"));
  };

  todas.addEventListener("change", () => {
    casillas.forEach((c) => { c.checked = false; });
    sincronizar();
  });
  casillas.forEach((c) => c.addEventListener("change", sincronizar));

  cont.append(boton, menu);
  select.after(cont);
  sincronizar();
}

// Filtro "Con / sin categoria" (14-oct-2026, docs/bi/metricas.md seccion 5). El <select> lo pinta
// templates/dashboard/_filtro_con_categoria.html. Valor del parametro con_categoria: "" = todos (default), "si", "no".
// Sin categoria = la categoria del registro es NULL, vacia o solo espacios (regla en dashboard/queries.py).
// Con "Sin categoria" la lista de categorias no aplica (en AND daria siempre vacio): se desactiva y no se envia.
function paramsCategoria(conCategoriaId, listaId = null) {
  const con = document.getElementById(conCategoriaId).value;
  const lista = listaId ? document.getElementById(listaId) : null;
  return {
    con_categoria: con,
    categoria: lista && con !== "no" ? valoresSeleccionados(lista) : [],
  };
}

function enlazarConCategoria(conCategoriaId, listaId) {
  const sel = document.getElementById(conCategoriaId);
  const actualizar = () => {
    const lista = document.getElementById(listaId);
    const boton = lista?.parentElement.querySelector(".filtro-lista > button");
    if (!boton) return;
    boton.disabled = sel.value === "no";
    boton.title = boton.disabled ? "No aplica a registros sin categoría" : valoresSeleccionados(lista).join(", ");
  };
  sel.addEventListener("change", actualizar);
  actualizar();
}

// Filtro "Folleto" (14-oct-2026, docs/bi/metricas.md seccion 6). El <input> lo pinta
// templates/dashboard/_filtro_folleto.html. Devuelve el id de la fuente sin espacios ("" = todos; qs() lo omite).
// Coincidencia exacta en el servidor: un id inexistente da vacio.
function valorFolleto(folletoId) {
  return document.getElementById(folletoId).value.trim();
}

// Aviso del filtro "Folleto" (14-oct-2026, docs/bi/metricas.md seccion 6). Consulta /api/filtros/folleto y pinta
// en `contenedorId` un aviso si el id no existe o si el folleto existe pero no tiene precios registrados. Con el
// filtro vacio no consulta nada y deja el contenedor oculto (la pagina queda igual que antes).
// modo: "precios" (paneles de registros: avisa no_existe y sin_precios) | "folletos" (paneles por folleto que no
// dependen de precios: solo no_existe) | "errores" (no_existe, diciendo si tiene errores de carga).
// Todo el texto va por textContent: el id lo escribe el usuario y nunca se interpreta como HTML.
function textoAvisoFolleto(e, modo = "precios") {
  if (!e || !e.estado) return null;
  const id = `"${e.folleto}"`;
  if (e.estado === "no_existe") {
    if (modo === "errores" && e.errores_carga > 0) {
      return { nivel: "warning", icono: "ti-file-alert",
        texto: `El folleto ${id} no está cargado en la BD (no hay fila en folletos), pero tiene ` +
               `${e.errores_carga} error(es) de carga registrados: su carga pudo fallar completa.` };
    }
    return { nivel: "warning", icono: "ti-alert-triangle",
      texto: `Folleto no encontrado: no existe ningún folleto con ID ${id}. El filtro usa el ID de la fuente ` +
             "(Tiendeo/Ofertomat), exacto, como aparece en la columna Origen o en la carpeta " +
             "data/raw/<fuente>/<tienda>/<id>." };
  }
  if (e.estado === "sin_precios" && modo === "precios") {
    const donde = [e.tiendas.join(", "), e.fuentes.join(", ")].filter(Boolean).join(" · ");
    return { nivel: "info", icono: "ti-info-circle",
      texto: `El folleto ${id} existe${donde ? ` (${donde})` : ""} pero no tiene precios registrados: ` +
             "no hay registros que mostrar con este filtro." };
  }
  return null;
}

async function avisoFolleto(folleto, contenedorId, modo = "precios") {
  const cont = document.getElementById(contenedorId);
  const turno = String(Number(cont.dataset.turno || 0) + 1);  // ignora respuestas de un Aplicar anterior
  cont.dataset.turno = turno;
  cont.replaceChildren();
  cont.hidden = true;
  if (!folleto) return null;
  const estado = await fetchJSON(`/api/filtros/folleto${qs({ folleto })}`);
  if (cont.dataset.turno !== turno) return estado;
  const aviso = textoAvisoFolleto(estado, modo);
  if (aviso) {
    const div = document.createElement("div");
    div.className = `alert alert-${aviso.nivel} py-2 small mb-3`;
    div.setAttribute("role", "status");
    const icono = document.createElement("i");
    icono.className = `ti ${aviso.icono} me-1`;
    div.append(icono, document.createTextNode(aviso.texto));
    cont.append(div);
    cont.hidden = false;
  }
  return estado;
}

// Texto corto del filtro activo, para notas de KPIs y avisos ("" si es todos).
function textoConCategoria(valor) {
  return valor === "si" ? "con categoría" : valor === "no" ? "sin categoría" : "";
}

// Inicializa o reinicializa una DataTable en `selector` con `data` (array de
// objetos) y `columns` (array de {data, title, render?}). Destruye la
// instancia previa si existia, para poder recargar filtros sin duplicar.
const _tablasActivas = {};

function renderTabla(selector, data, columns, opciones = {}) {
  if (_tablasActivas[selector]) {
    _tablasActivas[selector].destroy();
    $(selector).empty();
  }
  _tablasActivas[selector] = $(selector).DataTable({
    data: data,
    columns: columns,
    pageLength: 25,
    order: opciones.order || [],
    language: {
      search: "Buscar:",
      lengthMenu: "Mostrar _MENU_ filas",
      info: "_START_ a _END_ de _TOTAL_ filas",
      infoEmpty: "Sin datos",
      zeroRecords: "Sin resultados con estos filtros",
      paginate: { previous: "Anterior", next: "Siguiente" },
    },
    ...opciones,
  });
  return _tablasActivas[selector];
}

// Registro de graficas Chart.js activas por canvas id, para destruir antes
// de redibujar (Chart.js no permite reusar un canvas sin destruir la previa).
const _chartsActivos = {};

function renderChart(canvasId, config) {
  if (_chartsActivos[canvasId]) {
    _chartsActivos[canvasId].destroy();
  }
  const ctx = document.getElementById(canvasId).getContext("2d");
  _chartsActivos[canvasId] = new Chart(ctx, config);
  return _chartsActivos[canvasId];
}

// Para render de DataTables, que inserta el string como HTML
function escaparHtml(texto) {
  if (texto === null || texto === undefined) return "";
  return String(texto)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function formatoMoneda(valor) {
  if (valor === null || valor === undefined) return "—";
  return `$${Number(valor).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatoPct(valor) {
  if (valor === null || valor === undefined) return "—";
  return `${Number(valor).toFixed(1)}%`;
}

// -- Procedencia por registro (13-oct-2026, docs/bi/metricas.md "Procedencia por registro") --
// Celda "Origen": folleto_id_fuente · vigencia · pag. N, titulo en tooltip, [pag] al visor y [folleto] a
// url_origen (solo si existe; el servidor ya descarto lo que no sea http/https). Todo texto pasa por escaparHtml.
function formatoVigencia(desde, hasta) {
  const corto = (d) => (d ? String(d).slice(5).split("-").reverse().join("/") : "?");
  if (!desde && !hasta) return "sin vigencia";
  return `${corto(desde)}→${corto(hasta)}`;
}

function urlVisor(fila) {
  if (fila.id) return `/origen/extraccion/${encodeURIComponent(fila.id)}`;
  if (fila.pagina_id) return `/origen/pagina/${encodeURIComponent(fila.pagina_id)}`;
  return null;
}

function renderOrigen(fila, opciones = {}) {
  if (!fila || !fila.folleto_id_fuente) return "—";
  const partes = [];
  if (opciones.conTienda && fila.tienda) partes.push(escaparHtml(fila.tienda));
  partes.push(escaparHtml(fila.folleto_id_fuente));
  if (opciones.conVigencia !== false) {
    partes.push(escaparHtml(formatoVigencia(fila.vigencia_desde ?? fila.fecha, fila.vigencia_hasta)));
  }
  if (fila.numero_pagina) partes.push(`pág. ${escaparHtml(fila.numero_pagina)}`);
  const titulo = fila.folleto_titulo ? ` title="${escaparHtml(fila.folleto_titulo)}"` : "";
  const visor = urlVisor(fila);
  const enlaces = [];
  if (visor) enlaces.push(`<a href="${visor}" target="_blank" rel="noopener">[pág]</a>`);
  if (fila.url_origen) {
    enlaces.push(`<a href="${escaparHtml(fila.url_origen)}" target="_blank" rel="noopener noreferrer">[folleto]</a>`);
  }
  return `<span class="origen-celda"${titulo}>${partes.join(" · ")}</span> ${enlaces.join(" ")}`;
}
