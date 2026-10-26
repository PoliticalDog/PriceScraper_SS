"""Herramienta de BI (no es prueba, no toca la BD). Clave flexible de la Comparativa, 25-oct-2026.

Lee el catalogo (nlp/catalogo_productos.py; MARCAS_CONOCIDAS y CATALOGO_CANONICO de nlp/normalizador.py) y escribe
las consultas de medicion en docs/bi/consultas/comparativa_claves/:
  candidatas.sql        metricas por clave (cobertura, cadenas, pares, dispersion)
  muestra_<clave>.sql   40 grupos por clave con semilla documentada, para juzgar validez a mano
  walmex.sql            sensibilidad de la clave recomendada a juntar Bodega Aurrera y Sam's con Walmart
Las consultas se corren con .claude/skills/consulta-analitica/consulta.py --archivo (solo lectura).

    venv/Scripts/python.exe tests/_herramienta_bi_claves_comparativa.py
"""
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from nlp.catalogo_productos import CATALOGO  # noqa: E402
from nlp.normalizador import CATALOGO_CANONICO, MARCAS_CONOCIDAS  # noqa: E402

SEMILLA = "bi-comparativa-20261025"
CLAVES_MUESTRA = ("k0", "ka", "kb", "kb2", "kc", "khr")   # las que se juzgaron a mano (docs/bi/metricas.md sec. 8)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


# Marcas: MARCAS_CONOCIDAS + "marcas" del catalogo + marcas que el catalogo usa como keyword de tipo.
# Fuera las ambiguas en folletos: "sol" (lentes de sol), "roma" (tomate roma), "corona" (navidena), "modelo"
# (Mod.), "salvo" (= excepto), "victoria", "ace", "xx", "george", "op", "op brand", "off".
MARCAS_KW = {
    "bimbo", "marinela", "gamesa", "oreo", "maseca", "quaker", "sabritas", "barcel", "doritos", "ruffles",
    "tostitos", "yoplait", "danonino", "lala", "alpura", "yakult", "carnation", "nescafe", "dolca", "coca cola",
    "pepsi", "herdez", "la costena", "clemente jacques", "isadora", "ariel", "tide", "downy", "fabuloso", "pinol",
    "ajax", "raid", "pedigree", "purina", "whiskas", "dog chow", "oster", "mabe", "whirlpool", "acros",
    "hamilton beach", "black decker", "atvio", "taurus", "t fal", "tfal", "cuisinart", "daewoo", "energizer",
    "duracell", "italika", "bardahl", "gonher", "armor all", "turtle wax", "crayola", "sharpie", "reyma",
    "gatorlyte", "suerox", "electrolit", "clamato", "kermato", "lego", "teka", "koblenz", "nintendo",
}
AMBIGUAS = {"sol", "roma", "corona", "modelo", "salvo", "victoria", "ace", "xx", "george", "op", "op brand", "off"}
MARCAS = sorted({norm(m) for m in MARCAS_CONOCIDAS} | {norm(m) for m in MARCAS_KW}
                | {norm(m) for d in CATALOGO.values() for m in d.get("marcas", [])})
MARCAS = [m for m in MARCAS if m and m not in AMBIGUAS]

# Tipos: keywords del catalogo salvo atributos tecnicos, marcas y rotulos que no son un tipo de producto.
NO_TIPO = {"granel", "fruta", "verdura", "manojo", "talla", "tallas", "ch eg", "ch eeg", "s xl", "s xxl",
           "pulgadas", "mpx", "en tiras", "simply basic", "faded glory", "4k uhd", "oled", "qled", "webos",
           "android tv", "soluble", "lacteo", "botana", "dulce", "postre", "streaming", "led", "tira led"}
TIPOS, _vistos = [], set()
for _cat, _datos in CATALOGO.items():
    if _cat == "atributos_tecnicos":
        continue
    for _kw in _datos["keywords"]:
        _k = norm(_kw)
        if not _k or _k in _vistos or _k in NO_TIPO or _k in MARCAS or _k in AMBIGUAS:
            continue
        _vistos.add(_k)
        TIPOS.append((_k, _cat, len(TIPOS)))

# Canonicos de catalogo "a granel": comparables entre cadenas sin marca ni tamano (precio por kg o por pieza).
# El resto de CATALOGO_CANONICO ("Refresco", "Galletas", "Smart TV"...) junta productos distintos: la clave
# refinada (kar) no agrupa un texto que sea exactamente uno de esos nombres genericos.
GRANEL = {"Pollo entero", "Pechuga de pollo", "Carne molida", "Bistec de res", "Plátano", "Manzana", "Naranja",
          "Aguacate", "Tomate", "Cebolla", "Papa", "Melón", "Papaya", "Lechuga", "Sandía", "Elote", "Chile serrano",
          "Chile jalapeño", "Brócoli", "Zanahoria"}
