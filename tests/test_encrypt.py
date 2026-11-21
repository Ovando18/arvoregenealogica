import json

import pytest

from collector import encrypt


def test_roundtrip_and_wrong_key(tmp_path):
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "A.jpg").write_bytes(b"\xff\xd8foto")
    tree = {"meta": {}, "persons": {"A": {"id": "A", "name": "Fulano", "photo": "photos/A.jpg", "memories": []}}}
    (tmp_path / "family_tree.json").write_text(json.dumps(tree), encoding="utf-8")
    key = encrypt.new_key()
    token = encrypt.encrypt_bytes(encrypt.build_bundle(tmp_path), key)
    assert b"Fulano" not in token
    out, photos = encrypt.decrypt_bundle(token, key)
    assert out["persons"]["A"]["name"] == "Fulano" and photos["photos/A.jpg"] == b"\xff\xd8foto"
    with pytest.raises(Exception):
        encrypt.decrypt_bundle(token, encrypt.new_key())


def test_secrets_file_roundtrip(tmp_path):
    f = tmp_path / "secrets.toml"
    encrypt.write_secrets({"DATA_KEY": "abc=", "APP_PASSWORD": 'com "aspas" e ç'}, f)
    assert encrypt.read_secrets(f) == {"DATA_KEY": "abc=", "APP_PASSWORD": 'com "aspas" e ç'}


def test_gitignore_blocks_plain_data():
    from pathlib import Path
    gi = (Path(encrypt.__file__).parent.parent / ".gitignore").read_text()
    for pattern in ("data/family_tree.json", "data/photos/*", ".streamlit/secrets.toml", "*.rmtree", "*.ged"):
        assert pattern in gi
