import json

import pytest

from collector import import_gedcom as ig
from collector.demo_world import DemoWorld


# ---------------------------------------------------------------- unidades
def test_parser_conc_cont_and_pointers():
    recs = ig.parse_gedcom("0 HEAD\n0 @I1@ INDI\n1 NOTE Linha um\n2 CONT linha dois con\n2 CONC tinuação\n0 TRLR\n")
    indi = recs[1]
    assert indi.xref == "I1" and indi.tag == "INDI"
    assert indi.val("NOTE") == "Linha um\nlinha dois continuação"
    assert ig.pointer("@F12@") == "F12" and ig.pointer("texto") is None


@pytest.mark.parametrize("text,year,formal,normalized", [
    ("12 MAR 1850", 1850, "+1850-03-12", "12 de março de 1850"),
    ("MAR 1850", 1850, "+1850-03", "março de 1850"),
    ("ABT 1790", 1790, "A+1790", "cerca de 1790"),
    ("BEF 1700", 1700, "/+1700", "antes de 1700"),
    ("BET 1850 AND 1860", 1850, "+1850/+1860", "entre 1850 e 1860"),
])
def test_dates(text, year, formal, normalized):
    d = ig.parse_date(text)
    assert (d["year"], d["formal"], d["normalized"]) == (year, formal, normalized)
    assert d["original"] == text


def test_names_places_and_fs_ids():
    recs = ig.parse_gedcom(
        "0 @I1@ INDI\n1 NAME Carlos /Lima Souza/\n1 NAME Carlo /Lima/\n2 TYPE aka\n"
        "1 BIRT\n2 PLAC Cuiabá, Mato Grosso, Brasil\n3 MAP\n4 LATI S15.6\n4 LONG W56.1\n"
        "1 REFN AAAA-111\n2 TYPE FamilySearch\n"
        "0 @I2@ INDI\n1 _FSFTID ABCD-123\n"
        "0 @I3@ INDI\n1 WWW https://www.familysearch.org/tree/person/details/WXYZ-9Q8\n")
    n = ig.parse_name(recs[0].all("NAME")[0])
    assert (n["full"], n["given"], n["surname"]) == ("Carlos Lima Souza", "Carlos", "Lima Souza")
    assert ig.parse_name(recs[0].all("NAME")[1])["type"] == "AlsoKnownAs"
    pl = ig.parse_place(recs[0].first("BIRT").first("PLAC"))
    assert (pl["lat"], pl["lon"]) == (-15.6, -56.1)
    imp = ig.GedcomImporter.__new__(ig.GedcomImporter)
    assert [imp.fs_id(r) for r in recs] == ["AAAA-111", "ABCD-123", "WXYZ-9Q8"]


