"""
OCR experimental en CPU sobre las paginas del GT de dev, para medir un cambio de vision/preprocessor.py
o vision/ocr_engine.py sin tocar los ocr_resultado.json de produccion.

    python -m evaluador ocr --nombre base_heb --tienda heb             (codigo actual = base)
    ... editar preprocessor.py / ocr_engine.py ...
    python -m evaluador ocr --nombre cambio_heb --tienda heb
    python -m evaluador correr --ocr-exp base_heb     /   --ocr-exp cambio_heb
    python -m evaluador comparar <run base_heb> <run cambio_heb>

La base TIENE que correrse tambien en CPU con este comando: EasyOCR en CPU y en GPU no da
exactamente lo mismo, y comparar contra el OCR de produccion (GPU) mezclaria hardware con cambio.
Mismo formato que probar_vision.procesar_carpeta, solo con las paginas del GT.
"""
import hashlib
import json
import logging
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from . import splits
from .gt import FUENTE_GT, PaginaGT, cargar_gt

logger = logging.getLogger(__name__)

RAIZ_OCR_EXP = Path("data/processed/_eval/ocr_exp")
DATA_RAW = Path("data/raw")
ARCHIVOS_OCR = (Path("vision/preprocessor.py"), Path("vision/ocr_engine.py"))
MOTOR = "easyocr"


def version_ocr() -> str:
    h = hashlib.sha256()
    for archivo in ARCHIVOS_OCR:
        h.update(archivo.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


def carpeta_exp(nombre: str) -> Path:
    if not nombre or any(c in nombre for c in "/\\.:") or nombre != nombre.strip():
        raise ValueError(f"Nombre de experimento invalido: {nombre!r} (sin / \\ . :)")
    return RAIZ_OCR_EXP / nombre


def paginas_objetivo(tienda: str | None, max_paginas: int | None) -> list[PaginaGT]:
    """Paginas del GT de dev con al menos un precio (las unicas que el evaluador mide)."""
    paginas = [p for p in splits.filtrar(cargar_gt(), "dev", splits.cargar())
               if any(a.precio is not None for a in p.articulos)]
    if tienda:
        paginas = [p for p in paginas if p.tienda == tienda]
    return paginas[:max_paginas] if max_paginas else paginas


def correr_ocr(nombre: str, tienda: str | None = None, max_paginas: int | None = None,
               perfil: str | None = None, resolucion: int | None = None, forzar: bool = False) -> Path:
    import cv2
    from vision.ocr_engine import OCREngine
    from vision.preprocessor import obtener_preprocesador, perfil_para_tienda, resolucion_para_tienda

    raiz = carpeta_exp(nombre)
    meta_ruta = raiz / "meta.json"
    version = version_ocr()
    if meta_ruta.exists():
        previa = json.load(open(meta_ruta, encoding="utf-8"))
        if previa["version_ocr"] != version and not forzar:
            raise RuntimeError(f"{raiz} se genero con otro codigo de OCR ({previa['version_ocr']} vs {version}). "
                               "Usa otro --nombre o --forzar.")

    por_folleto = defaultdict(list)
    for p in paginas_objetivo(tienda, max_paginas):
        por_folleto[(p.tienda, p.folleto)].append(p.pagina)
    total = sum(len(v) for v in por_folleto.values())
    print(f"OCR experimental '{nombre}' en CPU: {total} paginas de {len(por_folleto)} folletos (version OCR {version})")

    ocr = OCREngine(idiomas=["es", "en"], usar_gpu=False)
    hechas, inicio = 0, time.time()
    for (t, folleto), nombres in sorted(por_folleto.items()):
        perfil_t = perfil or perfil_para_tienda(t)
        pre = obtener_preprocesador(perfil_t, ancho_objetivo=resolucion or resolucion_para_tienda(t))
        salida = raiz / t / folleto / "ocr_resultado.json"
        previo = json.load(open(salida, encoding="utf-8")) if salida.exists() and not forzar else {"paginas": []}
        listas = {p["pagina"] for p in previo["paginas"]}
        resultado = {"fuente": FUENTE_GT, "tienda": t, "folleto_id": folleto, "motor_ocr": MOTOR,
                     "perfil_imagen": perfil_t, "version_ocr": version, "paginas": list(previo["paginas"])}
        for nombre_pag in sorted(nombres):
            if nombre_pag in listas:
                hechas += 1
                continue
            imagen = pre.procesar(DATA_RAW / FUENTE_GT / t / folleto / nombre_pag)
            # Igual que probar_vision: guarda la imagen preprocesada como .webp y la relee con cv2.imread
            # (compresion y 3 canales incluidos), pero en memoria
            ok, buf = cv2.imencode(Path(nombre_pag).suffix or ".webp", imagen)
            imagen = cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else imagen
            bloques = ocr.extraer_texto(imagen, motor=MOTOR)
            conf = sum(b.confianza for b in bloques) / len(bloques) if bloques else 0.0
            resultado["paginas"].append({
                "pagina": nombre_pag, "ancho_pagina": imagen.shape[1], "confianza_prom": round(conf, 3),
                "bloques": [{"texto": b.texto, "confianza": round(b.confianza, 3), "bbox": b.bbox_simple, "motor": b.motor}
                            for b in bloques],
            })
            hechas += 1
            seg = (time.time() - inicio) / max(hechas, 1)
            print(f"  [{hechas}/{total}] {t}/{folleto}/{nombre_pag}: {len(bloques)} bloques | ~{seg:.0f} s/pagina, "
                  f"faltan ~{seg * (total - hechas) / 60:.0f} min", flush=True)
            # Se guarda pagina a pagina: si se interrumpe, se reanuda donde quedo
            salida.parent.mkdir(parents=True, exist_ok=True)
            resultado["paginas"].sort(key=lambda p: p["pagina"])
            json.dump(resultado, open(salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    meta = {"nombre": nombre, "version_ocr": version, "fecha": datetime.now().isoformat(timespec="seconds"),
            "tienda": tienda, "max_paginas": max_paginas, "perfil": perfil, "resolucion": resolucion,
            "paginas": total, "dispositivo": "cpu", "segundos": round(time.time() - inicio)}
    raiz.mkdir(parents=True, exist_ok=True)
    json.dump(meta, open(meta_ruta, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    return raiz


def paginas_disponibles(nombre: str) -> set[str]:
    """Claves tienda/folleto/pagina con OCR en el experimento."""
    raiz = carpeta_exp(nombre)
    if not raiz.exists():
        raise FileNotFoundError(f"No existe el experimento OCR {raiz}: corre `python -m evaluador ocr --nombre {nombre}`")
    claves = set()
    for ruta in raiz.glob("*/*/ocr_resultado.json"):
        datos = json.load(open(ruta, encoding="utf-8"))
        claves |= {f"{datos['tienda']}/{datos['folleto_id']}/{p['pagina']}" for p in datos["paginas"]}
    return claves
