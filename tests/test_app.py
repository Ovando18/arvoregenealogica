import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

os.environ["ARVORE_DEMO"] = "1"  # os testes usam sempre os dados fictícios

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def run(**state):
    at = AppTest.from_file(APP, default_timeout=60)
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    assert not at.exception, at.exception
    return at


def test_app_renders_demo():
    at = run()
    assert any("demonstração" in i.value for i in at.info)
    assert at.session_state.selected == "DM00-001"


def test_family_button_changes_focus_and_collateral_works():
    at = run()
    # clica no primeiro pai listado na aba Família
    btn = next(b for b in at.button if b.key and b.key.startswith("par-DM00-001-"))
    btn.click().run()
    assert at.session_state.selected == btn.key.split("-", 3)[-1]
    # pessoa colateral também abre sem erro
    import json
    tree = json.loads((Path(APP).parent / "data/sample/family_tree.json").read_text())
    pid = next(k for k, v in tree["persons"].items() if v["role"] == "collateral")
    run(selected=pid)


def test_search_and_controls():
    at = run()
    at.text_input[0].input("Braga").run()
    assert not at.exception
    assert any(b.key and b.key.startswith("hit-") for b in at.button)
    at.toggle[0].set_value(True).run()            # colaterais
    at.radio[1].set_value("Família da pessoa selecionada").run()
    at.radio[0].set_value("conjuge").run()
    assert not at.exception


def test_hide_living():
    at = run()
    hide = next(t for t in at.toggle if "vivas" in t.label)
    hide.set_value(True).run()
    assert any("pessoa viva" in i.value for i in at.info)


def test_encrypted_tree_requires_password(tmp_path, monkeypatch):
    import shutil

    from collector.encrypt import build_bundle, encrypt_bytes, new_key

    sample = Path(APP).parent / "data" / "sample"
    shutil.copytree(sample, tmp_path / "src")
    key = new_key()
    (tmp_path / "pub").mkdir()
    (tmp_path / "pub" / "family_tree.enc").write_bytes(encrypt_bytes(build_bundle(tmp_path / "src"), key))
    monkeypatch.setenv("ARVORE_DATA_DIR", str(tmp_path / "pub"))
    monkeypatch.setenv("ARVORE_DEMO", "0")

    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["DATA_KEY"] = key
    at.secrets["APP_PASSWORD"] = "senha-da-familia"
    at.run()
    assert not at.exception
    assert not at.metric and not at.tabs                # nada da árvore antes da senha
    at.text_input[0].input("errada")
    at.button[0].click().run()
    assert any("incorreta" in e.value for e in at.error)
    assert not at.metric
    at.text_input[0].input("senha-da-familia")
    at.button[0].click().run()
    assert not at.exception
    assert at.session_state.selected == "DM00-001"     # árvore aberta
    # foto vem de dentro do pacote criptografado (não há arquivos em pub/photos)
    assert not (tmp_path / "pub" / "photos").exists()
