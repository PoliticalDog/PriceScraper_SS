"""Capturas del dashboard con recuadros y etiquetas numeradas (skill documentar-proyecto).

Lee un YAML con la lista de capturas (formato en assets/capturas_ejemplo.yaml), abre cada pagina en Chromium sin
ventana con Playwright, ejecuta sus acciones, dibuja un recuadro de color con una etiqueta "N. texto" sobre cada
elemento anotado (calculado desde su selector CSS) y guarda el PNG.

Uso (desde la raiz del repo):
    venv/Scripts/python.exe .claude/skills/documentar-proyecto/scripts/capturas_dashboard.py \
        --config docs/manual_usuario/capturas.yaml --salida docs/manual_usuario/capturas [--solo NOMBRE] [--base URL]

Si el dashboard no responde en --base, levanta `manage.py runserver` con el mismo Python y lo apaga al terminar.
"""
import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import yaml
from playwright.sync_api import sync_playwright

COLORES = ["#e34948", "#2a78d6", "#1f9d55", "#d97706", "#7c3aed", "#0e7490"]

# Dibuja recuadros y etiquetas en coordenadas del documento (position:absolute sobre <body>), para que el
# recorte con full_page los incluya aunque esten fuera de la ventana. pointer-events:none: no tapan clics.
JS_ANOTAR = """
(anotaciones) => {
  document.querySelectorAll('.doc-anotacion').forEach(e => e.remove());
  // Sin desplazar: la captura de pagina completa parte de arriba, y la barra fija tapaba las etiquetas
  window.scrollTo(0, 0);
  const faltan = [];
  anotaciones.forEach((a, i) => {
    const el = document.querySelector(a.selector);
    if (!el) { faltan.push(a.selector); return; }
    const r = el.getBoundingClientRect();
    const x = r.left + window.scrollX, y = r.top + window.scrollY, pad = 4;
    const caja = document.createElement('div');
    caja.className = 'doc-anotacion';
    Object.assign(caja.style, {position: 'absolute', left: (x - pad) + 'px', top: (y - pad) + 'px',
      width: (r.width + 2 * pad) + 'px', height: (r.height + 2 * pad) + 'px', border: '3px solid ' + a.color,
      borderRadius: '6px', zIndex: 2147483646, pointerEvents: 'none', boxSizing: 'border-box'});
    const etq = document.createElement('div');
    etq.className = 'doc-anotacion';
    etq.textContent = (i + 1) + '. ' + a.etiqueta;
    Object.assign(etq.style, {position: 'absolute', left: (x - pad) + 'px', background: a.color, color: '#fff',
      font: '600 13px/1.3 "Segoe UI", Arial, sans-serif', padding: '3px 8px', borderRadius: '4px',
      zIndex: 2147483647, pointerEvents: 'none', whiteSpace: 'nowrap', boxShadow: '0 1px 3px rgba(0,0,0,.35)'});
    document.body.appendChild(caja);
    document.body.appendChild(etq);
    // arriba del recuadro si cabe; si no, dentro de su esquina superior
    const alto = etq.getBoundingClientRect().height;
    etq.style.top = (y - pad - alto - 2 >= 0 ? y - pad - alto - 2 : y + 2) + 'px';
  });
  return faltan;
}
"""

# Union del recorte (si hay selector) con todas las anotaciones (cajas y etiquetas), en coordenadas del documento
JS_CAJA = """
(selector) => {
  const rects = [];
  const sx = window.scrollX, sy = window.scrollY;
  const agregar = el => { const r = el.getBoundingClientRect(); rects.push([r.left + sx, r.top + sy, r.right + sx, r.bottom + sy]); };
  if (selector) {
    const base = document.querySelector(selector);
    if (!base) return null;
    agregar(base);
  }
  document.querySelectorAll('.doc-anotacion').forEach(agregar);
  if (!rects.length) return null;
  return [Math.min(...rects.map(r => r[0])), Math.min(...rects.map(r => r[1])),
          Math.max(...rects.map(r => r[2])), Math.max(...rects.map(r => r[3]))];
}
"""