assert GRANEL <= set(CATALOGO_CANONICO), GRANEL - set(CATALOGO_CANONICO)
GENERICOS = sorted(set(CATALOGO_CANONICO) - GRANEL)


def valores(filas) -> str:
    def lit(v):
        return str(v) if isinstance(v, int) else "'" + str(v).replace("'", "''") + "'"
    return ",\n        ".join("(" + ", ".join(lit(v) for v in f) + ")" for f in filas)


def normaliza(expr: str) -> str:
    """Expresion SQL de la normalizacion de texto (clave a). expr = texto de entrada."""
    return r"""regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
        regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
            translate(lower(""" + expr + r"""), 'áàäâãéèëêíìïîóòöôõúùüûñç', 'aaaaaeeeeiiiiooooouuuunc'),
            '(\d),(\d{3})\y', '\1\2', 'g'),
            '(\d),(\d{1,2})\y', '\1.\2', 'g'),
            '(\d+(?:\.\d+)?)\s*(?:kilogramos?|kilos?|kgs?)\y', '\1kg', 'g'),
            '(\d+(?:\.\d+)?)\s*(?:gramos?|grms?|grs?|gr|g)\y', '\1g', 'g'),
            '(\d+(?:\.\d+)?)\s*(?:mililitros?|mls?)\y', '\1ml', 'g'),
            '(\d+(?:\.\d+)?)\s*(?:litros?|lts?|lt|l)\y', '\1l', 'g'),
            '(\d+)\s*(?:piezas?|pzas?|pzs?|pz)\y', '\1pza', 'g'),
            '\y(?:kilogramos?|kilos?|kgs?)\y', 'kg', 'g'),
            '\y(?:piezas?|pzas?|pzs?)\y', 'pza', 'g'),
            '[^a-z0-9.]+', ' ', 'g'),
            '(?<![0-9])\.|\.(?![0-9])', ' ', 'g')"""


# Refinada (r): "medio kilo" y "1/2 kg" = 500 g antes de normalizar
ENTRADA_R = (r"regexp_replace(regexp_replace(lower(texto_norm), '\ymedio\s+(?:kilos?|kgs?)\y', '500 g', 'g'), "
             r"'\y1\s*/\s*2\s*(?:kilos?|kgs?)\y', '500 g', 'g')")
STOP = r"\y(?:de|del|la|las|el|los|con|en|para|y|o|0|a|al|por|un|una|e|c|u)\y"
# Refinada: + relleno de folleto ("Cada Uno", "Ejemplo:", "Precio", "Oferta", "Pack" suelto no)
STOP_R = r"\y(?:de|del|la|las|el|los|con|en|para|y|o|0|a|al|por|un|una|e|c|u|cada|uno|ejemplo|precio|oferta)\y"
UNIDAD_TOK = r"^([0-9.]+(kg|g|ml|l|pza)?|kg|g|ml|l|pza)$"
PRES_SQL = r"""CASE r[2]
               WHEN 'kg'  THEN 'g:'   || ROUND(r[1]::numeric * 1000)
               WHEN 'g'   THEN 'g:'   || ROUND(r[1]::numeric)
               WHEN 'l'   THEN 'ml:'  || ROUND(r[1]::numeric * 1000)
               WHEN 'ml'  THEN 'ml:'  || ROUND(r[1]::numeric)
               WHEN 'pza' THEN 'pza:' || ROUND(r[1]::numeric)
               ELSE CASE WHEN t1 ~ '\ykg\y' THEN 'por_kg' WHEN t1 ~ '\ypza\y' THEN 'por_pza' END
           END"""
PRES_RE = r"(\d+(?:\.\d+)?)(kg|g|ml|l|pza)\y"


def bloque_texto(suf: str, entrada: str, stop: str, tipo_orden: str) -> str:
    """CTEs n1/tok/ka/tipo/marca/pres de una version de reglas (suf '' = v1, '_r' = refinada)."""
    return f"""
n1{suf} AS (
    SELECT texto_norm, ' ' || btrim({normaliza(entrada)}) || ' ' AS t1
    FROM txt
),
tok{suf} AS (
    SELECT n.texto_norm, w
    FROM n1{suf} n, regexp_split_to_table(btrim(regexp_replace(n.t1, '{stop}', ' ', 'g')), '\\s+') AS w
    WHERE w <> ''
),
ka{suf} AS (
    SELECT texto_norm,
           string_agg(DISTINCT w, ' ' ORDER BY w) AS clave,
           COUNT(DISTINCT w) FILTER (WHERE w !~ '{UNIDAD_TOK}') AS contenido,
           MAX(w) FILTER (WHERE w !~ '{UNIDAD_TOK}') AS palabra
    FROM tok{suf}
    GROUP BY texto_norm
),
tipo{suf} AS (
    SELECT DISTINCT ON (n.texto_norm) n.texto_norm, ti.kw AS tipo
    FROM n1{suf} n JOIN tipos ti ON strpos(n.t1, ' ' || ti.kw) > 0 AND n.t1 ~ ('\\y' || ti.kw || '\\y')
    ORDER BY n.texto_norm, {tipo_orden}
),
marca{suf} AS (
    SELECT DISTINCT ON (n.texto_norm) n.texto_norm, m.marca
    FROM n1{suf} n JOIN marcas m ON strpos(n.t1, ' ' || m.marca) > 0 AND n.t1 ~ ('\\y' || m.marca || '\\y')
    ORDER BY n.texto_norm, length(m.marca) DESC, m.marca
),
pres{suf} AS (
    SELECT texto_norm, {PRES_SQL} AS pres
    FROM (SELECT texto_norm, t1, regexp_match(t1, '{PRES_RE}') AS r FROM n1{suf}) s
),"""


