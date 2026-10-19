#!/usr/bin/env python3
"""Télécharge la police Archivo (variable, sous-ensemble latin) pour l'auto-héberger.

Pourquoi : charger une police depuis fonts.googleapis.com transmet l'adresse IP
de chaque visiteur à Google sans consentement, ce qui pose un problème RGPD.
Une fois le fichier dans src/assets/fonts/, le site ne contacte plus aucun
serveur tiers.

À lancer une seule fois, puis à committer avec la licence :
    python tools/fetch_fonts.py
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "src" / "assets" / "fonts"
TARGET = FONTS_DIR / "archivo-latin.woff2"
LICENSE_TARGET = FONTS_DIR / "OFL-Archivo.txt"

CSS_URL = "https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,100..900&display=swap"
LICENSE_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/archivo/OFL.txt"
# Google Fonts ne renvoie du WOFF2 qu'à un navigateur moderne : on s'annonce comme tel.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
ALLOWED_HOSTS = ("https://fonts.gstatic.com/",)
MAX_BYTES = 2_000_000
TIMEOUT_S = 30


def fetch(url: str) -> bytes:
    # Seul le HTTPS est accepté : urllib ouvrirait aussi file:// ou ftp://.
    if not url.startswith("https://"):
        raise ValueError(f"schéma refusé : {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"réponse trop volumineuse pour {url}")
    return data


def latin_woff2_url(css: str) -> str:
    """Extrait l'URL du bloc @font-face marqué /* latin */ (et non latin-ext)."""
    match = re.search(r"/\*\s*latin\s*\*/\s*@font-face\s*\{(.*?)\}", css, re.S)
    if not match:
        raise ValueError("bloc /* latin */ introuvable dans la réponse de Google Fonts")
    url = re.search(r"url\((https://[^)]+\.woff2)\)", match.group(1))
    if not url:
        raise ValueError("URL WOFF2 introuvable dans le bloc latin")
    if not url.group(1).startswith(ALLOWED_HOSTS):
        raise ValueError(f"hôte inattendu : {url.group(1)}")
    return url.group(1)


def main() -> int:
    try:
        css = fetch(CSS_URL).decode("utf-8")
        font = fetch(latin_woff2_url(css))
        if not font.startswith(b"wOF2"):
            raise ValueError("le fichier reçu n'est pas une police WOFF2")
        license_text = fetch(LICENSE_URL)
    except (OSError, ValueError) as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1

    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(font)
    LICENSE_TARGET.write_bytes(license_text)
    print(f"Police enregistrée : {TARGET.relative_to(ROOT)} ({len(font) // 1024} Ko)")
    print(f"Licence enregistrée : {LICENSE_TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
