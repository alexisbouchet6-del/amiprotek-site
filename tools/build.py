#!/usr/bin/env python3
"""Générateur du site statique AMIPROTEK.

Assemble les pages de src/pages/ avec le gabarit src/layouts/base.html,
les fragments de src/partials/ et les données de src/site.json, puis écrit
le résultat dans dist/. Bibliothèque standard uniquement.

Syntaxe des gabarits :
    {{ site.contact.email }}   valeur échappée (HTML)
    {{> header }}              fragment src/partials/header.html
    {{@ tarifs_table }}        bloc HTML produit par un générateur Python

Usage :
    python tools/build.py            build de développement
    python tools/build.py --strict   échoue si des mentions légales manquent
    python tools/build.py --preview  ajoute la police via Google Fonts (aperçu uniquement)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import shutil
import sys
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DIST = ROOT / "dist"

TOKEN_RE = re.compile(r"\{\{\s*([>@]?)\s*([\w.\-]+)\s*\}\}")
META_RE = re.compile(r"\A\s*<!--meta\s+(\{.*?\})\s*-->\s*", re.S)
MAX_PARTIAL_DEPTH = 5
REQUIRED_META = ("title", "description")
EXTERNAL_SCHEMES = ("http", "https", "mailto", "tel", "data")


LEGAL_LABELS = {
    "raison_sociale": "Raison sociale",
    "nom_commercial": "Nom commercial",
    "forme_juridique": "Forme juridique",
    "capital": "Capital social",
    "siege": "Siège social",
    "siren": "SIREN",
    "rcs": "Immatriculation RCS",
    "tva": "Numéro de TVA intracommunautaire",
    "directeur_publication": "Directeur de la publication",
    "conception": "Conception et réalisation du site",
}
HOST_LABELS = {
    "hebergeur_nom": "Hébergeur",
    "hebergeur_adresse": "Adresse de l'hébergeur",
    "hebergeur_contact": "Contact de l'hébergeur",
}
# Mentions exigées par l'article 6 de la LCEN : leur absence bloque le build --strict.
REQUIRED_LEGAL = (
    "raison_sociale", "forme_juridique", "siege", "siren", "rcs",
    "directeur_publication", "hebergeur_nom", "hebergeur_adresse",
)
# Mentions attendues mais non bloquantes : un simple avertissement.
RECOMMENDED_LEGAL = ("capital", "tva")


class BuildError(Exception):
    """Erreur bloquante : le build s'arrête avec un message explicite."""


# --------------------------------------------------------------------------
# Moteur de gabarits
# --------------------------------------------------------------------------

Generator = Callable[[dict], str]


def resolve(ctx: dict, dotted: str) -> object:
    """Résout un chemin pointé (site.contact.email) dans le contexte."""
    value: object = ctx
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            raise BuildError(f"variable inconnue : {dotted}")
        value = value[part]
    return value


def render(
    text: str,
    ctx: dict,
    partials: dict[str, str],
    generators: dict[str, Generator],
    depth: int = 0,
) -> str:
    """Remplace les jetons {{ ... }} ; toute référence inconnue est une erreur."""
    if depth > MAX_PARTIAL_DEPTH:
        raise BuildError("imbrication de fragments trop profonde (boucle ?)")

    def replace(match: re.Match[str]) -> str:
        kind, name = match.group(1), match.group(2)
        if kind == ">":
            if name not in partials:
                raise BuildError(f"fragment inconnu : {name}")
            return render(partials[name], ctx, partials, generators, depth + 1)
        if kind == "@":
            if name not in generators:
                raise BuildError(f"générateur inconnu : {name}")
            return generators[name](ctx)
        value = resolve(ctx, name)
        if isinstance(value, (dict, list)):
            raise BuildError(f"{name} n'est pas une valeur simple")
        return html.escape(str(value), quote=True)

    return TOKEN_RE.sub(replace, text)