def comun(cadenas_extra: str = "") -> str:
    return f"""-- GENERADO por tests/_herramienta_bi_claves_comparativa.py (BI, 25-oct-2026) desde nlp/catalogo_productos.py
-- y nlp/normalizador.py. No editar a mano: regenerar si cambia el catalogo. Ver docs/bi/metricas.md seccion 8.
-- Base: registros del dashboard (PRECIO, valor y texto_norm no nulos) con 1 <= valor <= 100,000.
-- cadena: Soriana Hiper + Soriana Mercado = soriana; Walmart + Walmart Express = walmart; el resto, su tienda.
-- Grupo comparable = misma clave en >= 2 cadenas. Claves (NULL = el registro no entra en esa clave):
--   k0  texto_norm | categoria_nlp                           (la de v_comparativa_precios)
--   ka  texto normalizado: minusculas, sin acentos ni puntuacion, unidades unificadas (1 Kg = 1kg = 1 kilo),
--       sin palabras de relleno, palabras unicas y ordenadas. Exige >= 2 palabras de contenido (no unidad ni
--       numero) o 1 palabra que sea fruta/verdura del catalogo.
--   kb  tipo de producto del catalogo (keyword mas larga) | marca | presentacion (cantidad en g, ml o pza; o
--       por_kg / por_pza). Exige las tres.
--   kb2 tipo | presentacion (sin marca). Exige las dos.
--   kc  producto canonico de catalogo (metodo exacto/fuzzy/fuzzy_bajo del PRECIO o, si no, de su fila PRODUCTO)
--       | presentacion. Exige las dos.
--   kc0 producto canonico de catalogo solo (como agrupaba la Comparativa antes de la union de lineas).
--   kh  hibrida v1: 'B| ' || kb si kb existe; si no, 'A| ' || ka.
--   kar ka refinada: "medio kilo"/"1/2 kg" = 500 g; relleno extra (cada, uno, ejemplo, precio, oferta); NO agrupa
--       un texto que sea exactamente un nombre generico de CATALOGO_CANONICO (Refresco, Galletas, Smart TV...),
--       salvo los de granel (frutas, verduras, pollo, carne molida, bistec).
--   kbr kb refinada: tipo = keyword del catalogo que aparece PRIMERO en el texto (empate: la mas larga);
--       presentacion con "medio kilo" = 500 g.
--   khr hibrida refinada: 'B| ' || kbr si existe; si no, 'A| ' || kar.     <- RECOMENDADA
WITH cad(slug, cadena) AS (
    VALUES ('soriana_hiper', 'soriana'), ('soriana_mercado', 'soriana'),
           ('walmart', 'walmart'), ('walmart_express', 'walmart'){cadenas_extra}
),
tipos(kw, cat, ord) AS (
    VALUES
        {valores(TIPOS)}
),
marcas(marca) AS (
    VALUES
        {valores([(m,) for m in MARCAS])}
),
genericos(nombre) AS (
    VALUES
        {valores([(g,) for g in GENERICOS])}
),
reg AS (
    SELECT e.id, e.texto_norm, COALESCE(e.categoria_nlp, '') AS cat, e.valor, e.tienda_id, e.folleto_id,
           COALESCE(cad.cadena, t.slug) AS cadena,
           CASE WHEN e.metodo_norm IN ('exacto', 'fuzzy', 'fuzzy_bajo') THEN e.texto_norm
                WHEN pr.metodo_norm IN ('exacto', 'fuzzy', 'fuzzy_bajo') THEN pr.texto_norm END AS canon
    FROM extracciones e
    JOIN tiendas t ON t.id = e.tienda_id
    LEFT JOIN cad ON cad.slug = t.slug
    LEFT JOIN extracciones pr ON pr.id = e.producto_extraccion_id      -- N:1, no duplica (28,735 = 28,735)
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
      AND e.valor BETWEEN 1 AND 100000
),
txt AS (SELECT DISTINCT texto_norm FROM reg),{bloque_texto('', 'texto_norm', STOP, 'length(ti.kw) DESC, ti.ord')}{
        bloque_texto('_r', ENTRADA_R, STOP_R, "strpos(n.t1, ' ' || ti.kw), length(ti.kw) DESC, ti.ord")}
txt_claves AS (   -- 1 fila por texto_norm
    SELECT x.texto_norm,
           CASE WHEN ka.contenido >= 2
                  OR (ka.contenido = 1 AND ka.palabra IN (SELECT kw FROM tipos WHERE cat = 'frutas_verduras'))
                THEN ka.clave END AS ka,
           tipo.tipo, marca.marca, pres.pres,
           CASE WHEN (ka_r.contenido >= 2
                      OR (ka_r.contenido = 1 AND ka_r.palabra IN (SELECT kw FROM tipos WHERE cat = 'frutas_verduras')))
                 AND x.texto_norm NOT IN (SELECT nombre FROM genericos)
                THEN ka_r.clave END AS kar,
           tipo_r.tipo AS tipo_r, marca_r.marca AS marca_r, pres_r.pres AS pres_r
    FROM txt x
    LEFT JOIN ka      ON ka.texto_norm = x.texto_norm
    LEFT JOIN tipo    ON tipo.texto_norm = x.texto_norm
    LEFT JOIN marca   ON marca.texto_norm = x.texto_norm
    LEFT JOIN pres    ON pres.texto_norm = x.texto_norm
    LEFT JOIN ka_r    ON ka_r.texto_norm = x.texto_norm
    LEFT JOIN tipo_r  ON tipo_r.texto_norm = x.texto_norm
    LEFT JOIN marca_r ON marca_r.texto_norm = x.texto_norm
    LEFT JOIN pres_r  ON pres_r.texto_norm = x.texto_norm
),
reg_claves AS (   -- 1 fila por registro
    SELECT r.id, r.texto_norm, r.valor, r.tienda_id, r.folleto_id, r.cadena,
           r.texto_norm || ' | ' || r.cat                                           AS k0,
           c.ka,
           CASE WHEN c.tipo IS NOT NULL AND c.marca IS NOT NULL AND c.pres IS NOT NULL
                THEN c.tipo || ' | ' || c.marca || ' | ' || c.pres END              AS kb,
           CASE WHEN c.tipo IS NOT NULL AND c.pres IS NOT NULL
                THEN c.tipo || ' | ' || c.pres END                                  AS kb2,
           CASE WHEN r.canon IS NOT NULL AND c.pres IS NOT NULL
                THEN r.canon || ' | ' || c.pres END                                 AS kc,
           r.canon                                                                  AS kc0,
           c.kar,
           CASE WHEN c.tipo_r IS NOT NULL AND c.marca_r IS NOT NULL AND c.pres_r IS NOT NULL
                THEN c.tipo_r || ' | ' || c.marca_r || ' | ' || c.pres_r END        AS kbr
    FROM reg r JOIN txt_claves c ON c.texto_norm = r.texto_norm
),
largo AS (        -- (clave_nombre, clave) por registro
    SELECT rc.id, rc.texto_norm, rc.valor, rc.tienda_id, rc.folleto_id, rc.cadena, k.nombre, k.clave
    FROM reg_claves rc
    CROSS JOIN LATERAL (VALUES ('k0', rc.k0), ('ka', rc.ka), ('kb', rc.kb), ('kb2', rc.kb2), ('kc', rc.kc),
                               ('kc0', rc.kc0),
                               ('kh', CASE WHEN rc.kb IS NOT NULL THEN 'B| ' || rc.kb
                                           WHEN rc.ka IS NOT NULL THEN 'A| ' || rc.ka END),
                               ('kar', rc.kar), ('kbr', rc.kbr),
                               ('khr', CASE WHEN rc.kbr IS NOT NULL THEN 'B| ' || rc.kbr
                                            WHEN rc.kar IS NOT NULL THEN 'A| ' || rc.kar END)) AS k(nombre, clave)
    WHERE k.clave IS NOT NULL
),
grp AS (          -- grupos comparables: >= 2 cadenas
    SELECT nombre, clave, COUNT(*) AS registros, COUNT(DISTINCT tienda_id) AS tiendas,
           COUNT(DISTINCT cadena) AS cadenas, COUNT(DISTINCT texto_norm) AS textos
    FROM largo
    GROUP BY nombre, clave
    HAVING COUNT(DISTINCT cadena) >= 2
),
med AS (          -- mediana por cadena dentro del grupo
    SELECT l.nombre, l.clave, l.cadena, COUNT(*) AS n,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY l.valor) AS mediana
    FROM largo l JOIN grp g ON g.nombre = l.nombre AND g.clave = l.clave
    GROUP BY l.nombre, l.clave, l.cadena
),
disp AS (
    SELECT nombre, clave, MAX(mediana) / NULLIF(MIN(mediana), 0) AS ratio_medianas
    FROM med GROUP BY nombre, clave
)"""


