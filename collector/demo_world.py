"""
Família genealógica FICTÍCIA, exportada como arquivo GEDCOM. Serve para:

* testar o importador (`collector/import_gedcom.py`);
* gerar `data/sample/family_tree.json`, usado pelo painel enquanto a árvore real
  ainda não foi importada.

Todos os nomes, datas, locais, fontes e imagens aqui são inventados.
"""
from __future__ import annotations

import io
import random

GX = "http://gedcomx.org/"
FS = "http://familysearch.org/v1/"

MALE = ["João", "José", "Antônio", "Manuel", "Francisco", "Joaquim", "Pedro", "Luís", "Bento", "Domingos",
        "Inácio", "Sebastião", "Miguel", "Tomé", "Gaspar", "Custódio", "Valentim", "Raimundo", "Benedito", "Caetano"]
FEMALE = ["Maria", "Ana", "Joana", "Francisca", "Rita", "Teresa", "Rosa", "Luzia", "Josefa", "Inês",
          "Antônia", "Gertrudes", "Quitéria", "Emília", "Leonor", "Isabel", "Brígida", "Bárbara", "Clara", "Delfina"]
SURNAMES = ["Albuquerque", "Moreira", "Teixeira", "Barros", "Fontes", "Valadares", "Sampaio", "Quintela",
            "Rebelo", "Gouveia", "Pinheiro", "Seixas", "Lobato", "Caldeira", "Bastos", "Coutinho",
            "Brandão", "Falcão", "Mourão", "Paiva", "Lacerda", "Vieira", "Tavares", "Bettencourt",
            "Fontana", "Benedetti", "Castellani", "Otero", "Saavedra", "Arruda"]
OCCUPATIONS = ["Lavrador", "Tropeiro", "Comerciante", "Ferreiro", "Professora", "Costureira", "Alfaiate",
               "Fazendeiro", "Mestre de obras", "Escrivão", "Boticário", "Marinheiro", "Tecelã", "Ourives"]
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]

PLACES = {
    "P01": ("Cuiabá, Mato Grosso, Brasil", -15.601, -56.097),
    "P02": ("Corumbá, Mato Grosso do Sul, Brasil", -19.009, -57.651),
    "P03": ("Cidade de Goiás, Goiás, Brasil", -15.934, -50.140),
    "P04": ("Campo Grande, Mato Grosso do Sul, Brasil", -20.469, -54.620),
    "P05": ("São João del-Rei, Minas Gerais, Brasil", -21.136, -44.261),
    "P06": ("Ouro Preto, Minas Gerais, Brasil", -20.386, -43.504),
    "P07": ("Rio de Janeiro, Rio de Janeiro, Brasil", -22.907, -43.173),
    "P08": ("São Paulo, São Paulo, Brasil", -23.551, -46.633),
    "P09": ("Diamantina, Minas Gerais, Brasil", -18.241, -43.600),
    "P10": ("Braga, Portugal", 41.545, -8.426),
    "P11": ("Viana do Castelo, Portugal", 41.693, -8.833),
    "P12": ("Porto, Portugal", 41.150, -8.611),
    "P13": ("Lisboa, Portugal", 38.722, -9.139),
    "P14": ("Angra do Heroísmo, Açores, Portugal", 38.654, -27.218),
    "P15": ("Ourense, Galicia, España", 42.336, -7.864),
    "P16": ("Lucca, Toscana, Italia", 43.843, 10.502),
    "P17": ("Treviso, Veneto, Italia", 45.666, 12.243),
    "P18": ("Assunção, Paraguai", -25.264, -57.575),
    "P19": ("Cáceres, Mato Grosso, Brasil", -16.071, -57.679),
    "P20": ("Mariana, Minas Gerais, Brasil", -20.378, -43.416),
}
REGIONS = {
    ("titular", "near"): ["P01", "P02", "P04", "P19"],
    ("titular", "mid"): ["P01", "P03", "P19", "P18", "P08"],
    ("titular", "far"): ["P10", "P11", "P12", "P14", "P15"],
    ("conjuge", "near"): ["P05", "P07", "P08", "P09"],
    ("conjuge", "mid"): ["P05", "P06", "P09", "P20", "P07"],
    ("conjuge", "far"): ["P12", "P13", "P16", "P17", "P14"],
}
SOURCE_TITLES = [
    ("Brasil, Registros da Igreja Católica, 1640-1940", "Batismo"),
    ("Brasil, Registro Civil, 1870-2012", "Nascimento"),
    ("Portugal, Registros Paroquiais Católicos, 1570-1910", "Batismo"),
    ("Brasil, Casamentos, 1730-1955", "Casamento"),
    ("Brasil, Óbitos, 1850-1990", "Óbito"),
    ("Recenseamento Geral do Império, 1872", "Recenseamento"),
    ("Brasil, Cartões de Imigração, 1900-1965", "Imigração"),
]