def split_meta(raw: str, source: Path) -> tuple[dict, str]:
    """Sépare l'en-tête <!--meta {...} --> du corps de la page."""
    match = META_RE.match(raw)
    if not match:
        raise BuildError(f"{source.name} : en-tête <!--meta {{...}} --> manquant")
    try:
        meta = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise BuildError(f"{source.name} : en-tête meta invalide ({exc})") from exc
    missing = [key for key in REQUIRED_META if not meta.get(key)]
    if missing:
        raise BuildError(f"{source.name} : champs meta manquants {missing}")
    return meta, raw[match.end():]


# --------------------------------------------------------------------------
# Générateurs : blocs HTML construits à partir de site.json
# --------------------------------------------------------------------------

def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


# Pictogrammes des services (trait, 24 x 24), coloriés en CSS via currentColor.
ICONS = {
    "reseau": '<circle cx="12" cy="5" r="2.2"/><circle cx="5" cy="19" r="2.2"/><circle cx="19" cy="19" r="2.2"/>'
              '<path d="M12 7.2v4.3M12 11.5 6.5 17.2M12 11.5l5.5 5.7"/>',
    "nas": '<rect x="4" y="3.5" width="16" height="7" rx="1.5"/><rect x="4" y="13.5" width="16" height="7" rx="1.5"/>'
           '<path d="M7.5 7h.01M7.5 17h.01M11 7h6M11 17h6"/>',
    "videosurveillance": '<path d="M3 8.5 15.5 5l1.6 5.6L4.6 14.1z"/><path d="m17.1 10.6 3.4 1.2M7 13.4l1.1 3.6H4.5"/>'
                         '<path d="M4.5 17v3"/>',
    "maintenance": '<path d="M14.7 6.3a4 4 0 0 0-5.2 5.2L4 17l3 3 5.5-5.5a4 4 0 0 0 5.2-5.2l-2.6 2.6-2.4-.6-.6-2.4z"/>',
    "telephonie": '<path d="M6.6 10.8a15 15 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20'
                  'a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1z"/>',
    "securite": '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6z"/>'
                '<rect x="9" y="10.5" width="6" height="5" rx="1"/><path d="M10.2 10.5V9a1.8 1.8 0 0 1 3.6 0v1.5"/>',
}
PHOTO_DIR = "assets/img/offres"
PHOTO_EXTENSIONS = (".webp", ".jpg", ".jpeg", ".png", ".avif")


def icon(service_id: str, css_class: str = "icon") -> str:
    return (
        f'<svg class="{css_class}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        f"{ICONS[service_id]}</svg>"
    )


def find_photo(src: Path, service_id: str) -> str | None:
    """Photo déposée dans src/assets/img/offres/<service>.<ext>, détectée automatiquement."""
    for ext in PHOTO_EXTENSIONS:
        if (src / PHOTO_DIR / f"{service_id}{ext}").is_file():
            return f"{PHOTO_DIR}/{service_id}{ext}"
    return None


def photo_figure(ctx: dict, svc: dict, css_class: str) -> str:
    """Photo du service, ou emplacement réservé tant qu'aucune photo n'est fournie.

    En production (--strict), l'emplacement vide reste une tuile sobre avec le
    pictogramme, sans texte « à venir » ; en développement, il indique le nom
    du fichier attendu.
    """
    photo = find_photo(ctx["build"]["src"], svc["id"])
    if photo:
        return (
            f'<figure class="{css_class}"><img src="{esc(photo)}" alt="{esc(svc["name"])}, réalisation AMI TECH" '
            f'loading="lazy" decoding="async"></figure>'
        )
    hint = ""
    if not ctx["build"]["strict"]:
        hint = f'<span class="photo-slot__hint">Photo à déposer : {esc(PHOTO_DIR)}/{esc(svc["id"])}.jpg</span>'
    return (
        f'<figure class="{css_class} photo-slot" aria-hidden="true">'
        f'{icon(svc["id"], "photo-slot__icon")}{hint}</figure>'
    )