METRICAS_FINAL = """,
pares AS (
    SELECT DISTINCT a.nombre, a.cadena AS ca, b.cadena AS cb
    FROM med a JOIN med b ON b.nombre = a.nombre AND b.clave = a.clave AND b.cadena > a.cadena
),
k0_regs AS (      -- registros que ya estan en un grupo de >= 2 cadenas con la clave actual
    SELECT DISTINCT l.id FROM largo l JOIN grp g ON g.nombre = l.nombre AND g.clave = l.clave WHERE l.nombre = 'k0'
),
cob AS (
    SELECT l.nombre, COUNT(DISTINCT l.id) AS registros,
           COUNT(DISTINCT l.id) FILTER (WHERE NOT EXISTS (SELECT 1 FROM k0_regs k WHERE k.id = l.id))
               AS registros_nuevos_vs_k0
    FROM largo l JOIN grp g ON g.nombre = l.nombre AND g.clave = l.clave
    GROUP BY l.nombre
),
elegibles AS (SELECT nombre, COUNT(*) AS registros_con_clave FROM largo GROUP BY nombre)
SELECT g.nombre AS clave,
       el.registros_con_clave,
       COUNT(*)                                             AS grupos_2cad,
       cob.registros                                        AS registros_2cad,
       cob.registros_nuevos_vs_k0,
       COUNT(*) FILTER (WHERE g.cadenas >= 3)               AS grupos_3cad,
       (SELECT COUNT(*) FROM pares p WHERE p.nombre = g.nombre) AS pares_cadenas,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY d.ratio_medianas)::numeric, 2) AS mediana_ratio,
       ROUND(100.0 * COUNT(*) FILTER (WHERE d.ratio_medianas > 2) / COUNT(*), 1)        AS pct_ratio_gt2,
       ROUND(100.0 * COUNT(*) FILTER (WHERE g.textos >= 2) / COUNT(*), 1)                AS pct_grupos_multitexto
FROM grp g
JOIN disp d ON d.nombre = g.nombre AND d.clave = g.clave
JOIN cob ON cob.nombre = g.nombre
JOIN elegibles el ON el.nombre = g.nombre
GROUP BY g.nombre, cob.registros, cob.registros_nuevos_vs_k0, el.registros_con_clave
ORDER BY g.nombre
"""