def fs_id(n: int) -> str:
    return f"DM{n // 1000:02d}-{n % 1000:03d}"


class DemoWorld:
    def __init__(self, seed: int = 1907, generations: int = 9, end_branch_prob: float = 0.16) -> None:
        self.rng = random.Random(seed)
        self.max_gen = generations
        self.end_prob = end_branch_prob
        self.people: dict[str, dict] = {}
        self.parents: dict[str, list[str]] = {}   # filho -> [pai, mãe]
        self.couples: dict[str, dict] = {}         # "a|b" -> {...}
        self._n = 0
        self._build()

    # ---------------------------------------------------------------- construção
    def _new_id(self) -> str:
        self._n += 1
        return fs_id(self._n)

    def _region(self, lineage: str, gen: int) -> list[str]:
        band = "near" if gen <= 3 else "mid" if gen <= 5 else "far"
        return REGIONS[(lineage, band)]

    def _person(self, gender: str, surname: str, mother_surname: str | None, year: int,
                lineage: str, gen: int, given: str | None = None) -> str:
        rng = self.rng
        pid = self._new_id()
        given = given or rng.choice(MALE if gender == "M" else FEMALE)
        if year < 1850 or not mother_surname:
            full = f"{given} {surname}"
        else:
            full = f"{given} {mother_surname} {surname}"
        place = rng.choice(self._region(lineage, gen))
        death = None
        if year < 1950:
            death = year + rng.randint(38, 88)
            if death > 2024:
                death = None
        living = death is None and year >= 1930
        self.people[pid] = {
            "id": pid, "given": given, "surname": surname, "mother_surname": mother_surname,
            "full": full, "gender": gender, "birth": year, "birth_place": place,
            "birth_md": (rng.randint(1, 28), rng.randint(1, 12)),
            "death": death, "death_place": rng.choice(self._region(lineage, max(1, gen - 1))) if death else None,
            "death_md": (rng.randint(1, 28), rng.randint(1, 12)),
            "living": living, "lineage": lineage, "gen": gen,
            "occupation": rng.choice(OCCUPATIONS) if year < 1960 and rng.random() < 0.5 else None,
            "alt": self._alt_name(given, surname) if year < 1880 and rng.random() < 0.5 else None,
            "has_photo": year > 1830 and rng.random() < (0.55 if year > 1880 else 0.3),
        }
        return pid

    def _alt_name(self, given: str, surname: str) -> str:
        archaic = {"João": "Joam", "Luís": "Luiz", "Inês": "Ignez", "Teresa": "Thereza", "Antônio": "Antonio",
                   "Josefa": "Jozefa", "José": "Jozé", "Isabel": "Izabel", "Rita": "Ritta"}
        sur = surname.replace("Sampaio", "Sam Payo").replace("Teixeira", "Teixeyra").replace("Vieira", "Vieyra")
        return f"{archaic.get(given, given)} {sur}"

    def _marry(self, a: str, b: str, year: int, lineage: str, gen: int) -> None:
        key = "|".join(sorted((a, b)))
        self.couples[key] = {"a": a, "b": b, "year": year,
                             "place": self.rng.choice(self._region(lineage, gen)),
                             "md": (self.rng.randint(1, 28), self.rng.randint(1, 12))}

    def _child_of(self, father: str, mother: str, child: str) -> None:
        self.parents[child] = [father, mother]

    def _build(self) -> None:
        rng = self.rng
        self.root = self._person("M", "Albuquerque", "Moreira", 1981, "titular", 1, given="Rafael")
        self.spouse = self._person("F", "Valadares", "Sampaio", 1984, "conjuge", 1, given="Beatriz")
        self._marry(self.root, self.spouse, 2009, "titular", 1)
        self.kids = []
        for given, gender, year in (("Helena", "F", 2011), ("Lívia", "F", 2014), ("Davi", "M", 2018)):
            k = self._person(gender, "Albuquerque", "Valadares", year, "titular", 0, given=given)
            self.people[k]["full"] = f"{given} Valadares Albuquerque"
            self._child_of(self.root, self.spouse, k)
            self.kids.append(k)
        self._ancestors(self.root, 2, "titular")
        self._ancestors(self.spouse, 2, "conjuge")

    def _ancestors(self, child: str, gen: int, lineage: str) -> None:
        rng = self.rng
        if gen > self.max_gen:
            return
        if gen >= 4 and rng.random() < self.end_prob:
            return  # fim documentado do ramo
        c = self.people[child]
        fy = c["birth"] - rng.randint(24, 40)
        my = c["birth"] - rng.randint(18, 34)
        father = self._person("M", c["surname"], rng.choice(SURNAMES), fy, lineage, gen)
        mother = self._person("F", c["mother_surname"] or rng.choice(SURNAMES), rng.choice(SURNAMES), my, lineage, gen)
        self._marry(father, mother, c["birth"] - rng.randint(1, 6), lineage, gen)
        self._child_of(father, mother, child)

        # irmãos do ancestral (ramo colateral)
        for _ in range(rng.randint(1, 5)):
            sy = c["birth"] + rng.choice([-1, 1]) * rng.randint(1, 9)
            sib = self._person(rng.choice("MF"), c["surname"], self.people[mother]["surname"], sy, lineage, gen - 1)
            self._child_of(father, mother, sib)
            if sy < 1990 and rng.random() < 0.45:
                s = self.people[sib]
                spouse = self._person("F" if s["gender"] == "M" else "M", rng.choice(SURNAMES),
                                      rng.choice(SURNAMES), sy + rng.randint(-4, 4), lineage, gen - 1)
                self._marry(sib, spouse, sy + rng.randint(19, 28), lineage, gen - 1)
                # pais do cônjuge colateral (ficarão como resumo/"stub")
                sp = self.people[spouse]
                sf = self._person("M", sp["surname"], rng.choice(SURNAMES), sp["birth"] - 30, lineage, gen)
                sm = self._person("F", sp["mother_surname"], rng.choice(SURNAMES), sp["birth"] - 26, lineage, gen)
                self._marry(sf, sm, sp["birth"] - 2, lineage, gen)
                self._child_of(sf, sm, spouse)
                h, w = (sib, spouse) if s["gender"] == "M" else (spouse, sib)
                for _ in range(rng.randint(0, 3)):
                    gy = sy + rng.randint(22, 36)
                    if gy > 2022:
                        continue
                    g = self._person(rng.choice("MF"), self.people[h]["surname"], self.people[w]["surname"],
                                     gy, lineage, gen - 2)
                    self._child_of(h, w, g)

        # segundo casamento ocasional do pai
        if rng.random() < 0.1:
            w2 = self._person("F", rng.choice(SURNAMES), rng.choice(SURNAMES), fy + rng.randint(2, 12), lineage, gen)
            self._marry(father, w2, c["birth"] + rng.randint(5, 15), lineage, gen)
            for _ in range(rng.randint(1, 2)):
                hy = c["birth"] + rng.randint(6, 18)
                h = self._person(rng.choice("MF"), c["surname"], self.people[w2]["surname"], hy, lineage, gen - 1)
                self._child_of(father, w2, h)

        self._ancestors(father, gen + 1, lineage)
        self._ancestors(mother, gen + 1, lineage)

    # ---------------------------------------------------------------- GEDCOM
    def spouses_of(self, pid: str) -> list[str]:
        return [c["b"] if c["a"] == pid else c["a"] for c in self.couples.values() if pid in (c["a"], c["b"])]

    def children_of(self, pid: str) -> list[str]:
        return [c for c, ps in self.parents.items() if pid in ps]

    @staticmethod
    def _gdate(year: int, md: tuple[int, int], approx: bool = False) -> str:
        d, m = md
        months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
        return f"ABT {year}" if approx else f"{d} {months[m - 1]} {year}"

    def _place_lines(self, place: str, lvl: int, with_map: bool) -> list[str]:
        name, lat, lon = PLACES[place]
        out = [f"{lvl} PLAC {name}"]
        if with_map:
            out += [f"{lvl + 1} MAP", f"{lvl + 2} LATI {'N' if lat >= 0 else 'S'}{abs(lat)}",
                    f"{lvl + 2} LONG {'E' if lon >= 0 else 'W'}{abs(lon)}"]
        return out

    def _event(self, tag, year, md, place, pid, sources: list[tuple[str, str]], approx=False) -> list[str]:
        lines = [f"1 {tag}", f"2 DATE {self._gdate(year, md, approx)}"]
        lines += self._place_lines(place, 2, with_map=int(pid[-3:]) % 5 != 0)  # parte sem coordenadas
        for sid, page in sources:
            lines += [f"2 SOUR @{sid}@", f"3 PAGE {page}"]
        return lines

    def write_gedcom(self, path, media_dir) -> None:
        """Escreve a família fictícia como GEDCOM 5.5.1 (com fotos em media_dir)."""
        from pathlib import Path

        path, media_dir = Path(path), Path(media_dir)
        media_dir.mkdir(parents=True, exist_ok=True)
        xref = {pid: f"I{i}" for i, pid in enumerate(self.people, 1)}
        fam_ids: dict[str, str] = {}
        for i, key in enumerate(self.couples, 1):
            fam_ids[key] = f"F{i}"
        source_recs: dict[str, tuple[str, str]] = {}
        out = ["0 HEAD", "1 SOUR DEMO_WORLD", "2 NAME Família fictícia de demonstração", "1 GEDC",
               "2 VERS 5.5.1", "2 FORM LINEAGE-LINKED", "1 CHAR UTF-8"]

        trunk = set(self.kids) | {self.root, self.spouse}
        stack = [self.root, self.spouse]
        while stack:
            for par in self.parents.get(stack.pop(), []):
                trunk.add(par)
                stack.append(par)

        def src(title: str, kind: str) -> str:
            if title not in source_recs:
                source_recs[title] = (f"S{len(source_recs) + 1}", kind)
            return source_recs[title][0]

        for pid, p in self.people.items():
            rng = random.Random("ged" + pid)
            out += [f"0 @{xref[pid]}@ INDI"]
            given = p["given"] + (f" {p['mother_surname']}" if p["mother_surname"] and p["birth"] >= 1850 else "")
            out += [f"1 NAME {given} /{p['surname']}/", f"2 GIVN {given}", f"2 SURN {p['surname']}"]
            if p["alt"]:
                a = p["alt"].split(" ", 1)
                out += [f"1 NAME {a[0]} /{a[1] if len(a) > 1 else ''}/", "2 TYPE aka"]
            out += [f"1 SEX {p['gender']}", f"1 _FSFTID {pid}"]
            n_src = 0 if (p["living"] and p["gen"] == 0) else rng.randint(0 if p["birth"] > 1950 else 1, 3)
            options = [t for t in SOURCE_TITLES if p["death"] or t[1] != "Óbito"]
            cites = []
            for _ in range(n_src):
                title, kind = rng.choice(options)
                cites.append((src(title, kind), kind))
            def page(kind):
                year = p["birth"] if kind in ("Batismo", "Nascimento") else (p["death"] or p["birth"] + 25)
                return f"{kind} de {p['full']}, {year}, {PLACES[p['birth_place']][0]} (fonte fictícia)"
            birth_tag = "BIRT" if p["birth"] > 1890 else "CHR"
            out += self._event(birth_tag, p["birth"], p["birth_md"], p["birth_place"], pid,
                               [(s, page(k)) for s, k in cites if k in ("Batismo", "Nascimento", "Recenseamento")],
                               approx=p["birth"] < 1760)
            if p["death"]:
                out += self._event("DEAT", p["death"], p["death_md"], p["death_place"], pid,
                                   [(s, page(k)) for s, k in cites if k == "Óbito"])
                out += self._event("BURI", p["death"], p["death_md"], p["death_place"], pid, [])
            if p["occupation"]:
                out += [f"1 OCCU {p['occupation']}"]
            if p["birth"] < 1940 and rng.random() < 0.35:
                born = PLACES[p["birth_place"]][0].split(",")[0]
                sketch = (f"{p['given']} nasceu em {born} em {p['birth']}. "
                          + (f"Trabalhou como {p['occupation'].lower()} durante boa parte da vida. " if p["occupation"] else "")
                          + (f"Faleceu em {p['death']}, deixando descendentes que guardaram sua memória. " if p["death"] else "")
                          + "(Biografia fictícia gerada para demonstração.)")
                out += ["1 NOTE Esboço de vida", f"2 CONT {sketch[:60]}", f"2 CONC {sketch[60:]}"]
            if p["birth"] < 1900 and int(pid[-3:]) % 4 == 0:
                out += [f"1 NOTE Grafia do sobrenome varia nos registros ({p['surname']} / {p['alt'] or p['surname']}).",
                        "2 CONT Conferir livro de batismos da paróquia. (Nota fictícia.)"]
            n_media = 0
            if p["has_photo"] and (pid in trunk or rng.random() < 0.15):
                f = media_dir / f"{pid}_retrato.jpg"
                f.write_bytes(self.image(pid, "p"))
                out += ["1 OBJE", f"2 FILE {f.name}", "3 FORM jpg", f"3 TITL Retrato de {p['given']}", "2 _PRIM Y"]
                n_media += 1
            if p["birth"] < 1920 and pid in trunk and rng.random() < 0.25:
                f = media_dir / f"{pid}_documento.jpg"
                f.write_bytes(self.image(pid, "d"))
                out += ["1 OBJE", f"2 FILE {f.name}", "3 FORM jpg", "3 TITL Documento digitalizado (demonstração)"]
            for key, fid in fam_ids.items():
                c = self.couples[key]
                if pid in (c["a"], c["b"]):
                    out += [f"1 FAMS @{fid}@"]
            if pid in self.parents:
                f, m = self.parents[pid]
                key = "|".join(sorted((f, m)))
                if key in fam_ids:
                    out += [f"1 FAMC @{fam_ids[key]}@"]

        for key, fid in fam_ids.items():
            c = self.couples[key]
            h, w = (c["a"], c["b"]) if self.people[c["a"]]["gender"] == "M" else (c["b"], c["a"])
            out += [f"0 @{fid}@ FAM", f"1 HUSB @{xref[h]}@", f"1 WIFE @{xref[w]}@"]
            for k in self.children_of(h):
                if w in self.parents.get(k, []):
                    out += [f"1 CHIL @{xref[k]}@"]
            out += ["1 MARR", f"2 DATE {self._gdate(c['year'], c['md'])}"] + self._place_lines(c["place"], 2, True)

        for title, (sid, kind) in source_recs.items():
            out += [f"0 @{sid}@ SOUR", f"1 TITL {title}", "1 AUTH Arquivo fictício de demonstração",
                    f"1 WWW https://example.org/fonte-demonstracao/{sid}"]
        out.append("0 TRLR")
        path.write_text("\n".join(out) + "\n", encoding="utf-8")

    # ---------------------------------------------------------------- imagens
    def image(self, pid: str, kind: str) -> bytes:
        from PIL import Image, ImageDraw, ImageFont

        p = self.people[pid]
        rng = random.Random(pid + kind)
        w, h = (240, 300) if kind != "d" else (300, 220)
        img = Image.new("RGB", (w, h), (226, 212, 186))
        draw = ImageDraw.Draw(img)
        draw.rectangle([8, 8, w - 9, h - 9], outline=(150, 120, 80), width=3)
        if kind == "d":
            for y in range(40, h - 30, 16):
                draw.line([30, y, w - 30 - rng.randint(0, 80), y], fill=(120, 95, 65), width=2)
        else:
            tone = (110 + rng.randint(-15, 15), 85, 60)
            draw.ellipse([w / 2 - 45, 55, w / 2 + 45, 150], fill=tone)
            draw.pieslice([w / 2 - 90, 150, w / 2 + 90, 340], 180, 360, fill=tone)
        try:
            font = ImageFont.load_default(size=22)
        except TypeError:
            font = ImageFont.load_default()
        initials = "".join(x[0] for x in p["full"].split()[:2] if x)
        draw.text((18, h - 42), initials, fill=(60, 45, 30), font=font)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return buf.getvalue()
