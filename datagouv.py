#!/usr/bin/env python3
"""datagouv.py — explorer data.gouv.fr (open data français) et générer des programmes d'exploitation.

Sous-commandes (aucune clé API requise ; lecture seule sur le réseau) :
  chercher <mots…>            jeux de données correspondant aux mots-clés (numérotés)
  apis <mots…>                API (« dataservices ») correspondant aux mots-clés
  infos <n|id>                détail d'un jeu de données : producteur, licence, fichiers (numérotés)
  squelette <n|id> [fichier]  génère un programme Python autonome (pandas) pour un fichier CSV/XLSX
  siren <9 chiffres>          fiche d'une entreprise : état administratif (Sirene) + procédures collectives (BODACC)
  --check                     diagnostic : joint data.gouv.fr et vérifie la structure des réponses
  aide                        cette aide

<n> est le numéro affiché par la dernière commande « chercher » ; <id> est l'identifiant
(ou « slug ») du jeu de données. Le fichier est son numéro dans « infos » (défaut : le 1er CSV).

Le programme généré est écrit dans ./programmes/ à côté de ce script ; il n'est JAMAIS exécuté ici.
La commande « siren » lit la clé d'API Sirene (portail-api.insee.fr) dans le fichier .env placé à côté
de ce script (ligne INSEE_API_KEY_SIREN=...) ; elle n'est jamais affichée.
Dépendances : bibliothèque standard uniquement (le programme généré utilise pandas + matplotlib).
"""
import ipaddress
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = Path(os.environ.get("DATAGOUV_OUT", HERE / "programmes"))
LAST_FILE = HERE / "datagouv_last.json"     # derniers résultats de « chercher » (pour « infos 3 »)

API = "https://www.data.gouv.fr/api/1"
TABULAR = "https://tabular-api.data.gouv.fr/api"
# Seuls ces hôtes servent aux requêtes JSON (le reste est refusé).
JSON_HOSTS = {"www.data.gouv.fr", "data.gouv.fr", "tabular-api.data.gouv.fr"}
UA = "Mozilla/5.0 (X11; Linux aarch64) datagouv.py/1.0"
TIMEOUT = 25
JSON_MAX = 2_000_000
SNIFF_BYTES = 200_000
PAGE_SIZE = 8