MUESTRA_FINAL = f""",
muestra AS (      -- 40 grupos por clave, orden pseudoaleatorio reproducible: md5(clave_nombre|clave|semilla)
    SELECT nombre, clave, registros, cadenas, textos,
           ROW_NUMBER() OVER (PARTITION BY nombre ORDER BY md5(nombre || '|' || clave || '|{SEMILLA}')) AS rn
    FROM grp
    WHERE nombre = :NOMBRE
),
det AS (          -- por cadena: n, mediana y hasta 3 textos distintos
    SELECT m.nombre, m.clave, md.cadena, md.n, md.mediana,
           (SELECT string_agg(x, ' / ') FROM (SELECT DISTINCT l.texto_norm AS x FROM largo l
             WHERE l.nombre = m.nombre AND l.clave = m.clave AND l.cadena = md.cadena ORDER BY 1 LIMIT 3) s) AS textos
    FROM muestra m JOIN med md ON md.nombre = m.nombre AND md.clave = m.clave
    WHERE m.rn <= 40
)
SELECT m.rn, m.clave, m.registros AS regs, m.cadenas AS cad, ROUND(d.ratio_medianas::numeric, 2) AS ratio,
       string_agg(det.cadena || ' (' || det.n || ', $' || ROUND(det.mediana::numeric, 2) || '): ' || det.textos,
                  ' || ' ORDER BY det.cadena) AS detalle
FROM muestra m
JOIN disp d ON d.nombre = m.nombre AND d.clave = m.clave
JOIN det ON det.nombre = m.nombre AND det.clave = m.clave
WHERE m.rn <= 40
GROUP BY m.rn, m.clave, m.registros, m.cadenas, d.ratio_medianas
ORDER BY m.rn
"""

# Sensibilidad: Walmex (Bodega Aurrera y Sam's Club en la cadena walmart). Solo la clave recomendada.
WALMEX_FINAL = """
SELECT nombre AS clave, COUNT(*) AS grupos_2cad, SUM(registros) AS registros_2cad,
       COUNT(*) FILTER (WHERE cadenas >= 3) AS grupos_3cad
FROM grp
WHERE nombre IN ('k0', 'khr')
GROUP BY nombre
ORDER BY nombre
"""


