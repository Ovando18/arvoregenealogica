"""
Gera os dados de DEMONSTRAÇÃO (fictícios) em data/sample/:
cria um GEDCOM de uma família inventada e o importa com o MESMO importador
usado para a árvore real.

    python -m collector.make_sample
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from collector import import_gedcom
from collector.demo_world import DemoWorld

SAMPLE_DIR = import_gedcom.DATA_DIR / "sample"


def build(out_dir: Path = SAMPLE_DIR, generations: int = 8, seed: int = 1907, quiet: bool = True) -> dict:
    world = DemoWorld(seed=seed, generations=generations)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    with tempfile.TemporaryDirectory() as tmp:
        ged = Path(tmp) / "familia_ficticia.ged"
        world.write_gedcom(ged, Path(tmp))
        opts = import_gedcom.parse_args([str(ged), "--root", world.root, "--generations", str(generations)])
        opts.expected_spouse = "Beatriz"
        opts.expected_children = ("Helena", "Lívia", "Davi")
        if quiet:
            import_gedcom.log = lambda msg: None
        tree = import_gedcom.GedcomImporter(ged, opts, data_dir=out_dir).run()
    tree["meta"]["demo"] = True
    tree["meta"]["source"] = "Dados FICTÍCIOS de demonstração (collector/demo_world.py)"
    import_gedcom.write_json(out_dir / "family_tree.json", tree)
    return tree


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1907)
    a = ap.parse_args()
    t = build(generations=a.generations, seed=a.seed)
    m = t["meta"]
    print(f"Amostra gerada em {SAMPLE_DIR}: {m['persons_total']} pessoas, {m['generations_reached']} gerações.")
