"""
Árvore Genealógica Interativa — painel Streamlit.

Lê exclusivamente os arquivos estáticos em data/ (gerados por collector/import_gedcom.py
a partir de um GEDCOM exportado por um programa parceiro do FamilySearch).
"""
from __future__ import annotations

import hmac
import html
import json
import time
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_agraph import Config, Edge, Node, agraph

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("ARVORE_DATA_DIR") or APP_DIR / "data")
ENC_TREE = DATA_DIR / "family_tree.enc"   # árvore criptografada (repositório público)
REAL_TREE = DATA_DIR / "family_tree.json"  # árvore legível (só no seu computador)
SAMPLE_TREE = DATA_DIR / "sample" / "family_tree.json"

NAVY, GOLD, GREEN, PLUM, GREY, INK, PARCH = "#1F3A5F", "#B08D57", "#4F7A5A", "#7A4E6E", "#9A9184", "#2A2620", "#F7F1E3"
LINEAGE_COLORS = {"titular": NAVY, "conjuge": GOLD, "both": PLUM, "base": GREEN}
EVENT_ICONS = {"Birth": "✦", "Christening": "✚", "Baptism": "✚", "Marriage": "⚭", "Divorce": "⚮",
               "Death": "✝", "Burial": "⚱", "Residence": "⌂", "Occupation": "⚒", "Immigration": "⛵",
               "Emigration": "⛵", "Census": "☰"}


st.set_page_config(page_title="Árvore Genealógica", page_icon="🌳", layout="wide",
                   initial_sidebar_state="expanded")


