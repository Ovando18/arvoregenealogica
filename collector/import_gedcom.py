#!/usr/bin/env python3
"""
collector/import_gedcom.py — Converte um arquivo GEDCOM (.ged) — ou o arquivo do RootsMagic (.rmtree) — em data/family_tree.json.

Fluxo autorizado: exporte a sua árvore do FamilySearch por um programa parceiro
certificado (ex.: RootsMagic Essentials ou Ancestral Quest Basics, gratuitos),
gere um arquivo GEDCOM nesse programa e rode:

    python -m collector.import_gedcom caminho\\para\\arvore.ged

Nada aqui acessa o FamilySearch. A única conexão de rede opcional é a busca de
coordenadas de locais (--geocode) no OpenStreetMap/Nominatim, com cache local.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import unicodedata
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"

FS_PERSON_URL = "https://www.familysearch.org/tree/person/details/{}"
FS_ID_RE = re.compile(r"\b([A-Z0-9]{4}-[A-Z0-9]{3,4})\b")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}

EVENT_TAGS = {
    "BIRT": ("Birth", "Nascimento"), "CHR": ("Christening", "Batismo"), "BAPM": ("Baptism", "Batismo"),
    "CONF": ("Confirmation", "Crisma"), "DEAT": ("Death", "Óbito"), "BURI": ("Burial", "Sepultamento"),
    "CREM": ("Cremation", "Cremação"), "RESI": ("Residence", "Residência"), "OCCU": ("Occupation", "Ocupação"),
    "IMMI": ("Immigration", "Imigração"), "EMIG": ("Emigration", "Emigração"),
    "NATU": ("Naturalization", "Naturalização"), "CENS": ("Census", "Recenseamento"),
    "EDUC": ("Education", "Educação"), "RELI": ("Religion", "Religião"), "NATI": ("Nationality", "Nacionalidade"),
    "TITL": ("Title", "Título"), "GRAD": ("Graduation", "Formatura"), "RETI": ("Retirement", "Aposentadoria"),
    "PROB": ("Probate", "Inventário"), "WILL": ("Will", "Testamento"), "ADOP": ("Adoption", "Adoção"),
    "EVEN": ("Event", "Evento"), "FACT": ("Fact", "Fato"),
    # eventos de casal (FAM)
    "MARR": ("Marriage", "Casamento"), "DIV": ("Divorce", "Divórcio"), "ENGA": ("Engagement", "Noivado"),
    "MARB": ("MarriageBanns", "Proclamas"), "MARC": ("MarriageContract", "Contrato de casamento"),
    "ANUL": ("Annulment", "Anulação"), "DIVF": ("DivorceFiling", "Pedido de divórcio"),
}
MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
MONTHS_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
             "setembro", "outubro", "novembro", "dezembro"]


def log(msg: str) -> None:
    print(msg, flush=True)


def slug(text: str | None) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


# --------------------------------------------------------------------------------------
# Leitura do GEDCOM
# --------------------------------------------------------------------------------------
class GNode:
    __slots__ = ("level", "xref", "tag", "value", "children")

    def __init__(self, level: int, xref: str | None, tag: str, value: str) -> None:
        self.level, self.xref, self.tag, self.value, self.children = level, xref, tag, value, []

    def all(self, *tags: str) -> list["GNode"]:
        return [c for c in self.children if c.tag in tags]

    def first(self, *tags: str) -> "GNode | None":
        return next((c for c in self.children if c.tag in tags), None)

    def val(self, *tags: str) -> str | None:
        node = self.first(*tags)
        return node.value.strip() or None if node else None


LINE_RE = re.compile(r"^\s*(\d+)\s+(?:(@[^@\s]+@)\s+)?([A-Za-z0-9_]+)(?: (.*))?$")


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = raw.decode(enc)
            if "0 HEAD" in text[:200] or enc == "utf-8-sig":
                return text
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1252", errors="replace")


def parse_gedcom(text: str) -> list[GNode]:
    records: list[GNode] = []
    stack: list[GNode] = []
    for line in text.splitlines():
        m = LINE_RE.match(line.rstrip("\r"))
        if not m:
            continue
        level, xref, tag, value = int(m.group(1)), m.group(2), m.group(3).upper(), m.group(4) or ""
        if tag in ("CONC", "CONT") and stack:
            parent = stack[-1] if stack[-1].level == level - 1 else next(
                (n for n in reversed(stack) if n.level == level - 1), stack[-1])
            parent.value += ("\n" if tag == "CONT" else "") + value
            continue
        node = GNode(level, xref.strip("@") if xref else None, tag, value)
        while stack and stack[-1].level >= level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            records.append(node)
        stack.append(node)
    return records


def pointer(value: str | None) -> str | None:
    if value and value.startswith("@") and value.endswith("@") and len(value) > 2:
        return value.strip("@")
    return None


# --------------------------------------------------------------------------------------
# Datas, locais, nomes
# --------------------------------------------------------------------------------------
DATE_PART = re.compile(r"(?:(\d{1,2})\s+)?(?:([A-Z]{3})\s+)?(\d{3,4})(?:/\d{2})?")


def _one_date(text: str) -> tuple[int | None, int | None, int | None]:
    m = DATE_PART.search(text.upper())
    if not m:
        return None, None, None
    day = int(m.group(1)) if m.group(1) else None
    month = MONTHS.get(m.group(2) or "")
    if m.group(2) and not month:
        day = None
    return day, month, int(m.group(3))


def _formal(d, mth, y) -> str:
    out = f"+{y:04d}"
    if mth:
        out += f"-{mth:02d}"
        if d:
            out += f"-{d:02d}"
    return out


def _pt(d, mth, y) -> str:
    if mth and d:
        return f"{d} de {MONTHS_PT[mth - 1]} de {y}"
    if mth:
        return f"{MONTHS_PT[mth - 1]} de {y}"
    return str(y)


def parse_date(text: str | None) -> dict:
    """GEDCOM ('12 MAR 1850', 'ABT 1850', 'BET 1850 AND 1860'…) → original/normalizada/formal/ano."""
    if not text or not text.strip():
        return {}
    original = text.strip()
    up = original.upper()
    words = up.split()
    mod = words[0] if words else ""
    if mod in ("BET", "FROM") and re.search(r"\b(AND|TO)\b", up):
        a, b = re.split(r"\b(?:AND|TO)\b", up, maxsplit=1)
        da, db = _one_date(a), _one_date(b)
        if da[2] and db[2]:
            word = "entre" if mod == "BET" else "de"
            join = "e" if mod == "BET" else "a"
            return {"original": original, "normalized": f"{word} {_pt(*da)} {join} {_pt(*db)}",
                    "formal": f"{_formal(*da)}/{_formal(*db)}", "year": da[2]}
    d, mth, y = _one_date(up)
    if not y:
        return {"original": original, "normalized": None, "formal": None, "year": None}
    normalized, formal = _pt(d, mth, y), _formal(d, mth, y)
    if mod in ("ABT", "CAL", "EST"):
        normalized, formal = f"cerca de {normalized}", "A" + formal
    elif mod == "BEF":
        normalized, formal = f"antes de {normalized}", "/" + formal
    elif mod in ("AFT", "FROM"):
        normalized, formal = f"depois de {normalized}", formal + "/"
    elif mod == "TO":
        normalized, formal = f"até {normalized}", "/" + formal
    return {"original": original, "normalized": normalized, "formal": formal, "year": y}


def parse_coord(value: str | None) -> float | None:
    if not value:
        return None
    v = value.strip().upper().replace(",", ".")
    sign = -1 if v[:1] in ("S", "W") or v.startswith("-") else 1
    try:
        return sign * float(v.lstrip("NSEW+-"))
    except ValueError:
        return None


def parse_place(node: GNode | None) -> dict:
    if node is None or not node.value.strip():
        return {}
    mp = node.first("MAP")
    lat = parse_coord(mp.val("LATI")) if mp else None
    lon = parse_coord(mp.val("LONG")) if mp else None
    text = node.value.strip()
    return {"original": text, "normalized": text, "place_id": None, "lat": lat, "lon": lon}


def parse_name(node: GNode) -> dict:
    raw = node.value.strip()
    m = re.match(r"^(.*?)/(.*?)/(.*)$", raw)
    if m:
        given, surname, suffix = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
    else:
        given, surname, suffix = raw, "", ""
    given = node.val("GIVN") or given
    surname = node.val("SURN") or surname
    full = " ".join(x for x in (node.val("NPFX"), given, surname, suffix or node.val("NSFX")) if x)
    kind = (node.val("TYPE") or "").lower()
    kind = {"aka": "AlsoKnownAs", "married": "MarriedName", "birth": "BirthName", "maiden": "BirthName",
            "nickname": "Nickname", "immigrant": "AlsoKnownAs"}.get(kind, kind.title() or "BirthName")
    return {"full": full or "(sem nome)", "given": given or None, "surname": surname or None,
            "type": kind, "preferred": False, "lang": None}


# --------------------------------------------------------------------------------------
# Importação
# --------------------------------------------------------------------------------------
class GedcomImporter:
    def __init__(self, gedcom_path, opts: argparse.Namespace, data_dir: Path = DATA_DIR) -> None:
        paths = [Path(p) for p in (gedcom_path if isinstance(gedcom_path, (list, tuple)) else [gedcom_path])]
        self.paths = paths
        self.path = paths[0]
        self.opts = opts
        self.data_dir = Path(data_dir)
        self.photos_dir = self.data_dir / "photos"
        recs: list[GNode] = []
        for k, path in enumerate(paths):
            if path.suffix.lower() == ".rmtree":
                from collector.rmtree import rmtree_to_gedcom

                text = rmtree_to_gedcom(path)
            else:
                text = read_text(path)
            if len(paths) > 1:  # xrefs únicos por arquivo; as pessoas se juntam pelo ID do FamilySearch
                text = re.sub(r"@([^@\s]+)@", lambda m, k=k: f"@A{k}_{m.group(1)}@", text)
            recs += parse_gedcom(text)
        self.indis = {r.xref: r for r in recs if r.tag == "INDI" and r.xref}
        self.fams = {r.xref: r for r in recs if r.tag == "FAM" and r.xref}
        self.sources = {r.xref: r for r in recs if r.tag == "SOUR" and r.xref}
        self.notes = {r.xref: r for r in recs if r.tag in ("NOTE", "SNOTE") and r.xref}
        self.objes = {r.xref: r for r in recs if r.tag == "OBJE" and r.xref}
        self.warnings: list[str] = []
        self.media_missing = 0

    # -- utilidades -----------------------------------------------------------------
    def note_text(self, node: GNode) -> str:
        ref = pointer(node.value)
        if ref and ref in self.notes:
            return self.notes[ref].value.strip()
        return node.value.strip()

    @staticmethod
    def find_url(*texts: str | None) -> str | None:
        for t in texts:
            m = re.search(r"https?://[^\s<>\"']+", t or "")
            if m:
                return m.group(0).rstrip(".,;)")
        return None

    def fs_id(self, rec: GNode) -> str | None:
        for tag in ("_FSFTID", "_FSID", "_FID", "FSID", "_FS_ID"):
            v = rec.val(tag)
            if v and FS_ID_RE.fullmatch(v.strip().upper()):
                return v.strip().upper()
        for node in rec.all("REFN", "EXID", "_LINK", "WWW", "_URL"):
            kind = slug(node.val("TYPE") or "")
            m = re.search(r"familysearch\.org/(?:tree/person/(?:details/)?|ark:/61903/4:1:)([A-Z0-9]{4}-[A-Z0-9]{3,4})",
                          node.value, re.I)
            if m:
                return m.group(1).upper()
            if "familysearch" in kind and FS_ID_RE.fullmatch(node.value.strip().upper()):
                return node.value.strip().upper()
        return None

    def citation(self, node: GNode, event_label: str | None, event_date: dict | None) -> dict:
        ref = pointer(node.value)
        src = self.sources.get(ref) if ref else None
        page = node.val("PAGE")
        data = node.first("DATA")
        cdate = parse_date(data.val("DATE")) if data else {}
        ctext = data.val("TEXT") if data else None
        if src:
            title = src.val("TITL") or src.val("ABBR") or "(fonte sem título)"
            parts = [src.val("AUTH"), src.val("PUBL"), page, src.val("TEXT"), ctext]
            url = (src.val("WWW") or src.val("_LINK") or src.val("_URL") or node.val("WWW") or node.val("_LINK")
                   or self.find_url(page, ctext, src.val("TEXT"), src.val("PUBL"), *[self.note_text(n) for n in src.all("NOTE")]))
            notes = [self.note_text(n) for n in src.all("NOTE")]
        else:
            title = node.value.strip() or "(fonte sem título)"
            parts = [page, ctext]
            url = node.val("WWW") or node.val("_LINK") or self.find_url(node.value, page, ctext)
            notes = []
        notes += [self.note_text(n) for n in node.all("NOTE")]
        date = cdate.get("original") or (event_date or {}).get("original")
        return {
            "id": f"{ref or 'inline'}|{page or ''}",
            "title": title,
            "citation": " · ".join(p for p in parts if p) or None,
            "date": date, "event_date": (event_date or {}).get("original"),
            "added": None, "url": url, "resource_type": "", "notes": [n for n in notes if n],
            "tags": [event_label] if event_label else [],
        }

    def parse_event(self, node: GNode) -> tuple[dict, list[dict], list[str]]:
        key, label = EVENT_TAGS[node.tag]
        if node.tag in ("EVEN", "FACT") and node.val("TYPE"):
            label = node.val("TYPE")
            key = re.sub(r"\W+", "", label.title()) or key
        value = node.value.strip()
        if value.upper() in ("Y", "YES"):
            value = None
        date = parse_date(node.val("DATE"))
        fact = {"type": key, "label": label, "value": value or None, "date": date,
                "place": parse_place(node.first("PLAC")), "primary": False}
        cites = [self.citation(s, label, date) for s in node.all("SOUR")]
        notes = [self.note_text(n) for n in node.all("NOTE")]
        return fact, cites, notes

    def media(self, rec: GNode, pid: str) -> tuple[list[dict], str | None]:
        out, photo = [], None
        for i, node in enumerate(rec.all("OBJE")):
            ref = pointer(node.value)
            obj = self.objes.get(ref) if ref else node
            if obj is None:
                continue
            fnode = obj.first("FILE")
            if fnode is None:
                continue
            fpath = fnode.value.strip()
            title = obj.val("TITL") or fnode.val("TITL") or Path(fpath.replace("\\", "/")).stem
            form = (fnode.val("FORM") or obj.val("FORM") or Path(fpath).suffix.lstrip(".")).lower()
            primary = (obj.val("_PRIM") or node.val("_PRIM") or "").upper() in ("Y", "YES")
            mem = {"id": ref or f"{pid}-m{i}", "title": title, "description": obj.val("NOTE"),
                   "media_type": form, "kind": "foto", "url": None, "thumbnail": None, "image": None,
                   "created": None, "local_path": None}
            if fpath.lower().startswith("http"):
                mem["url"] = mem["thumbnail"] = fpath
                out.append(mem)
                continue
            ext = "." + form if not Path(fpath).suffix else Path(fpath).suffix.lower()
            if ext not in IMAGE_EXTS:
                mem["kind"] = "documento"
                out.append(mem)
                continue
            src = self.resolve_media(fpath)
            if src is None:
                self.media_missing += 1
                out.append(mem)
                continue
            if not getattr(self.opts, "no_photos", False):
                dest = self.photos_dir / f"{re.sub(r'[^A-Za-z0-9_-]', '_', pid)}_{len(out)}.jpg"
                if self.copy_image(src, dest):
                    mem["local_path"] = dest.relative_to(self.data_dir).as_posix()
                    if photo is None or primary:
                        photo = mem["local_path"]
            out.append(mem)
        return out, photo

    def resolve_media(self, fpath: str) -> Path | None:
        candidates = [Path(fpath)] + [p.parent / fpath for p in self.paths]
        name = Path(fpath.replace("\\", "/")).name
        for base in [getattr(self.opts, "media_dir", None)] + [p.parent for p in self.paths]:
            if base:
                candidates.append(Path(base) / name)
                candidates.append(Path(base) / fpath.replace("\\", "/"))
        return next((c for c in candidates if c.is_file()), None)

    @staticmethod
    def copy_image(src: Path, dest: Path, max_side: int = 900) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image

            with Image.open(src) as im:
                im = im.convert("RGB")
                im.thumbnail((max_side, max_side))
                im.save(dest, format="JPEG", quality=85)
            return True
        except Exception:
            try:
                shutil.copyfile(src, dest)
                return True
            except OSError:
                return False

    # -- pessoas ------------------------------------------------------------------------
    def build_people(self) -> None:
        self.id_of: dict[str, str] = {}
        seen_fs: set[str] = set()
        for xref, rec in self.indis.items():
            fs = self.fs_id(rec)
            if fs:
                seen_fs.add(fs)
                self.id_of[xref] = fs  # mesma pessoa em arquivos diferentes → um só registro
            else:
                self.id_of[xref] = xref
        self.has_fs_ids = bool(seen_fs)

        self.persons: dict[str, dict] = {}
        for xref, rec in self.indis.items():
            pid = self.id_of[xref]
            names = [parse_name(n) for n in rec.all("NAME")] or [{"full": "(sem nome)", "given": None,
                                                                  "surname": None, "type": "BirthName",
                                                                  "preferred": True, "lang": None}]
            names[0]["preferred"] = True
            facts, sources, notes = [], [], []
            for n in rec.children:
                if n.tag in EVENT_TAGS:
                    fact, cites, enotes = self.parse_event(n)
                    facts.append(fact)
                    sources += cites
                    notes += [{"id": None, "subject": f"Nota — {fact['label']}", "text": t, "modified": None}
                              for t in enotes if t]
            sources += [self.citation(s, None, None) for s in rec.all("SOUR")]
            life_sketch = None
            for n in rec.all("NOTE"):
                text = self.note_text(n)
                if not text:
                    continue
                first_line = slug(text.split("\n", 1)[0])
                if life_sketch is None and any(k in first_line for k in ("life sketch", "esboco de vida", "biografia")):
                    life_sketch = text.split("\n", 1)[1].strip() if "\n" in text else text
                else:
                    notes.append({"id": pointer(n.value), "subject": "Nota", "text": text, "modified": None})
            # fontes sem duplicatas (mesma fonte + página), juntando etiquetas
            merged: dict[str, dict] = {}
            for s in sources:
                if s["id"] in merged:
                    merged[s["id"]]["tags"] = sorted(set(merged[s["id"]]["tags"]) | set(s["tags"]))
                else:
                    merged[s["id"]] = s
            memories, photo = self.media(rec, pid)
            sex = (rec.val("SEX") or "").upper()[:1]
            living_flag = (rec.val("_LIVING") or "").upper()[:1] or None
            old = self.persons.get(pid)
            if old and len(old["facts"]) + len(old["sources"]) >= len(facts) + len(merged):
                continue  # já existe uma versão igual ou mais completa desta pessoa
            self.persons[pid] = {
                "id": pid, "xref": xref, "name": names[0]["full"], "given": names[0]["given"],
                "surname": names[0]["surname"], "gender": sex if sex in ("M", "F") else "?",
                "alt_names": names, "facts": facts, "life_sketch": life_sketch, "notes": notes,
                "sources": list(merged.values()), "memories": memories, "photo": photo, "portrait_url": None,
                "familysearch_url": FS_PERSON_URL.format(pid) if pid != xref else None,
                "_living_flag": living_flag,
            }

        self.edges: set[tuple[str, str]] = set()
        self.couples: dict[str, dict] = {}
        for fx, fam in self.fams.items():
            h = self.id_of.get(pointer(fam.val("HUSB")) or "")
            w = self.id_of.get(pointer(fam.val("WIFE")) or "")
            kids = [self.id_of.get(pointer(c.value) or "") for c in fam.all("CHIL")]
            for k in kids:
                for parent in (h, w):
                    if parent and k:
                        self.edges.add((parent, k))
            if h and w:
                facts = [self.parse_event(n)[0] for n in fam.children if n.tag in EVENT_TAGS]
                key = "|".join(sorted((h, w)))
                self.couples[key] = {"person1": min(h, w), "person2": max(h, w), "facts": facts}
        # pessoas sem FAM explícito, mas com FAMC/FAMS apontando para famílias já lidas, já estão cobertas

    def relatives(self) -> tuple[dict, dict, dict]:
        parents: dict[str, list[str]] = {}
        children: dict[str, list[str]] = {}
        spouses: dict[str, list[str]] = {}
        for p, c in sorted(self.edges):
            parents.setdefault(c, []).append(p)
            children.setdefault(p, []).append(c)
        for c in self.couples.values():
            spouses.setdefault(c["person1"], []).append(c["person2"])
            spouses.setdefault(c["person2"], []).append(c["person1"])
        return parents, children, spouses

    # -- vida / datas resumidas ---------------------------------------------------------
    def summarize(self, rec: dict) -> None:
        facts = rec["facts"]
        birth = next((f for t in ("Birth", "Christening", "Baptism") for f in facts if f["type"] == t), None)
        death = next((f for t in ("Death", "Burial", "Cremation") for f in facts if f["type"] == t), None)
        by = (birth or {}).get("date", {}).get("year")
        dy = (death or {}).get("date", {}).get("year")
        this_year = datetime.now().year
        flag = rec.pop("_living_flag", None)
        if flag in ("Y", "N"):
            living = flag == "Y" and death is None
        else:
            living = death is None and by is not None and by > this_year - 100
        rec["birth_year"] = by
        rec["living"] = bool(living)
        if by or dy or death:
            rec["lifespan"] = f"{by or '?'}–{dy or ('Vivo' if living else 'Falecido')}"
        else:
            rec["lifespan"] = None
        rec["birth_date"] = (birth or {}).get("date", {}).get("original")
        rec["birth_place"] = (birth or {}).get("place", {}).get("original")
        rec["death_date"] = (death or {}).get("date", {}).get("original")
        rec["death_place"] = (death or {}).get("place", {}).get("original")

    # -- base, tronco e colaterais ------------------------------------------------------
    def find_root(self) -> str:
        root = (getattr(self.opts, "root", None) or "").strip()
        if not root and not getattr(self.opts, "root_name", None):
            raise SystemExit("Informe o titular da árvore com --root SEU-ID-FAMILYSEARCH (ou --root-name \"Nome Completo\").")
        if root.upper() in self.persons:
            return root.upper()
        if root.strip("@") in self.id_of:
            return self.id_of[root.strip("@")]
        if not getattr(self.opts, "root_name", None):
            raise SystemExit(f"Não encontrei o titular '{root}' no arquivo. Confira o ID ou use --root-name \"Nome Completo\".")
        wanted = slug(self.opts.root_name)
        matches = [pid for pid, p in self.persons.items()
                   if any(slug(n["full"]) == wanted for n in p["alt_names"])]
        if not matches:
            tokens = wanted.split()
            matches = [pid for pid, p in self.persons.items()
                       if all(t in slug(" ".join(n["full"] for n in p["alt_names"])) for t in tokens)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise SystemExit("Mais de uma pessoa corresponde ao titular: " + ", ".join(
                f"{self.persons[m]['name']} ({m})" for m in matches) + ". Use --root com o ID.")
        raise SystemExit(f"Não encontrei o titular '{root or wanted}' no GEDCOM. "
                         "Use --root <ID FamilySearch ou @I123@> ou --root-name \"Nome Completo\".")

    def run(self) -> dict:
        self.build_people()
        parents, children, spouses = self.relatives()
        for rec in self.persons.values():
            self.summarize(rec)

        root = self.find_root()
        exp_spouse = slug(getattr(self.opts, "expected_spouse", None) or "")
        cands = spouses.get(root, [])
        spouse = getattr(self.opts, "spouse_id", None)
        if spouse and spouse not in self.persons:
            spouse = self.id_of.get(spouse.strip("@"))
        if not spouse:
            named = [s for s in cands if exp_spouse and exp_spouse in slug(self.persons[s]["name"])]
            shared = sorted(cands, key=lambda s: -len(set(children.get(s, [])) & set(children.get(root, []))))
            spouse = (named or shared or [None])[0]
        kids = sorted(set(children.get(root, [])) & set(children.get(spouse, []))) if spouse else children.get(root, [])
        kids = sorted(kids, key=lambda k: (self.persons[k].get("birth_year") is None, self.persons[k].get("birth_year") or 0))
        log(f"👤 Titular: {self.persons[root]['name']} ({root})")
        log(f"👪 Cônjuge: {self.persons[spouse]['name']} ({spouse})" if spouse else "⚠️  Cônjuge não encontrado.")
        log("👶 Filhos (base): " + (", ".join(f"{self.persons[k]['name']} ({k})" for k in kids) or "nenhum"))
        for name in getattr(self.opts, "expected_children", None) or ():
            if not any(slug(name) in slug(self.persons[k]["name"]) for k in kids):
                self.warnings.append(f"Não encontrei '{name}' entre os filhos do casal.")

        max_gen = self.opts.generations
        trunk: dict[str, dict] = {}

        def add_trunk(pid, gen, lineage):
            t = trunk.get(pid)
            if t is None:
                trunk[pid] = {"generation": gen, "lineage": {lineage}}
                return True
            changed = gen < t["generation"] or lineage not in t["lineage"]
            t["generation"] = min(t["generation"], gen)
            t["lineage"].add(lineage)
            return changed

        for k in kids:
            trunk[k] = {"generation": 0, "lineage": {"titular", "conjuge"}}
        queue = deque([(root, 1, "titular")] + ([(spouse, 1, "conjuge")] if spouse else []))
        while queue:
            pid, gen, lin = queue.popleft()
            if not add_trunk(pid, gen, lin) and pid not in (root, spouse):
                continue
            if gen < max_gen:
                for par in parents.get(pid, []):
                    queue.append((par, gen + 1, lin))

        # colaterais: todos os parentes conectados ao tronco (BFS por parentesco)
        info: dict[str, dict] = {pid: {"generation": t["generation"], "lineage": set(t["lineage"]), "depth": 0}
                                 for pid, t in trunk.items()}
        limit = getattr(self.opts, "collateral_depth", None)
        bfs = deque(sorted(trunk, key=lambda p: trunk[p]["generation"]))
        while bfs:
            pid = bfs.popleft()
            cur = info[pid]
            if limit is not None and cur["depth"] >= limit:
                continue
            for rel, delta in ((parents.get(pid, []), 1), (children.get(pid, []), -1), (spouses.get(pid, []), 0)):
                for other in rel:
                    if other in info:
                        continue
                    info[other] = {"generation": cur["generation"] + delta, "lineage": set(cur["lineage"]),
                                   "depth": cur["depth"] + 1}
                    bfs.append(other)

        persons_out: dict[str, dict] = {}
        for pid, i in info.items():
            rec = dict(self.persons[pid])
            t = trunk.get(pid)
            rec.update({
                "generation": i["generation"],
                "is_direct_ancestor": bool(t) and t["generation"] >= 1,
                "role": ("base" if t["generation"] == 0 else "ancestor") if t else "collateral",
                "lineage": sorted(i["lineage"]),
                "collateral_depth": i["depth"],
                "details_loaded": True,
            })
            persons_out[pid] = rec
        skipped = len(self.persons) - len(persons_out)

        if getattr(self.opts, "geocode", False):
            self.geocode(persons_out)

        edges = sorted((p, c) for p, c in self.edges if p in persons_out and c in persons_out)
        couples = sorted((c for c in self.couples.values()
                          if c["person1"] in persons_out and c["person2"] in persons_out),
                         key=lambda c: (c["person1"], c["person2"]))
        par_o: dict[str, list] = {}
        chi_o: dict[str, list] = {}
        spo_o: dict[str, list] = {}
        for p, c in edges:
            par_o.setdefault(c, []).append(p)
            chi_o.setdefault(p, []).append(c)
        for c in couples:
            spo_o.setdefault(c["person1"], []).append(c["person2"])
            spo_o.setdefault(c["person2"], []).append(c["person1"])
        for pid, rec in persons_out.items():
            rec["parents"], rec["children"], rec["spouses"] = par_o.get(pid, []), chi_o.get(pid, []), spo_o.get(pid, [])

        trunk_gens = [t["generation"] for t in trunk.values()]
        meta = {
            "source": "Importado de " + ", ".join(p.name for p in self.paths),
            "gedcom_file": ", ".join(p.name for p in self.paths),
            "root_id": root, "spouse_id": spouse, "children_ids": kids,
            "max_generations": max_gen,
            "generations_reached": max(trunk_gens) if trunk_gens else 0,
            "persons_total": len(persons_out), "persons_with_details": len(persons_out),
            "persons_not_connected": skipped,
            "sources_total": sum(len(r["sources"]) for r in persons_out.values()),
            "memories_total": sum(len(r["memories"]) for r in persons_out.values()),
            "has_familysearch_ids": self.has_fs_ids,
            "complete": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        if not self.has_fs_ids:
            self.warnings.append("O GEDCOM não trouxe IDs do FamilySearch; os links para o FamilySearch "
                                 "não aparecerão e as pessoas usarão os IDs internos do arquivo.")
        if self.media_missing:
            self.warnings.append(f"{self.media_missing} arquivo(s) de imagem citados no GEDCOM não foram "
                                 "encontrados; use --media-dir apontando para a pasta de mídia.")
        if skipped:
            self.warnings.append(f"{skipped} pessoa(s) do arquivo não têm parentesco com a base e foram ignoradas.")
        return {
            "meta": meta,
            "persons": persons_out,
            "relationships": {"parent_child": [list(e) for e in edges], "couples": couples},
        }

    # -- coordenadas (opcional) ---------------------------------------------------------
    def geocode(self, persons: dict) -> None:
        import requests

        cache_file = self.data_dir / "places_cache.json"
        cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
        facts = [f for r in persons.values() for f in r["facts"]] + \
                [f for c in self.couples.values() for f in c["facts"]]
        todo = sorted({f["place"]["original"] for f in facts
                       if f.get("place", {}).get("original") and f["place"].get("lat") is None} - set(cache))
        if todo:
            log(f"🗺️  Buscando coordenadas de {len(todo)} local(is) no OpenStreetMap (1 por segundo)…")
        headers = {"User-Agent": "arvore-genealogica-familiar/1.0 (uso pessoal, nao comercial)"}
        for i, place in enumerate(todo, 1):
            parts = [p.strip() for p in place.split(",") if p.strip()]
            result = None
            while parts and result is None:
                time.sleep(1.1)  # política de uso do Nominatim: no máximo 1 requisição/segundo
                try:
                    r = requests.get("https://nominatim.openstreetmap.org/search",
                                     params={"q": ", ".join(parts), "format": "json", "limit": 1},
                                     headers=headers, timeout=30)
                    data = r.json() if r.ok else []
                except Exception:
                    data = []
                if data:
                    result = {"lat": float(data[0]["lat"]), "lon": float(data[0]["lon"]),
                              "matched": ", ".join(parts)}
                elif len(parts) > 1:
                    parts = parts[1:]  # tenta o nível acima (cidade → estado → país)
                else:
                    break
            cache[place] = result
            if i % 20 == 0 or i == len(todo):
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
                log(f"   {i}/{len(todo)}")
        for f in facts:
            pl = f.get("place") or {}
            hit = cache.get(pl.get("original") or "")
            if hit and pl.get("lat") is None:
                pl["lat"], pl["lon"] = hit["lat"], hit["lon"]


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Importa um arquivo GEDCOM para data/family_tree.json.")
    ap.add_argument("gedcom", nargs="+",
                    help="Arquivo(s) .ged ou .rmtree. Vários arquivos são combinados pelo ID do FamilySearch")
    ap.add_argument("--root", default=None, help="ID FamilySearch (ex.: ABCD-123) ou @I123@ do titular da árvore")
    ap.add_argument("--root-name", default=None, help="Nome completo do titular, se o arquivo não tiver IDs")
    ap.add_argument("--spouse-name", dest="expected_spouse", default=None,
                    help="Parte do nome do cônjuge, para escolher entre vários cônjuges")
    ap.add_argument("--expect-children", dest="expected_children", default=None,
                    type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
                    help='Nomes dos filhos esperados, para conferência (ex.: "Ana,Pedro")')
    ap.add_argument("--spouse-id", default=None, help="ID do cônjuge, se a detecção automática falhar")
    ap.add_argument("--generations", type=int, default=14, help="Gerações a partir dos filhos (padrão %(default)s)")
    ap.add_argument("--collateral-depth", type=int, default=None,
                    help="Distância máxima (em parentescos) a partir do tronco. Padrão: todos os conectados")
    ap.add_argument("--media-dir", default=None, help="Pasta onde estão as fotos citadas no GEDCOM")
    ap.add_argument("--no-photos", action="store_true", help="Não copiar fotos para data/photos/")
    ap.add_argument("--geocode", action="store_true",
                    help="Buscar coordenadas dos locais no OpenStreetMap (cache em data/places_cache.json)")
    ap.add_argument("--output", default=str(DATA_DIR / "family_tree.json"))
    return ap.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    paths = [Path(p) for p in args.gedcom]
    for path in paths:
        if not path.is_file():
            log(f"Arquivo não encontrado: {path}")
            return 1
    out = Path(args.output)
    importer = GedcomImporter(paths, args, data_dir=out.parent)
    tree = importer.run()
    write_json(out, tree)
    m = tree["meta"]
    log(f"✅ {m['persons_total']} pessoas · {m['generations_reached']} gerações · "
        f"{m['sources_total']} fontes · {m['memories_total']} mídias → {out}")
    for w in importer.warnings:
        log(f"⚠️  {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
