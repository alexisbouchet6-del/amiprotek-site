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
        self.site = json.loads((ROOT / "src" / "site.json").read_text(encoding="utf-8"))
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

    def test_unknown_cable_color_is_rejected(self) -> None:
        site = copy.deepcopy(self.site)
        site["services"][0]["color"] = "rose"
        with self.assertRaises(build.BuildError):
            build.validate_site(site)


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
        names = ("index", "services", "diagnostic", "tarifs", "mentions-legales", "confidentialite", "404")
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

    def test_active_nav(self) -> None:
        text = (self.dist / "tarifs.html").read_text(encoding="utf-8")
        self.assertIn('data-nav="tarifs" aria-current="page"', text)

    def test_assets_are_versioned(self) -> None:
        text = (self.dist / "index.html").read_text(encoding="utf-8")
        self.assertRegex(text, r'assets/css/main\.css\?v=[0-9a-f]{10}')

    def test_404_is_noindex_and_out_of_sitemap(self) -> None:
        self.assertIn('content="noindex"', (self.dist / "404.html").read_text(encoding="utf-8"))
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
        self.assertTrue(title.endswith("| AMIPROTEK"))
        self.assertEqual(title.count("AMIPROTEK"), 1)


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
