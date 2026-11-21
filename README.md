# 🌳 Árvore Genealógica Interativa (FamilySearch Dashboard)

Painel em **Python + Streamlit** para explorar uma árvore da família: parte dos **filhos**,
sobe pelo **titular** e pelo **cônjuge** e vai até **14 gerações**. Inclui os ramos colaterais
(irmãos e cônjuges dos ancestrais). Os dados reais ficam **criptografados** (ver seção 5).

O projeto tem duas partes:

| Parte | Onde roda | O que faz |
|---|---|---|
| `collector/import_gedcom.py` | No seu computador | Converte um arquivo **GEDCOM** da sua árvore em `data/family_tree.json` |
| `app.py` | Local ou Streamlit Cloud | Lê apenas os arquivos de `data/` |

O projeto **não acessa o FamilySearch**. A árvore chega por um arquivo GEDCOM exportado
por um **programa parceiro certificado** do FamilySearch, que usa a API oficial com o seu login.

Enquanto `data/family_tree.json` não existir, o painel abre em **modo demonstração**
com uma família **fictícia** (`data/sample/`).

---

## 1. Instalação (Windows, no PowerShell)

```powershell
cd $HOME
git clone https://github.com/Ovando18/arvoregenealogica.git
cd arvoregenealogica
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Se a ativação der erro de "execução de scripts desabilitada", rode
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e tente de novo.

## 2. Obter a árvore em GEDCOM

O site do FamilySearch não exporta a árvore diretamente. Use um programa parceiro
gratuito, como o **RootsMagic Essentials** (rootsmagic.com) ou o **Ancestral Quest Basics**
(ancquest.com). Os nomes dos menus podem variar conforme a versão:

1. Instale o programa e crie um arquivo novo.
2. Escolha importar do FamilySearch, faça login **com a sua conta** e comece pelo
   **titular** da árvore (você, pelo seu ID do FamilySearch).
3. Peça o máximo de **gerações de ancestrais** (até 14) e inclua os **descendentes**
   (os filhos) e os ramos colaterais desejados. Se possível, traga também notas,
   fontes e mídias.
4. Exporte como **GEDCOM** (por exemplo, `arvore.ged`). Inclua notas, fontes, links de
   multimídia e os IDs do FamilySearch, se o programa oferecer essas opções.

## 3. Importar

O importador aceita o **GEDCOM** (`.ged`) ou diretamente o **arquivo do RootsMagic** (`.rmtree`),
sem precisar exportar. Vários arquivos são **combinados pelo ID do FamilySearch**. Isso é útil
porque cada download do RootsMagic parte de uma pessoa: baixe um arquivo a partir do titular
e outro a partir do cônjuge, e importe os dois juntos (troque `ABCD-123` pelo ID do titular):

```powershell
python -m collector.import_gedcom C:\caminho\titular.rmtree C:\caminho\conjuge.rmtree --root ABCD-123 --geocode
```

Para um único arquivo:

```powershell
python -m collector.import_gedcom C:\caminho\para\arvore.ged --root ABCD-123
```

O importador:

1. Encontra o titular pelo ID do FamilySearch (`--root`) ou, se o arquivo não tiver IDs,
   pelo nome completo (`--root-name "Nome Completo"`).
2. Identifica o cônjuge e os filhos do casal. Com `--expect-children "Ana,Pedro"`, avisa se
   algum filho esperado não aparecer; com `--spouse-name`, escolhe entre vários cônjuges.
3. Calcula as gerações (filhos = 0, titular e cônjuge = 1, avós = 2, … até `--generations 14`)
   e as linhagens `titular` / `conjuge`.
4. Marca como **colaterais** todos os parentes conectados ao tronco (irmãos dos ancestrais,
   outros cônjuges, sobrinhos…), com a geração relativa de cada um.
5. Converte nomes e variantes, eventos (com data original e padronizada), casamentos e
   divórcios, notas, esboço de vida, citações de fontes (com links, quando houver) e fotos.

Cada pessoa em `family_tree.json` traz `generation`, `is_direct_ancestor`, `role`
(`base` / `ancestor` / `collateral`) e `lineage`.

### Opções úteis

```text
--geocode               busca as coordenadas dos locais no OpenStreetMap, para o mapa
                        (1 consulta por segundo, com cache em data/places_cache.json)