def gen_wordmark(ctx: dict) -> str:
    """Logotype en texte : première lettre du dernier mot en rouge (AMI TECH)."""
    words = ctx["site"]["name"].split()
    last = words[-1]
    head = " ".join(words[:-1])
    head = f"{esc(head)} " if head else ""
    return f'{head}<span class="wordmark__accent">{esc(last[0])}</span>{esc(last[1:])}'


def gen_brand_line(ctx: dict) -> str:
    items = "".join(f"<li>{esc(t)}</li>" for t in ctx["site"]["brand"]["tagline"])
    return f'<ul class="brand-line" aria-label="Domaines d\'activité">{items}</ul>'


def gen_console(ctx: dict) -> str:
    """Console de l'accueil : une tuile cliquable par service, avec son état."""
    tiles = []
    for svc in ctx["site"]["services"]:
        tiles.append(
            f'<li><a class="console__tile" href="services.html#{esc(svc["id"])}">'
            f'<span class="console__icon">{icon(svc["id"])}</span>'
            f'<span class="console__text"><strong>{esc(svc["name"])}</strong><span>{esc(svc["short"])}</span></span>'
            f'<span class="console__state"><i aria-hidden="true"></i>En service</span></a></li>'
        )
    return "\n".join(tiles)


def gen_marquee(ctx: dict) -> str:
    """Bandeau défilant (site.json, brand.marquee). La 2e copie sert la boucle et reste muette."""
    seen = ctx["site"]["brand"]["marquee"]
    items = "".join(f"<li>{esc(w)}</li>" for w in seen)
    return (
        f'<ul class="marquee__list">{items}</ul>'
        f'<ul class="marquee__list" aria-hidden="true">{items}</ul>'
    )


def gen_page_styles(ctx: dict) -> str:
    """Feuilles de style propres à une page (clé « styles » de l'en-tête meta)."""
    return "".join(
        f'<link rel="stylesheet" href="assets/css/{esc(name)}.css">' for name in ctx["page"].get("styles", [])
    )


def gen_services_rows(ctx: dict) -> str:
    rows = []
    for svc in ctx["site"]["services"]:
        rows.append(
            f'<li class="svc-row">'
            f'<span class="svc-row__icon">{icon(svc["id"])}</span>'
            f'<h3 class="svc-row__name"><a href="services.html#{esc(svc["id"])}">'
            f'{esc(svc["name"])}</a></h3>'
            f'<p class="svc-row__text">{esc(svc["short"])}</p></li>'
        )
    return "\n".join(rows)


def gen_offers_gallery(ctx: dict) -> str:
    cards = []
    for svc in ctx["site"]["services"]:
        cards.append(
            f'<li class="offer"><a class="offer__link" href="services.html#{esc(svc["id"])}">'
            f'{photo_figure(ctx, svc, "offer__media")}'
            f'<span class="offer__name">{esc(svc["name"])}</span></a></li>'
        )
    return f'<ul class="offers">{"".join(cards)}</ul>'


def gen_services_detail(ctx: dict) -> str:
    contact = ctx["site"]["contact"]
    blocks = []
    for svc in ctx["site"]["services"]:
        points = "".join(f"<li>{esc(p)}</li>" for p in svc["points"])
        brands = (
            f'<p class="svc__brands"><strong>Matériel installé :</strong> {esc(svc["brands"])}</p>'
            if svc.get("brands")
            else ""
        )
        subject = esc(f"Demande de devis : {svc['name']}")
        blocks.append(
            f'<section class="svc" id="{esc(svc["id"])}" aria-labelledby="{esc(svc["id"])}-title">'
            f'<div class="svc__head">'
            f'<span class="svc__icon">{icon(svc["id"])}</span>'
            f'<h2 id="{esc(svc["id"])}-title">{esc(svc["name"])}</h2>'
            f'<p class="svc__intro">{esc(svc["intro"])}</p>'
            f'<p class="svc__audience"><strong>Pour qui :</strong> {esc(svc["audience"])}</p>'
            f"{brands}"
            f'<h3>Ce que nous faisons</h3><ul class="checklist">{points}</ul>'
            f'<a class="btn btn--primary" href="mailto:{esc(contact["email"])}?subject={subject}">'
            f"Demander un devis</a></div>"
            f'{photo_figure(ctx, svc, "svc__media")}</section>'
        )
    return "\n".join(blocks)


