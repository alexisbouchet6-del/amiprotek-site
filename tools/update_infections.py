#!/usr/bin/env python3
"""Met à jour le compteur « postes infectés sans antivirus actif, 7 derniers jours ».

Source : un registre tenu par l'atelier (Google Sheets ou Excel en ligne),
publié au format CSV. Une ligne par poste infecté pris en charge :

    date,antivirus_actif
    2026-10-14,non
    2026-10-16,oui

- date : AAAA-MM-JJ ou JJ/MM/AAAA (date de prise en charge)
- antivirus_actif : oui / non (l'antivirus était-il actif à l'arrivée du poste ?)

Le CSV publié est lisible par toute personne qui connaît son adresse : il ne
doit contenir AUCUN nom de client ni donnée personnelle.

La période comptée est celle des 7 jours complets qui se terminent la veille
(heure de Paris). Le résultat est écrit dans src/data/infections.json, lu par
le build. Lancé chaque jour par .github/workflows/antivirus-compteur.yml.

Usage :
    REGISTRE_CSV_URL="https://..." python tools/update_infections.py
    python tools/update_infections.py --csv registre.csv      (fichier local)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "src" / "data" / "infections.json"
TIMEZONE = ZoneInfo("Europe/Paris")
WINDOW_DAYS = 7
MAX_BYTES = 2_000_000
TIMEOUT_S = 30

DATE_COLUMNS = ("date", "date de prise en charge", "jour")
STATUS_COLUMNS = ("antivirus_actif", "antivirus actif", "antivirus")
NO_VALUES = {"non", "no", "n", "false", "faux", "0"}
YES_VALUES = {"oui", "yes", "o", "y", "true", "vrai", "1"}


class RegistryError(Exception):
    """Registre illisible : le compteur précédent est conservé."""


def parse_date(value: str) -> dt.date | None:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def find_column(header: list[str], candidates: tuple[str, ...]) -> int:
    normalized = [h.strip().lower() for h in header]
    for name in candidates:
        if name in normalized:
            return normalized.index(name)
    raise RegistryError(f"colonne introuvable : une de {candidates} attendue, en-tête reçu {header}")


def count_infections(csv_text: str, until: dt.date) -> int:
    """Nombre de postes sans antivirus actif pris en charge entre until-6 et until inclus."""
    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise RegistryError("registre vide")
    date_col = find_column(rows[0], DATE_COLUMNS)
    status_col = find_column(rows[0], STATUS_COLUMNS)
    start = until - dt.timedelta(days=WINDOW_DAYS - 1)
    count = 0
    for line_no, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue  # ligne vide
        if len(row) <= max(date_col, status_col):
            print(f"ATTENTION : ligne {line_no} incomplète, ignorée", file=sys.stderr)
            continue
        day = parse_date(row[date_col])
        status = row[status_col].strip().lower()
        if day is None or status not in NO_VALUES | YES_VALUES:
            print(f"ATTENTION : ligne {line_no} illisible ({row[date_col]!r}, {row[status_col]!r}), ignorée", file=sys.stderr)
            continue
        if start <= day <= until and status in NO_VALUES:
            count += 1
    return count


def fetch(url: str) -> str:
    if not url.startswith("https://"):
        raise RegistryError("l'adresse du registre doit commencer par https://")
    request = urllib.request.Request(url, headers={"User-Agent": "amitech-compteur/1.0"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
            data = response.read(MAX_BYTES + 1)
    except OSError as exc:
        raise RegistryError(f"registre inaccessible : {exc}") from exc
    if len(data) > MAX_BYTES:
        raise RegistryError("registre trop volumineux")
    text = data.decode("utf-8-sig")
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        raise RegistryError("l'adresse renvoie une page web, pas un CSV : publiez la feuille au format CSV")
    return text


def write_result(count: int, until: dt.date, output: Path = OUTPUT) -> bool:
    """Écrit le fichier seulement si le compteur ou la période change. Retourne True si modifié."""
    new = {"count": count, "until": until.isoformat()}
    try:
        old = json.loads(output.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        old = {}
    if {k: old.get(k) for k in new} == new:
        return False
    output.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Mise à jour du compteur antivirus")
    parser.add_argument("--csv", type=Path, help="fichier CSV local (à la place de REGISTRE_CSV_URL)")
    parser.add_argument("--until", help="dernier jour compté, AAAA-MM-JJ (par défaut : hier, heure de Paris)")
    args = parser.parse_args()

    until = parse_date(args.until) if args.until else dt.datetime.now(TIMEZONE).date() - dt.timedelta(days=1)
    if until is None:
        print("ERREUR : --until doit être au format AAAA-MM-JJ", file=sys.stderr)
        return 1

    try:
        if args.csv:
            text = args.csv.read_text(encoding="utf-8-sig")
        else:
            url = os.environ.get("REGISTRE_CSV_URL", "").strip()
            if not url:
                # Pas encore configuré : on ne fait pas échouer la tâche planifiée chaque jour.
                print("REGISTRE_CSV_URL non configuré : compteur inchangé.")
                return 0
            text = fetch(url)
        count = count_infections(text, until)
    except (RegistryError, OSError) as exc:
        print(f"ERREUR : {exc}. Compteur précédent conservé.", file=sys.stderr)
        return 1

    changed = write_result(count, until)
    print(f"{count} poste(s) sans antivirus actif du {until - dt.timedelta(days=WINDOW_DAYS - 1)} au {until}"
          f" ({'mis à jour' if changed else 'inchangé'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
