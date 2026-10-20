"""Prépare des photos de chantier pour la rubrique « Nos chantiers ».

Pour chaque photo : rotation selon l'orientation du téléphone, suppression de
toutes les métadonnées (position GPS, modèle de téléphone, date), redimensionnement
et compression. Deux fichiers sont écrits dans src/assets/img/chantiers/<catégorie>/ :

    07.jpg        image agrandie (1600 px sur le plus grand côté)
    07.thumb.jpg  vignette de la galerie (720 px de large)

Les numéros reprennent à la suite des photos déjà présentes.

Dépendance (uniquement pour ce script, pas pour le build) :
    python -m pip install Pillow

Exemple :
    python tools/prepare_photos.py videosurveillance ~/Images/portail.jpg ~/Images/camera.heic
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - message pour l'utilisateur
    sys.exit("Pillow est nécessaire : python -m pip install Pillow")

ROOT = Path(__file__).resolve().parent.parent
GALLERY = ROOT / "src" / "assets" / "img" / "chantiers"
SITE = ROOT / "src" / "site.json"
FULL_SIZE = 1600
THUMB_WIDTH = 720
QUALITY = 80
NUMBERED = re.compile(r"^(\d+)\.jpg$")


def categories() -> list[str]:
    services = json.loads(SITE.read_text(encoding="utf-8"))["services"]
    return [s["id"] for s in services]


def next_number(folder: Path) -> int:
    numbers = [int(m.group(1)) for p in folder.glob("*.jpg") if (m := NUMBERED.match(p.name))]
    return max(numbers, default=0) + 1


def save_clean(image: Image.Image, path: Path) -> None:
    """Enregistre en JPEG progressif, sans aucune métadonnée (EXIF, GPS, XMP)."""
    image.save(path, "JPEG", quality=QUALITY, optimize=True, progressive=True)


def prepare(source: Path, folder: Path, number: int) -> tuple[Path, Path]:
    with Image.open(source) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
    full = image.copy()
    full.thumbnail((FULL_SIZE, FULL_SIZE), Image.LANCZOS)
    thumb = image.copy()
    thumb.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 4), Image.LANCZOS)

    full_path = folder / f"{number:02d}.jpg"
    thumb_path = folder / f"{number:02d}.thumb.jpg"
    save_clean(full, full_path)
    save_clean(thumb, thumb_path)
    return full_path, thumb_path


def main() -> int:
    known = categories()
    parser = argparse.ArgumentParser(description="Prépare des photos pour la rubrique Nos chantiers")
    parser.add_argument("categorie", choices=known, help="identifiant du service")
    parser.add_argument("photos", nargs="+", type=Path, help="photos à ajouter (JPEG, PNG, WebP…)")
    args = parser.parse_args()

    folder = GALLERY / args.categorie
    folder.mkdir(parents=True, exist_ok=True)
    number = next_number(folder)
    errors = 0
    for source in args.photos:
        if not source.is_file():
            print(f"ERREUR : fichier introuvable : {source}", file=sys.stderr)
            errors += 1
            continue
        try:
            full_path, _ = prepare(source, folder, number)
        except OSError as exc:  # format illisible ou fichier corrompu
            print(f"ERREUR : {source} : {exc}", file=sys.stderr)
            errors += 1
            continue
        size_kb = full_path.stat().st_size // 1024
        print(f"{source.name} -> {full_path.relative_to(ROOT)} ({size_kb} Ko)")
        number += 1

    print(
        "\nLégendes (facultatives) : src/data/chantiers.json, "
        f'ex. "{args.categorie}/{number - 1:02d}.jpg": "Description de la photo"'
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