--media-dir PASTA       pasta onde estão as fotos citadas no GEDCOM
--no-photos             não copia fotos para data/photos/
--generations 14        limite de gerações do tronco
--collateral-depth 2    limita a distância dos colaterais (padrão: todos os conectados)
--spouse-id ID          informa a cônjuge se a detecção automática falhar
```

As fotos encontradas são **reduzidas** (máximo de 900 px) e copiadas para `data/photos/`.
Se o GEDCOM já tiver coordenadas (`MAP/LATI/LONG`), o `--geocode` não é necessário para esses locais.

Para atualizar a árvore depois, exporte um GEDCOM novo e rode o importador outra vez.

## 4. Painel (`app.py`)

```bash
streamlit run app.py
```

- **Árvore** em formato clássico de pedigree (filhos à esquerda, ancestrais à direita; pai acima,
  mãe abaixo), com profundidade de 2 a 14 gerações, filtro de linhagem
  (completa / só do titular / só do cônjuge, com os nomes vindos dos dados) e ramos colaterais opcionais.
- **Modo “Família da pessoa selecionada”:** avós, pais, irmãos, cônjuges, filhos e netos de qualquer
  pessoa, inclusive de ramos colaterais.
- **Busca** por nome (inclui variantes), sobrenome, ID FamilySearch ou local.
- **Ficha com 4 abas:** Geral (foto, variantes do nome, esboço de vida, notas e linha do tempo
  com data e local originais e padronizados) · Família (cards clicáveis que mudam o foco)
  · Fotos & recordações · Fontes (com citação e link).
- **Mapa** de nascimentos, casamentos e óbitos, com filtro de período; **estatísticas** de
  sobrenomes, gerações, décadas e países.

### Testes

```bash
python -m pytest -q
```

Os testes importam um GEDCOM de uma família **fictícia** (`collector/demo_world.py`) e conferem
datas, nomes, locais, tronco, linhagens, colaterais, fontes e fotos. Também abrem o painel com
`streamlit.testing`. Para regenerar a demonstração:
`python -m collector.make_sample`.

## 5. Publicação (repositório público + dados criptografados)

Este repositório é **público**. Os dados reais da família **nunca** vão para ele em forma legível:

| Arquivo | Vai para o GitHub? |
|---|---|
| Código, `data/sample/` (fictício) | ✅ sim |
| `data/family_tree.enc` (árvore **criptografada**) | ✅ sim, ilegível sem a chave |
| `data/family_tree.json`, `data/photos/`, `*.rmtree`, `*.ged` | ❌ não (`.gitignore`) |
| `.streamlit/secrets.toml` (chave e senha) | ❌ não (`.gitignore`) |

### Criptografar e enviar

```powershell
python -m collector.encrypt
git add data/family_tree.enc
git commit -m "Atualizar árvore (criptografada)"
git push
```

Na primeira vez, o comando gera uma chave aleatória (`DATA_KEY`) e pede a **senha de acesso**
(`APP_PASSWORD`) que você vai passar à família. As duas ficam só em `.streamlit/secrets.toml`,
no seu computador. O comando mostra o bloco a colar no Streamlit Cloud.

Antes de cada `git push`, confira com `git status` que só o `.enc` está indo.

### Streamlit Community Cloud

1. Em <https://share.streamlit.io>, clique em **Create app**, escolha este repositório, branch `main` e arquivo `app.py`.
2. Em **Advanced settings → Secrets**, cole o bloco mostrado pelo `collector.encrypt`:
   ```toml
   DATA_KEY = "…"
   APP_PASSWORD = "…"
   HIDE_LIVING = "true"
   ```
3. Clique em **Deploy**. Quem abrir o link verá uma tela de senha. Com a senha certa, a árvore é
   descriptografada na memória do servidor.

Para atualizar: rode o importador, depois `python -m collector.encrypt`, e faça commit/push do `.enc`.
A chave e a senha são mantidas, então não é preciso mexer nos Secrets. Para trocar a senha, use
`python -m collector.encrypt --new-password` e atualize `APP_PASSWORD` nos Secrets.

> 🔒 Quem tem a senha vê toda a árvore. Com `HIDE_LIVING = "true"`, o painel abre ocultando datas,
> locais, fotos e fontes de pessoas vivas, inclusive dos menores de idade. **Nunca** publique a
> `DATA_KEY` nem o `secrets.toml`.

## Estrutura

```text
arvore-familysearch/
├── .gitignore
├── .streamlit/config.toml     # tema pergaminho / azul-marinho / dourado
├── requirements.txt
├── README.md
├── app.py                     # painel Streamlit
├── collector/
│   ├── __init__.py
│   ├── import_gedcom.py       # GEDCOM → data/family_tree.json
│   ├── rmtree.py              # leitura direta do arquivo do RootsMagic
│   ├── encrypt.py             # criptografia da árvore para o repositório público
│   ├── demo_world.py          # família fictícia em GEDCOM (testes / demonstração)
│   └── make_sample.py         # gera data/sample/
├── data/
│   ├── family_tree.enc        # árvore criptografada (vai para o GitHub)
│   ├── family_tree.json       # árvore legível (só no seu computador)
│   ├── places_cache.json      # cache de coordenadas (--geocode)
│   ├── photos/                # fotos reduzidas
│   └── sample/                # dados FICTÍCIOS de demonstração
└── tests/
```

---

*Uso pessoal. Os dados vêm do FamilySearch por meio de programas parceiros certificados,
respeitando os Termos de Uso do FamilySearch.*