# Potencial de una tabla de equivalencias (clave d): textos distintos de cadenas distintas con el mismo tipo y la
# misma presentacion (o ambas sin presentacion) y similitud de trigramas (pg_trgm) >= 0.6 entre sus claves kar.
# Solo mide candidatos; la tabla real requeriria revision humana.
SIMILARES_BASE = """,
txt_cad AS (      -- clave kar x cadena con su tipo y presentacion refinados
    SELECT DISTINCT rc.kar, rc.cadena, c.tipo_r, c.pres_r
    FROM reg_claves rc JOIN txt_claves c ON c.texto_norm = rc.texto_norm
    WHERE rc.kar IS NOT NULL AND c.tipo_r IS NOT NULL
),
pares_sim AS (
    SELECT a.kar AS kar_a, b.kar AS kar_b, a.cadena AS cad_a, b.cadena AS cad_b, a.tipo_r, a.pres_r,
           similarity(a.kar, b.kar) AS sim
    FROM txt_cad a
    JOIN txt_cad b ON b.tipo_r = a.tipo_r AND b.pres_r IS NOT DISTINCT FROM a.pres_r
                  AND b.cadena <> a.cadena AND b.kar > a.kar
    WHERE similarity(a.kar, b.kar) >= 0.6
)"""

SIMILARES_RESUMEN = SIMILARES_BASE + """,
ya AS (           -- claves kar que ya forman un grupo de >= 2 cadenas (un par entre dos de ellas no aporta)
    SELECT DISTINCT clave FROM grp WHERE nombre = 'kar'
)
SELECT COUNT(*) AS pares, COUNT(*) FILTER (WHERE sim >= 0.8) AS pares_sim_080,
       COUNT(DISTINCT kar_a) + COUNT(DISTINCT kar_b) AS claves_involucradas_aprox,
       COUNT(*) FILTER (WHERE kar_a NOT IN (SELECT clave FROM ya) AND kar_b NOT IN (SELECT clave FROM ya))
           AS pares_nuevos
FROM pares_sim
"""

SIMILARES_MUESTRA = SIMILARES_BASE + f"""
SELECT ROW_NUMBER() OVER (ORDER BY md5(kar_a || '|' || kar_b || '|{SEMILLA}')) AS rn,
       ROUND(sim::numeric, 2) AS sim, tipo_r, pres_r, cad_a, kar_a, cad_b, kar_b
FROM pares_sim
ORDER BY md5(kar_a || '|' || kar_b || '|{SEMILLA}')
LIMIT 40
"""


# Diferencias ka -> khr (censo, no muestra): grupos de >= 2 cadenas que estan en una clave y no en la otra.
# Para comparar textos: la clave khr sin el prefijo 'A| ' es la kar.
DIFERENCIAS = """,
g_ka AS (SELECT clave, registros, cadenas FROM grp WHERE nombre = 'ka'),
g_khr AS (SELECT CASE WHEN clave LIKE 'A| %' THEN substr(clave, 4) ELSE clave END AS clave, clave AS clave_khr,
                 registros, cadenas FROM grp WHERE nombre = 'khr')
SELECT 'solo_ka' AS lado, a.clave, a.registros, a.cadenas,
       (SELECT LEFT(string_agg(DISTINCT l.texto_norm, ' / '), 200) FROM largo l
         WHERE l.nombre = 'ka' AND l.clave = a.clave) AS textos
FROM g_ka a WHERE NOT EXISTS (SELECT 1 FROM g_khr h WHERE h.clave = a.clave)
UNION ALL
SELECT 'solo_khr', h.clave_khr, h.registros, h.cadenas,
       (SELECT LEFT(string_agg(DISTINCT l.texto_norm || ' [' || l.cadena || ']', ' / '), 300) FROM largo l
         WHERE l.nombre = 'khr' AND l.clave = h.clave_khr)
FROM g_khr h WHERE NOT EXISTS (SELECT 1 FROM g_ka a WHERE a.clave = h.clave)
ORDER BY 1, 3 DESC
"""


# Dispersion de la clave recomendada: que cadena pone la mediana mas alta en los grupos con ratio > 2 y > 10
# (senal de precio mal leido, p. ej. centavos pegados "$2189" = $21.89).
DISPERSION = """,
top AS (
    SELECT DISTINCT ON (m.clave) m.clave, m.cadena AS cadena_max, d.ratio_medianas
    FROM med m JOIN disp d ON d.nombre = m.nombre AND d.clave = m.clave
    WHERE m.nombre = 'khr'
    ORDER BY m.clave, m.mediana DESC
)
SELECT cadena_max, COUNT(*) AS grupos, COUNT(*) FILTER (WHERE ratio_medianas > 2) AS ratio_gt2,
       COUNT(*) FILTER (WHERE ratio_medianas > 10) AS ratio_gt10,
       COUNT(*) FILTER (WHERE ratio_medianas BETWEEN 50 AND 200) AS ratio_50_200
FROM top
GROUP BY cadena_max
ORDER BY grupos DESC
"""


# Validacion independiente del conteo (otro camino: EXISTS de un registro de otra cadena con la misma clave, en
# lugar de GROUP BY ... HAVING COUNT(DISTINCT cadena) >= 2). Debe dar lo mismo que candidatas.sql.
VALIDACION = """
SELECT l.nombre AS clave,
       COUNT(DISTINCT l.clave) AS grupos_2cad,
       COUNT(*) AS registros_2cad
FROM largo l
WHERE l.nombre IN ('k0', 'ka', 'kar', 'kbr', 'khr')
  AND EXISTS (SELECT 1 FROM largo o WHERE o.nombre = l.nombre AND o.clave = l.clave AND o.cadena <> l.cadena)
GROUP BY l.nombre
ORDER BY l.nombre
"""


