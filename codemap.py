#!/usr/bin/env python3
"""
codemap — decostruisce repo (Python + TS/TSX/JS/JSX) in note markdown per il vault.
Estensione Synapse al codice. Zero dipendenze (stdlib `ast` + regex).

USO
  python codemap.py --all                     # rigenera tutti i repo configurati
  python codemap.py --repo <slug>             # rigenera un repo configurato
  python codemap.py <repo_path> <repo_name>   # ad-hoc, repo non configurato
  python codemap.py --install-hooks [slug…]   # installa post-commit hook (default: tutti)
  python codemap.py --uninstall-hooks [slug…] # rimuove gli hook installati da noi
  python codemap.py --list                    # mostra i repo configurati
  python codemap.py --check-fresh             # monitor: commit vs note (exit 1 se stale)
  python codemap.py --config <path> …         # config alternativa (default: accanto al file)

CONFIG: codemap.config.json accanto a questo file (vedi codemap.config.example.json).

Genera vault/codemap/<repo>-code-<modulo>.md (namespace separato da /esperienza/).
READ-ONLY sui repo (gli hook vivono in .git/hooks/, mai nei sorgenti).
Note rigenerabili (auto-generate, confidence: extracted).
"""
import os, ast, re, sys, json
from collections import defaultdict

try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

# Config esterna: codemap.config.json accanto a questo file (o --config <path>).
# Schema: {"out": <dir note md>, "projects_root": <root dei repo>,
#          "repos": {slug: {"dir": <subdir>|"path": <abs>, "py": [...], "ts": [...]}}}
# Lo slug diventa il prefisso delle note (<slug>-code-<mod>) e quindi lo scope
# in synapse.py (project_of). Se aggiungi uno slug, allinea SCOPE_ALIASES lì.
CONFIG_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codemap.config.json")

def load_config(path=None):
    p = path or CONFIG_DEFAULT
    if not os.path.isfile(p):
        return {"out": "", "projects_root": "", "repos": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def apply_config(path=None):
    """Carica la config nei globals (chiamata a import e, se --config, in main)."""
    global OUT, PROJECTS_ROOT, REPOS
    cfg = load_config(path)
    OUT = cfg.get("out", "")
    PROJECTS_ROOT = cfg.get("projects_root", "")
    REPOS = cfg.get("repos", {})
    return cfg

apply_config()

EXCLUDE = {"tests", "alembic", "node_modules", ".venv", "venv", "__pycache__",
           "migrations", "dist", "build", ".next", ".git", ".embed_cache",
           "playwright-report", "coverage"}
MAX_JS_BYTES = 300_000  # sopra: quasi certamente bundle — skip
TS_EXT = (".ts", ".tsx", ".js", ".jsx")

TS_EXPORT = re.compile(
    r"export\s+(?:default\s+)?(?:async\s+)?"
    r"(?:(function|class|const|interface|type)\s+([A-Za-z_]\w*))")
TS_IMPORT = re.compile(r"from\s+['\"]((?:@/|\.\.?/)[^'\"]+)['\"]")

HOOK_MARKER = "synapse-codemap auto-regen"


def mod_key_for(rel_dir):
    """Ultimo segmento utile del path (salta route-group Next.js '(x)' e dynamic '[x]')."""
    parts = [p for p in rel_dir.replace("\\", "/").split("/")
             if p and p != "." and not (p.startswith("(") and p.endswith(")"))
             and not p.startswith("[")]
    return parts[-1] if parts else "root"


def skip_js(filename, size):
    """Guardia anti-bundle: salta minificati e .js/.jsx enormi."""
    if not filename.endswith((".js", ".jsx")):
        return False
    return ".min." in filename or size > MAX_JS_BYTES


def new_mod():
    return {"files": [], "classes": set(), "funcs": set(),
            "components": set(), "types": set(), "deps": set(), "lang": set()}


def scan_repo(repo_path, include_py, include_ts):
    """Decostruisce un repo in moduli. READ-ONLY."""
    mods = defaultdict(new_mod)

    # --- Python (stdlib ast) ---
    for inc in include_py:
        base = os.path.normpath(os.path.join(repo_path, inc))
        if not os.path.isdir(base): continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in EXCLUDE and not d.startswith(".")]
            for fn in files:
                if not fn.endswith(".py") or fn == "__init__.py": continue
                path = os.path.join(root, fn)
                rel = os.path.relpath(path, repo_path).replace("\\", "/")
                m = mods[mod_key_for(os.path.dirname(rel))]
                try: tree = ast.parse(open(path, encoding="utf-8").read())
                except Exception: continue
                m["files"].append(os.path.basename(rel)); m["lang"].add("py")
                for node in tree.body:
                    if isinstance(node, ast.ClassDef): m["classes"].add(node.name)
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m["funcs"].add(node.name)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        parts = node.module.split(".")
                        if "api" in parts or "openswarm" in parts or (node.level or 0) > 0:
                            if parts[-1]: m["deps"].add(parts[-1])

    # --- TypeScript / TSX / JS / JSX (regex leggero) ---
    for inc in include_ts:
        base = os.path.normpath(os.path.join(repo_path, inc))
        if not os.path.isdir(base): continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in EXCLUDE and not d.startswith(".")]
            for fn in files:
                if not fn.endswith(TS_EXT): continue
                path = os.path.join(root, fn)
                try: size = os.path.getsize(path)
                except OSError: continue
                if skip_js(fn, size): continue
                rel = os.path.relpath(path, repo_path).replace("\\", "/")
                m = mods[mod_key_for(os.path.dirname(rel))]
                try: txt = open(path, encoding="utf-8").read()
                except Exception: continue
                ext = fn.rsplit(".", 1)[-1]
                m["files"].append(os.path.basename(rel)); m["lang"].add(ext)
                for kind, name in TS_EXPORT.findall(txt):
                    if kind == "class": m["classes"].add(name)
                    elif kind in ("interface", "type"): m["types"].add(name)
                    elif name[:1].isupper() and ext in ("tsx", "jsx"):
                        m["components"].add(name)
                    else: m["funcs"].add(name)
                for imp in TS_IMPORT.findall(txt):
                    seg = [p for p in imp.replace("@/", "").split("/")
                           if p and p not in (".", "..")]
                    if seg:
                        m["deps"].add(mod_key_for("/".join(seg[:-1])) if len(seg) > 1 else seg[0])
    return mods


