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

function formatoMoneda(valor) {
  if (valor === null || valor === undefined) return "—";
  return `$${Number(valor).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatoPct(valor) {
  if (valor === null || valor === undefined) return "—";
  return `${Number(valor).toFixed(1)}%`;
}
