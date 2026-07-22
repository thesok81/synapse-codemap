#!/usr/bin/env python3
"""Test unitari codemap (stdlib unittest, zero dipendenze).
Coprono: mod_key_for, regex TS export, guardia js, config REPOS, hook script.
"""
import os
import unittest
from codemap import (mod_key_for, TS_EXPORT, skip_js, REPOS, load_config,
                     make_hook_script, HOOK_MARKER, governance_drift,
                     DRIFT_THRESHOLD, parse_known_namespaces, mirror_drift,
                     scan_repo)


class TestSymbolIndexScan(unittest.TestCase):
    """Indice simbolo→file: scan_repo traccia (nome, kind, file, riga) per simbolo."""

    def test_python_simboli_con_riga(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            api = os.path.join(d, "api"); os.makedirs(api)
            open(os.path.join(api, "router.py"), "w", encoding="utf-8").write(
                "import os\n"                # riga 1
                "\n"
                "def top():\n"               # riga 3
                "    pass\n"
                "\n"
                "class Handler:\n"           # riga 6
                "    def metodo(self):\n"    # NON top-level: escluso
                "        pass\n"
                "\n"
                "async def stream():\n"      # riga 10
                "    pass\n")
            mods = scan_repo(d, ["."], [])
            syms = {s["n"]: s for s in mods["api"]["symbols"]}
            self.assertEqual(syms["top"], {"n": "top", "k": "func",
                                           "f": "api/router.py", "l": 3})
            self.assertEqual(syms["Handler"]["k"], "class")
            self.assertEqual(syms["Handler"]["l"], 6)
            self.assertEqual(syms["stream"]["l"], 10)
            self.assertNotIn("metodo", syms)  # solo top-level, come i set esistenti

    def test_ts_tsx_simboli_con_riga_e_kind(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            ui = os.path.join(d, "ui"); os.makedirs(ui)
            open(os.path.join(ui, "widget.tsx"), "w", encoding="utf-8").write(
                "import React from 'react'\n"        # riga 1
                "export const helper = () => 1\n"    # riga 2 → func (const cade in func)
                "\n"
                "export interface Props {}\n"        # riga 4 → type
                "export class Store {}\n"            # riga 5 → class
                "export default function Widget() {}\n")  # riga 6 → component (maiuscola+tsx)
            mods = scan_repo(d, [], ["."])
            syms = {s["n"]: s for s in mods["ui"]["symbols"]}
            self.assertEqual(syms["helper"], {"n": "helper", "k": "func",
                                              "f": "ui/widget.tsx", "l": 2})
            self.assertEqual(syms["Props"]["k"], "type")
            self.assertEqual(syms["Props"]["l"], 4)
            self.assertEqual(syms["Store"]["k"], "class")
            self.assertEqual(syms["Widget"], {"n": "Widget", "k": "component",
                                              "f": "ui/widget.tsx", "l": 6})

    def test_write_symbol_index_json_per_repo(self):
        import tempfile, json
        from codemap import write_symbol_index, new_mod
        mods = {"api": new_mod(), "db": new_mod()}
        mods["api"]["files"].append("router.py")
        mods["api"]["symbols"].append({"n": "top", "k": "func", "f": "api/router.py", "l": 3})
        mods["api"]["deps"] = {"db", "external"}   # 'external' non è un modulo del repo
        mods["db"]["files"].append("schema.py")
        mods["db"]["symbols"].append({"n": "Schema", "k": "class", "f": "db/schema.py", "l": 1})
        with tempfile.TemporaryDirectory() as d:
            write_symbol_index(mods, "demo", out_dir=d)
            p = os.path.join(d, "_symbol-index-demo.json")
            idx = json.load(open(p, encoding="utf-8"))
            self.assertEqual(idx["repo"], "demo")
            self.assertIn("generated", idx)
            self.assertEqual(idx["module_deps"], {"api": ["db"]})  # filtrate ai moduli noti
            by_name = {s["n"]: s for s in idx["symbols"]}
            self.assertEqual(by_name["top"]["m"], "api")           # modulo aggiunto in scrittura
            self.assertEqual(by_name["Schema"]["m"], "db")
            write_symbol_index(mods, "demo", out_dir=d)            # rigenerazione: overwrite
            idx2 = json.load(open(p, encoding="utf-8"))
            self.assertEqual(len(idx2["symbols"]), 2)              # niente duplicati

    def test_run_repo_scrive_anche_indice(self):
        import tempfile, json
        import codemap as cm
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.join(d, "demo"); os.makedirs(os.path.join(repo, "api"))
            open(os.path.join(repo, "api", "x.py"), "w", encoding="utf-8").write(
                "def f():\n    pass\n")
            out = os.path.join(d, "out")
            cfgp = os.path.join(d, "cfg.json")
            json.dump({"out": out, "projects_root": d,
                       "repos": {"demo": {"dir": "demo", "py": ["."], "ts": []}}},
                      open(cfgp, "w", encoding="utf-8"))
            old = (cm.OUT, cm.PROJECTS_ROOT, cm.REPOS, cm.MIRRORS)
            try:
                cm.apply_config(cfgp)
                cm.run_repo("demo", quiet=True)
                self.assertTrue(os.path.isfile(
                    os.path.join(out, "_symbol-index-demo.json")))
            finally:
                cm.OUT, cm.PROJECTS_ROOT, cm.REPOS, cm.MIRRORS = old


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


class TestMirrorDrift(unittest.TestCase):
    def test_allineati_e_divergenti(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            a = os.path.join(d, "a.py"); b = os.path.join(d, "b.py"); c = os.path.join(d, "c.py")
            open(a, "w").write("x = 1\n"); open(b, "w").write("x = 1\n"); open(c, "w").write("x = 2\n")
            self.assertEqual(mirror_drift({a: b}, base_dir=d), [])                      # identici
            self.assertEqual(mirror_drift({a: c}, base_dir=d), [(a, "DIVERGE")])        # diversi
            self.assertEqual(mirror_drift({a: os.path.join(d, "no.py")}, base_dir=d),
                             [(a, "MIRROR MANCANTE")])

    def test_mirrors_vuoto(self):
        self.assertEqual(mirror_drift({}, base_dir="."), [])


class TestNamespaceRegistry(unittest.TestCase):
    def test_parse_known(self):
        txt = "# Registry\nbla\nknown: esperienza, codemap, progetti\n"
        self.assertEqual(parse_known_namespaces(txt),
                         {"esperienza", "codemap", "progetti"})

    def test_senza_riga_known(self):
        self.assertIsNone(parse_known_namespaces("# Registry senza riga macchina"))

    def test_spazi_e_vuoti(self):
        self.assertEqual(parse_known_namespaces("known: a , b,, c "), {"a", "b", "c"})


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