FRUTAS = [k for k, c, _ in TIPOS if c == "frutas_verduras"]


def arreglo(xs) -> str:
    return "ARRAY[" + ", ".join("'" + x.replace("'", "''") + "'" for x in xs) + "]"


def cuerpo_clave(expr: str) -> str:
    """Clave kar de un texto (expr) como subconsulta escalar: NULL si no es comparable."""
    entrada = ENTRADA_R.replace("texto_norm", expr)
    return f"""(
    WITH n AS (SELECT ' ' || btrim({normaliza(entrada)}) || ' ' AS t1),
    tok AS (
        SELECT w FROM n, regexp_split_to_table(btrim(regexp_replace(n.t1, '{STOP_R}', ' ', 'g')), '\\s+') AS w
        WHERE w <> ''
    ),
    k AS (
        SELECT string_agg(DISTINCT w, ' ' ORDER BY w) AS clave,
               COUNT(DISTINCT w) FILTER (WHERE w !~ '{UNIDAD_TOK}') AS contenido,
               MAX(w) FILTER (WHERE w !~ '{UNIDAD_TOK}') AS palabra
        FROM tok
    )
    SELECT CASE
               WHEN {expr} = ANY ({arreglo(GENERICOS)}) THEN NULL
               WHEN contenido >= 2 OR (contenido = 1 AND palabra = ANY ({arreglo(FRUTAS)})) THEN clave
           END
    FROM k
)"""


def cuerpo_vista(fuente_clave: str, fuente_cadena: str, join_cadena: str) -> str:
    return f"""WITH base AS (
    SELECT e.id, {fuente_clave} AS clave, e.texto_norm, e.categoria_nlp, e.valor, e.tienda_id,
           t.nombre AS tienda, {fuente_cadena} AS cadena
    FROM extracciones e
    JOIN tiendas t ON t.id = e.tienda_id{join_cadena}
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
      AND e.valor BETWEEN 1 AND 100000
),
grp AS (
    SELECT clave FROM base WHERE clave IS NOT NULL GROUP BY clave HAVING COUNT(DISTINCT cadena) >= 2
),
por_cadena AS (
    SELECT b.clave, b.cadena, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.valor) AS mediana
    FROM base b JOIN grp USING (clave)
    GROUP BY b.clave, b.cadena
),
disp AS (
    SELECT clave, MAX(mediana) / NULLIF(MIN(mediana), 0) AS ratio_medianas FROM por_cadena GROUP BY clave
)
SELECT MIN(b.id)                                                       AS id,   -- PK para Django (managed=False)
       b.clave                                                         AS clave,
       MODE() WITHIN GROUP (ORDER BY b.texto_norm)                     AS producto,
       COUNT(DISTINCT b.texto_norm)                                    AS num_textos,
       MODE() WITHIN GROUP (ORDER BY NULLIF(BTRIM(b.categoria_nlp), '')) AS categoria,
       MIN(b.valor)                                                    AS precio_min,
       MAX(b.valor)                                                    AS precio_max,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.valor)::numeric, 2) AS precio_mediana,
       ROUND(d.ratio_medianas::numeric, 2)                             AS ratio_medianas_cadena,
       (d.ratio_medianas > 10)                                         AS precio_sospechoso,
       COUNT(*)                                                        AS num_registros,
       COUNT(DISTINCT b.tienda_id)                                     AS num_tiendas,
       COUNT(DISTINCT b.cadena)                                        AS num_cadenas,
       STRING_AGG(DISTINCT b.tienda, ', ' ORDER BY b.tienda)           AS tiendas
FROM base b
JOIN grp USING (clave)
JOIN disp d USING (clave)
GROUP BY b.clave, d.ratio_medianas"""


