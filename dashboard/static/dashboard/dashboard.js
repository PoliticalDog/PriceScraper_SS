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
