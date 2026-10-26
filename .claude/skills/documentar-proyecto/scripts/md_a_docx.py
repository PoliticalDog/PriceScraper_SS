"""Convierte los .md del manual en un .docx con la plantilla de estilos del proyecto (skill documentar-proyecto).

Conserva los estilos, margenes, encabezado y pie de la plantilla y reemplaza su contenido por: portada, indices
(general, de tablas y de figuras, como campos de Word) y los capitulos de los .md, en el orden recibido.

Mapeo (convenciones en SKILL.md):
    # Titulo            -> Titulos_capitulos (nueva pagina)
    ## / ### / ####     -> Titulo_punteado, niveles 1 / 2 / 3 de su numeracion
    parrafo             -> Normal          | - item / 1. item -> List Paragraph con vinetas / numeros
    ```bloque```        -> resaltado_codigo_diagramas, una linea por parrafo
    tabla | a | b |     -> tabla + pie "Tabla n – desc. Fuente: Creación propia." (linea "Tabla: desc [| Fuente: X]")
    ![desc](ruta.png)   -> imagen centrada + pie "Figura n – desc. Fuente: Creación propia." (estilo Figuras)
    > cita              -> Normal en cursiva con sangria
    **negrita**, *cursiva*, `codigo`, [texto](url)

Dos modos:
  - Borrador de capitulo (--capitulo): sin portada ni indices; los titulos bajan un nivel para pegarse dentro de
    un capitulo del documento de la persona (# -> Titulo_punteado nivel 1, ## -> nivel 2...). Arriba lleva una
    nota con el .md y el commit de origen, y --registro anota que version se entrego (para saber despues que cambio).
  - Documento completo (sin --capitulo): portada (--portada), indices y un capitulo por cada `#`.

Uso (desde la raiz del repo):
    venv/Scripts/python.exe .claude/skills/documentar-proyecto/scripts/md_a_docx.py --capitulo \
        --registro docs/entregables/registro_borradores.yaml \
        --salida docs/entregables/documentacion_tecnica/borrador_03_nlp.docx md_modulos_leeme/03_nlp.md
"""
import argparse
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import docx
import yaml
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Inches, Pt

ESTILO_CAPITULO = "Titulos_capitulos"
ESTILO_TITULO = "Titulo_punteado"
ESTILO_LISTA = "List Paragraph"
ESTILO_CODIGO = "resaltado_codigo_diagramas"
ESTILO_PIE_TABLA = "Tablas"
ESTILO_PIE_FIGURA = "Figuras"
FUENTE_DEFECTO = "Creación propia"

RE_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|(?<![\w*])\*[^*\s][^*]*\*(?![\w*]))")
RE_IMAGEN = re.compile(r"^!\[(.*?)\]\((.+?)\)\s*$")
RE_PIE_TABLA = re.compile(r"^Tabla:\s*(.+?)(?:\s*\|\s*Fuente:\s*(.+))?\s*$")
RE_LISTA = re.compile(r"^(\s*)([-*]|\d+[.)])\s+(.*)$")
RE_SEPARADOR_TABLA = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


# -- utilidades de XML -----------------------------------------------------------------------------------------------

def vaciar_cuerpo(doc):
    """Quita todo el contenido y deja el sectPr final (tamano de pagina, margenes, encabezado y pie)."""
    body = doc.element.body
    for hijo in list(body):
        if hijo.tag != qn("w:sectPr"):
            body.remove(hijo)


def campo_simple(parrafo, instr: str, texto: str):
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instr)
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = texto
    r.append(t)
    fld.append(r)
    parrafo._p.append(fld)


def campo_complejo(parrafo, instr: str, texto: str):
    """Campo TOC: Word lo rellena al actualizar campos (se activa updateFields al guardar)."""
    def fld_char(tipo):
        r = OxmlElement("w:r")
        fc = OxmlElement("w:fldChar")
        fc.set(qn("w:fldCharType"), tipo)
        r.append(fc)
        return r
    parrafo._p.append(fld_char("begin"))
    r = OxmlElement("w:r")
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = instr
    r.append(it)
    parrafo._p.append(r)
    parrafo._p.append(fld_char("separate"))
    parrafo.add_run(texto).italic = True
    parrafo._p.append(fld_char("end"))