PROPUESTA = f"""-- PROPUESTA (no aplicada) BI 25-oct-2026: clave flexible de la Comparativa, opcion 1 (SQL puro, sin recarga).
-- GENERADO por tests/_herramienta_bi_claves_comparativa.py: las listas (84 genericos de CATALOGO_CANONICO y
-- {len(FRUTAS)} frutas/verduras de nlp/catalogo_productos.py) salen del catalogo; regenerar si cambia.
-- La aplica la persona (DDL). Medicion previa sin crear nada: comparativa_claves/propuesta_inline.sql
-- (debe dar 132 grupos y 1,343 registros con los datos del 25-oct-2026). Ver docs/bi/metricas.md seccion 8.
-- No se ejecuta con consulta.py (solo acepta SELECT).

-- 1) Cadena de cada tienda (hoy no existe). NULL = la tienda es su propia cadena.
ALTER TABLE tiendas ADD COLUMN IF NOT EXISTS cadena VARCHAR(50);
UPDATE tiendas SET cadena = 'soriana' WHERE slug IN ('soriana_hiper', 'soriana_mercado');
UPDATE tiendas SET cadena = 'walmart' WHERE slug IN ('walmart', 'walmart_express');
-- Decision de la persona: Bodega Aurrera y Sam's Club quedan como cadena propia (otro formato y otra politica de
-- precio). Para juntarlas con Walmart: UPDATE tiendas SET cadena = 'walmart' WHERE slug IN ('bodega_aurrera',
-- 'sam''s_club');  (con la clave recomendada quita 4 grupos: 140 -> 136).

-- 2) Clave de comparacion del texto (kar): minusculas, sin acentos ni puntuacion, unidades unificadas
--    (1 Kg = 1kg = 1 kilo; medio kilo = 500 g), sin relleno, palabras unicas y ordenadas. NULL si el texto es
--    un generico de catalogo (Refresco, Galletas, Smart TV...) o no tiene >= 2 palabras de contenido (salvo
--    una fruta/verdura sola: "Pepino", "Jicama").
CREATE OR REPLACE FUNCTION clave_comparativa(p_texto text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
SELECT {cuerpo_clave('p_texto')}
$$;

-- 3) Vista nueva (la actual v_comparativa_precios no se toca hasta que la persona apruebe cambiar el panel).
CREATE OR REPLACE VIEW v_comparativa_precios_v2 AS
{cuerpo_vista('clave_comparativa(e.texto_norm)', 'COALESCE(t.cadena, t.slug)', '')};

COMMENT ON VIEW v_comparativa_precios_v2 IS
    'Comparativa por clave flexible (clave_comparativa del texto) en >= 2 cadenas. Ver docs/bi/metricas.md sec. 8.';

-- 4) Validacion tras crearla (debe cuadrar con comparativa_claves/candidatas.sql, clave kar):
-- SELECT COUNT(*) AS grupos, SUM(num_registros) AS registros FROM v_comparativa_precios_v2;   -- 132 | 1343
"""

PROPUESTA_INLINE = f"""-- Medicion de la vista propuesta (comparativa_clave_flexible_propuesta.sql) SIN crearla: misma consulta con la
-- funcion y la cadena en linea. GENERADO por tests/_herramienta_bi_claves_comparativa.py. Esperado (25-oct-2026):
-- 132 grupos y 1,343 registros (= clave kar de candidatas.sql).
WITH cad(slug, cadena) AS (
    VALUES ('soriana_hiper', 'soriana'), ('soriana_mercado', 'soriana'),
           ('walmart', 'walmart'), ('walmart_express', 'walmart')
),
vista AS (
{cuerpo_vista(cuerpo_clave('e.texto_norm'), 'COALESCE(cad.cadena, t.slug)', chr(10) + '    LEFT JOIN cad ON cad.slug = t.slug')}
)
SELECT COUNT(*) AS grupos, SUM(num_registros) AS registros, SUM(num_textos) AS textos,
       COUNT(*) FILTER (WHERE num_cadenas >= 3) AS grupos_3cad,
       COUNT(*) FILTER (WHERE precio_sospechoso) AS grupos_precio_sospechoso
FROM vista
"""


def main() -> None:
    dest = RAIZ / "docs" / "bi" / "consultas" / "comparativa_claves"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "candidatas.sql").write_text(comun() + METRICAS_FINAL, encoding="utf-8")
    for nombre in CLAVES_MUESTRA:
        (dest / f"muestra_{nombre}.sql").write_text(
            comun() + MUESTRA_FINAL.replace(":NOMBRE", f"'{nombre}'"), encoding="utf-8")
    walmex = ",\n           ('bodega_aurrera', 'walmart'), ('sam''s_club', 'walmart')"
    (dest / "walmex.sql").write_text(comun(walmex) + WALMEX_FINAL, encoding="utf-8")
    (dest / "diferencias_ka_khr.sql").write_text(comun() + DIFERENCIAS, encoding="utf-8")
    (dest / "dispersion_khr.sql").write_text(comun() + DISPERSION, encoding="utf-8")
    (dest / "validacion.sql").write_text(comun() + VALIDACION, encoding="utf-8")
    (dest / "propuesta_inline.sql").write_text(PROPUESTA_INLINE, encoding="utf-8")
    (dest.parent / "comparativa_clave_flexible_propuesta.sql").write_text(PROPUESTA, encoding="utf-8")
    (dest / "similares_resumen.sql").write_text(comun() + SIMILARES_RESUMEN, encoding="utf-8")
    (dest / "similares_muestra.sql").write_text(comun() + SIMILARES_MUESTRA, encoding="utf-8")
    print(f"tipos={len(TIPOS)} marcas={len(MARCAS)} genericos={len(GENERICOS)} -> {dest}")


if __name__ == "__main__":
    main()
