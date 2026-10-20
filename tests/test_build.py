"""Tests du générateur de site (bibliothèque standard : python -m unittest)."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build  # noqa: E402
import fetch_fonts  # noqa: E402
import update_infections  # noqa: E402


class RenderTests(unittest.TestCase):
    def test_variable_is_escaped(self) -> None:
        out = build.render("{{ a.b }}", {"a": {"b": "<script>"}}, {}, {})
        self.assertEqual(out, "&lt;script&gt;")

    def test_unknown_variable_fails(self) -> None:
        with self.assertRaises(build.BuildError):
            build.render("{{ inconnu }}", {}, {}, {})

    def test_partial_and_generator(self) -> None:
        out = build.render(
            "{{> p }}|{{@ g }}", {"x": "1"}, {"p": "P{{ x }}"}, {"g": lambda ctx: "<b>G</b>"}
        )
        self.assertEqual(out, "P1|<b>G</b>")

    def test_partial_loop_is_detected(self) -> None:
        with self.assertRaises(build.BuildError):
            build.render("{{> a }}", {}, {"a": "{{> a }}"}, {})

    def test_meta_is_required(self) -> None:
        with self.assertRaises(build.BuildError):
            build.split_meta("<p>sans en-tête</p>", Path("x.html"))


class DataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.site = build.load_site(build.SRC)
        self.tree = json.loads((ROOT / "src" / "data" / "diagnostic.json").read_text(encoding="utf-8"))

    def test_diagnostic_tree_is_valid(self) -> None:
        build.validate_diagnostic(self.tree, self.site)

    def test_every_node_is_reachable(self) -> None:
        seen, todo = set(), [self.tree["start"]]
        while todo:
            node_id = todo.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            for option in self.tree["nodes"][node_id].get("options", []):
                todo.append(option["next"])
        self.assertEqual(seen, set(self.tree["nodes"]), "nœuds inaccessibles")

    def test_broken_link_in_tree_is_rejected(self) -> None:
        tree = copy.deepcopy(self.tree)
        tree["nodes"]["start"]["options"][0]["next"] = "nexiste_pas"
        with self.assertRaises(build.BuildError):
            build.validate_diagnostic(tree, self.site)

    def test_unknown_tarif_is_rejected(self) -> None:
        tree = copy.deepcopy(self.tree)
        tree["nodes"]["r_ssd"]["tarifs"] = ["inconnu"]
        with self.assertRaises(build.BuildError):
            build.validate_diagnostic(tree, self.site)

    def test_tarif_without_price_is_rejected(self) -> None:
        site = copy.deepcopy(self.site)
        site["tarifs"][0]["items"][0]["part"] = ""
        with self.assertRaises(build.BuildError):
            build.validate_site(site)

    def test_legal_notices_are_complete(self) -> None:
        self.assertEqual(build.missing_legal(self.site), [])

    def test_service_without_icon_is_rejected(self) -> None:
        site = copy.deepcopy(self.site)
        site["services"][0]["id"] = "inconnu"
        with self.assertRaises(build.BuildError):
            build.validate_site(site)

    def test_review_rating_out_of_range_is_rejected(self) -> None:
        site = copy.deepcopy(self.site)
        site["reviews"]["items"][0]["rating"] = 6
        with self.assertRaises(build.BuildError):
            build.validate_site(site)

    def test_infection_window_format(self) -> None:
        import datetime as dt
        self.assertEqual(build.format_window(dt.date(2026, 10, 19)), "du 13 au 19 octobre 2026")
        self.assertEqual(build.format_window(dt.date(2026, 10, 3)), "du 27 septembre au 3 octobre 2026")
        self.assertEqual(build.format_window(dt.date(2027, 1, 2)), "du 27 décembre 2026 au 2 janvier 2027")

    def test_infection_stat_hidden_when_empty_zero_or_stale(self) -> None:
        import datetime as dt
        today = dt.date(2026, 10, 20)
        site = copy.deepcopy(self.site)
        for data in ({}, {"count": None, "until": None}, {"count": 0, "until": "2026-10-19"},
                     {"count": 4, "until": "2026-10-10"}):
            site["antivirus"]["infections"] = data
            self.assertIsNone(build.infection_stat(site, today), data)

    def test_infection_stat_text(self) -> None:
        import datetime as dt
        site = copy.deepcopy(self.site)
        site["antivirus"]["infections"] = {"count": 4, "until": "2026-10-19"}
        stat = build.infection_stat(site, dt.date(2026, 10, 20))
        self.assertEqual(stat["count"], 4)
        self.assertIn("4 postes infectés", stat["text"])
        self.assertIn("du 13 au 19 octobre 2026", stat["text"])

    def test_infection_stat_rejects_future_or_invalid(self) -> None:
        for count, until in ((3, "2999-01-01"), ("trois", "2026-10-19"), (3, "19/10/2026")):
            site = copy.deepcopy(self.site)
            site["antivirus"]["infections"] = {"count": count, "until": until}
            with self.assertRaises(build.BuildError, msg=(count, until)):
                build.validate_site(site)

    def test_antivirus_tarif_generated_from_price(self) -> None:
        group = build.antivirus_tarif_group(self.site)
        item = group["items"][0]
        price = self.site["antivirus"]["price"]
        self.assertEqual(item["pro"], f"{price['pro']} € / an")
        self.assertEqual(item["part"], f"{price['part']} € / an")

    def test_unknown_offer_is_rejected(self) -> None:
        tree = copy.deepcopy(self.tree)
        tree["nodes"]["r_adware"]["offer"] = "inconnue"
        with self.assertRaises(build.BuildError):
            build.validate_diagnostic(tree, self.site)

    def test_virus_results_offer_antivirus(self) -> None:
        for node in ("r_adware", "r_ransom", "r_scam", "r_reinstall", "r_security_pro"):
            self.assertEqual(self.tree["nodes"][node].get("offer"), "antivirus", node)

    def test_review_date_format(self) -> None:
        self.assertEqual(build.format_review_date("2026-03"), "mars 2026")
        self.assertEqual(build.format_review_date("2026-13"), "")
        self.assertEqual(build.format_review_date(""), "")


class BuildTests(unittest.TestCase):
    """Construit le site dans un dossier temporaire et inspecte le résultat."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        cls.dist = cls.tmp / "dist"
        cls.warnings = build.build(dist=cls.dist)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp)

    def test_pages_are_generated(self) -> None:
        names = ("index", "services", "chantiers", "diagnostic", "tarifs", "antivirus",
                 "mentions-legales", "confidentialite", "404")
        for name in names:
            self.assertTrue((self.dist / f"{name}.html").is_file(), name)

    def test_no_template_token_left(self) -> None:
        for page in self.dist.glob("*.html"):
            self.assertNotIn("{{", page.read_text(encoding="utf-8"), page.name)

    def test_no_inline_style_or_script(self) -> None:
        """La CSP interdit le style et le script en ligne : on le vérifie ici."""
        for page in self.dist.glob("*.html"):
            text = page.read_text(encoding="utf-8")
            self.assertNotIn(" style=", text, page.name)
            self.assertNotIn("<style", text, page.name)
            for chunk in text.split("<script")[1:]:
                head = chunk.split(">", 1)[0]
                self.assertTrue(
                    "src=" in head or "application/json" in head or "application/ld+json" in head,
                    f"{page.name} : script en ligne exécutable",
                )

    def test_no_third_party_request(self) -> None:
        for page in self.dist.glob("*.html"):
            text = page.read_text(encoding="utf-8")
            self.assertNotIn("fonts.googleapis.com", text, page.name)

    def test_htaccess_for_ovh(self) -> None:
        conf = (self.dist / ".htaccess").read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", conf)
        self.assertIn("RewriteCond %{SERVER_PORT} 80", conf)
        self.assertIn("ErrorDocument 404 /404.html", conf)
        self.assertIn("RewriteRule ^infrastructure\\-réseau/?$ /services.html#reseau [R=301,L,NE]", conf)
        self.assertIn("RewriteRule ^service\\-page/.*$ /tarifs.html", conf)
        self.assertNotIn("{{", conf)

    def test_antivirus_price_on_pages(self) -> None:
        self.assertIn("antivirus_poste", (self.dist / "diagnostic.html").read_text(encoding="utf-8"))
        self.assertIn('id="antivirus"', (self.dist / "tarifs.html").read_text(encoding="utf-8"))
        self.assertIn("data-av-calc", (self.dist / "antivirus.html").read_text(encoding="utf-8"))

    def test_antivirus_page_linked_and_data_injected(self) -> None:
        self.assertIn('href="antivirus.html"', (self.dist / "tarifs.html").read_text(encoding="utf-8"))
        diag = (self.dist / "diagnostic.html").read_text(encoding="utf-8")
        self.assertIn('"antivirus": {"product": "Kaspersky Next EDR Foundations"', diag)

    def test_active_nav(self) -> None:
        text = (self.dist / "tarifs.html").read_text(encoding="utf-8")
        self.assertIn('data-nav="tarifs" aria-current="page"', text)

    def test_assets_are_versioned(self) -> None:
        text = (self.dist / "index.html").read_text(encoding="utf-8")
        self.assertRegex(text, r'assets/css/main\.css\?v=[0-9a-f]{10}')

    def test_404_is_noindex_and_out_of_sitemap(self) -> None:
        self.assertIn('content="noindex, nofollow"', (self.dist / "404.html").read_text(encoding="utf-8"))
        self.assertNotIn("404", (self.dist / "sitemap.xml").read_text(encoding="utf-8"))

    def test_internal_links_are_valid(self) -> None:
        self.assertEqual(build.check_links(self.dist), [])

    def test_broken_link_is_detected(self) -> None:
        bad = self.dist / "casse.html"
        bad.write_text('<a href="absente.html">x</a><a href="index.html#nulle-part">y</a>', encoding="utf-8")
        try:
            self.assertEqual(len(build.check_links(self.dist)), 2)
        finally:
            bad.unlink()

    def test_noindex_preview_build(self) -> None:
        """Aperçu public : aucune page indexable, 404 servie depuis le sous-dossier."""
        out = self.tmp / "noindex"
        build.build(dist=out, noindex=True, base_path="/amiprotek-site/")
        for page in out.glob("*.html"):
            self.assertIn('content="noindex, nofollow"', page.read_text(encoding="utf-8"), page.name)
        self.assertIn("Disallow: /", (out / "robots.txt").read_text(encoding="utf-8"))
        self.assertIn('<base href="/amiprotek-site/">', (out / "404.html").read_text(encoding="utf-8"))

    def test_strict_mode_builds(self) -> None:
        """Le build de production (--strict) passe : mentions légales complètes."""
        build.build(dist=self.tmp / "strict", strict=True)

    def test_strict_mode_fails_without_siren(self) -> None:
        site = json.loads((ROOT / "src" / "site.json").read_text(encoding="utf-8"))
        site["legal"]["siren"] = ""
        self.assertIn("SIREN", build.missing_legal(site))

    def test_title_carries_company_name_once(self) -> None:
        text = (self.dist / "tarifs.html").read_text(encoding="utf-8")
        title = text.split("<title>", 1)[1].split("</title>", 1)[0]
        name = json.loads((ROOT / "src" / "site.json").read_text(encoding="utf-8"))["name"]
        self.assertTrue(title.endswith(f"| {name}"))
        self.assertEqual(title.count(name), 1)

    def test_reviews_carry_legal_notice(self) -> None:
        text = (self.dist / "index.html").read_text(encoding="utf-8")
        self.assertIn("reviews__track", text)
        self.assertIn("procédure de vérification", text)

    def test_chantiers_page_and_navigation(self) -> None:
        self.assertTrue((self.dist / "chantiers.html").is_file())
        text = (self.dist / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="chantiers.html" data-nav="chantiers"', text)

    def test_chantiers_gallery_lists_photos_with_thumbnails(self) -> None:
        src = Path(tempfile.mkdtemp())
        try:
            folder = src / build.CHANTIERS_DIR / "reseau"
            folder.mkdir(parents=True)
            for name in ("02.jpg", "01.jpg", "01.thumb.jpg", "notes.txt"):
                (folder / name).write_bytes(b"x")
            photos = build.find_chantiers(src, "reseau")
            self.assertEqual([p["key"] for p in photos], ["reseau/01.jpg", "reseau/02.jpg"])
            self.assertTrue(photos[0]["thumb"].endswith("01.thumb.jpg"))
            self.assertTrue(photos[1]["thumb"].endswith("02.jpg"))  # pas de vignette : image complète
            self.assertEqual(build.find_chantiers(src, "nas"), [])
        finally:
            shutil.rmtree(src)

    def test_chantiers_empty_categories_hidden_in_production(self) -> None:
        site = build.load_site(build.SRC)
        src = Path(tempfile.mkdtemp())
        try:
            (src / build.CHANTIERS_DIR / "nas").mkdir(parents=True)
            (src / build.CHANTIERS_DIR / "nas" / "01.jpg").write_bytes(b"x")
            (src / "data").mkdir()
            (src / build.CHANTIERS_CAPTIONS).write_text('{"nas/01.jpg": "Baie <NAS>"}', encoding="utf-8")
            ctx = {"site": site, "build": {"src": src, "strict": True}}
            html = build.gen_chantiers(ctx)
            self.assertIn('id="chantiers-nas"', html)
            self.assertNotIn('id="chantiers-reseau"', html)
            self.assertIn('data-caption="Baie &lt;NAS&gt;"', html)
            ctx["build"]["strict"] = False
            self.assertIn("Aucune photo pour le moment", build.gen_chantiers(ctx))
        finally:
            shutil.rmtree(src)

    def test_photo_slots_show_hint_only_outside_production(self) -> None:
        dev = (self.dist / "index.html").read_text(encoding="utf-8")
        strict_dist = self.tmp / "strict-photos"
        build.build(dist=strict_dist, strict=True)
        prod = (strict_dist / "index.html").read_text(encoding="utf-8")
        missing = [s for s in json.loads((ROOT / "src" / "site.json").read_text(encoding="utf-8"))["services"]
                   if not build.find_photo(build.SRC, s["id"])]
        if not missing:
            self.skipTest("toutes les photos sont fournies")
        self.assertIn("Photo à déposer", dev)
        self.assertNotIn("Photo à déposer", prod)


class InfectionCounterTests(unittest.TestCase):
    """Comptage depuis le registre CSV de l'atelier."""

    CSV = (
        "Date,Antivirus actif\n"
        "2026-10-12,non\n"       # hors période (avant le 13)
        "13/10/2026,non\n"       # format JJ/MM/AAAA, compté
        "2026-10-15,oui\n"       # antivirus actif : non compté
        "2026-10-19,NON\n"       # dernier jour, compté
        "2026-10-20,non\n"       # après la période
        "\n"
        "pas une date,non\n"     # ligne illisible, ignorée
    )

    def test_counts_only_window_and_inactive(self) -> None:
        import datetime as dt
        self.assertEqual(update_infections.count_infections(self.CSV, dt.date(2026, 10, 19)), 2)

    def test_missing_column_is_an_error(self) -> None:
        import datetime as dt
        with self.assertRaises(update_infections.RegistryError):
            update_infections.count_infections("jour,client\n2026-10-19,Dupont\n", dt.date(2026, 10, 19))

    def test_http_url_refused(self) -> None:
        with self.assertRaises(update_infections.RegistryError):
            update_infections.fetch("http://exemple.fr/registre.csv")

    def test_write_only_when_changed(self) -> None:
        import datetime as dt
        out = Path(tempfile.mkdtemp()) / "infections.json"
        try:
            self.assertTrue(update_infections.write_result(3, dt.date(2026, 10, 19), out))
            self.assertFalse(update_infections.write_result(3, dt.date(2026, 10, 19), out))
            self.assertTrue(update_infections.write_result(4, dt.date(2026, 10, 19), out))
        finally:
            shutil.rmtree(out.parent)


class FontTests(unittest.TestCase):
    CSS = """
/* latin-ext */
@font-face { src: url(https://fonts.gstatic.com/s/archivo/v1/ext.woff2) format('woff2'); }
/* latin */
@font-face { src: url(https://fonts.gstatic.com/s/archivo/v1/latin.woff2) format('woff2'); }
"""

    def test_latin_block_is_selected(self) -> None:
        self.assertTrue(fetch_fonts.latin_woff2_url(self.CSS).endswith("/latin.woff2"))

    def test_unexpected_host_is_refused(self) -> None:
        css = "/* latin */ @font-face { src: url(https://evil.example/x.woff2); }"
        with self.assertRaises(ValueError):
            fetch_fonts.latin_woff2_url(css)


if __name__ == "__main__":
    unittest.main()
