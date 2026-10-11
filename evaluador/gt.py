"""Ground truth: data/raw/_revision_manual/tiendeo/<tienda>/<folleto>_contenido.json (etiquetado a mano)."""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

RAIZ_GT = Path("data/raw/_revision_manual/tiendeo")
FUENTE_GT = "tiendeo"


@dataclass(frozen=True)
class ArticuloGT:
    tienda: str
    folleto: str
    pagina: str
    id: int
    producto: str
    categoria: str | None
    precio: float | None
    precio_anterior: float | None
    promocion: str | None


@dataclass
class PaginaGT:
    tienda: str
    folleto: str
    pagina: str
    articulos: list[ArticuloGT] = field(default_factory=list)
    promociones: list[str] = field(default_factory=list)  # texto + notas de promociones_pagina

    @property
    def clave(self) -> str:
        return f"{self.tienda}/{self.folleto}/{self.pagina}"


def archivos_gt(raiz: Path = RAIZ_GT) -> list[Path]:
    return sorted(Path(raiz).rglob("*_contenido.json"))


def cargar_gt(raiz: Path = RAIZ_GT) -> list[PaginaGT]:
    paginas = []
    for archivo in archivos_gt(raiz):
        datos = json.load(open(archivo, encoding="utf-8"))
        tienda, folleto = archivo.parent.name, str(datos["folleto_id"])
        for pg in datos["paginas"]:
            pagina = PaginaGT(tienda, folleto, pg["pagina"])
            for art in pg.get("articulos", []):
                pagina.articulos.append(ArticuloGT(
                    tienda, folleto, pg["pagina"], art.get("id"), art.get("producto") or "",
                    art.get("categoria"), art.get("precio"), art.get("precio_anterior"), art.get("promocion"),
                ))
            pagina.promociones = [
                " ".join(t for t in (promo.get("texto"), promo.get("notas")) if t)
                for promo in pg.get("promociones_pagina", [])
            ]
            paginas.append(pagina)
    return paginas


def huella_gt(raiz: Path = RAIZ_GT) -> dict[str, str]:
    """sha256 de cada archivo del GT (ruta relativa -> hash). data/ no esta en git: esto es lo que lo protege."""
    return {
        archivo.relative_to(raiz).as_posix(): hashlib.sha256(archivo.read_bytes()).hexdigest()
        for archivo in archivos_gt(raiz)
    }