# ---------------------------------------------------------------- ponta a ponta
@pytest.fixture(scope="module")
def imported(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ged")
    world = DemoWorld(seed=3, generations=6)
    ged = tmp / "demo.ged"
    world.write_gedcom(ged, tmp / "media")
    opts = ig.parse_args([str(ged), "--root", world.root, "--generations", "6", "--media-dir", str(tmp / "media")])
    opts.expected_spouse, opts.expected_children = "Beatriz", ("Helena", "Lívia", "Davi")
    out = tmp / "data"
    imp = ig.GedcomImporter(ged, opts, data_dir=out)
    tree = imp.run()
    ig.write_json(out / "family_tree.json", tree)
    return world, tree, out, imp


def test_base_trunk_and_lineages(imported):
    world, tree, _, _ = imported
    P, meta = tree["persons"], tree["meta"]
    assert meta["root_id"] == world.root and meta["spouse_id"] == world.spouse
    assert sorted(meta["children_ids"]) == sorted(world.kids)

    def ancestors(pid, gen):
        if gen > 6 or pid not in world.parents:
            return
        for p in world.parents[pid]:
            yield p, gen
            yield from ancestors(p, gen + 1)
    expected = dict(ancestors(world.root, 2)) | dict(ancestors(world.spouse, 2))
    for pid, gen in expected.items():
        assert P[pid]["role"] == "ancestor" and P[pid]["is_direct_ancestor"], pid
        assert P[pid]["generation"] == gen
    assert P[world.root]["lineage"] == ["titular"] and P[world.spouse]["lineage"] == ["conjuge"]
    for k in world.kids:
        assert P[k]["role"] == "base" and P[k]["generation"] == 0
    assert meta["generations_reached"] == max(expected.values())


def test_collaterals_relations_and_details(imported):
    world, tree, out, imp = imported
    P = tree["persons"]
    coll = [p for p in P.values() if p["role"] == "collateral"]
    assert coll and not any(p["is_direct_ancestor"] for p in coll)
    for p in P.values():
        for rel in p["parents"] + p["children"] + p["spouses"]:
            assert rel in P
    # um irmão de ancestral fica uma geração abaixo dos pais
    sib = next(p for p in coll if p["parents"] and P[p["parents"][0]]["role"] == "ancestor")
    assert sib["generation"] == P[sib["parents"][0]]["generation"] - 1
    # dados ricos
    assert any(p["life_sketch"] for p in P.values())
    assert any(p["notes"] for p in P.values())
    assert any(f["type"] == "Marriage" for c in tree["relationships"]["couples"] for f in c["facts"])
    src = next(s for p in P.values() for s in p["sources"])
    assert src["title"] and src["citation"] and src["url"].startswith("https://example.org/")
    assert any(p["alt_names"][1:] for p in P.values())
    # fotos copiadas e reduzidas para data/photos
    photos = [p["photo"] for p in P.values() if p["photo"]]
    assert photos and all((out / ph).is_file() for ph in photos)
    assert P[world.root]["familysearch_url"].endswith(world.root)
    assert not imp.media_missing


def test_no_network_without_geocode(imported, monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("rede usada sem --geocode"))
    world, *_ = imported
    # roda de novo sem --geocode: nenhuma chamada de rede
    test_base_trunk_and_lineages(imported)


def test_root_by_name_and_generation_limit(tmp_path):
    world = DemoWorld(seed=11, generations=5)
    ged = tmp_path / "d.ged"
    world.write_gedcom(ged, tmp_path)
    name = world.people[world.root]["full"]
    opts = ig.parse_args([str(ged), "--root", "XXXX-XXX", "--root-name", name, "--generations", "3"])
    opts.expected_spouse = "Beatriz"
    tree = ig.GedcomImporter(ged, opts, data_dir=tmp_path / "o").run()
    assert tree["meta"]["root_id"] == world.root
    assert max(p["generation"] for p in tree["persons"].values() if p["role"] == "ancestor") == 3


def test_cli_writes_file(tmp_path):
    world = DemoWorld(seed=2, generations=4)
    ged = tmp_path / "d.ged"
    world.write_gedcom(ged, tmp_path)
    out = tmp_path / "data" / "family_tree.json"
    assert ig.main([str(ged), "--root", world.root, "--output", str(out)]) == 0
    assert json.loads(out.read_text())["meta"]["persons_total"] > 10


# ---------------------------------------------------------------- RootsMagic / vários arquivos
def test_rm_dates():
    from collector.rmtree import rm_date
    assert rm_date("D.+19830618..+00000000..") == "18 JUN 1983"
    assert rm_date("DB+19680000..+00000000..") == "BEF 1968"
    assert rm_date("DR+18330100..+18331200..") == "BET JAN 1833 AND DEC 1833"
    assert rm_date("D.+18900000.A+00000000..") == "ABT 1890"
    assert rm_date(".") is None and rm_date("Tem 1850, perto da festa") == "em 1850, perto da festa"


HEAD = "0 HEAD\n1 CHAR UTF-8\n"


def indi(x, name, sex, fs, year):
    return f"0 @{x}@ INDI\n1 NAME {name}\n1 SEX {sex}\n1 _FSFTID {fs}\n1 BIRT\n2 DATE {year}\n"


def test_two_files_are_merged_by_familysearch_id(tmp_path):
    # arquivo 1: baixado a partir do titular (só os pais dele)
    a = HEAD + indi("I1", "Carlos /Lima Souza/", "M", "AAAA-111", 1983) + indi("I2", "Rita /Prado/", "F", "BBBB-222", 1985) \
        + indi("I3", "Lia /Prado Souza/", "F", "KID1-111", 2020) + indi("I4", "Pai /Lima/", "M", "PAI1-111", 1950) \
        + indi("I5", "Mae /Souza/", "F", "MAE1-111", 1955) \
        + "0 @F1@ FAM\n1 HUSB @I1@\n1 WIFE @I2@\n1 CHIL @I3@\n0 @F2@ FAM\n1 HUSB @I4@\n1 WIFE @I5@\n1 CHIL @I1@\n0 TRLR\n"
    # arquivo 2: baixado a partir da cônjuge (xrefs diferentes, mesmos IDs)
    b = HEAD + indi("I1", "Rita /Prado/", "F", "BBBB-222", 1985) + indi("I7", "Carlos /Lima Souza/", "M", "AAAA-111", 1983) \
        + indi("I8", "Lia /Prado Souza/", "F", "KID1-111", 2020) + indi("I2", "Avo /Prado/", "M", "AVO1-222", 1950) \
        + indi("I3", "Avó /Reis/", "F", "AVO2-222", 1958) \
        + "0 @F1@ FAM\n1 HUSB @I7@\n1 WIFE @I1@\n1 CHIL @I8@\n0 @F9@ FAM\n1 HUSB @I2@\n1 WIFE @I3@\n1 CHIL @I1@\n0 TRLR\n"
    (tmp_path / "a.ged").write_text(a, encoding="utf-8")
    (tmp_path / "b.ged").write_text(b, encoding="utf-8")
    opts = ig.parse_args([str(tmp_path / "a.ged"), str(tmp_path / "b.ged"), "--root", "AAAA-111", "--expect-children", "Lia"])
    tree = ig.GedcomImporter([tmp_path / "a.ged", tmp_path / "b.ged"], opts, data_dir=tmp_path / "o").run()
    P = tree["persons"]
    assert len(P) == 7
    assert tree["meta"]["children_ids"] == ["KID1-111"]
    assert P["PAI1-111"]["lineage"] == ["titular"] and P["AVO1-222"]["lineage"] == ["conjuge"]
    assert P["AVO2-222"]["generation"] == 2 and P["AVO2-222"]["is_direct_ancestor"]
    assert sorted(P["KID1-111"]["parents"]) == ["AAAA-111", "BBBB-222"]


def test_root_is_required(tmp_path):
    (tmp_path / "x.ged").write_text(HEAD + indi("I1", "A /B/", "M", "AAAA-111", 1900) + "0 TRLR\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        ig.GedcomImporter(tmp_path / "x.ged", ig.parse_args([str(tmp_path / "x.ged")]), data_dir=tmp_path).run()