def num_pr(parrafo, num_id: str, ilvl: int):
    ppr = parrafo._p.get_or_add_pPr()
    for viejo in ppr.findall(qn("w:numPr")):
        ppr.remove(viejo)
    numpr = OxmlElement("w:numPr")
    lvl = OxmlElement("w:ilvl")
    lvl.set(qn("w:val"), str(ilvl))
    nid = OxmlElement("w:numId")
    nid.set(qn("w:val"), str(num_id))
    numpr.append(lvl)
    numpr.append(nid)
    ppr.insert(0, numpr)


class Numeracion:
    """Encuentra en la plantilla la numeracion de los titulos y un formato de vinetas y de lista numerada."""

    def __init__(self, doc):
        estilo = doc.styles[ESTILO_TITULO].element
        nid = estilo.find(qn("w:pPr")).find(qn("w:numPr")).find(qn("w:numId"))
        self.titulos = nid.get(qn("w:val"))
        self.numbering = doc.part.numbering_part.element
        abstractos = {}
        for ab in self.numbering.findall(qn("w:abstractNum")):
            lvl0 = next((l for l in ab.findall(qn("w:lvl")) if l.get(qn("w:ilvl")) == "0"), None)
            fmt = lvl0.find(qn("w:numFmt")).get(qn("w:val")) if lvl0 is not None and lvl0.find(qn("w:numFmt")) is not None else None
            abstractos[ab.get(qn("w:abstractNumId"))] = fmt
        self.vinetas = None
        self.abstracto_decimal = None
        abstracto_titulos = self._abstracto(self.titulos)
        for num in self.numbering.findall(qn("w:num")):
            ab = num.find(qn("w:abstractNumId")).get(qn("w:val"))
            if abstractos.get(ab) == "bullet" and self.vinetas is None:
                self.vinetas = num.get(qn("w:numId"))
            if abstractos.get(ab) == "decimal" and ab != abstracto_titulos and self.abstracto_decimal is None:
                self.abstracto_decimal = ab

    def _abstracto(self, num_id):
        for num in self.numbering.findall(qn("w:num")):
            if num.get(qn("w:numId")) == num_id:
                return num.find(qn("w:abstractNumId")).get(qn("w:val"))
        return None

    def lista_numerada_nueva(self):
        """Cada lista numerada empieza en 1: un w:num nuevo sobre el abstracto decimal con startOverride."""
        if self.abstracto_decimal is None:
            return None
        nuevo = str(max(int(n.get(qn("w:numId"))) for n in self.numbering.findall(qn("w:num"))) + 1)
        num = OxmlElement("w:num")
        num.set(qn("w:numId"), nuevo)
        ab = OxmlElement("w:abstractNumId")
        ab.set(qn("w:val"), self.abstracto_decimal)
        num.append(ab)
        ov = OxmlElement("w:lvlOverride")
        ov.set(qn("w:ilvl"), "0")
        so = OxmlElement("w:startOverride")
        so.set(qn("w:val"), "1")
        ov.append(so)
        num.append(ov)
        self.numbering.append(num)
        return nuevo


# -- escritura -------------------------------------------------------------------------------------------------------