def responde(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except Exception:
        return False


def levantar_servidor(base: str, repo: Path):
    if responde(base):
        return None
    puerto = urlparse(base).port or 8000
    print(f"[capturas] el dashboard no responde en {base}: levanto runserver en el puerto {puerto}")
    proc = subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{puerto}", "--noreload"],
                            cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if responde(base):
            return proc
        time.sleep(1)
    proc.terminate()
    raise SystemExit("[capturas] runserver no respondio en 60 s (¿PostgreSQL arriba? ¿.env?)")


def ejecutar_acciones(page, acciones: list):
    for acc in acciones or []:
        if "clic" in acc:
            page.click(acc["clic"])
        elif "escribir" in acc:
            page.fill(acc["escribir"]["selector"], str(acc["escribir"]["texto"]))
        elif "seleccionar" in acc:
            page.select_option(acc["seleccionar"]["selector"], str(acc["seleccionar"]["valor"]))
        elif "esperar" in acc:
            page.wait_for_selector(acc["esperar"], state="visible", timeout=30000)
        elif "esperar_ms" in acc:
            page.wait_for_timeout(int(acc["esperar_ms"]))
        else:
            raise SystemExit(f"[capturas] accion desconocida: {acc}")


def capturar(page, base: str, cap: dict, salida: Path, espera_graficas: int) -> str:
    page.goto(base.rstrip("/") + cap["url"], wait_until="networkidle")
    if cap.get("esperar"):
        page.wait_for_selector(cap["esperar"], state="visible", timeout=30000)
    ejecutar_acciones(page, cap.get("acciones"))
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(espera_graficas)          # animaciones de Chart.js y DataTables
    anot = [{"selector": a["selector"], "etiqueta": a["etiqueta"],
             "color": a.get("color", COLORES[i % len(COLORES)])} for i, a in enumerate(cap.get("anotaciones") or [])]
    faltan = page.evaluate(JS_ANOTAR, anot)
    if faltan:
        print(f"[capturas] AVISO {cap['archivo']}: no existen los selectores {faltan}")
    page.wait_for_timeout(150)
    destino = salida / cap["archivo"]
    # por defecto: el rectangulo que encierra todas las anotaciones (o la ventana si no hay)
    recorte = cap.get("recorte", "auto" if anot else "ventana")
    if recorte == "ventana":
        page.screenshot(path=str(destino))
    elif recorte == "pagina":
        page.screenshot(path=str(destino), full_page=True)
    else:
        caja = page.evaluate(JS_CAJA, None if recorte == "auto" else recorte)
        if caja is None:
            raise SystemExit(f"[capturas] {cap['archivo']}: el selector de recorte {recorte!r} no existe")
        m = int(cap.get("margen", 16))
        x0, y0 = max(caja[0] - m, 0), max(caja[1] - m, 0)
        alto = caja[3] + m - y0
        if cap.get("alto_max"):            # tablas largas: se corta abajo (las anotaciones de abajo se pierden)
            alto = min(alto, int(cap["alto_max"]))
        page.screenshot(path=str(destino), full_page=True,
                        clip={"x": x0, "y": y0, "width": caja[2] + m - x0, "height": alto})
    return str(destino)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="YAML con las capturas")
    ap.add_argument("--salida", required=True, help="carpeta de los PNG")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--solo", action="append", help="nombre del archivo (sin .png) a regenerar; se puede repetir")
    ap.add_argument("--repo", default=".", help="raiz del repo (donde esta manage.py)")
    a = ap.parse_args()

    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    ventana = cfg.get("ventana", {})
    capturas = cfg["capturas"]
    if a.solo:
        capturas = [c for c in capturas if Path(c["archivo"]).stem in a.solo]
        if not capturas:
            raise SystemExit(f"[capturas] ninguna captura se llama {a.solo}")
    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)

    servidor = levantar_servidor(a.base, Path(a.repo).resolve())
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch()
            page = nav.new_page(viewport={"width": int(ventana.get("ancho", 1440)), "height": int(ventana.get("alto", 900))},
                                device_scale_factor=float(ventana.get("escala", 1.5)), locale="es-MX")
            for cap in capturas:
                ruta = capturar(page, a.base, cap, salida, int(cfg.get("espera_graficas_ms", 1200)))
                print(f"[capturas] {ruta} ({len(cap.get('anotaciones') or [])} anotaciones)")
            nav.close()
    finally:
        if servidor is not None:
            servidor.terminate()
            servidor.wait(timeout=15)


if __name__ == "__main__":
    main()