_ID_RE = re.compile(r"^[0-9a-f]{24}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,150}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class DGError(Exception):
    pass


# ─────────────────────────── réseau ───────────────────────────
def _host_is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for fam, _t, _p, _c, sa in infos:
        ip = ipaddress.ip_address(sa[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return bool(infos)


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl, getattr(req, "_dg_hosts", None))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _check_url(url: str, hosts=None):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or not p.hostname:
        raise DGError("seules les adresses https sont acceptées")
    if hosts is not None and p.hostname not in hosts:
        raise DGError(f"hôte non autorisé : {p.hostname}")
    if not _host_is_public(p.hostname):
        raise DGError(f"adresse non publique refusée : {p.hostname}")


def _read(url: str, max_bytes: int, hosts=None, accept="*/*", range_bytes=None, headers=None) -> bytes:
    _check_url(url, hosts)
    hdrs = {"User-Agent": UA, "Accept": accept, "Accept-Encoding": "identity"}
    if headers:
        hdrs.update(headers)
    if range_bytes:
        hdrs["Range"] = f"bytes=0-{range_bytes - 1}"
    req = urllib.request.Request(url, headers=hdrs)
    req._dg_hosts = hosts
    opener = urllib.request.build_opener(_Redirect)
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            return r.read(max_bytes)
    except DGError:
        raise
    except urllib.error.HTTPError as e:
        raise DGError(f"HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        raise DGError(f"connexion impossible : {e.reason}")
    except Exception as e:
        raise DGError(f"{type(e).__name__} : {e}")


def get_json(url: str):
    raw = _read(url, JSON_MAX, hosts=JSON_HOSTS, accept="application/json")
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise DGError("réponse non JSON (service indisponible ?)")


# ─────────────────────────── utilitaires ───────────────────────────
def _clean(s, n=80) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _kw(words) -> str:
    q = " ".join(w for w in words if w)
    q = re.sub(r"[^\w\sÀ-ÿ'’-]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()[:100]
    return q


def _date(x) -> str:
    return str(x or "")[:10] or "?"


def _org(d: dict) -> str:
    o = d.get("organization")
    if isinstance(o, dict) and o.get("name"):
        return _clean(o["name"], 40)
    ow = d.get("owner")
    if isinstance(ow, dict):
        n = ow.get("slug") or ow.get("first_name") or ""
        if n:
            return _clean(n, 40)
    return "?"


def _formats(d: dict) -> str:
    fm = []
    for r in d.get("resources") or []:
        f = str(r.get("format") or "").strip().lower()
        if f and f not in fm:
            fm.append(f)
    return ",".join(fm[:5]) or "?"


def _size(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for u in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or u == "Go":
            return f"{n:.0f} {u}" if u == "o" else f"{n:.1f} {u}"
        n /= 1024
    return "?"


def _items(js) -> list:
    if isinstance(js, dict) and isinstance(js.get("data"), list):
        return [x for x in js["data"] if isinstance(x, dict)]
    return []


def _save_last(kind: str, items: list):
    try:
        LAST_FILE.write_text(json.dumps(
            {"kind": kind, "items": [{"id": i.get("id"), "slug": i.get("slug"), "title": i.get("title")}
                                     for i in items]}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def resolve_dataset(ref: str) -> str:
    """Numéro (dernière recherche) → id ; id ou slug → tel quel après validation stricte."""
    ref = (ref or "").strip().lower()
    if ref.isdigit() and len(ref) <= 2:
        try:
            last = json.loads(LAST_FILE.read_text(encoding="utf-8"))
            if last.get("kind") != "datasets":
                raise DGError("le dernier résultat n'est pas une liste de jeux de données ; relancez « chercher »")
            it = last["items"][int(ref) - 1]
            ref = str(it.get("id") or it.get("slug") or "").lower()
        except (OSError, ValueError, IndexError, KeyError):
            raise DGError(f"n° {ref} inconnu : lancez d'abord « chercher <mots> »")
    if _ID_RE.match(ref) or _SLUG_RE.match(ref):
        return ref
    raise DGError("référence invalide (n° d'un résultat, identifiant de 24 caractères ou slug)")


def get_dataset(ref: str) -> dict:
    js = get_json(f"{API}/datasets/{urllib.parse.quote(resolve_dataset(ref))}/")
    if not isinstance(js, dict) or not js.get("id"):
        raise DGError("jeu de données introuvable")
    return js


def _is_tabular(r: dict) -> bool:
    return str(r.get("format") or "").strip().lower() in ("csv", "tsv", "xlsx", "xls")


# ─────────────────────────── commandes ───────────────────────────
def cmd_chercher(words):
    q = _kw(words)
    if not q:
        return "❌ Usage : chercher <mots-clés>   ex : chercher entreprises redressement"
    js = get_json(f"{API}/datasets/?q={urllib.parse.quote(q)}&page_size={PAGE_SIZE}&sort=-last_modified")
    items = _items(js)
    total = js.get("total") if isinstance(js, dict) else None
    if not items:
        return f"🔍 Aucun jeu de données pour « {q} ». Essayez des mots plus généraux."
    _save_last("datasets", items)
    out = [f"🔍 data.gouv.fr — « {q} » : {total if total is not None else len(items)} jeu(x), {len(items)} affiché(s)"]
    for i, d in enumerate(items, 1):
        out.append(f"{i}. {_clean(d.get('title'), 75)}\n   {_org(d)} · {_formats(d)} · maj {_date(d.get('last_modified') or d.get('last_update'))}")
    out.append("→ détail : infos <n°>    → programme : squelette <n°>")
    return "\n".join(out)


def cmd_apis(words):
    q = _kw(words)
    if not q:
        return "❌ Usage : apis <mots-clés>   ex : apis entreprises"
    js = get_json(f"{API}/dataservices/?q={urllib.parse.quote(q)}&page_size={PAGE_SIZE}")
    items = _items(js)
    if not items:
        return f"🔍 Aucune API pour « {q} »."
    out = [f"🔌 API data.gouv.fr — « {q} » : {len(items)} affichée(s)"]
    for i, d in enumerate(items, 1):
        url = d.get("base_api_url") or d.get("machine_documentation_url") or d.get("self_web_url") or ""
        out.append(f"{i}. {_clean(d.get('title'), 75)}\n   {_org(d)}" + (f" · {_clean(url, 70)}" if url else ""))
    return "\n".join(out)


def cmd_infos(ref):
    d = get_dataset(ref)
    out = [f"📊 {_clean(d.get('title'), 100)}",
           f"Producteur : {_org(d)} · Licence : {_clean(d.get('license') or '?', 30)} · maj {_date(d.get('last_modified') or d.get('last_update'))}",
           f"id : {d.get('id')}"]
    desc = _clean(d.get("description"), 300)
    if desc:
        out.append(desc)
    res = [r for r in (d.get("resources") or []) if isinstance(r, dict)]
    out.append(f"Fichiers ({len(res)}) :")
    for i, r in enumerate(res[:12], 1):
        out.append(f"{i}. [{str(r.get('format') or '?').lower()}] {_clean(r.get('title'), 55)} · {_size(r.get('filesize'))} · maj {_date(r.get('last_modified'))}")
    if len(res) > 12:
        out.append(f"… +{len(res) - 12} autre(s)")
    if d.get("page"):
        out.append(f"Page : {d['page']}")
    out.append(f"→ programme : squelette {ref} [n° de fichier]")
    return "\n".join(out)


# ─────────────────────────── squelette ───────────────────────────
def _columns_from_profile(rid: str):
    try:
        js = get_json(f"{TABULAR}/resources/{urllib.parse.quote(rid)}/profile/")
    except DGError:
        return None
    prof = js.get("profile") if isinstance(js, dict) else None
    if isinstance(prof, dict):
        cols = prof.get("header")
        if isinstance(cols, list) and cols:
            return [str(c) for c in cols][:200]
        cols = prof.get("columns")
        if isinstance(cols, dict) and cols:
            return [str(c) for c in cols][:200]
    return None


def _columns_from_sample(url: str):
    """Entête d'un CSV lu sur les premiers Ko (repli si le profil n'est pas disponible)."""
    try:
        raw = _read(url, SNIFF_BYTES, accept="text/csv,*/*", range_bytes=SNIFF_BYTES)
    except DGError:
        return None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    first = text.splitlines()[0] if text.splitlines() else ""
    sep = max((";", ",", "\t", "|"), key=first.count)
    cols = [c.strip().strip('"') for c in first.split(sep)]
    return [c for c in cols if c][:200] or None


_TEMPLATE = r'''#!/usr/bin/env python3
"""Programme généré par datagouv.py — exploitation d'un fichier de data.gouv.fr.

Jeu de données : __TITLE__
Producteur     : __ORG__   ·   Licence : __LICENSE__
Page           : __PAGE__
Généré le      : __DATE__

Le programme télécharge le fichier une fois (dossier donnees/), puis le lit et l'analyse.
Dépendances : pandas, matplotlib (et openpyxl pour un fichier Excel).

Exemples :
  python3 __NAME__ --colonnes
  python3 __NAME__ --apercu 20
  python3 __NAME__ --filtre "COLONNE=valeur" --apercu 20
  python3 __NAME__ --top COLONNE 15
  python3 __NAME__ --graphe COLONNE --sortie graphique.png
  python3 __NAME__ --export extrait.csv --filtre "COLONNE=valeur"
Les données sont celles du producteur : vérifiez leur date et leur licence avant tout usage.
"""
import argparse
import sys
import urllib.request
from pathlib import Path

import pandas as pd

URL = __URL__
FORMAT = __FORMAT__
COLONNES_CONNUES = __COLUMNS__          # indicatif : la lecture réelle fait foi
DOSSIER = Path(__file__).resolve().parent / "donnees"
FICHIER = DOSSIER / __LOCAL__


def telecharger(force=False):
    DOSSIER.mkdir(exist_ok=True)
    if FICHIER.exists() and not force:
        return FICHIER
    print(f"Téléchargement : {URL}")
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (programme datagouv)"})
    with urllib.request.urlopen(req, timeout=120) as r, open(FICHIER, "wb") as f:
        while True:
            bloc = r.read(1 << 20)
            if not bloc:
                break
            f.write(bloc)
    return FICHIER


def lire():
    chemin = telecharger()
    if FORMAT in ("xlsx", "xls"):
        return pd.read_excel(chemin)
    # CSV français : séparateur « ; » ou « , », encodage UTF-8 ou Latin-1, virgule décimale
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(chemin, sep=None, engine="python", encoding=enc,
                               decimal=",", dtype_backend="numpy_nullable")
        except UnicodeDecodeError:
            continue
    sys.exit("Lecture impossible (encodage inconnu).")


def appliquer_filtre(df, filtre):
    if not filtre:
        return df
    if "=" not in filtre:
        sys.exit("Filtre attendu : COLONNE=valeur")
    col, val = filtre.split("=", 1)
    col = col.strip()
    if col not in df.columns:
        sys.exit(f"Colonne inconnue : {col}  (voir --colonnes)")
    return df[df[col].astype(str).str.contains(val.strip(), case=False, na=False, regex=False)]


def main():
    p = argparse.ArgumentParser(description="Exploitation d'un fichier data.gouv.fr")
    p.add_argument("--maj", action="store_true", help="retélécharger le fichier")
    p.add_argument("--colonnes", action="store_true", help="liste des colonnes, types et valeurs manquantes")
    p.add_argument("--apercu", type=int, metavar="N", help="affiche N lignes")
    p.add_argument("--filtre", metavar="COL=valeur", help="garde les lignes dont COL contient valeur")
    p.add_argument("--top", nargs=2, metavar=("COL", "N"), help="N valeurs les plus fréquentes de COL")
    p.add_argument("--graphe", metavar="COL", help="histogramme (numérique) ou barres (texte) de COL")
    p.add_argument("--sortie", default="graphique.png", help="fichier image du graphique")
    p.add_argument("--export", metavar="FICHIER.csv", help="enregistre les lignes retenues")
    a = p.parse_args()

    if a.maj:
        telecharger(force=True)
    df = appliquer_filtre(lire(), a.filtre)
    print(f"{len(df)} ligne(s) × {len(df.columns)} colonne(s)")

    if a.colonnes or not any([a.apercu, a.top, a.graphe, a.export]):
        for c in df.columns:
            print(f"  {c:<40} {str(df[c].dtype):<12} manquants : {int(df[c].isna().sum())}")
    if a.apercu:
        with pd.option_context("display.max_columns", 30, "display.width", 200):
            print(df.head(a.apercu).to_string())
    if a.top:
        col, n = a.top[0], int(a.top[1])
        if col not in df.columns:
            sys.exit(f"Colonne inconnue : {col}")
        print(df[col].value_counts(dropna=False).head(n).to_string())
    if a.graphe:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        if a.graphe not in df.columns:
            sys.exit(f"Colonne inconnue : {a.graphe}")
        fig, ax = plt.subplots(figsize=(9, 5))
        if pd.api.types.is_numeric_dtype(df[a.graphe]):
            df[a.graphe].dropna().plot.hist(bins=30, ax=ax)
        else:
            df[a.graphe].value_counts().head(20).plot.barh(ax=ax)
            ax.invert_yaxis()
        ax.set_title(a.graphe)
        fig.tight_layout()
        fig.savefig(a.sortie, dpi=120)
        print(f"Graphique enregistré : {a.sortie}")
    if a.export:
        df.to_csv(a.export, index=False, sep=";", encoding="utf-8-sig")
        print(f"Export : {a.export}")


if __name__ == "__main__":
    main()
'''


def _py(v) -> str:
    """Littéral Python sûr (aucune chaîne du réseau n'est insérée telle quelle dans le code)."""
    return json.dumps(v, ensure_ascii=False)


def cmd_squelette(ref, num=None):
    from datetime import date
    d = get_dataset(ref)
    res = [r for r in (d.get("resources") or []) if isinstance(r, dict)]
    if not res:
        return "❌ Ce jeu de données ne contient aucun fichier."
    if num:
        if not num.isdigit() or not 1 <= int(num) <= len(res):
            return f"❌ Fichier n° {num} inconnu (1 à {len(res)}, voir « infos »)."
        r = res[int(num) - 1]
    else:
        r = next((x for x in res if _is_tabular(x)), None)
        if r is None:
            return "❌ Aucun fichier CSV/Excel dans ce jeu de données (formats : " + _formats(d) + ")."
    fmt = str(r.get("format") or "").strip().lower()
    if not _is_tabular(r):
        return f"❌ Le fichier choisi est au format « {fmt or '?'} » : seuls CSV/TSV/XLSX sont gérés."
    url = str(r.get("url") or "")
    try:
        _check_url(url)
    except DGError as e:
        return f"❌ Adresse du fichier inutilisable : {e}"
    size = r.get("filesize")
    prefix = ""
    if isinstance(size, (int, float)) and size > 200 * 1024 * 1024:
        prefix = f"⚠️ Fichier volumineux ({_size(size)}) : le programme le téléchargera en entier.\n"
    rid = str(r.get("id") or "")
    cols = (_columns_from_profile(rid) if _UUID_RE.match(rid) else None) or \
           (_columns_from_sample(url) if fmt in ("csv", "tsv") else None) or []
    slug = re.sub(r"[^a-z0-9]+", "_", str(d.get("slug") or d.get("id")).lower()).strip("_")[:40] or "donnees"
    name = f"exploiter_{slug}.py"
    local = f"{slug}.{fmt if fmt in ('xlsx', 'xls') else 'csv'}"
    code = (_TEMPLATE
            .replace("__TITLE__", _clean(d.get("title"), 120).replace('"""', "'"))
            .replace("__ORG__", _org(d).replace('"""', "'"))
            .replace("__LICENSE__", _clean(d.get("license") or "?", 40).replace('"""', "'"))
            .replace("__PAGE__", _clean(d.get("page") or "?", 150).replace('"""', "'"))
            .replace("__DATE__", date.today().isoformat())
            .replace("__NAME__", name)
            .replace("__URL__", _py(url))
            .replace("__FORMAT__", _py(fmt))
            .replace("__COLUMNS__", _py(cols))
            .replace("__LOCAL__", _py(local)))
    try:
        compile(code, name, "exec")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / name
        path.write_text(code, encoding="utf-8")
    except (SyntaxError, OSError) as e:
        return f"❌ Génération impossible : {e}"
    lignes = [prefix + f"✅ Programme généré : {path}",
              f"Fichier : [{fmt}] {_clean(r.get('title'), 60)} · {_size(size)}",
              f"Colonnes ({len(cols)}) : " + (", ".join(_clean(c, 25) for c in cols[:15]) + (" …" if len(cols) > 15 else "") if cols else "lues au premier lancement"),
              f"Essai : cd {OUT_DIR} && python3 {name} --colonnes"]
    return "\n".join(lignes)


# ─────────────────────────── entreprise (SIREN) ───────────────────────────
SIRENE_URL = "https://api.insee.fr/api-sirene/3.11/siren/"
SIRENE_HEADERS = ("X-INSEE-Api-Key-Integration", "X-INSEE-ApiKey-Integration")   # 2e forme tentée si la 1re est refusée (401)
BODACC_URL = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
KEY_NAMES = ("INSEE_API_KEY_SIREN", "INSEE_API_KEY")
ENV_FILE = HERE / ".env"
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-\.]{8,200}$")


def _load_key() -> str:
    """Clé Sirene : variable d'environnement, sinon fichier .env voisin. Jamais affichée ni journalisée."""
    for n in KEY_NAMES:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        raise DGError(f"clé Sirene introuvable : créez {ENV_FILE} avec une ligne INSEE_API_KEY_SIREN=...")
    vals = {}
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        vals[k.strip()] = v.strip().strip('"').strip("'")
    for n in KEY_NAMES:
        if vals.get(n):
            return vals[n]
    raise DGError(f"aucune ligne INSEE_API_KEY_SIREN=... dans {ENV_FILE}")


def _env_perm_warning() -> str:
    try:
        if ENV_FILE.exists() and ENV_FILE.stat().st_mode & 0o077:
            return f"⚠️ {ENV_FILE.name} est lisible par d'autres comptes : chmod 600 {ENV_FILE}"
    except OSError:
        pass
    return ""


def _valid_siren(s: str) -> bool:
    if not re.fullmatch(r"\d{9}", s):
        return False
    if s == "356000000":          # La Poste : exception connue à la clé de contrôle
        return True
    tot = 0
    for i, ch in enumerate(s):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        tot += d
    return tot % 10 == 0


def _sirene_get(siren: str) -> dict:
    key = _load_key()
    if not _KEY_RE.match(key):
        raise DGError("la clé du fichier .env a un format inattendu (espaces, guillemets ou caractères étrangers ?)")
    last = None
    for hdr in SIRENE_HEADERS:
        try:
            raw = _read(SIRENE_URL + siren, JSON_MAX, hosts={"api.insee.fr"}, accept="application/json", headers={hdr: key})
            return json.loads(raw.decode("utf-8", "replace"))
        except DGError as e:
            last = str(e)
            if "HTTP 401" in last:
                continue
            break
        except ValueError:
            raise DGError("réponse Sirene non JSON")
    if "HTTP 401" in (last or ""):
        raise DGError("clé refusée par l'INSEE (401) : vérifiez la clé et la souscription à l'API Sirene")
    if "HTTP 404" in (last or ""):
        raise DGError(f"SIREN {siren} inconnu de la base Sirene")
    if "HTTP 403" in (last or ""):
        raise DGError(f"SIREN {siren} non accessible (403) : entreprise non diffusible, ou souscription inactive")
    if "HTTP 429" in (last or ""):
        raise DGError("quota INSEE atteint (429) : réessayez dans une minute")
    raise DGError(last or "erreur Sirene")


def _bodacc_collectives(siren: str):
    """Annonces de procédures collectives pour ce SIREN (liste), ou None si le BODACC est injoignable."""
    spaced = f"{siren[:3]} {siren[3:6]} {siren[6:]}"
    where_forms = (f'search(registre, "{spaced}")', f'registre:"{spaced}"', f'registre like "{spaced}"')
    data = None
    for w in where_forms:
        q = urllib.parse.urlencode({"where": w, "order_by": "dateparution desc", "limit": 50})
        try:
            raw = _read(f"{BODACC_URL}?{q}", JSON_MAX, hosts={"bodacc-datadila.opendatasoft.com"}, accept="application/json")
            data = json.loads(raw.decode("utf-8", "replace"))
            break
        except (DGError, ValueError):
            continue
    if not isinstance(data, dict):
        return None
    out = []
    for r in data.get("results") or []:
        if not isinstance(r, dict):
            continue
        fam = f"{r.get('familleavis', '')} {r.get('familleavis_lib', '')}".lower()
        if "collective" in fam:
            out.append(r)
    return out


def _jugement_text(r: dict) -> str:
    j = r.get("jugement")
    if isinstance(j, str):
        try:
            j = json.loads(j)
        except ValueError:
            j = {"nature": j}
    if isinstance(j, dict):
        return _clean(j.get("nature") or j.get("famille") or j.get("complementJugement") or "", 60)
    return ""


_EFFECTIFS = {"NN": "non renseigné", "00": "0 salarié", "01": "1-2", "02": "3-5", "03": "6-9", "11": "10-19", "12": "20-49",
              "21": "50-99", "22": "100-199", "31": "200-249", "32": "250-499", "41": "500-999", "42": "1 000-1 999",
              "51": "2 000-4 999", "52": "5 000-9 999", "53": "10 000+"}


def cmd_siren(words):
    siren = re.sub(r"\D", "", "".join(words))
    if not _valid_siren(siren):
        return "❌ Usage : siren <9 chiffres>  (numéro absent ou clé de contrôle invalide)"
    js = _sirene_get(siren)
    ul = js.get("uniteLegale") if isinstance(js, dict) else None
    if not isinstance(ul, dict):
        raise DGError("réponse Sirene inattendue")
    per = [p for p in (ul.get("periodesUniteLegale") or []) if isinstance(p, dict)]
    cur = per[0] if per else {}
    cj = str(cur.get("categorieJuridiqueUniteLegale") or ul.get("categorieJuridiqueUniteLegale") or "")
    cree = _date(ul.get("dateCreationUniteLegale"))
    if cj.startswith("1"):
        return (f"👤 SIREN {siren} : entrepreneur individuel (personne physique). Les données personnelles ne sont pas détaillées ici.\n"
                f"Création : {cree}")
    etat = {"A": "✅ en activité", "C": "⛔ cessée"}.get(cur.get("etatAdministratifUniteLegale"), "état inconnu")
    nom = _clean(cur.get("denominationUniteLegale") or ul.get("denominationUniteLegale") or "(dénomination non diffusée)", 80)
    out = [f"🏢 {nom} — SIREN {siren}", f"État : {etat}" + (f" depuis le {_date(cur.get('dateDebut'))}" if cur.get("etatAdministratifUniteLegale") == "C" else ""),
           f"Création : {cree} · NAF : {cur.get('activitePrincipaleUniteLegale') or '?'} · catégorie juridique : {cj or '?'}"]
    eff = str(ul.get("trancheEffectifsUniteLegale") or "")
    if eff:
        out.append(f"Effectifs : {_EFFECTIFS.get(eff, eff)}" + (f" (année {ul['anneeEffectifsUniteLegale']})" if ul.get("anneeEffectifsUniteLegale") else ""))
    bod = _bodacc_collectives(siren)
    if bod is None:
        out.append("⚠️ BODACC injoignable : procédures collectives non vérifiées.")
    elif not bod:
        out.append("⚖️ BODACC : aucune annonce de procédure collective trouvée.")
    else:
        out.append(f"⚖️ BODACC : {len(bod)} annonce(s) de procédure collective (plus récentes d'abord)")
        for r in bod[:5]:
            out.append(f"  {_date(r.get('dateparution'))} · {_clean(r.get('typeavis_lib') or r.get('typeavis'), 30)} · {_jugement_text(r) or _clean(r.get('familleavis_lib'), 40)} · {_clean(r.get('tribunal'), 35)}")
    w = _env_perm_warning()
    if w:
        out.append(w)
    out.append("Sources : API Sirene (INSEE), BODACC (DILA). À vérifier sur bodacc.fr avant toute décision.")
    return "\n".join(out)


# ─────────────────────────── diagnostic ───────────────────────────
def cmd_check():
    out = []
    try:
        js = get_json(f"{API}/datasets/?q=entreprises&page_size=1")
        it = _items(js)
        out.append(f"✅ datasets : clés {sorted(js)[:8]} ; total={js.get('total')}")
        if it:
            d = it[0]
            out.append(f"   élément : {sorted(d)[:14]}")
            res = d.get("resources") or []
            if res and isinstance(res[0], dict):
                out.append(f"   fichier : {sorted(res[0])[:12]}")
            org = d.get("organization")
            out.append(f"   organisation : {'ok' if isinstance(org, dict) and org.get('name') else 'absente/autre forme'}")
    except DGError as e:
        out.append(f"❌ datasets : {e}")
    try:
        js = get_json(f"{API}/dataservices/?q=entreprises&page_size=1")
        it = _items(js)
        out.append(f"✅ dataservices : {len(it)} élément(s)" + (f" ; clés {sorted(it[0])[:10]}" if it else ""))
    except DGError as e:
        out.append(f"❌ dataservices : {e}")
    try:
        js = get_json(f"{TABULAR}/resources/00000000-0000-0000-0000-000000000000/profile/")
        out.append("ℹ️ tabular : réponse reçue")
    except DGError as e:
        out.append(f"ℹ️ tabular : {e} (404 attendu avec un faux identifiant : service joignable)")
    try:
        _load_key()
        out.append("✅ clé Sirene trouvée (.env)")
        ul = (_sirene_get("120027016") or {}).get("uniteLegale") or {}
        out.append(f"✅ Sirene : réponse reçue ; clés {sorted(ul)[:8]}")
    except DGError as e:
        out.append(f"❌ Sirene : {e}")
    try:
        b = _bodacc_collectives("120027016")
        out.append("✅ BODACC joignable" if b is not None else "❌ BODACC : aucune des requêtes n'a abouti")
    except DGError as e:
        out.append(f"❌ BODACC : {e}")
    return "\n".join(out)


def main(argv):
    if not argv or argv[0] in ("aide", "-h", "--help", "help"):
        return (__doc__ or "").strip()
    cmd, rest = argv[0].lower().lstrip("-"), argv[1:]
    try:
        if cmd in ("chercher", "search"):
            return cmd_chercher(rest)
        if cmd in ("apis", "api"):
            return cmd_apis(rest)
        if cmd == "infos":
            return cmd_infos(rest[0]) if rest else "❌ Usage : infos <n°|id>"
        if cmd in ("squelette", "skeleton"):
            return cmd_squelette(rest[0], rest[1] if len(rest) > 1 else None) if rest else "❌ Usage : squelette <n°|id> [n° de fichier]"
        if cmd == "siren":
            return cmd_siren(rest) if rest else "❌ Usage : siren <9 chiffres>"
        if cmd == "check":
            return cmd_check()
    except DGError as e:
        return f"❌ {e}"
    return f"❌ Commande inconnue : {argv[0]}\n\n" + (__doc__ or "").strip().split("\n\n")[0]


if __name__ == "__main__":
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except Exception:
        pass
    print(main(sys.argv[1:]))