STAR_PATH = "M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5-4.8-4.6 6.6-.9z"


def stars(rating: float | int) -> str:
    full = int(float(rating) + 0.5)  # 4,9 -> 5 étoiles pleines
    items = "".join(
        f'<svg class="star{" star--on" if i < full else ""}" viewBox="0 0 24 24" aria-hidden="true" '
        f'focusable="false"><path d="{STAR_PATH}"/></svg>'
        for i in range(5)
    )
    return f'<span class="stars" role="img" aria-label="{esc(rating)} sur 5">{items}</span>'


def format_review_date(value: str) -> str:
    """'2026-03' -> 'mars 2026' (format AAAA-MM)."""
    months = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
              "août", "septembre", "octobre", "novembre", "décembre")
    match = re.fullmatch(r"(\d{4})-(\d{2})", value or "")
    if not match or not 1 <= int(match.group(2)) <= 12:
        return ""
    return f"{months[int(match.group(2)) - 1]} {match.group(1)}"


def gen_reviews(ctx: dict) -> str:
    """Carrousel d'avis Google. Chaque avis renvoie vers la fiche Google (nouvel onglet).

    Les avis sont saisis dans site.json : le site ne contacte jamais Google
    (pas de script tiers, pas de cookie). La mention finale répond à
    l'article L111-7-2 du Code de la consommation (sélection, absence de
    vérification).
    """
    reviews = ctx["site"]["reviews"]
    google_url = reviews.get("google_url", "")
    cards = []
    for review in reviews["items"]:
        when = format_review_date(review.get("date", ""))
        meta = esc(review["author"]) + (f", {esc(when)}" if when else "")
        rating = stars(review["rating"]) if review.get("rating") else ""
        body = (
            f'{rating}<blockquote class="review__text"><p>{esc(review["text"])}</p></blockquote>'
            f'<figcaption class="review__meta"><span class="review__author">{meta}</span>'
            f'<span class="review__source">Avis Google</span></figcaption>'
        )
        target = review.get("url") or google_url
        if target:
            body = (
                f'<a class="review__link" href="{esc(target)}" target="_blank" rel="noopener" '
                f'aria-label="Avis de {esc(review["author"])}, lire sur Google (nouvel onglet)">{body}</a>'
            )
        cards.append(f'<li class="review"><figure class="review__figure">{body}</figure></li>')

    summary = ""
    if reviews.get("rating") and reviews.get("count"):
        score = float(str(reviews["rating"]).replace(",", "."))
        summary = (
            f'<p class="reviews__score">{stars(score)}'
            f'<span><strong>{esc(reviews["rating"])}/5</strong> sur {esc(reviews["count"])} avis Google</span></p>'
        )
    controls = ""
    if len(reviews["items"]) > 1:
        controls = (
            '<div class="reviews__controls" data-carousel-controls hidden>'
            '<button type="button" class="carousel-btn" data-prev aria-label="Avis précédent">'
            '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M15 5 8 12l7 7"/></svg></button>'
            '<span class="reviews__count" data-count aria-live="polite"></span>'
            '<button type="button" class="carousel-btn" data-next aria-label="Avis suivant">'
            '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m9 5 7 7-7 7"/></svg></button>'
            "</div>"
        )
    links = []
    if google_url:
        links.append(f'<a href="{esc(google_url)}" target="_blank" rel="noopener">Voir tous nos avis sur Google</a>')
    if reviews.get("write_url"):
        links.append(f'<a href="{esc(reviews["write_url"])}" target="_blank" rel="noopener">Laisser un avis</a>')
    links_html = f'<p class="reviews__links">{"".join(links)}</p>' if links else ""
    return (
        f"{summary}"
        f'<div class="reviews__viewport" data-carousel tabindex="0" role="region" '
        f'aria-label="Avis clients, faites défiler horizontalement">'
        f'<ul class="reviews__track" data-track>{"".join(cards)}</ul></div>{controls}{links_html}'
        '<p class="reviews__legal">Avis publiés par nos clients sur notre fiche Google, sélectionnés par nos soins. '
        "Ils ne font pas l'objet d'une procédure de vérification de notre part.</p>"
    )


