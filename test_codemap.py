#!/usr/bin/env python3
"""Test unitari codemap (stdlib unittest, zero dipendenze).
Coprono: mod_key_for, regex TS export, guardia js, config REPOS, hook script.
"""
import os
import unittest
from codemap import (mod_key_for, TS_EXPORT, skip_js, REPOS, load_config,
                     make_hook_script, HOOK_MARKER, governance_drift,
                     DRIFT_THRESHOLD)


class TestModKey(unittest.TestCase):
    def test_ultimo_segmento(self):
        self.assertEqual(mod_key_for("packages/api/billing"), "billing")

    def test_route_group_nextjs_saltato(self):
        self.assertEqual(mod_key_for("packages/web/app/(dashboard)/settings"), "settings")
        self.assertEqual(mod_key_for("app/(auth)"), "app")

    def test_dynamic_segment_saltato(self):
        self.assertEqual(mod_key_for("app/posts/[id]"), "posts")

    def test_root(self):
        self.assertEqual(mod_key_for(""), "root")
        self.assertEqual(mod_key_for("."), "root")


class TestTsExport(unittest.TestCase):
    def test_function_class_const(self):
        src = ("export function foo() {}\n"
               "export default async function bar() {}\n"
               "export class Baz {}\n"
               "export const qux = 1\n"
               "export interface Props {}\n"
               "export type Alias = string\n")
        found = {(k, n) for k, n in TS_EXPORT.findall(src)}
        self.assertIn(("function", "foo"), found)
        self.assertIn(("function", "bar"), found)
        self.assertIn(("class", "Baz"), found)
        self.assertIn(("const", "qux"), found)
        self.assertIn(("interface", "Props"), found)
        self.assertIn(("type", "Alias"), found)


class TestSkipJs(unittest.TestCase):
    def test_minificato_per_nome(self):
        self.assertTrue(skip_js("vendor.min.js", 1000))

    def test_bundle_per_dimensione(self):
        self.assertTrue(skip_js("app.js", 500_000))

    def test_js_normale_ok(self):
        self.assertFalse(skip_js("app.js", 12_000))
        self.assertFalse(skip_js("worker.ts", 500_000))  # guardia solo per .js/.jsx


class TestReposConfig(unittest.TestCase):
    """I test sulla config locale girano solo se codemap.config.json esiste
    (repo privato). Nel repo pubblico, senza config, vengono saltati."""

    def test_load_config_mancante_ritorna_vuoto(self):
        cfg = load_config("/path/inesistente/x.json")
        self.assertEqual(cfg["repos"], {})

    @unittest.skipUnless(REPOS, "nessuna codemap.config.json locale")
    def test_shape(self):
        for slug, cfg in REPOS.items():
            self.assertRegex(slug, r"^[a-z][a-z0-9-]*$")
            self.assertTrue("dir" in cfg or "path" in cfg, f"{slug} manca 'dir'/'path'")
            for key in ("py", "ts"):
                self.assertIn(key, cfg, f"{slug} manca '{key}'")

    # I test legati alla config specifica di QUESTA macchina (slug reali,
    # include attesi) vivono in test_codemap_local.py — non nel file pubblico.


class TestGovernanceDrift(unittest.TestCase):
    def test_repo_inesistente(self):
        self.assertEqual(governance_drift("/path/che/non/esiste"), (None, None))

    def test_threshold_positivo(self):
        self.assertGreater(DRIFT_THRESHOLD, 0)

    def test_su_questo_repo(self):
        """Integrazione leggera: questo repo ha CLAUDE.md committato in git."""
        here = os.path.dirname(os.path.abspath(__file__))
        date, n = governance_drift(here)
        if date is None:
            self.skipTest("repo senza CLAUDE.md committato")
        self.assertIsInstance(n, int)
        self.assertGreaterEqual(n, 0)


class TestHookScript(unittest.TestCase):
    def test_contiene_marker_e_slug(self):
        s = make_hook_script("my-saas")
        self.assertIn(HOOK_MARKER, s)
        self.assertIn("--repo my-saas", s)
        self.assertTrue(s.startswith("#!/bin/sh"))

    def test_non_blocca_mai_il_commit(self):
        self.assertIn("exit 0", make_hook_script("demo"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
