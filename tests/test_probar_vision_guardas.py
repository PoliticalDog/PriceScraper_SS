"""probar_vision.procesar_carpeta no destruye un ocr_resultado.json existente (26-oct-2026): ni con Tesseract sin
instalar ni con un OCR que no lee nada. Sin OCR real: motor y preprocesador falsos sobre carpetas temporales."""
import json

import cv2
import numpy as np
import pytest

import probar_vision as pv


class _Pre:
    def procesar_y_guardar(self, origen, destino):
        cv2.imwrite(str(destino), np.zeros((20, 30, 3), dtype=np.uint8))


class _OCR:
    def __init__(self, tesseract_ok=True, bloques=()):
        self._ok, self._bloques = tesseract_ok, list(bloques)

    def _verificar_tesseract(self):
        return self._ok

    def extraer_texto(self, imagen, motor="easyocr"):
        return self._bloques


@pytest.fixture
def carpetas(tmp_path, monkeypatch):
    raw, proc = tmp_path / "raw", tmp_path / "processed"
    folleto = raw / "tiendeo" / "heb" / "999"
    folleto.mkdir(parents=True)
    cv2.imwrite(str(folleto / "pagina_001.webp"), np.zeros((20, 30, 3), dtype=np.uint8))
    destino = proc / "tiendeo" / "heb" / "999"
    destino.mkdir(parents=True)
    (destino / "ocr_resultado.json").write_text(json.dumps({"total_bloques": 57}), encoding="utf-8")
    monkeypatch.setattr(pv, "DATA_RAW", raw)
    monkeypatch.setattr(pv, "DATA_PROCESSED", proc)
    return folleto, destino / "ocr_resultado.json"


def test_tesseract_sin_instalar_no_toca_el_json(carpetas):
    folleto, json_prod = carpetas
    r = pv.procesar_carpeta(folleto, _Pre(), _OCR(tesseract_ok=False), "tesseract", "color_normal", forzar=True)
    assert r is None and json.loads(json_prod.read_text(encoding="utf-8")) == {"total_bloques": 57}


def test_ocr_sin_bloques_no_reemplaza_el_json(carpetas):
    folleto, json_prod = carpetas
    r = pv.procesar_carpeta(folleto, _Pre(), _OCR(bloques=[]), "easyocr", "color_normal", forzar=True)
    assert r is None and json.loads(json_prod.read_text(encoding="utf-8")) == {"total_bloques": 57}