# ======================================================================================
# Estilo
# ======================================================================================
st.markdown(
    f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap');
html, body, [class*="css"], .stMarkdown, p, li, label {{ font-family: 'Source Serif 4', Georgia, serif; }}
h1, h2, h3, h4 {{ font-family: 'Cormorant Garamond', Georgia, serif !important; color: {NAVY}; letter-spacing: .01em; }}
.block-container {{ padding-top: 1.6rem; max-width: 1500px; }}
[data-testid="stSidebar"] {{ background: linear-gradient(180deg, #EFE6D0 0%, #E7DABD 100%); border-right: 1px solid #D8C8A4; }}
.hero {{ border-bottom: 2px solid {GOLD}; margin-bottom: .6rem; padding-bottom: .3rem; }}
.hero h1 {{ margin: 0; font-size: 2.35rem; }}
.hero p {{ margin: 0; color: #6B5E48; font-style: italic; }}
[data-testid="stMetric"] {{ background: #FBF7EE; border: 1px solid #DCCDAA; border-radius: 10px; padding: .55rem .8rem;
    box-shadow: 0 1px 0 rgba(176,141,87,.25); }}
[data-testid="stMetricValue"] {{ font-family: 'Cormorant Garamond', serif; color: {NAVY}; font-size: 1.9rem; }}
[data-testid="stMetricLabel"] p {{ color: #6B5E48; font-size: .82rem; text-transform: uppercase; letter-spacing: .06em; }}
.person-head {{ display:flex; gap: 1rem; align-items: center; background: #FBF7EE; border: 1px solid #DCCDAA;
    border-left: 5px solid {GOLD}; border-radius: 10px; padding: .8rem 1rem; margin-bottom: .6rem; }}
.person-head h2 {{ margin: 0; font-size: 1.75rem; line-height: 1.1; }}
.person-head .sub {{ color: #6B5E48; font-size: .95rem; }}
.chip {{ display:inline-block; padding: .05rem .55rem; margin: .2rem .25rem 0 0; border-radius: 999px; font-size: .78rem;
    border: 1px solid #CDBB93; background: #F3EAD5; color: {INK}; }}
.chip.navy {{ background: {NAVY}; color: #fff; border-color: {NAVY}; }}
.chip.gold {{ background: {GOLD}; color: #fff; border-color: {GOLD}; }}
.chip.green {{ background: {GREEN}; color: #fff; border-color: {GREEN}; }}
.timeline {{ border-left: 2px solid {GOLD}; margin: .4rem 0 0 .6rem; padding-left: 1.1rem; }}
.tl-item {{ position: relative; margin-bottom: .75rem; }}
.tl-item:before {{ content: ''; position: absolute; left: -1.48rem; top: .35rem; width: .7rem; height: .7rem;
    border-radius: 50%; background: {PARCH}; border: 2px solid {NAVY}; }}
.tl-year {{ font-family: 'Cormorant Garamond', serif; font-weight: 700; color: {NAVY}; font-size: 1.15rem; }}
.tl-label {{ font-weight: 600; }}
.tl-meta {{ color: #6B5E48; font-size: .88rem; }}
.sketch {{ background: #FBF7EE; border: 1px dashed #CDBB93; border-radius: 8px; padding: .7rem .9rem; font-style: italic; }}
.story {{ background: #FBF7EE; border-left: 3px solid {GOLD}; padding: .6rem .8rem; border-radius: 6px; margin-bottom: .6rem; }}
.legend span {{ display:inline-flex; align-items:center; margin-right: .9rem; font-size: .85rem; color:#4A4236; }}
.legend i {{ display:inline-block; width: .8rem; height: .8rem; border-radius: 50%; margin-right: .35rem; }}
div[data-testid="stButton"] button {{ text-align: left; justify-content: flex-start; background: #FBF7EE;
    border: 1px solid #DCCDAA; line-height: 1.25; height: auto; padding: .45rem .7rem; }}
div[data-testid="stButton"] button * {{ white-space: pre-line !important; overflow: visible !important;
    text-overflow: clip !important; text-align: left; }}
div[data-testid="stButton"] button:hover {{ border-color: {NAVY}; color: {NAVY}; background: #F3EAD5; }}
.stTabs [data-baseweb="tab"] {{ font-family: 'Cormorant Garamond', serif; font-size: 1.08rem; font-weight: 600; }}
</style>
""",
    unsafe_allow_html=True,
)


# ======================================================================================
# Dados
# ======================================================================================
def slug(text: str | None) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def setting(name: str, default: str = "") -> str:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


@st.cache_data(show_spinner="Carregando a árvore…")
def load_tree(path: str, mtime: float, key: str = "") -> dict:
    if key:
        from collector.encrypt import decrypt_bundle

        tree, photos = decrypt_bundle(Path(path).read_bytes(), key)
    else:
        tree, photos = json.loads(Path(path).read_text(encoding="utf-8")), {}
    tree["_photos"] = photos
    persons = tree["persons"]
    # Compatibilidade: árvores geradas por versões antigas do importador usavam outros nomes
    # para as linhagens. Renomeia a linhagem do titular e a do cônjuge para os nomes atuais.
    rename = {}
    for pid, new in ((tree["meta"].get("root_id"), "titular"), (tree["meta"].get("spouse_id"), "conjuge")):
        lin = (persons.get(pid) or {}).get("lineage") or []
        if len(lin) == 1 and lin[0] != new:
            rename[lin[0]] = new
    if rename:
        for p in persons.values():
            p["lineage"] = sorted({rename.get(x, x) for x in p.get("lineage") or []})
    # índice de casais (fatos de casamento/divórcio)
    couples = {}
    for c in (tree.get("relationships") or {}).get("couples") or []:
        couples.setdefault(c["person1"], []).append(c)
        couples.setdefault(c["person2"], []).append(c)
    tree["_couples"] = couples
    # índice de busca
    index = []
    for pid, p in persons.items():
        places = [p.get("birth_place"), p.get("death_place")]
        places += [(f.get("place") or {}).get("normalized") or (f.get("place") or {}).get("original")
                   for f in p.get("facts") or []]
        alt = [n.get("full") for n in p.get("alt_names") or []]
        surnames = {p.get("surname")} | {n.get("surname") for n in p.get("alt_names") or []}
        index.append({
            "id": pid,
            "nome": slug(" ".join([p.get("name") or ""] + [a or "" for a in alt])),
            "sobrenome": slug(" ".join(s for s in surnames if s) or (p.get("name") or "").split(" ")[-1]),
            "local": slug(" | ".join(x for x in places if x)),
            "idfs": pid.lower(),
        })
    tree["_index"] = index
    return tree


def pick_data() -> tuple[Path, bool, bool]:
    """(arquivo, é_demonstração, é_criptografado). ARVORE_DEMO=1 força a demonstração."""
    if os.environ.get("ARVORE_DEMO") != "1":
        if REAL_TREE.exists():
            return REAL_TREE, False, False
        if ENC_TREE.exists():
            return ENC_TREE, False, True
    return SAMPLE_TREE, True, False


def password_gate() -> str:
    """Tela de senha para a árvore criptografada. Devolve a chave de dados se liberado."""
    key, password = setting("DATA_KEY"), setting("APP_PASSWORD")
    if not key or not password:
        st.error("A árvore está criptografada, mas `DATA_KEY` e `APP_PASSWORD` não foram configurados "
                 "em Settings → Secrets. Rode `python -m collector.encrypt` e cole o bloco mostrado.")
        st.stop()
    if st.session_state.get("auth_ok"):
        return key
    st.markdown("<div class='hero'><h1>🌳 Árvore Genealógica da Família</h1>"
                "<p>Acesso restrito à família</p></div>", unsafe_allow_html=True)
    with st.form("login"):
        typed = st.text_input("Senha de acesso", type="password")
        ok = st.form_submit_button("Entrar")
    if ok:
        if hmac.compare_digest(typed.encode(), password.encode()):
            st.session_state.auth_ok = True
            st.rerun()
        time.sleep(2)  # desacelera tentativas
        st.error("Senha incorreta.")
    st.stop()


TREE_PATH, IS_DEMO, IS_ENCRYPTED = pick_data()
if not TREE_PATH.exists():
    st.error("Nenhum dado encontrado. Rode `python -m collector.import_gedcom arquivo.ged` (árvore real) ou "
             "`python -m collector.make_sample` (demonstração).")
    st.stop()
DATA_KEY = password_gate() if IS_ENCRYPTED else ""
try:
    TREE = load_tree(str(TREE_PATH), TREE_PATH.stat().st_mtime, DATA_KEY)
except Exception:
    st.error("Não foi possível abrir a árvore criptografada: confira se `DATA_KEY` nos Secrets é a mesma "
             "chave usada no `python -m collector.encrypt`.")
    st.stop()
BASE_DIR = TREE_PATH.parent
PHOTOS: dict[str, bytes] = TREE["_photos"]
P: dict[str, dict] = TREE["persons"]
META = TREE["meta"]
ROOT_ID = META.get("root_id")
SPOUSE_ID = META.get("spouse_id")
KIDS = META.get("children_ids") or []
LIN_NAME = {"titular": (P.get(ROOT_ID, {}).get("name") or "titular").split()[0],
            "conjuge": (P.get(SPOUSE_ID, {}).get("name") or "cônjuge").split()[0]}
LINEAGE_LABELS = {"completa": f"Completa ({LIN_NAME['titular']} + {LIN_NAME['conjuge']})",
                  "titular": f"Apenas linhagem {LIN_NAME['titular']}",
                  "conjuge": f"Apenas linhagem {LIN_NAME['conjuge']}"}

if "selected" not in st.session_state:
    st.session_state.selected = ROOT_ID if ROOT_ID in P else next(iter(P))
if "graph_last" not in st.session_state:
    st.session_state.graph_last = None


def select(pid: str) -> None:
    if pid in P:
        st.session_state.selected = pid


# ======================================================================================
# Helpers de apresentação
# ======================================================================================
def name(pid: str) -> str:
    return (P.get(pid) or {}).get("name") or pid


def fact_year(f: dict) -> int | None:
    return (f.get("date") or {}).get("year")


def first_fact(p: dict, *types: str) -> dict | None:
    for t in types:
        for f in p.get("facts") or []:
            if f.get("type") == t:
                return f
    return None


def lifespan(p: dict) -> str:
    if p.get("lifespan"):
        return p["lifespan"]
    b = first_fact(p, "Birth", "Christening", "Baptism")
    d = first_fact(p, "Death", "Burial")
    by, dy = (fact_year(b) if b else None), (fact_year(d) if d else None)
    if by or dy:
        return f"{by or '?'}–{dy or ('Vivo' if p.get('living') else '?')}"
    return ""


def lineage_key(p: dict) -> str:
    if p.get("role") == "base":
        return "base"
    lin = set(p.get("lineage") or [])
    if lin == {"titular", "conjuge"}:
        return "both"
    return next(iter(lin), "titular")


def is_hidden(p: dict) -> bool:
    return HIDE_LIVING and bool(p.get("living"))


def image_src(rel: str | None):
    """Imagem local: bytes (pacote criptografado) ou caminho do arquivo; None se não existir."""
    if not rel:
        return None
    if rel in PHOTOS:
        return PHOTOS[rel]
    path = BASE_DIR / rel
    return str(path) if path.exists() else None


def photo_of(p: dict):
    if is_hidden(p):
        return None
    if image_src(p.get("photo")):
        return image_src(p["photo"])
    for m in p.get("memories") or []:
        if m.get("kind") == "foto":
            if image_src(m.get("local_path")):
                return image_src(m["local_path"])
            if m.get("thumbnail", "").startswith("http"):
                return m["thumbnail"]
    return None


def place_text(f: dict) -> str:
    pl = f.get("place") or {}
    return pl.get("normalized") or pl.get("original") or ""


def date_text(f: dict) -> str:
    d = f.get("date") or {}
    return d.get("original") or d.get("normalized") or ""


def in_lineage(p: dict, mode: str) -> bool:
    if mode == "completa" or p.get("role") == "base":
        return True
    return mode in (p.get("lineage") or [])


def e(text) -> str:
    return html.escape(str(text)) if text is not None else ""


# ======================================================================================
# Barra lateral
# ======================================================================================
max_gen_available = max([p.get("generation") or 0 for p in P.values() if p.get("role") in ("base", "ancestor")] + [1])
with st.sidebar:
    st.markdown("## 🌳 Navegação")
    depth_options = sorted({g for g in (2, 3, 4, 5, 6, 8, 10, 12, 14) if g <= max_gen_available} | {max_gen_available})
    depth = st.select_slider("Profundidade exibida (gerações)", options=depth_options,
                             value=next((g for g in depth_options if g >= 4), depth_options[-1]),
                             help="Filhos = geração 0, pais = 1, avós = 2…")
    lineage_mode = st.radio("Linhagem", list(LINEAGE_LABELS), format_func=LINEAGE_LABELS.get)
    show_collateral = st.toggle("Mostrar ramos colaterais (irmãos e cônjuges)", value=False)
    graph_mode = st.radio("Modo do gráfico", ["Árvore principal", "Família da pessoa selecionada"],
                          help="O segundo modo mostra três gerações em volta da pessoa em foco, útil para ramos colaterais.")

    st.markdown("---")
    st.markdown("## 🔎 Busca")
    search_field = st.selectbox("Buscar por", ["Tudo", "Nome", "Sobrenome", "ID FamilySearch", "Local"])
    query = st.text_input("Digite para buscar", placeholder="ex.: sobrenome, cidade ou ID…")
    if query.strip():
        q = slug(query.strip())
        fields = {"Tudo": ("nome", "sobrenome", "local", "idfs"), "Nome": ("nome",), "Sobrenome": ("sobrenome",),
                  "ID FamilySearch": ("idfs",), "Local": ("local",)}[search_field]
        hits = [r["id"] for r in TREE["_index"] if any(q in r[f] for f in fields)]
        hits.sort(key=lambda pid: (P[pid].get("role") == "stub", P[pid].get("generation") is None,
                                   P[pid].get("generation") or 0, name(pid)))
        st.caption(f"{len(hits)} resultado(s)" + (" — mostrando 60" if len(hits) > 60 else ""))
        for pid in hits[:60]:
            p = P[pid]
            g = p.get("generation")
            st.button(f"{name(pid)}\n{lifespan(p)} · {pid}" + (f" · G{g}" if g is not None else ""),
                      key=f"hit-{pid}", on_click=select, args=(pid,), width="stretch")

    st.markdown("---")
    hide_default = setting("HIDE_LIVING", "false").lower() in ("1", "true", "yes", "sim")
    HIDE_LIVING = st.toggle("Ocultar detalhes de pessoas vivas", value=hide_default,
                            help="Recomendado ao publicar o painel. Também pode ser ativado com HIDE_LIVING=true nos Secrets.")
    st.caption(f"Fonte: {META.get('source', '')}")
    if META.get("generated_at"):
        st.caption(f"Atualizado em {META['generated_at'][:10]}")


# ======================================================================================
# Cabeçalho + métricas
# ======================================================================================
root_name = name(ROOT_ID) if ROOT_ID in P else "?"
spouse_name = name(SPOUSE_ID) if SPOUSE_ID in P else "?"
kid_names = ", ".join(name(k).split(" ")[0] for k in KIDS if k in P)
st.markdown(
    f"""<div class="hero"><h1>Árvore Genealógica da Família</h1>
<p>{e(kid_names)} · filhos de {e(root_name)} &amp; {e(spouse_name)} — {e(META.get('generations_reached', '?'))} gerações documentadas</p></div>""",
    unsafe_allow_html=True,
)
if IS_DEMO:
    st.info("**Modo demonstração:** os dados exibidos são **fictícios** (`data/sample/`). "
            "Importe o GEDCOM da sua árvore (`python -m collector.import_gedcom arquivo.ged`) para gerar `data/family_tree.json`.", icon="🧪")

full_people = [p for p in P.values() if p.get("details_loaded")]
surnames = Counter()
for p in full_people:
    s = p.get("surname") or (p.get("name") or "").split(" ")[-1]
    if s and s != "(sem nome)":
        surnames[s] += 1
fmt = lambda n: f"{n:,}".replace(",", ".")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Pessoas", fmt(len(P)), help=f"{fmt(len(full_people))} com ficha completa; demais como resumo")
m2.metric("Ancestrais diretos", fmt(sum(1 for p in P.values() if p.get("is_direct_ancestor"))))
m3.metric("Gerações", META.get("generations_reached", max_gen_available))
m4.metric("Fontes", fmt(META.get("sources_total", 0)))
m5.metric("Recordações", fmt(META.get("memories_total", 0)))
if surnames:
    st.markdown("<div style='margin:.2rem 0 .4rem'><span class='tl-meta'>Sobrenomes mais recorrentes:</span> " + " ".join(
        f"<span class='chip'>{e(s)} · {n}</span>" for s, n in surnames.most_common(8)) + "</div>", unsafe_allow_html=True)


# ======================================================================================
# Grafo
# ======================================================================================
COLW, ROWH = 200, 46  # horizontal: gerações da esquerda (filhos) para a direita (ancestrais)


def male_first(ids: list[str]) -> list[str]:
    return sorted(ids, key=lambda x: (P.get(x, {}).get("gender") != "M", x))


def spread(center: float, items: list[str], gen: int, pos: dict) -> None:
    for i, pid in enumerate(items):
        pos.setdefault(pid, (gen * COLW, (center + i - (len(items) - 1) / 2) * ROWH))


def layout_pedigree() -> tuple[dict, list[str]]:
    """Posições fixas (x, y) para a árvore principal, no formato clássico de pedigree:
    filhos à esquerda, ancestrais à direita; pai acima, mãe abaixo; cada pessoa
    centrada na faixa ocupada pelos seus próprios ancestrais (sem cruzamentos)."""
    trunk = {pid for pid, p in P.items()
             if p.get("role") in ("base", "ancestor") and (p.get("generation") or 0) <= depth and in_lineage(p, lineage_mode)}
    side: dict[str, list[str]] = {}  # pessoa do tronco -> colaterais exibidos ao lado dela
    if show_collateral:
        for pid in trunk:
            sibs = {c for par in P[pid].get("parents", []) if par in trunk
                    for c in P[par].get("children", []) if P.get(c, {}).get("role") == "collateral"}
            sps = [s for s in P[pid].get("spouses", []) if P.get(s, {}).get("role") == "collateral"]
            side[pid] = sorted(sibs, key=lambda c: lifespan(P[c])) + sps

    def tparents(pid: str) -> list[str]:
        return male_first([x for x in P.get(pid, {}).get("parents", []) if x in trunk])

    kids = [k for k in KIDS if k in trunk]
    top = male_first([x for x in (ROOT_ID, SPOUSE_ID) if x in trunk])
    widths: dict[str, float] = {}

    def width(pid: str, stack: frozenset = frozenset()) -> float:
        if pid not in widths:
            ps = [x for x in tparents(pid) if x not in stack]
            own = 1 + len(side.get(pid, []))
            widths[pid] = max(own, sum(width(x, stack | {pid}) for x in ps))
        return widths[pid]

    pos: dict[str, tuple[float, float]] = {}

    def place(pid: str, x0: float) -> None:
        if pid in pos:
            return  # colapso de pedigree: a pessoa aparece só uma vez
        w = width(pid)
        cx = x0 + w / 2
        x = (P[pid].get("generation") or 0) * COLW
        pos[pid] = (x, cx * ROWH)
        group = side.get(pid, [])
        for i, c in enumerate(group):  # colaterais alternando acima/abaixo
            off = (i // 2 + 1) * (1 if i % 2 else -1)
            pos.setdefault(c, (x, (cx + off) * ROWH))
        ps = tparents(pid)
        start = x0 + (w - sum(width(x) for x in ps)) / 2
        for x in ps:
            place(x, start)
            start += width(x)

    total = max(len(kids), sum(width(t) for t in top), 1)
    start = (total - sum(width(t) for t in top)) / 2
    for t in top:
        place(t, start)
        start += width(t)
    spread(total / 2, kids, 0, pos)
    return pos, kids


def layout_focus(sel: str) -> dict:
    """Três gerações em volta da pessoa em foco (avós → netos), com irmãos e cônjuges."""
    p = P[sel]
    g = p.get("generation") or 0
    parents = male_first([x for x in p.get("parents", []) if x in P])
    grand = [gp for par in parents for gp in male_first([x for x in P[par].get("parents", []) if x in P])]
    sibs = sorted({c for par in parents for c in P[par].get("children", []) if c != sel and c in P},
                  key=lambda c: lifespan(P[c]))
    spouses = [x for x in p.get("spouses", []) if x in P]
    kids = sorted([x for x in p.get("children", []) if x in P],
                  key=lambda k: (next((i for i, s in enumerate(spouses) if s in P[k].get("parents", [])), 99), lifespan(P[k])))
    gkids = [gk for k in kids for gk in P[k].get("children", []) if gk in P]
    half = len(sibs) // 2
    row0 = sibs[:half] + [sel] + spouses + sibs[half:]
    pos: dict = {}
    for items, dy in ((grand, 2), (parents, 1), (row0, 0), (kids, -1), (gkids, -2)):
        spread(0, items, g + dy, pos)
    return pos


def build_graph(pos: dict):
    sel = st.session_state.selected
    ids = set(pos)
    nodes, edges = [], []
    for pid, (x, y) in pos.items():
        p = P[pid]
        role = p.get("role")
        color = GREY if role in ("collateral", "stub") else LINEAGE_COLORS.get(lineage_key(p), NAVY)
        parts = (p.get("name") or pid).split()
        short = " ".join(parts[:1] + parts[-1:]) if len(parts) > 2 else " ".join(parts)
        is_sel = pid == sel
        light = role in ("collateral", "stub")
        nodes.append(Node(
            id=pid, label=f"{short}\n{lifespan(p)}",
            title=f"{p.get('name')} ({pid}) · {lifespan(p)}" + (
                f" · geração {p.get('generation')}" if p.get("generation") is not None else ""),
            shape="box", x=x, y=y, size=10, margin={"top": 5, "bottom": 5, "left": 8, "right": 8},
            widthConstraint={"minimum": 150, "maximum": 170},
            color={"background": "#FBF7EE" if light else color, "border": "#C0392B" if is_sel else color,
                   "highlight": {"background": "#F3EAD5" if light else color, "border": "#C0392B"},
                   "hover": {"background": "#F3EAD5" if light else color, "border": INK}},
            borderWidth=4 if is_sel else (1 if light else 1.5), shapeProperties={"borderRadius": 6},
            font={"face": "Georgia", "size": 13, "color": INK if light else "#FFFFFF", "multi": False},
        ))
    for pid in ids:
        for c in P[pid].get("children", []):
            if c in ids:
                edges.append(Edge(source=pid, target=c, color="#B9A98A", width=1.4))
    seen = set()
    for pid in ids:
        for s in P[pid].get("spouses", []):
            k = tuple(sorted((pid, s)))
            if s in ids and k not in seen:
                seen.add(k)
                edges.append(Edge(source=k[0], target=k[1], color=GOLD, dashes=True, width=1))
    return nodes, edges


def render_graph() -> None:
    sel = st.session_state.selected
    if graph_mode == "Família da pessoa selecionada":
        pos = layout_focus(sel)
        st.caption(f"Família de **{name(sel)}** — avós, pais, irmãos, cônjuges, filhos e netos.")
    else:
        pos, _ = layout_pedigree()
        if sel not in pos:
            st.caption(f"**{name(sel)}** está fora desta visão (profundidade/linhagem/colaterais). "
                       "Use o modo *Família da pessoa selecionada* para vê-la no gráfico.")
    if len(pos) > 1500:
        st.warning(f"{len(pos)} pessoas nesta visão — o gráfico pode ficar lento. Reduza a profundidade ou desative os colaterais.")
    nodes, edges = build_graph(pos)
    cfg = Config(height=760, width=1000, directed=False, physics=False, hierarchical=False)
    cfg.width = "100%"
    cfg.edges = {"smooth": {"type": "cubicBezier", "forceDirection": "horizontal", "roundness": 0.55},
                 "arrows": {"to": {"enabled": False}}}
    cfg.interaction = {"hover": True, "keyboard": True, "multiselect": False, "tooltipDelay": 150,
                       "zoomSpeed": 0.6}
    st.markdown(
        '<div class="legend">'
        f'<span><i style="background:{GREEN}"></i>Filhos (base)</span>'
        f'<span><i style="background:{NAVY}"></i>Linhagem {e(LIN_NAME["titular"])}</span>'
        f'<span><i style="background:{GOLD}"></i>Linhagem {e(LIN_NAME["conjuge"])}</span>'
        f'<span><i style="background:{PLUM}"></i>Ambas</span>'
        f'<span><i style="background:{GREY}"></i>Colateral / resumo</span>'
        '<span>· clique para abrir a ficha · role/arraste para zoom e navegação</span></div>',
        unsafe_allow_html=True,
    )
    clicked = agraph(nodes=nodes, edges=edges, config=cfg)
    if clicked and clicked != st.session_state.graph_last:
        st.session_state.graph_last = clicked
        if clicked in P and clicked != sel:
            st.session_state.selected = clicked
            st.rerun()


# ======================================================================================
# Ficha da pessoa
# ======================================================================================
def person_events(pid: str) -> list[dict]:
    p = P[pid]
    events = [dict(f) for f in p.get("facts") or []]
    for c in TREE["_couples"].get(pid, []):
        other = c["person2"] if c["person1"] == pid else c["person1"]
        for f in c.get("facts") or []:
            events.append({**f, "with": other})
    events.sort(key=lambda f: (fact_year(f) is None, fact_year(f) or 0, (f.get("date") or {}).get("formal") or ""))
    return events


def family_button(pid: str, key: str, extra: str = "") -> None:
    p = P.get(pid)
    if not p:
        return
    tag = {"stub": " · resumo", "collateral": " · colateral"}.get(p.get("role"), "")
    if p.get("is_direct_ancestor"):
        tag = f" · ancestral G{p.get('generation')}"
    icon = "👨" if p.get("gender") == "M" else "👩" if p.get("gender") == "F" else "👤"
    label = f"{icon} {p.get('name') or pid}\n{lifespan(p) or '—'}{tag}" + (f"\n{extra}" if extra else "")
    st.button(label, key=key, on_click=select, args=(pid,), width="stretch",
              help="Abrir a ficha desta pessoa")


def render_header(pid: str) -> None:
    p = P[pid]
    chips = []
    if p.get("role") == "base":
        chips.append('<span class="chip green">Base da árvore</span>')
    if p.get("is_direct_ancestor"):
        chips.append(f'<span class="chip navy">Ancestral direto · geração {e(p.get("generation"))}</span>')
    elif p.get("role") == "collateral":
        chips.append('<span class="chip">Ramo colateral</span>')
    elif p.get("role") == "stub":
        chips.append('<span class="chip">Somente resumo</span>')
    for lin in p.get("lineage") or []:
        chips.append(f'<span class="chip {"navy" if lin == "titular" else "gold"}">Linhagem {e(LIN_NAME.get(lin, lin))}</span>')
    if p.get("living"):
        chips.append('<span class="chip">Pessoa viva</span>')
    c1, c2 = st.columns([1, 3.2], vertical_alignment="center")
    with c1:
        ph = photo_of(p)
        if ph:
            st.image(ph, width="stretch")
        else:
            initials = "".join(w[0] for w in (p.get("name") or "?").split()[:2])
            st.markdown(
                f'<div style="aspect-ratio:4/5;border-radius:10px;background:#E5D8BB;display:flex;align-items:center;'
                f'justify-content:center;font-family:Cormorant Garamond,serif;font-size:2.4rem;color:{NAVY};'
                f'border:1px solid #CDBB93">{e(initials)}</div>', unsafe_allow_html=True)
    with c2:
        st.markdown(
            f'<div class="person-head"><div><h2>{e(p.get("name"))}</h2>'
            f'<div class="sub">{e(lifespan(p))} · ID '
            + (f'<a href="{e(p["familysearch_url"])}" target="_blank">{e(pid)}</a>' if p.get("familysearch_url") else e(pid))
            + '</div>'
            f'<div>{"".join(chips)}</div></div></div>', unsafe_allow_html=True)


def tab_overview(pid: str) -> None:
    p = P[pid]
    if is_hidden(p):
        st.info("Detalhes ocultos: pessoa viva (opção de privacidade ativa).")
        return
    if not p.get("details_loaded"):
        st.info("Esta pessoa foi registrada apenas como **resumo**.")
        rows = [("Nascimento", p.get("birth_date"), p.get("birth_place")), ("Óbito", p.get("death_date"), p.get("death_place"))]
        for label, d, pl in rows:
            if d or pl:
                st.markdown(f"**{label}:** {e(d or '')} {('— ' + e(pl)) if pl else ''}")
        if p.get("familysearch_url"):
            st.link_button("Abrir no FamilySearch ↗", p["familysearch_url"])
        return
    alt = [n for n in p.get("alt_names") or [] if n.get("full") != p.get("name")]
    if alt:
        st.markdown("**Nomes alternativos / variantes:** " + " · ".join(
            f"{e(n['full'])} <span class='chip'>{e(n.get('type') or '')}</span>" for n in alt), unsafe_allow_html=True)
    if p.get("life_sketch"):
        st.markdown("#### Esboço de vida")
        st.markdown(f'<div class="sketch">{e(p["life_sketch"])}</div>', unsafe_allow_html=True)
    events = person_events(pid)
    st.markdown("#### Linha do tempo")
    if not events:
        st.caption("Nenhum evento registrado.")
    else:
        items = []
        for f in events:
            year = fact_year(f)
            label = f.get("label") or f.get("type")
            if f.get("with"):
                label += f" com {name(f['with'])}"
            if f.get("value") and f.get("type") not in ("Birth", "Death"):
                label += f": {f['value']}"
            d = f.get("date") or {}
            date_bits = d.get("original") or ""
            if d.get("normalized") and d.get("normalized") != d.get("original"):
                date_bits += f" <span class='chip'>padronizada: {e(d['normalized'])}</span>"
            elif d.get("formal"):
                date_bits = e(date_bits) + f" <span class='chip'>{e(d['formal'])}</span>"
            else:
                date_bits = e(date_bits)
            pl = f.get("place") or {}
            place_bits = e(pl.get("original") or "")
            if pl.get("normalized") and pl.get("normalized") != pl.get("original"):
                place_bits += f" <span class='chip'>padronizado: {e(pl['normalized'])}</span>"
            items.append(
                f'<div class="tl-item"><span class="tl-year">{e(year) if year else "s/d"}</span> '
                f'<span class="tl-label">{e(EVENT_ICONS.get(f.get("type"), "•"))} {e(label)}</span>'
                f'<div class="tl-meta">{date_bits}{" · " + place_bits if place_bits else ""}</div></div>')
        st.markdown('<div class="timeline">' + "".join(items) + "</div>", unsafe_allow_html=True)
    notes = p.get("notes") or []
    if notes:
        st.markdown("#### Notas")
        for n in notes:
            with st.expander(n.get("subject") or "Nota"):
                st.write(n.get("text") or "(sem texto)")


def tab_family(pid: str) -> None:
    p = P[pid]
    parents = [x for x in p.get("parents", []) if x in P]
    siblings = sorted({s for par in parents for s in P[par].get("children", []) if s != pid and s in P},
                      key=lambda s: lifespan(P[s]))
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Pais")
        if not parents:
            st.caption("Pais não registrados.")
        for x in parents:
            family_button(x, f"par-{pid}-{x}")
    with c2:
        st.markdown("#### Cônjuges")
        spouses = [x for x in p.get("spouses", []) if x in P]
        if not spouses:
            st.caption("Nenhum cônjuge registrado.")
        for s in spouses:
            mar = ""
            for c in TREE["_couples"].get(pid, []):
                if s in (c["person1"], c["person2"]):
                    for f in c.get("facts") or []:
                        if f.get("type") == "Marriage":
                            mar = f"⚭ {date_text(f)}" + (f" · {place_text(f)}" if place_text(f) else "")
            family_button(s, f"sp-{pid}-{s}", mar)
    st.markdown("#### Filhos")
    kids = [x for x in p.get("children", []) if x in P]
    if not kids:
        st.caption("Nenhum filho registrado.")
    else:
        by_other: dict[str, list[str]] = {}
        for k in kids:
            others = [x for x in P[k].get("parents", []) if x != pid]
            by_other.setdefault(others[0] if others else "", []).append(k)
        for other, group in by_other.items():
            if len(by_other) > 1:
                st.caption(f"Com {name(other)}" if other else "Outro genitor não registrado")
            cols = st.columns(2)
            for i, k in enumerate(sorted(group, key=lambda k: lifespan(P[k]))):
                with cols[i % 2]:
                    family_button(k, f"ch-{pid}-{k}")
    if siblings:
        with st.expander(f"Irmãos ({len(siblings)})"):
            cols = st.columns(2)
            for i, s in enumerate(siblings):
                with cols[i % 2]:
                    family_button(s, f"sib-{pid}-{s}")


def tab_memories(pid: str) -> None:
    p = P[pid]
    if is_hidden(p):
        st.info("Recordações ocultas: pessoa viva.")
        return
    mems = p.get("memories") or []
    images = []
    if image_src(p.get("photo")):
        images.append((image_src(p["photo"]), "Retrato principal", None))
    stories = []
    for m in mems:
        src = None
        if image_src(m.get("local_path")):
            src = image_src(m["local_path"])
        elif (m.get("thumbnail") or "").startswith("http"):
            src = m["thumbnail"]
        if m.get("kind") in ("foto", "documento") and src:
            images.append((src, m.get("title") or m.get("kind").title(), m.get("url")))
        else:
            stories.append(m)
    if not images and not stories:
        st.caption("Nenhuma foto ou recordação vinculada a este perfil.")
        return
    if images:
        cols = st.columns(3)
        for i, (src, title, url) in enumerate(images):
            with cols[i % 3]:
                st.image(src, caption=title, width="stretch")
                if url and url.startswith("http"):
                    st.markdown(f"[ver original ↗]({url})")
    for m in stories:
        st.markdown(
            f'<div class="story"><b>{e(m.get("title") or m.get("kind", "").title())}</b>'
            f'<div class="tl-meta">{e(m.get("kind"))} · {e(m.get("created") or "")}</div>'
            f'<div>{e(m.get("description") or "")}</div></div>', unsafe_allow_html=True)
        if (m.get("url") or "").startswith("http"):
            st.markdown(f"[abrir recordação ↗]({m['url']})")


def tab_sources(pid: str) -> None:
    p = P[pid]
    if is_hidden(p):
        st.info("Fontes ocultas: pessoa viva.")
        return
    src = p.get("sources") or []
    if not src:
        st.caption("Nenhuma fonte anexada a este perfil.")
        return
    as_table = st.toggle("Ver como tabela", key=f"srctable-{pid}")
    if as_table:
        df = pd.DataFrame([{
            "Título": s.get("title"), "Data": s.get("date") or "", "Citação": s.get("citation") or "",
            "Etiquetas": ", ".join(s.get("tags") or []), "Anexada em": s.get("added") or "", "Link": s.get("url"),
        } for s in src])
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={"Link": st.column_config.LinkColumn("Consultar", display_text="abrir ↗")})
        return
    for s in sorted(src, key=lambda s: s.get("date") or ""):
        tags = " ".join(f"<span class='chip'>{e(t)}</span>" for t in s.get("tags") or [])
        meta = " · ".join(x for x in (e(s.get("date")), f"anexada em {e(s['added'])}" if s.get("added") else "") if x)
        link = f" · <a href='{e(s['url'])}' target='_blank'>consultar ↗</a>" if (s.get("url") or "").startswith("http") else ""
        st.markdown(
            f'<div class="story"><b>{e(s.get("title"))}</b><div class="tl-meta">{meta}{link}</div>'
            f'<div style="font-size:.9rem;margin-top:.25rem">{e(s.get("citation") or "")}</div>{tags}</div>',
            unsafe_allow_html=True)


def render_person(pid: str) -> None:
    render_header(pid)
    t1, t2, t3, t4 = st.tabs(["📜 Geral", "👪 Família", "🖼️ Fotos", "📚 Fontes"])
    with t1:
        tab_overview(pid)
    with t2:
        tab_family(pid)
    with t3:
        tab_memories(pid)
    with t4:
        tab_sources(pid)


# ======================================================================================
# Mapa e estatísticas
# ======================================================================================
@st.cache_data
def event_rows(path: str, mtime: float, key: str = "") -> pd.DataFrame:
    tree = load_tree(path, mtime, key)
    rows = []
    for pid, p in tree["persons"].items():
        if not p.get("details_loaded"):
            continue
        for f in p.get("facts") or []:
            pl = f.get("place") or {}
            if pl.get("lat") is None or f.get("type") not in ("Birth", "Christening", "Baptism", "Death", "Burial"):
                continue
            rows.append({"id": pid, "pessoa": p.get("name"), "evento": f.get("label"), "tipo": f.get("type"),
                         "ano": fact_year(f), "local": pl.get("normalized") or pl.get("original"),
                         "lat": pl["lat"], "lon": pl["lon"], "geração": p.get("generation"),
                         "papel": p.get("role"), "linhagem": ",".join(p.get("lineage") or []),
                         "living": bool(p.get("living"))})
    for c in (tree.get("relationships") or {}).get("couples") or []:
        for f in c.get("facts") or []:
            pl = f.get("place") or {}
            if f.get("type") != "Marriage" or pl.get("lat") is None:
                continue
            a, b = tree["persons"].get(c["person1"], {}), tree["persons"].get(c["person2"], {})
            main = a if a.get("role") in ("ancestor", "base") else b if b.get("role") in ("ancestor", "base") else a
            rows.append({"id": main.get("id"), "pessoa": f"{a.get('name')} & {b.get('name')}", "evento": "Casamento",
                         "tipo": "Marriage", "ano": fact_year(f), "local": pl.get("normalized") or pl.get("original"),
                         "lat": pl["lat"], "lon": pl["lon"], "geração": main.get("generation"),
                         "papel": main.get("role"), "linhagem": ",".join(main.get("lineage") or []),
                         "living": bool(a.get("living") or b.get("living"))})
    return pd.DataFrame(rows)


def render_map() -> None:
    df = event_rows(str(TREE_PATH), TREE_PATH.stat().st_mtime, DATA_KEY)
    if df.empty:
        st.info("Nenhum local com coordenadas. Rode o importador com `--geocode` para buscar as coordenadas.")
        return
    c1, c2, c3 = st.columns([2, 2, 3])
    types = c1.multiselect("Eventos", ["Nascimento/Batismo", "Casamento", "Óbito/Sepultamento"],
                           default=["Nascimento/Batismo", "Casamento"])
    only_direct = c2.toggle("Somente ancestrais diretos", value=True)
    group = {"Birth": "Nascimento/Batismo", "Christening": "Nascimento/Batismo", "Baptism": "Nascimento/Batismo",
             "Marriage": "Casamento", "Death": "Óbito/Sepultamento", "Burial": "Óbito/Sepultamento"}
    df = df.assign(grupo=df["tipo"].map(group))
    df = df[df["grupo"].isin(types)]
    if only_direct:
        df = df[df["papel"].isin(["ancestor", "base"])]
    if lineage_mode != "completa":
        df = df[df["linhagem"].str.contains(lineage_mode) | (df["papel"] == "base")]
    if HIDE_LIVING:
        df = df[~df["living"]]
    years = df["ano"].dropna()
    if years.empty:
        st.info("Sem eventos para os filtros escolhidos.")
        return
    lo, hi = int(years.min()), int(years.max())
    if lo < hi:
        lo, hi = c3.slider("Período", lo, hi, (lo, hi))
    df = df[df["ano"].between(lo, hi) | df["ano"].isna()]
    if df.empty:
        st.info("Sem eventos neste período.")
        return
    agg = (df.groupby(["local", "lat", "lon", "grupo"])
             .agg(eventos=("pessoa", "size"), pessoas=("pessoa", lambda s: "<br>".join(sorted(set(s))[:12])),
                  primeiro=("ano", "min"), ultimo=("ano", "max"))
             .reset_index())
    fig = px.scatter_geo(
        agg, lat="lat", lon="lon", size="eventos", color="grupo", size_max=34,
        hover_name="local", hover_data={"eventos": True, "primeiro": True, "ultimo": True, "pessoas": True,
                                        "lat": False, "lon": False, "grupo": False},
        color_discrete_map={"Nascimento/Batismo": NAVY, "Casamento": GOLD, "Óbito/Sepultamento": "#8C3B3B"},
        projection="natural earth", height=640,
    )
    fig.update_traces(marker=dict(opacity=0.8, line=dict(width=1, color="#FBF7EE")))
    fig.update_geos(fitbounds="locations", showcountries=True, countrycolor="#C9B88F", showcoastlines=True,
                    coastlinecolor="#B9A98A", landcolor="#EFE4CA", showocean=True, oceancolor="#DCE3E3",
                    showlakes=False, bgcolor=PARCH, resolution=50, lataxis_range=None)
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), legend=dict(title="", orientation="h", y=1.04, x=0),
                      paper_bgcolor=PARCH, font_family="Georgia")
    st.plotly_chart(fig, width="stretch")
    st.caption(f"{len(df)} eventos em {df['local'].nunique()} locais, de {lo} a {hi}.")
    with st.expander("Locais mais frequentes"):
        top = df.groupby("local").agg(eventos=("pessoa", "size"), de=("ano", "min"), até=("ano", "max")) \
                .sort_values("eventos", ascending=False).head(30)
        st.dataframe(top, width="stretch")


def render_stats() -> None:
    rows = []
    for p in P.values():
        b = first_fact(p, "Birth", "Christening", "Baptism")
        rows.append({"surname": p.get("surname") or (p.get("name") or "").split(" ")[-1], "role": p.get("role"),
                     "generation": p.get("generation"), "lineage": lineage_key(p),
                     "birth_year": fact_year(b) if b else None,
                     "country": (place_text(b).split(",")[-1].strip() if b and place_text(b) else None)})
    df = pd.DataFrame(rows)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Sobrenomes mais recorrentes")
        top = df[df["role"] != "stub"]["surname"].value_counts().head(15).sort_values()
        fig = px.bar(top, orientation="h", color_discrete_sequence=[NAVY], height=430)
        fig.update_layout(showlegend=False, xaxis_title="pessoas", yaxis_title="", paper_bgcolor=PARCH,
                          plot_bgcolor=PARCH, margin=dict(l=0, r=10, t=10, b=0), font_family="Georgia")
        st.plotly_chart(fig, width="stretch")
    with c2:
        st.markdown("#### Ancestrais diretos por geração")
        anc = df[df["role"].isin(["ancestor", "base"])].dropna(subset=["generation"])
        lt, lc = LIN_NAME["titular"], LIN_NAME["conjuge"]
        anc = anc.assign(linhagem=anc["lineage"].map({"titular": lt, "conjuge": lc,
                                                      "both": "Ambas", "base": "Filhos"}))
        counts = anc.groupby(["generation", "linhagem"]).size().reset_index(name="pessoas")
        fig = px.bar(counts, x="generation", y="pessoas", color="linhagem", height=430,
                     color_discrete_map={lt: NAVY, lc: GOLD, "Ambas": PLUM, "Filhos": GREEN})
        fig.update_layout(xaxis_title="geração", yaxis_title="", paper_bgcolor=PARCH, plot_bgcolor=PARCH,
                          legend_title="", margin=dict(l=0, r=10, t=10, b=0), font_family="Georgia")
        st.plotly_chart(fig, width="stretch")
    c3, c4 = st.columns(2)
    with c3:
        st.markdown("#### Nascimentos por década")
        yrs = df.dropna(subset=["birth_year"])
        yrs = yrs.assign(decada=(yrs["birth_year"] // 10 * 10).astype(int))
        fig = px.histogram(yrs, x="decada", color_discrete_sequence=[GOLD], height=360)
        fig.update_layout(xaxis_title="", yaxis_title="", paper_bgcolor=PARCH, plot_bgcolor=PARCH,
                          margin=dict(l=0, r=10, t=10, b=0), bargap=0.08, font_family="Georgia")
        st.plotly_chart(fig, width="stretch")
    with c4:
        st.markdown("#### Países / regiões de nascimento")
        countries = df["country"].dropna().value_counts().head(10).sort_values()
        fig = px.bar(countries, orientation="h", color_discrete_sequence=[GREEN], height=360)
        fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="", paper_bgcolor=PARCH,
                          plot_bgcolor=PARCH, margin=dict(l=0, r=10, t=10, b=0), font_family="Georgia")
        st.plotly_chart(fig, width="stretch")


# ======================================================================================
# Layout principal
# ======================================================================================
tab_tree, tab_map, tab_stats = st.tabs(["🌳 Árvore & ficha", "🗺️ Mapa da família", "📊 Estatísticas"])
with tab_tree:
    col_graph, col_person = st.columns([1.35, 1], gap="large")
    with col_graph:
        render_graph()
    with col_person:
        render_person(st.session_state.selected)
with tab_map:
    render_map()
with tab_stats:
    render_stats()