class Escritor:
    def __init__(self, doc):
        self.doc = doc
        self.num = Numeracion(doc)
        sec = doc.sections[0]
        self.ancho_util = sec.page_width - sec.left_margin - sec.right_margin
        self.n_tabla = 0
        self.n_figura = 0
        self.primer_capitulo = True
        self.lista_numerada = None
        self.avisos = []
        self.desplazar_titulos = False      # borrador de capitulo: "#" es una seccion, no un capitulo

    def nota_origen(self, texto):
        p = self.doc.add_paragraph(style="Normal")
        r = p.add_run(texto)
        r.italic = True
        r.font.size = Pt(8)

    def texto_inline(self, parrafo, texto: str, tam=None):
        for trozo in RE_INLINE.split(texto):
            if not trozo:
                continue
            if trozo.startswith("**") and trozo.endswith("**"):
                run = parrafo.add_run(trozo[2:-2])
                run.bold = True
            elif trozo.startswith("`") and trozo.endswith("`"):
                run = parrafo.add_run(trozo[1:-1])
                run.font.name = "Consolas"
            elif trozo.startswith("[") and "](" in trozo:
                txt, url = trozo[1:-1].split("](", 1)
                run = parrafo.add_run(txt if txt == url else f"{txt} ({url})")
            elif trozo.startswith("*") and trozo.endswith("*") and len(trozo) > 2:
                run = parrafo.add_run(trozo[1:-1])
                run.italic = True
            else:
                run = parrafo.add_run(trozo)
            if tam:
                run.font.size = Pt(tam)
        return parrafo

    def portada(self, datos: dict):
        def linea(texto, tam, negrita=False, espacio=0):
            p = self.doc.add_paragraph(style="Normal")
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(espacio)
            r = p.add_run(texto)
            r.font.size = Pt(tam)
            r.bold = negrita
        if datos.get("proyecto"):
            linea(datos["proyecto"], 20, True, 120)
        linea(datos.get("titulo", "Manual"), 18, True, 24)
        if datos.get("subtitulo"):
            linea(datos["subtitulo"], 13, False, 6)
        if datos.get("tipo"):
            linea(datos["tipo"], 12, False, 24)
        if datos.get("presenta"):
            linea("Presenta:", 12, True, 90)
            linea(datos["presenta"], 12)
        if datos.get("tutor"):
            linea("Tutor:", 12, True, 18)
            linea(datos["tutor"], 12)
        if datos.get("fecha"):
            linea(str(datos["fecha"]), 11, False, 60)

    def indices(self):
        for titulo, instr, aviso in (
            ("Índice", 'TOC \\h \\z \\t "Titulos_capitulos,1,Titulo_punteado,2"', "Actualice los campos para ver el índice."),
            ("Índice de tablas", 'TOC \\h \\z \\c "Tabla"', "Actualice los campos para ver el índice de tablas."),
            ("Índice de figuras", 'TOC \\h \\z \\c "Figura"', "Actualice los campos para ver el índice de figuras."),
        ):
            p = self.doc.add_paragraph(style="Normal")
            p.paragraph_format.page_break_before = True
            r = p.add_run(titulo)
            r.bold = True
            r.font.size = Pt(14)
            campo_complejo(self.doc.add_paragraph(style="Normal"), instr, aviso)

    def capitulo(self, texto):
        p = self.doc.add_paragraph(style=ESTILO_CAPITULO)
        p.paragraph_format.page_break_before = True
        self.texto_inline(p, texto)

    def titulo(self, texto, nivel):
        p = self.doc.add_paragraph(style=ESTILO_TITULO)
        if nivel > 0:
            num_pr(p, self.num.titulos, nivel)
        self.texto_inline(p, texto)

    def parrafo(self, texto, cursiva=False):
        p = self.doc.add_paragraph(style="Normal")
        if cursiva:
            p.paragraph_format.left_indent = Inches(0.4)
        self.texto_inline(p, texto)
        if cursiva:
            for r in p.runs:
                r.italic = True

    def item(self, texto, numerado, nivel):
        p = self.doc.add_paragraph(style=ESTILO_LISTA)
        if numerado:
            if self.lista_numerada is None:
                self.lista_numerada = self.num.lista_numerada_nueva()
            if self.lista_numerada is not None:
                num_pr(p, self.lista_numerada, nivel)
            else:
                texto = "1. " + texto
        elif self.num.vinetas is not None:
            num_pr(p, self.num.vinetas, nivel)
        else:
            texto = "• " + texto
        self.texto_inline(p, texto)

    def codigo(self, lineas):
        for l in lineas or [""]:
            p = self.doc.add_paragraph(style=ESTILO_CODIGO)
            run = p.add_run(l if l else " ")
            run.font.name = "Consolas"
            run.font.size = Pt(9)
            p.paragraph_format.space_after = Pt(0)

    def pie(self, estilo, etiqueta, numero, descripcion, fuente):
        p = self.doc.add_paragraph(style=estilo)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run(f"{etiqueta} ")
        campo_simple(p, f" SEQ {etiqueta} \\* ARABIC ", str(numero))
        desc = descripcion.rstrip(".")
        p.add_run(f" – {desc}. Fuente: {fuente.rstrip('.')}.")

    def tabla(self, filas, descripcion, fuente):
        ncols = max(len(f) for f in filas)
        t = self.doc.add_table(rows=len(filas), cols=ncols)
        estilos = {s.name for s in self.doc.styles}
        t.style = "Table Grid" if "Table Grid" in estilos else t.style
        for i, fila in enumerate(filas):
            for j in range(ncols):
                celda = t.cell(i, j)
                celda.paragraphs[0].style = self.doc.styles["Normal"]
                self.texto_inline(celda.paragraphs[0], fila[j] if j < len(fila) else "", tam=9)
                if i == 0:
                    for r in celda.paragraphs[0].runs:
                        r.bold = True
        self.n_tabla += 1
        if not descripcion:
            self.avisos.append(f"tabla {self.n_tabla} sin linea 'Tabla: ...' (pie generico)")
            descripcion = "Tabla sin descripción"
        self.pie(ESTILO_PIE_TABLA, "Tabla", self.n_tabla, descripcion, fuente or FUENTE_DEFECTO)

    def imagen(self, ruta: Path, descripcion):
        if not ruta.exists():
            self.avisos.append(f"no existe la imagen {ruta}")
            self.parrafo(f"[Falta la imagen {ruta.name}]", cursiva=True)
            return
        p = self.doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        ancho = self.ancho_util
        try:
            from PIL import Image
            with Image.open(ruta) as im:
                px = im.size[0]
            ancho = min(ancho, Emu(int(Inches(px / 144))))   # capturas a escala 1.5 (144 ppp)
        except Exception:
            pass
        p.add_run().add_picture(str(ruta), width=ancho)
        self.n_figura += 1
        self.pie(ESTILO_PIE_FIGURA, "Figura", self.n_figura, descripcion or ruta.stem, FUENTE_DEFECTO)


