from pathlib import Path
from PIL import Image
import pytesseract

# Ruta directa al ejecutable de Tesseract
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

imagen_path = Path(__file__).parent / "pagina_001.webp"

img = Image.open(imagen_path)

data = pytesseract.image_to_data(
    img,
    lang="spa+eng",
    config="--oem 3 --psm 11",
    output_type=pytesseract.Output.DICT
)

confianzas = []

print("\nRESULTADOS OCR")
print("=" * 80)

for i in range(len(data["text"])):
    texto = data["text"][i].strip()

    try:
        conf = float(data["conf"][i])
    except ValueError:
        conf = -1

    if texto and conf >= 0:
        confianzas.append(conf)

        print(
            f"Texto: {texto:<30} "
            f"Confianza: {conf:>6.2f}%"
        )

print("=" * 80)

if confianzas:
    promedio = sum(confianzas) / len(confianzas)
    print(f"Confianza promedio: {promedio:.2f}%")
else:
    print("No se detectó texto.")