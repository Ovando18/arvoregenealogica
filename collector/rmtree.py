"""
Leitura direta de um arquivo do RootsMagic (.rmtree, versões 8 a 12), que é um banco
SQLite. O conteúdo é convertido para texto GEDCOM e então processado pelo mesmo
importador (`collector/import_gedcom.py`), sem precisar exportar o GEDCOM no RootsMagic.

O arquivo é aberto SOMENTE PARA LEITURA.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
NAME_TYPES = {1: "aka", 2: "birth", 3: "immigrant", 4: "maiden", 5: "married", 6: "nickname", 7: "aka"}
APPROX = set("ACELS?123456")


def _one(sign: str, digits: str) -> str | None:
    if len(digits) < 8 or not digits.isdigit():
        return None
    y, m, d = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
    if not y:
        return None
    parts = []
    if d and m:
        parts.append(str(d))
    if 1 <= m <= 12:
        parts.append(MONTHS[m - 1])
    parts.append(str(y) + (" B.C." if sign == "-" else ""))
    return " ".join(parts)


def rm_date(value: str | None) -> str | None:
    """Converte o formato interno do RootsMagic ('D.+19830618..+00000000..') para GEDCOM."""
    if not value or value == ".":
        return None
    if value[0] == "T":
        return value[1:].strip() or None
    if value[0] != "D" or len(value) < 11:
        return None
    mod = value[1]
    d1 = _one(value[2], value[3:11])
    qual = value[12] if len(value) > 12 else "."
    d2 = _one(value[13], value[14:22]) if len(value) >= 22 else None
    if not d1:
        return None
    if mod == "R" and d2:
        return f"BET {d1} AND {d2}"
    if mod == "S" and d2:
        return f"FROM {d1} TO {d2}"
    prefix = {"B": "BEF ", "A": "AFT ", "F": "FROM ", "T": "TO ", "Y": "BEF ", "U": "BEF ", "Z": "AFT "}.get(mod, "")
    if not prefix and qual in APPROX:
        prefix = "ABT "
    return prefix + d1


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def _note_lines(level: int, text: str) -> list[str]:
    lines = str(text).replace("\r", "").split("\n")
    out = [f"{level} NOTE {lines[0]}"]
    out += [f"{level + 1} CONT {ln}" for ln in lines[1:]]
    return out


def rmtree_to_gedcom(path: Path) -> str:
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    con.create_collation("RMNOCASE", lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()))
    try:
        q = lambda sql: con.execute(sql).fetchall()
        facts = {r[0]: (r[1], (r[2] or "").strip().upper()) for r in q("SELECT FactTypeID, Name, GedcomTag FROM FactTypeTable")}
        places = {}
        for pid, name, lat, lon in q("SELECT PlaceID, Name, Latitude, Longitude FROM PlaceTable"):
            places[pid] = (_clean(name), (lat or 0) / 1e7, (lon or 0) / 1e7)
        fsids = {r[0]: r[1] for r in q("SELECT rmID, fsID FROM FamilySearchTable WHERE LinkType = 0 AND fsID <> ''")}
        names: dict[int, list] = {}
        for owner, sur, given, pre, suf, ntype, primary in q(
                "SELECT OwnerID, Surname, Given, Prefix, Suffix, NameType, IsPrimary FROM NameTable "
                "ORDER BY OwnerID, IsPrimary DESC, NameID"):
            names.setdefault(owner, []).append((_clean(sur), _clean(given), _clean(pre), _clean(suf), ntype, primary))
        events: dict[tuple[int, int], list] = {}
        for etype, otype, owner, place, date, details, note in q(
                "SELECT EventType, OwnerType, OwnerID, PlaceID, Date, Details, Note FROM EventTable "
                "ORDER BY OwnerType, OwnerID, SortDate, EventID"):
            events.setdefault((otype, owner), []).append((etype, place, date, details, note))

        def event_lines(evs) -> list[str]:
            out = []
            for etype, place, date, details, note in evs:
                name, tag = facts.get(etype, ("Evento", "EVEN"))
                if not tag or tag.startswith("_") and tag not in ("_MILT",):
                    tag = "EVEN"
                details = _clean(details)
                out.append(f"1 {tag}" + (f" {details}" if details and tag != "EVEN" else ""))
                if tag == "EVEN":
                    out.append(f"2 TYPE {name}")
                    if details:
                        out += _note_lines(2, details)
                gdate = rm_date(date)
                if gdate:
                    out.append(f"2 DATE {gdate}")
                if place and place in places and places[place][0]:
                    pname, lat, lon = places[place]
                    out.append(f"2 PLAC {pname}")
                    if lat or lon:
                        out += ["3 MAP", f"4 LATI {'N' if lat >= 0 else 'S'}{abs(lat):.5f}",
                                f"4 LONG {'E' if lon >= 0 else 'W'}{abs(lon):.5f}"]
                if note and note.strip():
                    out += _note_lines(2, note.strip())
            return out

        lines = ["0 HEAD", "1 SOUR ROOTSMAGIC_RMTREE", "1 GEDC", "2 VERS 5.5.1", "1 CHAR UTF-8"]
        for pid, sex, living, note in q("SELECT PersonID, Sex, Living, Note FROM PersonTable ORDER BY PersonID"):
            lines.append(f"0 @I{pid}@ INDI")
            for sur, given, pre, suf, ntype, primary in names.get(pid, []) or [("", "", "", "", 0, 1)]:
                lines.append(f"1 NAME {given} /{sur}/" + (f" {suf}" if suf else ""))
                if given:
                    lines.append(f"2 GIVN {given}")
                if sur:
                    lines.append(f"2 SURN {sur}")
                if pre:
                    lines.append(f"2 NPFX {pre}")
                if not primary and ntype in NAME_TYPES:
                    lines.append(f"2 TYPE {NAME_TYPES[ntype]}")
            lines.append(f"1 SEX {({0: 'M', 1: 'F'}).get(sex, 'U')}")
            lines.append(f"1 _LIVING {'Y' if living else 'N'}")
            if pid in fsids:
                lines.append(f"1 _FSFTID {fsids[pid]}")
            lines += event_lines(events.get((0, pid), []))
            if note and note.strip():
                lines += _note_lines(1, note.strip())

        children: dict[int, list[int]] = {}
        for child, fam in q("SELECT ChildID, FamilyID FROM ChildTable ORDER BY FamilyID, ChildOrder"):
            children.setdefault(fam, []).append(child)
        for fid, father, mother, note in q("SELECT FamilyID, FatherID, MotherID, Note FROM FamilyTable ORDER BY FamilyID"):
            lines.append(f"0 @F{fid}@ FAM")
            if father:
                lines.append(f"1 HUSB @I{father}@")
            if mother:
                lines.append(f"1 WIFE @I{mother}@")
            for c in children.get(fid, []):
                lines.append(f"1 CHIL @I{c}@")
            lines += event_lines(events.get((1, fid), []))
            if note and note.strip():
                lines += _note_lines(1, note.strip())
        lines.append("0 TRLR")
        return "\n".join(lines) + "\n"
    finally:
        con.close()