def celdas(linea: str):
    linea = linea.strip()
    if linea.startswith("|"):
        linea = linea[1:]
    if linea.endswith("|"):
        linea = linea[:-1]
    return [c.strip() for c in linea.split("|")]


def convertir(escritor: Escritor, ruta_md: Path):
    lineas = ruta_md.read_text(encoding="utf-8").splitlines()
    if lineas and lineas[0].strip() == "---":                      # front matter opcional
        fin = next((i for i, l in enumerate(lineas[1:], 1) if l.strip() == "---"), 0)
        lineas = lineas[fin + 1:]
    i, parrafo = 0, []

    def cerrar_parrafo():
        if parrafo:
            escritor.parrafo(" ".join(s.strip() for s in parrafo))
            parrafo.clear()

    while i < len(lineas):
        l = lineas[i]
        s = l.strip()
        if s.startswith("```"):
            cerrar_parrafo()
            bloque, i = [], i + 1
            while i < len(lineas) and not lineas[i].strip().startswith("```"):
                bloque.append(lineas[i].rstrip())
                i += 1
            escritor.codigo(bloque)
            i += 1
            continue
        m_h = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m_h:
            cerrar_parrafo()
            escritor.lista_numerada = None
            nivel = len(m_h.group(1))
            if escritor.desplazar_titulos:
                escritor.titulo(m_h.group(2), min(nivel - 1, 2))
            elif nivel == 1:
                escritor.capitulo(m_h.group(2))
            else:
                escritor.titulo(m_h.group(2), nivel - 2)
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lineas) and RE_SEPARADOR_TABLA.match(lineas[i + 1].strip()):
            cerrar_parrafo()
            filas = [celdas(s)]
            i += 2
            while i < len(lineas) and lineas[i].strip().startswith("|"):
                filas.append(celdas(lineas[i]))
                i += 1
            while i < len(lineas) and not lineas[i].strip():
                i += 1
            desc = fuente = None
            if i < len(lineas):
                m_p = RE_PIE_TABLA.match(lineas[i].strip())
                if m_p:
                    desc, fuente = m_p.group(1), m_p.group(2)
                    i += 1
            escritor.tabla(filas, desc, fuente)
            continue
        m_i = RE_IMAGEN.match(s)
        if m_i:
            cerrar_parrafo()
            escritor.imagen((ruta_md.parent / m_i.group(2)).resolve(), m_i.group(1))
            i += 1
            continue
        m_l = RE_LISTA.match(l)
        if m_l and s:
            cerrar_parrafo()
            nivel = min(len(m_l.group(1).replace("\t", "    ")) // 2, 2)
            numerado = m_l.group(2)[0].isdigit()
            if not numerado and nivel == 0:
                escritor.lista_numerada = None
            texto = m_l.group(3)
            i += 1
            while i < len(lineas) and lineas[i].startswith("   ") and lineas[i].strip() and not RE_LISTA.match(lineas[i]):
                texto += " " + lineas[i].strip()                     # continuacion del item
                i += 1
            escritor.item(texto, numerado, nivel)
            continue
        if s.startswith(">"):
            cerrar_parrafo()
            escritor.parrafo(s.lstrip("> ").strip(), cursiva=True)
            i += 1
            continue
        if not s or re.match(r"^(-{3,}|\*{3,})$", s):
            cerrar_parrafo()
            escritor.lista_numerada = None
            i += 1
            continue
        parrafo.append(s)
        i += 1
    cerrar_parrafo()


def origen_git(ruta: Path) -> str:
    """Commit corto de HEAD y si el .md tiene cambios sin commit (el borrador no corresponde a ningun commit)."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                check=True).stdout.strip()
        sucio = subprocess.run(["git", "status", "--porcelain", "--", str(ruta)], capture_output=True, text=True,
                               check=True).stdout.strip()
        return commit + (" + cambios sin commit" if sucio else "")
    except Exception:
        return "sin git"


def registrar(registro: Path, salida: Path, fuentes: list[Path], commit: str):
    datos = yaml.safe_load(registro.read_text(encoding="utf-8")) if registro.exists() else None
    datos = datos or {}
    # Copia de lo entregado junto al borrador: docs/ no esta en git, asi que el diff contra un commit no
    # sirve para el manual de usuario; con la copia: git diff --no-index <copia> <md actual>
    copias = []
    for i, f in enumerate(fuentes):
        copia = salida.with_name(f"{salida.stem}.entregado{'' if len(fuentes) == 1 else i}.md")
        copia.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        copias.append(copia.as_posix())
    datos[salida.as_posix()] = {"fuentes": [f.as_posix() for f in fuentes], "commit": commit,
                               "fecha": date.today().isoformat(), "copias_entregadas": copias}
    registro.parent.mkdir(parents=True, exist_ok=True)
    registro.write_text("# Que version de cada .md se entrego como borrador (lo escribe md_a_docx.py --registro).\n"
                        "# Para ver que cambio desde entonces: git diff <commit> -- <fuente>\n"
                        + yaml.safe_dump(datos, allow_unicode=True, sort_keys=True), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("md", nargs="+", help="archivos .md en orden")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--portada", help="YAML con titulo, subtitulo, proyecto, tipo, presenta, tutor, fecha")
    ap.add_argument("--plantilla", default="Propuesta_PriceScraper_SS.docx")
    ap.add_argument("--capitulo", action="store_true", help="borrador de capitulo: sin portada ni indices, titulos un nivel abajo")
    ap.add_argument("--registro", help="YAML donde anotar fuente, commit y fecha del borrador entregado")
    a = ap.parse_args()

    plantilla = Path(a.plantilla)
    if not plantilla.exists():
        sys.exit(f"[docx] No encuentro la plantilla {plantilla}. Es el documento de estilos del servicio social; "
                 "pasala con --plantilla en vez de generar con otro formato.")
    doc = docx.Document(str(plantilla))
    faltan = [e for e in (ESTILO_CAPITULO, ESTILO_TITULO, ESTILO_LISTA, ESTILO_CODIGO, ESTILO_PIE_TABLA, ESTILO_PIE_FIGURA)
              if e not in {s.name for s in doc.styles}]
    if faltan:
        sys.exit(f"[docx] La plantilla no tiene los estilos {faltan}")
    vaciar_cuerpo(doc)
    esc = Escritor(doc)
    fuentes = sorted({Path(m) for m in a.md}, key=lambda p: p.name)
    commit = origen_git(fuentes[0])
    if a.capitulo:
        esc.desplazar_titulos = True
        esc.nota_origen(f"Borrador generado de {', '.join(f.as_posix() for f in fuentes)} (commit {commit}, "
                        f"{date.today().isoformat()}). Intégralo a tu documento con tu redacción; la versión técnica "
                        "de referencia es el .md del repositorio. Borra esta nota al integrarlo.")
    else:
        if a.portada:
            esc.portada(yaml.safe_load(Path(a.portada).read_text(encoding="utf-8")) or {})
        esc.indices()
    for ruta in fuentes:
        convertir(esc, ruta)
    upd = OxmlElement("w:updateFields")
    upd.set(qn("w:val"), "true")
    doc.settings.element.append(upd)
    salida = Path(a.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(salida))
    if a.registro:
        registrar(Path(a.registro), salida, fuentes, commit)

    estilos = Counter(p.style.name for p in doc.paragraphs)
    print(f"[docx] {salida}: {len(a.md)} archivo(s), {esc.n_tabla} tablas, {esc.n_figura} figuras")
    print("[docx] parrafos por estilo:", dict(estilos.most_common()))
    for aviso in esc.avisos:
        print("[docx] AVISO:", aviso)


if __name__ == "__main__":
    main()