def all_tarifs(site: dict) -> list[dict]:
    """Liste à plat de tous les tarifs, toutes catégories confondues."""
    return [item for group in site["tarifs"] for item in group["items"]]


def tarif_table(items: list[dict], caption: str) -> str:
    rows = "".join(
        f'<tr><th scope="row">{esc(t["name"])}</th>'
        f'<td class="num">{esc(t["pro"])}</td><td class="num">{esc(t["part"])}</td></tr>'
        for t in items
    )
    return (
        f'<div class="table-scroll"><table class="tarifs"><caption class="sr-only">{esc(caption)}</caption>'
        '<thead><tr><th scope="col">Prestation</th>'
        '<th scope="col" class="num">Professionnels <span class="unit">HT</span></th>'
        '<th scope="col" class="num">Particuliers <span class="unit">TTC</span></th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


def gen_tarifs_toc(ctx: dict) -> str:
    links = "".join(
        f'<li><a href="#{esc(g["id"])}">{esc(g["title"])}</a></li>' for g in ctx["site"]["tarifs"]
    )
    return f'<nav class="toc" aria-label="Catégories de tarifs"><ul>{links}</ul></nav>'


def gen_tarifs_tables(ctx: dict) -> str:
    sections = []
    for group in ctx["site"]["tarifs"]:
        note = f'<p class="note">{esc(group["note"])}</p>' if group.get("note") else ""
        sections.append(
            f'<section class="tarif-group" id="{esc(group["id"])}" '
            f'aria-labelledby="{esc(group["id"])}-title">'
            f'<h2 id="{esc(group["id"])}-title">{esc(group["title"])}</h2>'
            f'{tarif_table(group["items"], group["title"])}{note}</section>'
        )
    return "\n".join(sections)


def gen_conditions(ctx: dict) -> str:
    items = "".join(f"<li>{esc(c)}</li>" for c in ctx["site"].get("conditions", []))
    return f'<ul class="conditions">{items}</ul>' if items else ""


def gen_prices_note(ctx: dict) -> str:
    note = ctx["site"].get("prices_note", "")
    return f'<p class="note">{esc(note)}</p>' if note else ""


def _legal_rows(legal: dict, labels: dict[str, str]) -> str:
    """Seules les mentions renseignées sont affichées ; le build signale les manques."""
    return "".join(
        f"<dt>{esc(label)}</dt><dd>{esc(legal[key])}</dd>"
        for key, label in labels.items()
        if legal.get(key)
    )


def gen_legal_editor(ctx: dict) -> str:
    return f'<dl class="legal">{_legal_rows(ctx["site"]["legal"], LEGAL_LABELS)}</dl>'


def gen_legal_host(ctx: dict) -> str:
    return f'<dl class="legal">{_legal_rows(ctx["site"]["legal"], HOST_LABELS)}</dl>'


def gen_diagnostic_data(ctx: dict) -> str:
    """Injecte l'arbre de décision en JSON (bloc de données, non exécuté)."""
    payload = {
        "tree": ctx["diagnostic"],
        "tarifs": {t["id"]: t for t in all_tarifs(ctx["site"])},
        "services": {s["id"]: s["name"] for s in ctx["site"]["services"]},
        "contact": ctx["site"]["contact"],
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/json" id="diagnostic-data">{data}</script>'


def gen_content(ctx: dict) -> str:
    return ctx["page_content"]


def gen_base_tag(ctx: dict) -> str:
    base = ctx["page"].get("base")
    return f'<base href="{esc(base)}">' if base else ""


def gen_robots_meta(ctx: dict) -> str:
    return '<meta name="robots" content="noindex">' if ctx["page"].get("noindex") else ""


def gen_preview_fonts(ctx: dict) -> str:
    """Aperçu uniquement : en production, la police est auto-hébergée (RGPD)."""
    if not ctx["build"]["preview"]:
        return ""
    return (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Archivo:wdth,wght@62..125,100..900&amp;display=swap">'
    )


FONT_FILE = "assets/fonts/archivo-latin.woff2"


def gen_font_preload(ctx: dict) -> str:
    """Précharge la police seulement si elle a été téléchargée (tools/fetch_fonts.py)."""
    if not (ctx["build"]["src"] / FONT_FILE).is_file():
        return ""
    return f'<link rel="preload" href="{FONT_FILE}" as="font" type="font/woff2" crossorigin>'


def gen_jsonld(ctx: dict) -> str:
    """Données structurées LocalBusiness (accueil uniquement), pour Google."""
    if ctx["page"]["slug"] != "index":
        return ""
    site, contact = ctx["site"], ctx["site"]["contact"]
    data = {
        "@context": "https://schema.org",
        "@type": "ComputerRepair",
        "name": site["name"],
        "legalName": site["legal"]["raison_sociale"],
        "url": site["url"],
        "telephone": contact["phone_link"],
        "email": contact["email"],
        "address": {
            "@type": "PostalAddress",
            "streetAddress": contact["street"],
            "postalCode": contact["postcode"],
            "addressLocality": contact["city"],
            "addressCountry": "FR",
        },
        "areaServed": "Région lyonnaise",
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{payload}</script>'


GENERATORS: dict[str, Generator] = {
    "content": gen_content,
    "font_preload": gen_font_preload,
    "jsonld": gen_jsonld,
    "base_tag": gen_base_tag,
    "robots_meta": gen_robots_meta,
    "preview_fonts": gen_preview_fonts,
    "wordmark": gen_wordmark,
    "brand_line": gen_brand_line,
    "console": gen_console,
    "marquee": gen_marquee,
    "page_styles": gen_page_styles,
    "offers_gallery": gen_offers_gallery,
    "reviews": gen_reviews,
    "services_rows": gen_services_rows,
    "services_detail": gen_services_detail,
    "tarifs_toc": gen_tarifs_toc,
    "tarifs_tables": gen_tarifs_tables,
    "conditions": gen_conditions,
    "prices_note": gen_prices_note,
    "legal_editor": gen_legal_editor,
    "legal_host": gen_legal_host,
    "diagnostic_data": gen_diagnostic_data,
}


# --------------------------------------------------------------------------
# Validation des données
# --------------------------------------------------------------------------

def validate_site(site: dict) -> None:
    ids = [s["id"] for s in site["services"]]
    if len(ids) != len(set(ids)):
        raise BuildError("site.json : identifiants de services en double")
    for svc in site["services"]:
        if svc["id"] not in ICONS:
            raise BuildError(f"service {svc['id']} : aucun pictogramme défini dans ICONS")
    for review in site["reviews"]["items"]:
        if not review.get("author") or not review.get("text"):
            raise BuildError("avis : auteur et texte obligatoires")
        rating = review.get("rating")
        if rating not in (None, "") and (not isinstance(rating, (int, float)) or not 1 <= rating <= 5):
            raise BuildError(f"avis de {review['author']} : note hors de 1 à 5")
    group_ids = [g["id"] for g in site["tarifs"]]
    tarif_ids = [t["id"] for t in all_tarifs(site)]
    if len(group_ids + tarif_ids) != len(set(group_ids + tarif_ids)):
        raise BuildError("site.json : identifiants de tarifs ou de catégories en double")
    for tarif in all_tarifs(site):
        if not tarif.get("pro") or not tarif.get("part"):
            raise BuildError(f"tarif {tarif['id']} : prix professionnel ou particulier manquant")


def validate_diagnostic(tree: dict, site: dict) -> None:
    """Vérifie que l'arbre est cohérent : chaque lien mène à un nœud existant."""
    nodes = tree.get("nodes", {})
    start = tree.get("start")
    if start not in nodes:
        raise BuildError(f"diagnostic : nœud de départ inconnu {start!r}")
    tarif_ids = {t["id"] for t in all_tarifs(site)}
    service_ids = {s["id"] for s in site["services"]}
    for node_id, node in nodes.items():
        kind = node.get("type")
        if kind == "question":
            if not node.get("options"):
                raise BuildError(f"diagnostic : {node_id} n'a aucune option")
            for opt in node["options"]:
                if opt.get("next") not in nodes:
                    raise BuildError(f"diagnostic : {node_id} -> nœud inconnu {opt.get('next')!r}")
        elif kind == "result":
            for tid in node.get("tarifs", []):
                if tid not in tarif_ids:
                    raise BuildError(f"diagnostic : {node_id} -> tarif inconnu {tid!r}")
            svc = node.get("service")
            if svc and svc not in service_ids:
                raise BuildError(f"diagnostic : {node_id} -> service inconnu {svc!r}")
        else:
            raise BuildError(f"diagnostic : {node_id} a un type invalide {kind!r}")
    for key, target in tree.get("shortcuts", {}).items():
        if target not in nodes:
            raise BuildError(f"diagnostic : raccourci {key} -> nœud inconnu {target!r}")


def missing_legal(site: dict) -> list[str]:
    """Mentions obligatoires absentes (bloquantes en mode --strict)."""
    labels = {**LEGAL_LABELS, **HOST_LABELS}
    missing = [labels[k] for k in REQUIRED_LEGAL if not site["legal"].get(k)]
    if not site.get("prices_note"):
        missing.append("Mention TTC/HT des prix (prices_note)")
    return missing


def recommended_legal(site: dict) -> list[str]:
    """Mentions attendues mais non bloquantes."""
    return [LEGAL_LABELS[k] for k in RECOMMENDED_LEGAL if not site["legal"].get(k)]


# --------------------------------------------------------------------------
# Vérification des liens internes
# --------------------------------------------------------------------------

class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        for name in ("href", "src"):
            value = attributes.get(name)
            if value and tag != "base":
                self.refs.append(value)


def check_links(dist: Path) -> list[str]:
    """Retourne la liste des liens internes cassés (fichier ou ancre)."""
    pages: dict[Path, LinkCollector] = {}
    for page in dist.rglob("*.html"):
        collector = LinkCollector()
        collector.feed(page.read_text(encoding="utf-8"))
        pages[page.resolve()] = collector

    errors = []
    for page, collector in pages.items():
        for ref in collector.refs:
            parts = urlsplit(ref)
            if parts.scheme in EXTERNAL_SCHEMES or ref.startswith("//"):
                continue
            if page.name == "404.html" and ref.startswith("/"):
                ref_path = dist / unquote(parts.path).lstrip("/")
            elif parts.path:
                ref_path = page.parent / unquote(parts.path)
            else:
                ref_path = page
            target = ref_path.resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                errors.append(f"{page.name} : cible absente {ref}")
                continue
            if parts.fragment and target.suffix == ".html":
                ids = pages.get(target, LinkCollector()).ids
                if parts.fragment not in ids:
                    errors.append(f"{page.name} : ancre absente {ref}")
    return errors


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BuildError(f"fichier absent : {path.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise BuildError(f"{path.relative_to(ROOT)} : JSON invalide ({exc})") from exc


def page_url(site: dict, slug: str) -> str:
    base = site["url"].rstrip("/")
    if slug == "index":
        return base + "/"
    return f"{base}/{slug}" if site.get("clean_urls") else f"{base}/{slug}.html"


def fingerprint(dist: Path, html_text: str) -> str:
    """Ajoute ?v=<hash> aux CSS/JS locaux pour invalider le cache à chaque modification."""

    def add_version(match: re.Match[str]) -> str:
        attr, path = match.group(1), match.group(2)
        file = dist / path.lstrip("/")
        if not file.is_file():
            return match.group(0)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()[:10]
        return f'{attr}="{path}?v={digest}"'

    return re.sub(r'(href|src)="(/?assets/[^"?#]+\.(?:css|js))"', add_version, html_text)


def build(src: Path = SRC, dist: Path = DIST, strict: bool = False, preview: bool = False) -> list[str]:
    """Construit le site et retourne la liste des avertissements."""
    site = load_json(src / "site.json")
    diagnostic = load_json(src / "data" / "diagnostic.json")
    validate_site(site)
    validate_diagnostic(diagnostic, site)

    warnings = []
    missing = missing_legal(site)
    if missing:
        message = "informations manquantes : " + ", ".join(missing)
        if strict:
            raise BuildError(message)
        warnings.append(message)
    recommended = recommended_legal(site)
    if recommended:
        warnings.append("mentions recommandées absentes : " + ", ".join(recommended))
    undated = [r["author"] for r in site["reviews"]["items"] if not format_review_date(r.get("date", ""))]
    if undated:
        warnings.append("avis sans date (AAAA-MM, obligatoire à l'affichage) : " + ", ".join(undated))
    no_photo = [s["id"] for s in site["services"] if not find_photo(src, s["id"])]
    if no_photo:
        warnings.append(f"photos manquantes dans src/{PHOTO_DIR}/ : " + ", ".join(no_photo))

    layout = (src / "layouts" / "base.html").read_text(encoding="utf-8")
    partials = {p.stem: p.read_text(encoding="utf-8") for p in (src / "partials").glob("*.html")}

    if dist.exists():
        shutil.rmtree(dist)
    shutil.copytree(src / "assets", dist / "assets")
    static = src / "static"
    if static.is_dir():
        shutil.copytree(static, dist, dirs_exist_ok=True)

    sitemap_urls = []
    for page_file in sorted((src / "pages").glob("*.html")):
        slug = page_file.stem
        meta, body = split_meta(page_file.read_text(encoding="utf-8"), page_file)
        ctx = {
            "site": site,
            "diagnostic": diagnostic,
            "page": {**meta, "slug": slug, "url": page_url(site, slug)},
            "build": {"year": str(dt.date.today().year), "preview": preview, "src": src, "strict": strict},
        }
        ctx["page_content"] = render(body, ctx, partials, GENERATORS)
        output = render(layout, ctx, partials, GENERATORS)

        # Lien actif dans la navigation (aria-current indique la page courante).
        nav = meta.get("nav")
        if nav:
            output = output.replace(f'data-nav="{nav}"', f'data-nav="{nav}" aria-current="page"')

        if "{{" in output:
            raise BuildError(f"{page_file.name} : jeton non remplacé dans la sortie")

        output = fingerprint(dist, output)
        (dist / f"{slug}.html").write_text(output, encoding="utf-8")
        if not meta.get("noindex"):
            sitemap_urls.append(ctx["page"]["url"])

    write_seo_files(site, dist, sitemap_urls)

    broken = check_links(dist)
    if broken:
        raise BuildError("liens cassés :\n  " + "\n  ".join(broken))
    return warnings


def write_seo_files(site: dict, dist: Path, urls: list[str]) -> None:
    today = dt.date.today().isoformat()
    entries = "".join(f"<url><loc>{esc(u)}</loc><lastmod>{today}</lastmod></url>" for u in urls)
    (dist / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>\n',
        encoding="utf-8",
    )
    (dist / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {site['url'].rstrip('/')}/sitemap.xml\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build du site AMI TECH")
    parser.add_argument("--strict", action="store_true", help="échoue si des mentions légales manquent")
    parser.add_argument("--preview", action="store_true", help="charge la police depuis Google Fonts")
    args = parser.parse_args()
    try:
        warnings = build(strict=args.strict, preview=args.preview)
    except BuildError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(f"ATTENTION : {warning}", file=sys.stderr)
    print(f"Site généré dans {DIST.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