def write_notes(mods, repo_name, out_dir=None, clean=True, quiet=False):
    """Scrive le note. clean=True rimuove prima le note stale di QUESTO repo."""
    if out_dir is None: out_dir = OUT
    os.makedirs(out_dir, exist_ok=True)
    removed = 0
    if clean:
        prefix = f"{repo_name}-code-"
        for fn in os.listdir(out_dir):
            if fn.startswith(prefix) and fn.endswith(".md"):
                try: os.remove(os.path.join(out_dir, fn)); removed += 1
                except OSError: pass
    known = set(mods.keys()); written = 0
    for mod_key, m in sorted(mods.items()):
        if not m["files"]: continue
        slug = f"{repo_name}-code-{mod_key}"
        deps = sorted(d for d in m["deps"] if d in known and d != mod_key)
        langs = "+".join(sorted(m["lang"]))
        L = [f"# {repo_name} · modulo {mod_key} ({langs})", ""]
        L.append(f"> code-map auto-generata (`codemap.py`, repo {repo_name}). Rigenerabile, confidence: extracted. Namespace /codemap/.")
        L.append("")
        L.append(f"**File** ({len(m['files'])}): " + ", ".join(sorted(set(m['files']))[:25]))
        if m["classes"]:    L.append("\n**Classi**: " + ", ".join(sorted(m["classes"])[:30]))
        if m["components"]: L.append("\n**Componenti UI**: " + ", ".join(sorted(m["components"])[:30]))
        if m["funcs"]:      L.append("\n**Funzioni/const esportate**: " + ", ".join(sorted(m["funcs"])[:30]))
        if m["types"]:      L.append("\n**Tipi/interfacce**: " + ", ".join(sorted(m["types"])[:20]))
        if deps:
            L.append("\n**Dipende da** (import interni):")
            L += [f"- [[codemap/{repo_name}-code-{d}]]" for d in deps]
        open(os.path.join(out_dir, slug + ".md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
        written += 1
    if not quiet:
        print(f"  [{repo_name}] {written} moduli scritti, {removed} note stale rimosse")
        print(f"  [{repo_name}] moduli: {', '.join(sorted(known))[:260]}")
    return written, removed


def repo_path_of(slug):
    cfg = REPOS[slug]
    if cfg.get("path"): return cfg["path"]          # path assoluto esplicito
    return os.path.join(PROJECTS_ROOT, cfg["dir"])


def run_repo(slug, quiet=False):
    cfg = REPOS[slug]
    path = repo_path_of(slug)
    if not os.path.isdir(path):
        if not quiet: print(f"  [{slug}] SKIP — path non trovato: {path}")
        return 0, 0
    mods = scan_repo(path, cfg["py"], cfg["ts"])
    return write_notes(mods, slug, quiet=quiet)


# --- auto-regen: post-commit hook -------------------------------------------
def make_hook_script(slug):
    """Hook POSIX sh (git-for-windows lo esegue con la sua sh).
    Non deve MAI bloccare il commit: exit 0 sempre."""
    me = os.path.abspath(__file__).replace("\\", "/")
    return (f"#!/bin/sh\n"
            f"# {HOOK_MARKER} — installato da codemap.py --install-hooks\n"
            f"# Rigenera la code-map di questo repo nel vault dopo ogni commit.\n"
            f"python \"{me}\" --repo {slug} --quiet 2>/dev/null "
            f"|| py -3 \"{me}\" --repo {slug} --quiet 2>/dev/null "
            f"|| echo \"[{HOOK_MARKER}] regen fallita (non bloccante)\"\n"
            f"exit 0\n")


def install_hook(slug, uninstall=False):
    """Idempotente e defensive: non tocca hook altrui."""
    hooks_dir = os.path.join(repo_path_of(slug), ".git", "hooks")
    if not os.path.isdir(hooks_dir):
        return f"  [{slug}] SKIP — non è un repo git ({hooks_dir})"
    target = os.path.join(hooks_dir, "post-commit")
    exists = os.path.isfile(target)
    current = open(target, encoding="utf-8", errors="replace").read() if exists else ""
    ours = HOOK_MARKER in current
    if uninstall:
        if not exists:  return f"  [{slug}] ok — nessun hook presente"
        if not ours:    return f"  [{slug}] LASCIATO — post-commit esistente NON nostro"
        os.remove(target); return f"  [{slug}] RIMOSSO post-commit"
    if exists and not ours:
        return f"  [{slug}] ⚠️ SALTATO — esiste un post-commit NON nostro (non sovrascrivo)"
    open(target, "w", encoding="utf-8", newline="\n").write(make_hook_script(slug))
    try: os.chmod(target, 0o755)
    except OSError: pass
    return f"  [{slug}] hook {'aggiornato' if ours else 'installato'} → {target}"


DRIFT_THRESHOLD = 30  # commit dopo l'ultimo touch di CLAUDE.md -> audit consigliato

def parse_known_namespaces(registry_text):
    """Estrae il set 'known:' dalla riga machine-readable del registry."""
    m = re.search(r"^known:\s*(.+)$", registry_text, re.M)
    if not m: return None
    return {t.strip() for t in m.group(1).split(",") if t.strip()}

def vault_namespace_drift():
    """Confronta le dir top-level del vault col registry meta/vault-namespaces.md.
    Ritorna (nuove, registry_path) — nuove = dir non dichiarate. None se registry assente."""
    vault_root = os.path.dirname(OUT)  # OUT = <vault>/codemap
    reg = os.path.join(vault_root, "meta", "vault-namespaces.md")
    if not os.path.isfile(reg): return None, reg
    known = parse_known_namespaces(open(reg, encoding="utf-8", errors="replace").read())
    if known is None: return None, reg
    actual = {d for d in os.listdir(vault_root)
              if os.path.isdir(os.path.join(vault_root, d)) and not d.startswith(".")}
    return sorted(actual - known), reg

def governance_drift(path, fname="CLAUDE.md"):
    """(data ultimo touch, n commit dopo) del file governance nel repo.
    (None, None) se file assente o mai committato."""
    import subprocess
    if not os.path.isfile(os.path.join(path, fname)): return None, None
    try:
        last = subprocess.run(
            ["git", "-C", path, "log", "-1", "--format=%H|%ad",
             "--date=format:%m-%d", "--", fname],
            capture_output=True, text=True, timeout=15).stdout.strip()
        if not last: return None, None
        sha, date = last.split("|", 1)
        n = int(subprocess.run(
            ["git", "-C", path, "rev-list", "--count", f"{sha}..HEAD"],
            capture_output=True, text=True, timeout=15).stdout.strip() or 0)
        return date, n
    except Exception:
        return None, None


def check_fresh():
    """Monitor auto-regen: per ogni repo, ultimo commit vs note più recenti.
    Se un commit è più nuovo delle note (+60s margine) l'hook NON ha girato.
    Exit code 1 se almeno un repo è STALE (utile per scheduling).
    In coda: governance drift (CLAUDE.md) — SOLO warning, non cambia l'exit code
    (drift cronico non deve mascherare i guasti veri dell'auto-regen)."""
    import subprocess, datetime
    stale = []
    print(f"  {'repo':<10} {'ultimo commit':<17} {'note codemap':<17} verdict")
    for slug in REPOS:
        path = repo_path_of(slug)
        if not os.path.isdir(os.path.join(path, ".git")):
            print(f"  {slug:<10} {'—':<17} {'—':<17} SKIP (no git)"); continue
        try:
            out = subprocess.run(["git", "-C", path, "log", "-1", "--format=%ct"],
                                 capture_output=True, text=True, timeout=15)
            commit_ts = int(out.stdout.strip() or 0)
        except Exception:
            print(f"  {slug:<10} {'?':<17} {'?':<17} SKIP (git error)"); continue
        prefix = f"{slug}-code-"
        try:
            note_ts = max((os.path.getmtime(os.path.join(OUT, fn))
                           for fn in os.listdir(OUT)
                           if fn.startswith(prefix) and fn.endswith(".md")), default=0)
        except OSError:
            note_ts = 0
        fmt = lambda t: datetime.datetime.fromtimestamp(t).strftime("%m-%d %H:%M") if t else "mai"
        ok = note_ts + 60 >= commit_ts
        if not ok: stale.append(slug)
        print(f"  {slug:<10} {fmt(commit_ts):<17} {fmt(note_ts):<17} {'FRESH ✓' if ok else 'STALE ✗ (hook non ha girato)'}")
    # --- governance drift (livello 1: solo detection, mai exit!=0) ---
    drifted = []
    print(f"\n  {'repo':<10} {'CLAUDE.md':<12} {'commit dopo':<12} governance")
    for slug in REPOS:
        date, n = governance_drift(repo_path_of(slug))
        if date is None:
            print(f"  {slug:<10} {'—':<12} {'—':<12} (assente o mai committato)"); continue
        warn = n > DRIFT_THRESHOLD
        if warn: drifted.append((slug, n))
        print(f"  {slug:<10} {date:<12} {n:<12} {'⚠️ AUDIT consigliato (>' + str(DRIFT_THRESHOLD) + ')' if warn else 'ok'}")
    if drifted:
        tops = ", ".join(f"{s} ({n})" for s, n in sorted(drifted, key=lambda x: -x[1]))
        print(f"\n  ⚠️ governance drift: {tops}")
        print("     → audit con /claude-md-improver sul repo (proposta automatica = livello 2, non attivo)")

    # --- namespace drift vault (livello 1: solo detection) ---
    new_ns, reg = vault_namespace_drift()
    if new_ns is None:
        print(f"\n  (namespace check saltato — registry assente: {reg})")
    elif new_ns:
        print(f"\n  ⚠️ NAMESPACE NON DICHIARATI nel vault: {', '.join(new_ns)}")
        print(f"     → registrali in meta/vault-namespaces.md (scopo, schema, consumer, known:)")
    else:
        print("\n  namespace vault: tutti dichiarati nel registry ✓")

    if stale:
        print(f"\n  ⚠️ STALE: {', '.join(stale)} — verifica .git/hooks/post-commit in quei repo")
        sys.exit(1)
    print("\n  monitor ok — code-map tutte fresche" + (", governance drift segnalato sopra" if drifted else " e governance in linea"))


# --- CLI ---------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    quiet = "--quiet" in args
    args = [a for a in args if a != "--quiet"]

    if "--config" in args:
        i = args.index("--config")
        apply_config(args[i + 1] if i + 1 < len(args) else None)
        args = args[:i] + args[i + 2:]

    needs_config = any(f in args for f in
                       ("--all", "--repo", "--list", "--install-hooks",
                        "--uninstall-hooks", "--check-fresh"))
    if needs_config and not REPOS:
        print("  config mancante o vuota: crea codemap.config.json accanto a codemap.py")
        print("  (vedi codemap.config.example.json) oppure passa --config <path>")
        sys.exit(1)

    if "--list" in args:
        for slug, cfg in REPOS.items():
            mark = "✓" if os.path.isdir(repo_path_of(slug)) else "✗ path mancante"
            print(f"  {slug:<10} {cfg['dir']:<18} {mark}")
        return

    if "--check-fresh" in args:
        check_fresh()
        return

    if "--install-hooks" in args or "--uninstall-hooks" in args:
        un = "--uninstall-hooks" in args
        flag = "--uninstall-hooks" if un else "--install-hooks"
        sel = [a for a in args[args.index(flag) + 1:] if not a.startswith("--")]
        for slug in (sel or list(REPOS)):
            if slug not in REPOS: print(f"  [{slug}] slug sconosciuto"); continue
            print(install_hook(slug, uninstall=un))
        return

    if "--all" in args:
        tot_w = tot_r = 0
        for slug in REPOS:
            w, r = run_repo(slug, quiet=quiet)
            tot_w += w; tot_r += r
        print(f"  TOTALE: {tot_w} moduli in {OUT} ({tot_r} stale rimosse)")
        return

    if "--repo" in args:
        i = args.index("--repo")
        slug = args[i + 1] if i + 1 < len(args) else None
        if slug not in REPOS:
            print(f"  slug sconosciuto: {slug!r} — usa --list"); sys.exit(1)
        run_repo(slug, quiet=quiet)
        return

    # retro-compat: posizionale <repo_path> <repo_name> (ad-hoc, non configurato)
    if len(args) >= 2 and not args[0].startswith("--"):
        mods = scan_repo(args[0], ["."], ["."])
        write_notes(mods, args[1], quiet=quiet)
        return

    print(__doc__)


if __name__ == "__main__":
    main()
