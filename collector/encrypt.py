#!/usr/bin/env python3
"""
collector/encrypt.py — Criptografa a árvore para publicar num repositório PÚBLICO.

    python -m collector.encrypt

1. Na primeira vez, gera uma chave aleatória (DATA_KEY) e pede uma senha de acesso
   (APP_PASSWORD). As duas ficam só em .streamlit/secrets.toml, que NÃO vai para o GitHub.
2. Junta data/family_tree.json e as fotos de data/photos/ num pacote, compacta e
   criptografa (Fernet: AES-128-CBC + HMAC-SHA256) em data/family_tree.enc.
3. Mostra o bloco a colar em Settings → Secrets no Streamlit Cloud.

Só o arquivo .enc deve ir para o GitHub.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import secrets
import sys
import zlib
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
SECRETS_FILE = PROJECT_DIR / ".streamlit" / "secrets.toml"


def _fernet(key: str):
    from cryptography.fernet import Fernet

    return Fernet(key.encode() if isinstance(key, str) else key)


def new_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def build_bundle(data_dir: Path) -> bytes:
    tree = json.loads((data_dir / "family_tree.json").read_text(encoding="utf-8"))
    photos: dict[str, str] = {}
    for p in tree["persons"].values():
        rels = [p.get("photo")] + [m.get("local_path") for m in p.get("memories") or []]
        for rel in rels:
            if rel and rel not in photos and (data_dir / rel).is_file():
                photos[rel] = base64.b64encode((data_dir / rel).read_bytes()).decode()
    return json.dumps({"version": 1, "tree": tree, "photos": photos}, ensure_ascii=False).encode()


def encrypt_bytes(raw: bytes, key: str) -> bytes:
    return _fernet(key).encrypt(zlib.compress(raw, 9))


def decrypt_bundle(token: bytes, key: str) -> tuple[dict, dict[str, bytes]]:
    """Devolve (árvore, {caminho_relativo: bytes_da_imagem}). Lança erro se a chave estiver errada."""
    bundle = json.loads(zlib.decompress(_fernet(key).decrypt(token)))
    photos = {k: base64.b64decode(v) for k, v in (bundle.get("photos") or {}).items()}
    return bundle["tree"], photos


def read_secrets(path: Path = SECRETS_FILE) -> dict:
    if not path.exists():
        return {}
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))


def write_secrets(values: dict, path: Path = SECRETS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{k} = {json.dumps(str(v), ensure_ascii=False)}' for k, v in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ask_password() -> str:
    print("\nEscolha a SENHA DE ACESSO que você vai passar para a família.")
    print("(mínimo de 8 caracteres; deixe em branco para gerar uma senha aleatória)")
    while True:
        pw = getpass.getpass("Senha: ")
        if not pw:
            pw = "-".join(secrets.token_hex(3) for _ in range(3))
            print(f"Senha gerada: {pw}")
            return pw
        if len(pw) < 8:
            print("Use pelo menos 8 caracteres.")
            continue
        if getpass.getpass("Repita a senha: ") != pw:
            print("As senhas não conferem. Tente de novo.")
            continue
        return pw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Criptografa data/family_tree.json em data/family_tree.enc")
    ap.add_argument("--new-password", action="store_true", help="Trocar a senha de acesso")
    ap.add_argument("--new-key", action="store_true",
                    help="Gerar chave nova (será preciso atualizar DATA_KEY nos Secrets do Streamlit)")
    args = ap.parse_args(argv)

    src = DATA_DIR / "family_tree.json"
    if not src.is_file():
        print(f"Não encontrei {src}. Rode antes o importador (python -m collector.import_gedcom ...).")
        return 1
    values = read_secrets()
    created = []
    if args.new_key or not values.get("DATA_KEY"):
        values["DATA_KEY"] = new_key()
        created.append("DATA_KEY")
    if args.new_password or not values.get("APP_PASSWORD"):
        values["APP_PASSWORD"] = ask_password()
        created.append("APP_PASSWORD")
    values.setdefault("HIDE_LIVING", "true")
    write_secrets(values)

    raw = build_bundle(DATA_DIR)
    token = encrypt_bytes(raw, values["DATA_KEY"])
    out = DATA_DIR / "family_tree.enc"
    out.write_bytes(token)
    decrypt_bundle(token, values["DATA_KEY"])  # confere que abre de volta
    n_photos = len(json.loads(raw)["photos"])
    print(f"\n✅ {out} gerado ({len(token) / 1e6:.1f} MB, {n_photos} foto(s) incluída(s)).")
    print(f"   Segredos guardados em {SECRETS_FILE} (este arquivo NÃO vai para o GitHub).")
    if created:
        print("\nCole o bloco abaixo em share.streamlit.io → seu app → Settings → Secrets:\n")
        print("-" * 60)
        print(SECRETS_FILE.read_text(encoding="utf-8").rstrip())
        print("-" * 60)
    else:
        print("   Chave e senha mantidas; não é preciso mexer nos Secrets do Streamlit.")
    print("\nDepois envie o arquivo criptografado:")
    print("   git add data/family_tree.enc")
    print('   git commit -m "Atualizar árvore (criptografada)"')
    print("   git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
