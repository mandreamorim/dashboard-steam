"""Dashboard interativo (Streamlit) recriando a lógica do relatório Power BI.

Fontes: arquivo `trabalho com a teresa.pbix` (apenas referência, nunca alterado)
e `data/games_march2025_cleaned.csv` (via preparar_dados.py).
"""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from preparar_dados import SAIDA, preparar

BASE = Path(__file__).resolve().parent

PALETA = [
    "#1F9D8F",  # teal
    "#3A6EA5",  # azul
    "#E9A23B",  # âmbar
    "#7B61FF",  # roxo
    "#D1495B",  # vermelho
    "#2E9E6B",  # verde
]
NAVY = "#12263A"
CINZA = "#52677A"
BORDA = "#DCE4EC"
GRID = "#E6ECF2"
FUNDO = "#F5F7FA"

CSS = f"""
<style>
  .stApp {{ background-color: {FUNDO}; }}
  .block-container {{ padding-top: 1.6rem; max-width: 1550px; }}
  [data-testid="stSidebar"] {{ background-color: #FFFFFF; border-right: 1px solid {BORDA}; }}
  [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ color: {NAVY}; }}
  h1, h2, h3 {{ color: {NAVY}; font-family: "Segoe UI", sans-serif; }}
  .subtitulo {{ color: {CINZA}; font-size: 0.92rem; margin-bottom: 1.1rem; }}
  .kpi-label {{ color: {CINZA}; font-size: 0.75rem; text-transform: uppercase;
                letter-spacing: .06em; font-weight: 600; }}
  .kpi-valor {{ color: {NAVY}; font-size: 1.55rem; font-weight: 700;
                font-family: "Segoe UI", sans-serif; line-height: 1.25; }}
  [data-testid="stMetricValue"] {{ color: {NAVY}; }}
  .selecao-chip {{ display:inline-block; background:{PALETA[0]}18; color:{PALETA[0]};
                   border:1px solid {PALETA[0]}55; border-radius:999px;
                   padding:.25rem .8rem; font-size:.82rem; font-weight:600; }}
</style>
"""


# ---------------------------------------------------------------------------
# Exclusão de jogos, publishers e desenvolvedores
# ---------------------------------------------------------------------------

TIPOS_EXCLUIVEIS = {"jogo", "publisher", "developer"}
ROTULO_EXCLUSAO = {
    "jogo": "Excluir jogo em foco",
    "publisher": "Excluir publisher em foco",
    "developer": "Excluir desenvolvedor em foco",
}


def adicionar_exclusao(selecao: dict[str, Any]) -> None:
    """Guarda o jogo/pub/dev clicado para remover todos os seus jogos."""
    tipo = selecao.get("tipo")
    valor = selecao.get("valor")
    if tipo not in TIPOS_EXCLUIVEIS or valor is None:
        return
    if tipo == "jogo":
        jogos = set(st.session_state.get("jogos_excluidos", []))
        jogos.add(int(valor))
        st.session_state["jogos_excluidos"] = sorted(jogos)
    else:
        entidades = list(st.session_state.get("entidades_excluidas", []))
        if not any(
            item.get("tipo") == tipo and item.get("valor") == valor
            for item in entidades
        ):
            entidades.append({"tipo": tipo, "valor": valor})
        st.session_state["entidades_excluidas"] = entidades
    st.session_state["selecionado"] = None


def callback_excluir_foco() -> None:
    """Botão nativo: exclui o jogo/pub/dev em foco pelo clique esquerdo."""
    selecao = st.session_state.get("selecionado")
    if selecao and selecao.get("tipo") in TIPOS_EXCLUIVEIS:
        adicionar_exclusao(selecao)


def callback_restaurar_exclusoes() -> None:
    """Volta a considerar todos os jogos e entidades do parquet."""
    st.session_state["jogos_excluidos"] = []
    st.session_state["entidades_excluidas"] = []
    st.session_state["selecionado"] = None


# ---------------------------------------------------------------------------
# Carregamento e transformações derivadas
# ---------------------------------------------------------------------------


def parse_lista(valor: Any) -> list[str]:
    """Converte uma string tipo "['A', 'B']" em lista de strings."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return []
    try:
        obj = ast.literal_eval(str(valor))
    except (ValueError, SyntaxError):
        return []
    if not isinstance(obj, (list, tuple, set)):
        obj = [obj]
    return [str(item).strip() for item in obj if str(item).strip()]


@st.cache_data(show_spinner="Lendo base de jogos...")
def carregar_base() -> pd.DataFrame:
    if not SAIDA.exists():
        preparar(verbose=False)
    base = pd.read_parquet(SAIDA)
    base["genero_principal"] = base["genres"].map(
        lambda s: (parse_lista(s) or [None])[0]
    )
    return base


COLUNAS_FATO = [
    "appid", "ano_lancamento", "name", "price", "positive", "negative",
    "estimated_owners_num", "average_playtime_forever", "num_reviews_total",
    "pct_pos_total", "publishers", "developers",
]


def explodir(base: pd.DataFrame, coluna: str, nome: str) -> pd.DataFrame:
    """Uma linha por jogo por editora/desenvolvedora/gênero (tabelas 'gambiarra')."""
    itens = base[coluna].map(parse_lista)
    out = base[COLUNAS_FATO].copy()
    out[nome] = itens
    out = out.explode(nome).dropna(subset=[nome])
    out[nome] = out[nome].astype(str)
    return out[out[nome] != ""].reset_index(drop=True)


@st.cache_data(show_spinner="Montando dimensões...")
def carregar_tabelas_longas() -> dict[str, pd.DataFrame]:
    base = carregar_base()
    return {
        "publisher": explodir(base, "publishers", "entidade"),
        "developer": explodir(base, "developers", "entidade"),
        "genero": explodir(base, "genres", "genero"),
        "categoria": explodir(base, "categories", "categoria"),
    }


@st.cache_data(show_spinner="Indexando editoras e desenvolvedoras...")
def opcoes_entidades() -> dict[str, list[str]]:
    """Nomes de todas as entidades, com as maiores no início da lista.

    São ~50 mil publishers e ~60 mil developers: renderizar tudo no
    multiselect é inviável, então a sidebar mostra só um topo (ou os resultados
    da busca) e mantém os itens já escolhidos sempre visíveis.
    """
    tabelas = carregar_tabelas_longas()
    opcoes: dict[str, list[str]] = {}
    for tipo in ("publisher", "developer"):
        contagem = (
            tabelas[tipo].groupby("entidade")["appid"].nunique()
            .sort_values(ascending=False)
        )
        principais = list(contagem.head(150).index)
        vistos = set(principais)
        opcoes[tipo] = principais + sorted(
            nome for nome in contagem.index if nome not in vistos
        )
    return opcoes


def entidades_grafico(
    agg: pd.DataFrame,
    coluna: str,
    limite: int,
    selecionadas: list[str] | None,
    peso: str = "reviews",
) -> list[str]:
    """Top `limite` por `peso`, garantindo que as entidades escolhidas apareçam."""
    ranking = agg.groupby(coluna)[peso].sum().sort_values(ascending=False)
    top = list(ranking.head(limite).index)
    if not selecionadas:
        return top
    validas = set(ranking.index)
    escolhidas = [e for e in selecionadas if e in validas]
    return escolhidas + [e for e in top if e not in escolhidas]


# ---------------------------------------------------------------------------
# Medidas (equivalentes às medidas DAX do Power BI)
# ---------------------------------------------------------------------------


def medidas(dados: pd.DataFrame) -> dict[str, float]:
    if dados.empty:
        return dict.fromkeys(
            ["qtd_jogos", "pct_positivas", "reviews", "playtime", "preco", "popularidade"],
            float("nan"),
        )
    positivas = float(dados["positive"].sum())
    negativas = float(dados["negative"].sum())
    total_av = positivas + negativas
    medias = dict(
        qtd_jogos=float(dados["appid"].nunique()),
        pct_positivas=positivas / total_av if total_av else float("nan"),
        reviews=float(dados["num_reviews_total"].fillna(0).sum()),
        playtime=float(dados.loc[dados["average_playtime_forever"] > 0, "average_playtime_forever"].mean()),
        preco=float(dados.loc[dados["price"] > 0, "price"].mean()),
        # Média simples de todos os jogos: títulos grandes (ex.: War Thunder)
        # entram normalmente, sem remoção de outlier nem winsorização.
        popularidade=float(dados["estimated_owners_num"].mean()),
    )
    return medias


def agregar(dados: pd.DataFrame, colunas: str | list[str]) -> pd.DataFrame:
    """Agrega dados por entidade/ano/gênero mantendo as medidas do modelo."""
    d = dados.copy()
    d["_reviews"] = d["num_reviews_total"].fillna(0)
    d["_playtime"] = d["average_playtime_forever"].where(
        d["average_playtime_forever"] > 0
    )
    d["_preco"] = d["price"].where(d["price"] > 0)
    out = (
        d.groupby(colunas, dropna=False)
        .agg(
            qtd_jogos=("appid", "nunique"),
            positive=("positive", "sum"),
            negative=("negative", "sum"),
            reviews=("_reviews", "sum"),
            playtime=("_playtime", "mean"),
            popularidade=("estimated_owners_num", "mean"),
            preco=("_preco", "mean"),
        )
        .reset_index()
    )
    denominador = out["positive"] + out["negative"]
    out["pct_positivas"] = np.where(
        denominador > 0, out["positive"] / denominador.replace(0, np.nan), np.nan
    )
    return out


# ---------------------------------------------------------------------------
# Formatação e estilo dos gráficos
# ---------------------------------------------------------------------------


def fmt_int(valor: float) -> str:
    return "—" if pd.isna(valor) else f"{int(round(valor)):,}".replace(",", ".")


def fmt_pct(valor: float) -> str:
    return "—" if pd.isna(valor) else f"{valor * 100:,.1f}%".replace(",", ".")


def fmt_dec(valor: float) -> str:
    return "—" if pd.isna(valor) else f"{valor:,.2f}".replace(",", ".")


def estilo_fig(fig: go.Figure, altura: int = 450) -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=altura,
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Segoe UI, Arial, sans-serif", size=12, color=NAVY),
        margin=dict(l=55, r=25, t=20, b=55),
        hoverlabel=dict(
            bgcolor="#FFFFFF", bordercolor=BORDA,
            font=dict(family="Segoe UI", size=12, color=NAVY),
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, x=0,
            font=dict(size=10, color=CINZA), title=None,
        ),
    )
    fig.update_xaxes(
        gridcolor=GRID, zeroline=False, linecolor=BORDA,
        title_font=dict(size=12, color=CINZA), tickfont=dict(color=CINZA, size=10),
    )
    fig.update_yaxes(
        gridcolor=GRID, zeroline=False, linecolor=BORDA,
        title_font=dict(size=12, color=CINZA), tickfont=dict(color=CINZA, size=10),
    )
    return fig


def tamanhos(
    valores: pd.Series,
    max_px: float = 38,
    min_px: float = 10,
    escala: float | None = None,
    base: float | None = None,
    log: bool = True,
) -> np.ndarray:
    """Diâmetro das bolhas, por padrão em escala logarítmica.

    A escala log é ancorada no **menor valor positivo exibido**, não no zero.
    Ancorar no zero comprime tudo para o meio da faixa (ex.: reviews de 4 mil
    a 8,6 M viravam 21-34 px); com a âncora no mínimo, o menor ponto fica em
    `min_px` e o maior em `max_px`, com a compressão log entre eles.

    `escala` e `base` permitem usar os mesmos limites em várias séries
    (grupos), para que bolhas de grupos diferentes sejam comparáveis.
    """
    v = pd.to_numeric(valores, errors="coerce").fillna(0).clip(lower=0).to_numpy(float)
    topo = float(escala) if escala is not None and float(escala) > 0 else (v.max() if len(v) else 0)
    if not len(v) or not topo or pd.isna(topo) or topo <= 0:
        return np.full(len(v), float(min_px))

    if not log:
        piso = float(base) if base is not None and float(base) >= 0 else 0.0
        if piso >= topo:
            return np.full(len(v), float(min_px))
        normalizado = (np.clip(v, piso, topo) - piso) / (topo - piso)
    else:
        piso = float(base) if base is not None and float(base) > 0 else (
            v[v > 0].min() if (v > 0).any() else 0.0
        )
        if not piso or pd.isna(piso) or piso >= topo:
            return np.full(len(v), float(min_px))
        normalizado = (
            np.log(np.clip(v, piso, topo)) - np.log(piso)
        ) / (np.log(topo) - np.log(piso))

    return min_px + normalizado * (max_px - min_px)


def selecao_json(tipo: str, valor: Any) -> str:
    return json.dumps({"tipo": tipo, "valor": valor}, ensure_ascii=False)


def scatter_agrupado(
    agg: pd.DataFrame,
    grupo: str,
    x: str,
    y: str,
    tamanho: str,
    tipo: str,
    titulos: tuple[str, str],
    max_grupos: int = 25,
    grupos: list[str] | None = None,
) -> go.Figure:
    """Dispersão com uma série por entidade/gênero e seleção no clique."""
    if grupos is None:
        total = agg.groupby(grupo)["reviews"].sum().sort_values(ascending=False)
        grupos = list(total.head(max_grupos).index)
    else:
        validos = set(agg[grupo].dropna())
        grupos = [g for g in grupos if g in validos]

    # Uma escala única para todos os grupos: sem isso, cada série (que, na
    # maioria das vezes, tem um único ponto) normalizaria pelo próprio máximo
    # e todas as bolhas ficariam com o mesmo diâmetro.
    visiveis = agg[agg[grupo].isin(grupos)]
    vals = pd.to_numeric(visiveis[tamanho], errors="coerce").clip(lower=0)
    escala = vals.max()
    base = vals[vals > 0].min()

    fig = go.Figure()
    for i, nome in enumerate(grupos):
        g = agg[agg[grupo] == nome]
        custom = pd.DataFrame(
            {
                "_sel": [selecao_json(tipo, nome)] * len(g),
                "rotulo": g[grupo].astype(str),
                "qtd": g["qtd_jogos"],
                "pct": g["pct_positivas"],
                "reviews": g["reviews"],
                "play_horas": g["playtime"] / 60,
                "pop": g["popularidade"],
            }
        )
        fig.add_trace(
            go.Scatter(
                x=g[x], y=g[y], mode="markers", name=str(nome),
                customdata=custom,
                marker=dict(
                    size=tamanhos(g[tamanho], escala=escala, base=base),
                    color=PALETA[i % len(PALETA)],
                    opacity=0.78, line=dict(width=0.5, color="#FFFFFF"),
                ),
                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>"
                    "Qtd. jogos: %{customdata[2]:,.0f}<br>"
                    "% positivas: %{customdata[3]:.1%}<br>"
                    "Reviews: %{customdata[4]:,.0f}<br>"
                    "Tempo médio: %{customdata[5]:.1f} h<br>"
                    "Popularidade média: %{customdata[6]:,.0f}"
                    "<extra></extra>"
                ),
            )
        )
    fig.update_layout(xaxis_title=titulos[0], yaxis_title=titulos[1])
    return estilo_fig(fig)


def pizza_portfolio(
    jogos: pd.DataFrame,
    selecao_por_fatia,
    top_n: int = 8,
) -> tuple[go.Figure, int]:
    """Donut dos gêneros principais de um grupo de jogos.

    Cada jogo entra **uma única vez**, pelo primeiro gênero da lista original.
    Assim as fatias somam 100% do grupo, diferente da contagem por gênero (onde
    um jogo com vários gêneros aparece em cada um deles). `selecao_por_fatia`
    define o que é gravado no clique de cada fatia.
    """
    jogos = jogos.dropna(subset=["genero_principal"])
    if jogos.empty:
        return go.Figure(), 0

    contagem = jogos["genero_principal"].value_counts()
    if len(contagem) > top_n:
        contagem = pd.concat(
            [
                contagem.iloc[:top_n],
                pd.Series({"Outros": int(contagem.iloc[top_n:].sum())}),
            ]
        )
    total = int(contagem.sum())
    rotulos = [str(g) for g in contagem.index]
    custom = pd.DataFrame(
        {
            "_sel": [selecao_por_fatia(g) for g in rotulos],
            "rotulo": rotulos,
            "qtd": contagem.to_numpy(),
            "pct": contagem.to_numpy() / total,
        }
    )
    cores = [PALETA[i % len(PALETA)] for i in range(len(contagem))]
    if "Outros" in rotulos:
        cores[rotulos.index("Outros")] = "#A9B6C3"

    fig = go.Figure(
        go.Pie(
            labels=rotulos,
            values=contagem.to_numpy(),
            customdata=custom,
            hole=0.42,
            sort=False,
            textinfo="percent",
            insidetextorientation="radial",
            marker=dict(colors=cores, line=dict(width=1, color="#FFFFFF")),
            hovertemplate=(
                "<b>%{customdata[1]}</b><br>"
                "Jogos: %{customdata[2]:,.0f}<br>"
                "Participação: %{customdata[3]:.1%}"
                "<extra></extra>"
            ),
        )
    )
    fig = estilo_fig(fig, 430)
    fig.update_layout(
        legend=dict(
            orientation="v", yanchor="middle", y=0.5, x=1.01,
            font=dict(size=10, color=CINZA), title=None,
        ),
        margin=dict(l=10, r=10, t=10, b=10),
    )
    fig.add_annotation(
        x=0.5, y=0.5, showarrow=False,
        text=f"<b>{total:,}</b><br>jogos".replace(",", "."),
        font=dict(size=14, color=NAVY, family="Segoe UI"),
    )
    return fig, total


# ---------------------------------------------------------------------------
# Interatividade: clique nos gráficos
# ---------------------------------------------------------------------------


def callback_selecao(chave: str):
    """Callback de on_select: grava o ponto clicado como foco."""

    def _callback() -> None:
        estado = st.session_state.get(chave)
        selecao = getattr(estado, "selection", None) if estado else None
        pontos = dict(selecao).get("points", []) if selecao else []
        if not pontos:
            return
        cru = pontos[0].get("customdata")
        if isinstance(cru, (list, tuple, np.ndarray)):
            cru = cru[0] if len(cru) else None
        if not isinstance(cru, str):
            return
        try:
            objeto = json.loads(cru)
        except json.JSONDecodeError:
            return
        tipo = objeto.get("tipo")
        if tipo not in {"publisher", "developer", "genero", "ano", "jogo"}:
            return
        if st.session_state.get("modo_exclusao"):
            # Switch ligado: o clique vira exclusão, sem abrir foco.
            if tipo in TIPOS_EXCLUIVEIS:
                adicionar_exclusao(objeto)
            return
        st.session_state["selecionado"] = objeto

    return _callback


def aplicar_selecao(
    base: pd.DataFrame,
    longas: dict[str, pd.DataFrame],
    selecao: dict | None,
) -> pd.DataFrame:
    """Reduz a base aos jogos da entidade/gênero/ano/jogo selecionado."""
    if not selecao:
        return base
    tipo, valor = selecao.get("tipo"), selecao.get("valor")
    if tipo in {"publisher", "developer"}:
        tabela = longas["publisher" if tipo == "publisher" else "developer"]
        ids = tabela.loc[tabela["entidade"] == valor, "appid"].unique()
        return base[base["appid"].isin(ids)]
    if tipo == "genero":
        tabela = longas["genero"]
        ids = tabela.loc[tabela["genero"] == valor, "appid"].unique()
        return base[base["appid"].isin(ids)]
    if tipo == "ano":
        return base[base["ano_lancamento"] == valor]
    if tipo == "jogo":
        return base[base["appid"] == valor]
    return base


def desenhar_chart(fig: go.Figure, chave: str, altura: int = 450) -> None:
    st.plotly_chart(
        fig,
        width="stretch",
        height=altura,
        key=chave,
        on_select=callback_selecao(chave),
        selection_mode=("points",),
        config={"displayModeBar": False, "scrollZoom": False},
    )


def cartao(label: str, valor: str) -> None:
    with st.container(border=True):
        st.markdown(
            f'<div class="kpi-label">{label}</div><div class="kpi-valor">{valor}</div>',
            unsafe_allow_html=True,
        )


def limpar_foco() -> None:
    """Trocar a visão limpa entidades e clique: os nomes são conjuntos distintos."""
    st.session_state["entidades_sel"] = []
    st.session_state["selecionado"] = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Steam Dashboard", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

if "selecionado" not in st.session_state:
    st.session_state["selecionado"] = None
if "jogos_excluidos" not in st.session_state:
    st.session_state["jogos_excluidos"] = []
if "entidades_excluidas" not in st.session_state:
    st.session_state["entidades_excluidas"] = []

base_completa = carregar_base()
longas = carregar_tabelas_longas()

jogos_excluidos = [int(appid) for appid in st.session_state["jogos_excluidos"]]
entidades_excluidas = list(st.session_state["entidades_excluidas"])

# Um pub/dev excluído remove todos os jogos em que ele aparece — e também suas
# linhas nas tabelas longas, para que filtros e gráficos não reintroduzam o grupo.
appids_excluidos = set(jogos_excluidos)
for exclusao in entidades_excluidas:
    tipo_exc = exclusao.get("tipo")
    if tipo_exc not in {"publisher", "developer"}:
        continue
    tabela_exc = longas[tipo_exc]
    appids_excluidos.update(
        tabela_exc.loc[tabela_exc["entidade"] == exclusao.get("valor"), "appid"]
        .unique()
        .tolist()
    )

if appids_excluidos:
    base = base_completa[~base_completa["appid"].isin(appids_excluidos)].copy()
    longas = {
        tipo: tabela[~tabela["appid"].isin(appids_excluidos)].copy()
        for tipo, tabela in longas.items()
    }
else:
    base = base_completa
n_excluidos = len(base_completa) - len(base)

st.title("Steam Dashboard — jogos, editoras e jogadores")
st.markdown(
    '<div class="subtitulo">Recriação interativa do relatório Power BI: '
    'desempenho, portfólio e mercado a partir dos dados originais do Steam.</div>',
    unsafe_allow_html=True,
)

# -------------------------- filtros globais -------------------------------
anos = base["ano_lancamento"].dropna().astype(int)
ano_min, ano_max = int(anos.min()), int(anos.max())
preco_max = float(base["price"].max())
generos = sorted(longas["genero"]["genero"].unique())
reviews_max = float(base["num_reviews_total"].max())

with st.sidebar:
    st.header("Filtros")
    visao = st.radio(
        "Visão por", ["Publisher", "Desenvolvedor"],
        key="visao_radio", on_change=limpar_foco,
    )
    ent_col = "entidade"
    tipo_entidade = "publisher" if visao == "Publisher" else "developer"

    entidades_sel = st.multiselect(
        f"Analisar {visao.lower()}s",
        opcoes_entidades()[tipo_entidade],
        key="entidades_sel",
        placeholder="Todas",
        help=(
            "Digite para buscar em qualquer uma das entidades da base. "
            "Sem busca, as maiores aparecem primeiro."
        ),
    )

    faixa_ano = st.slider(
        "Ano de lançamento", ano_min, ano_max, (ano_min, ano_max)
    )
    generos_sel = st.multiselect(
        "Gêneros", generos, default=[], placeholder="Todos os gêneros"
    )
    categorias = sorted(longas["categoria"]["categoria"].unique())
    categorias_sel = st.multiselect(
        "Categorias", categorias, default=[], placeholder="Todas as categorias",
        help="Ex.: Single-player, Co-op, Steam Achievements. Combine com gêneros.",
    )
    faixa_preco = st.slider(
        "Preço (US$)", 0.0, preco_max, (0.0, preco_max), format="%.2f"
    )
    min_reviews_exp = st.slider(
        "Mínimo de reviews (escala log)", 0,
        math.ceil(math.log10(max(reviews_max, 10))), 0,
    )
    min_reviews = 0 if min_reviews_exp == 0 else 10**min_reviews_exp
    min_pct = st.slider("Mínimo de % avaliações positivas", 0, 100, 0, format="%d%%")
    busca = st.text_input("Busca por jogo", placeholder="Nome do jogo...")
    st.caption(
        "Clique em qualquer gráfico: todos os painéis acompanham o foco."
    )
    st.caption(
        f"Base: {fmt_int(len(base))} jogos · origem: "
        f"`{SAIDA.relative_to(BASE)}`"
    )

    modo_exclusao = st.toggle(
        "Modo exclusão",
        value=False,
        key="modo_exclusao",
        help=(
            "Ligado: clique em um jogo, publisher ou desenvolvedor para remover "
            "todos os jogos do grupo de todos os painéis."
        ),
    )
    if modo_exclusao:
        st.caption(
            "Modo exclusão ativo — clique em um jogo, pub ou dev para removê-lo."
        )

    if jogos_excluidos:
        nomes_excluidos = (
            base_completa.loc[base_completa["appid"].isin(jogos_excluidos), "name"]
            .dropna().astype(str).tolist()
        )
        resumo = ", ".join(nomes_excluidos[:2]) + (
            "…" if len(nomes_excluidos) > 2 else ""
        )
        st.caption(f"{len(jogos_excluidos)} jogo(s) excluído(s): {resumo}")
    if entidades_excluidas:
        resumo_ent = ", ".join(
            f"{'pub' if item.get('tipo') == 'publisher' else 'dev'}: "
            f"{item.get('valor')}"
            for item in entidades_excluidas[:3]
        ) + ("…" if len(entidades_excluidas) > 3 else "")
        st.caption(
            f"{len(entidades_excluidas)} pub/dev excluído(s): {resumo_ent}"
        )
    if appids_excluidos:
        st.caption(f"{fmt_int(n_excluidos)} jogo(s) fora do recorte")
        st.button(
            "Restaurar exclusões",
            key="restaurar_excluidos",
            on_click=callback_restaurar_exclusoes,
        )

selecao = st.session_state["selecionado"]
if entidades_sel:
    resumo = ", ".join(entidades_sel[:3]) + (
        "…" if len(entidades_sel) > 3 else ""
    )
    st.markdown(
        f'<span class="selecao-chip">{len(entidades_sel)} '
        f'{visao.lower()}(s) em análise: {resumo}</span>',
        unsafe_allow_html=True,
    )
if selecao:
    st.markdown(
        f'<span class="selecao-chip">Foco: {selecao["tipo"]} · '
        f'{selecao["valor"]}</span>',
        unsafe_allow_html=True,
    )
    if st.button("Limpar clique", type="primary"):
        st.session_state["selecionado"] = None
        st.rerun()
    if selecao.get("tipo") in TIPOS_EXCLUIVEIS:
        tipo_foco = selecao["tipo"]
        st.button(
            ROTULO_EXCLUSAO[tipo_foco],
            key="excluir_foco",
            on_click=callback_excluir_foco,
            help=(
                "Remove todos os jogos deste foco dos gráficos, KPIs e da "
                "tabela; o parquet não é alterado."
            ),
        )

mask = (
    base["ano_lancamento"].between(faixa_ano[0], faixa_ano[1])
    & base["price"].between(faixa_preco[0], faixa_preco[1])
)
if generos_sel:
    ids_genero = set(
        longas["genero"].loc[longas["genero"]["genero"].isin(generos_sel), "appid"]
    )
    mask &= base["appid"].isin(ids_genero)
if entidades_sel:
    tabela_ent = longas[tipo_entidade]
    ids_ent = set(
        tabela_ent.loc[tabela_ent["entidade"].isin(entidades_sel), "appid"]
    )
    mask &= base["appid"].isin(ids_ent)
if categorias_sel:
    ids_cat = set(
        longas["categoria"].loc[
            longas["categoria"]["categoria"].isin(categorias_sel), "appid"
        ]
    )
    mask &= base["appid"].isin(ids_cat)
if min_reviews > 0:
    mask &= base["num_reviews_total"].fillna(0) >= min_reviews
if min_pct > 0:
    mask &= base["pct_pos_total"].fillna(0) >= min_pct / 100
if busca.strip():
    mask &= base["name"].fillna("").str.contains(busca.strip(), case=False, regex=False)

base_filtrada = base[mask].copy()  # recorte da sidebar, sem o clique
foco = aplicar_selecao(base_filtrada, longas, selecao)  # o clique sempre comanda

ids_explorar = set(base_filtrada["appid"])
ids_foco = set(foco["appid"])

long_explorar = longas[tipo_entidade]
long_explorar = long_explorar[long_explorar["appid"].isin(ids_explorar)].copy()

selecao_entidade = (
    selecao if selecao and selecao.get("tipo") in {"publisher", "developer"} else None
)
if selecao_entidade:
    ent_foco = str(selecao_entidade["valor"])
    tipo_foco = selecao_entidade["tipo"]
elif entidades_sel:
    ent_foco = entidades_sel[0]
    tipo_foco = tipo_entidade
else:
    ranking = agregar(long_explorar, ent_col).groupby(ent_col)[
        "qtd_jogos"
    ].sum().sort_values(ascending=False)
    ent_foco = str(ranking.index[0]) if len(ranking) else None
    tipo_foco = tipo_entidade

long_foco_ent = longas[tipo_foco]
long_foco_ent = long_foco_ent[long_foco_ent["appid"].isin(ids_foco)].copy()

ent_agg_explorar = agregar(long_explorar, ent_col)

tem_filtro = bool(
    selecao
    or entidades_sel
    or generos_sel
    or categorias_sel
    or faixa_ano != (ano_min, ano_max)
    or faixa_preco != (0.0, preco_max)
    or min_reviews > 0
    or min_pct > 0
    or busca.strip()
    or bool(appids_excluidos)
)
modo_portfolio = (
    "entidade" if selecao_entidade else ("recorte" if tem_filtro else "geral")
)
if selecao_entidade:
    rotulo_grupo = f"{tipo_foco}: {ent_foco}"
elif selecao and selecao.get("tipo") == "jogo":
    appid_sel = selecao.get("valor")
    nomes_jogo = base.loc[base["appid"] == appid_sel, "name"].dropna()
    nome_jogo = str(nomes_jogo.iloc[0]) if len(nomes_jogo) else str(appid_sel)
    rotulo_grupo = f"Jogo: {nome_jogo}"
elif selecao:
    rotulo_grupo = f"{selecao['tipo']}: {selecao['valor']}"
elif appids_excluidos:
    rotulo_grupo = f"Recorte filtrado ({fmt_int(n_excluidos)} jogo(s) excluído(s))"
elif tem_filtro:
    rotulo_grupo = "Recorte filtrado"
else:
    rotulo_grupo = "Todos os jogos"

# -------------------------- painéis (tela única) ------------------------
st.subheader("Visão competitiva")
st.markdown(
    '<div class="subtitulo">Todos os painéis ficam nesta mesma tela. Clique em '
    'qualquer gráfico para trocar o foco: composição, evolução, distribuição, '
    'KPIs e tabela bruta acompanham a seleção.</div>',
    unsafe_allow_html=True,
)
with st.container(border=True):
    st.markdown(
        "Qtd. de jogos × satisfação · tamanho = popularidade média (escala log)"
    )
    competitivo = ent_agg_explorar.dropna(subset=["pct_positivas"])
    grupos_comp = entidades_grafico(
        competitivo, ent_col, 30,
        [ent_foco] if selecao_entidade else entidades_sel,
        "reviews",
    )
    fig = scatter_agrupado(
        competitivo,
        ent_col, "qtd_jogos", "pct_positivas", "popularidade",
        tipo_entidade,
        ("Qtd. de jogos", "% de avaliações positivas"),
        grupos=grupos_comp,
    )
    desenhar_chart(fig, "chart_competitivo")

st.caption(
    "Clique em um ponto para trocar o foco de todos os painéis abaixo."
)

st.subheader("Painéis do grupo em análise")
st.caption(
    f"Grupo em análise: {rotulo_grupo} · {fmt_int(len(foco))} jogo(s) · "
    f"modo: {modo_portfolio}."
)
if foco.empty:
    st.info("Nenhum jogo no recorte atual. Ajuste os filtros na sidebar.")

st.markdown(
    '<div class="subtitulo">Composição, evolução, distribuição dos jogos, '
    'KPIs e dados brutos — tudo do grupo selecionado ou filtrado.</div>',
    unsafe_allow_html=True,
)

with st.expander("Como funciona e onde o gráfico é limitado"):
    st.markdown(
        """
        **Pizza — composição do portfólio**
        - Sem seleção nem filtro, mostra a distribuição **geral** de todos
          os jogos. Com seleção ou filtro, mostra o grupo em análise
          (pub/dev, gênero, categoria, ano ou jogo).
        - Cada jogo entra **uma única vez**, pelo primeiro gênero listado
          em `genres`; por isso as fatias somam 100% do grupo.
        - A participação é: jogos daquele gênero / jogos distintos do grupo
          **após todos os filtros**.
        - Apenas os **8 gêneros** mais comuns têm fatia própria; os demais
          são agrupados em "Outros". Jogos sem gênero ficam de fora.

        **Linha — evolução dos lançamentos**
        - No eixo X está o ano de lançamento; no eixo Y, a quantidade de
          jogos lançados naquele ano.
        - Sem filtro, a linha é **geral**. Com pub/dev selecionado, mostra
          somente ele. Com outro filtro/seleção, mostra o grupo filtrado;
          se for um jogo, vira um único ponto (o ano daquele lançamento).

        **Distribuição dos jogos**
        - O mapa de gêneros e a dispersão popularidade/satisfação usam os
          mesmos jogos do grupo em análise. Se o foco for um jogo, cada
          gráfico mostra apenas aquele título.
        - Com **Modo exclusão** ligado, clicar em um jogo, pub ou dev
          remove todos os jogos do grupo dos painéis. Sem o switch, use
          **Excluir … em foco** após clicar. **Restaurar exclusões** na
          sidebar desfaz isso.

        **Limitações**
        - Gênero e categoria são listas: um jogo pode pertencer a vários
          gêneros/categorias nos filtros. A pizza evita a dupla contagem ao
          usar só o gênero principal.
        - Anos sem lançamento não viram ponto (não são zeros explícitos).
        - Clique em uma fatia, ponto ou linha para trocar o foco.
        """
    )

m = medidas(foco)
colunas_kpi = st.columns(6, gap="small")
for col, label, valor in zip(
    colunas_kpi,
    ["Qtd. jogos", "% avaliações positivas", "Qtd. reviews",
     "Tempo médio de jogo", "Preço médio", "Popularidade estimada"],
    [fmt_int(m["qtd_jogos"]), fmt_pct(m["pct_positivas"]), fmt_int(m["reviews"]),
     f'{fmt_dec(m["playtime"] / 60)} h', f'US$ {fmt_dec(m["preco"])}',
     fmt_int(m["popularidade"])],
):
    with col:
        cartao(label, valor)

col_pizza, col_linha = st.columns([1, 1.25])
with col_pizza:
    with st.container(border=True):
        if modo_portfolio == "entidade":
            ids_pizza = set(
                long_foco_ent.loc[
                    long_foco_ent[ent_col] == ent_foco, "appid"
                ]
            )
            jogos_pizza = foco[foco["appid"].isin(ids_pizza)]
            selecao_fatia = lambda genero: selecao_json(tipo_foco, ent_foco)
            titulo_pizza = f"Composição do portfólio — {ent_foco}"
        else:
            jogos_pizza = foco
            selecao_fatia = lambda genero: selecao_json("genero", genero)
            titulo_pizza = (
                "Composição dos portfólios"
                if modo_portfolio == "geral"
                else f"Composição — {rotulo_grupo}"
            )
        st.markdown(f"**{titulo_pizza}**  \nDistribuição dos gêneros principais")
        fig_pizza, total_pizza = pizza_portfolio(jogos_pizza, selecao_fatia)
        if total_pizza:
            desenhar_chart(fig_pizza, "chart_portfolio_pizza", 430)
        else:
            st.info("Sem jogos com gênero no grupo em análise.")

with col_linha:
    with st.container(border=True):
        st.markdown(
            "**Evolução dos lançamentos**  \nAno de lançamento × quantidade de jogos"
        )
        lin = agregar(foco, "ano_lancamento").dropna(
            subset=["ano_lancamento"]
        ).sort_values("ano_lancamento")
        nome_linha = ent_foco if modo_portfolio == "entidade" else rotulo_grupo
        if modo_portfolio == "entidade":
            custom_linha = [selecao_json(tipo_foco, ent_foco)] * len(lin)
        else:
            custom_linha = [
                selecao_json("ano", int(a)) for a in lin["ano_lancamento"]
            ]

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=lin["ano_lancamento"].astype(int), y=lin["qtd_jogos"],
                mode="lines+markers", name=str(nome_linha),
                line=dict(width=3, color=PALETA[0]),
                marker=dict(size=6, color=PALETA[0]),
                customdata=custom_linha,
                hovertemplate=(
                    "<b>" + str(nome_linha) + "</b><br>Ano: %{x}<br>"
                    "Qtd. jogos: %{y:,.0f}<extra></extra>"
                ),
            )
        )
        fig.update_layout(
            xaxis_title="Ano de lançamento", yaxis_title="Qtd. de jogos"
        )
        desenhar_chart(estilo_fig(fig, 430), "chart_portfolio_linha")
        if modo_portfolio == "entidade":
            st.caption("A linha mostra somente o pub/dev selecionado.")
        elif modo_portfolio == "geral":
            st.caption("Linha geral: todos os jogos da base.")
        else:
            st.caption(f"Linha do grupo: {rotulo_grupo}.")

col_generos, col_jogos = st.columns([1, 1.25])
with col_generos:
    with st.container(border=True):
        st.markdown(
            "**Mapa de desempenho dos gêneros**  \n"
            "Tempo médio de jogo (h) × satisfação · tamanho = reviews (escala log)"
        )
        gen_agg = agregar(foco, "genero_principal").dropna(
            subset=["pct_positivas", "playtime", "reviews"]
        ).assign(playtime_h=lambda d: d["playtime"] / 60)
        fig = scatter_agrupado(
            gen_agg, "genero_principal", "playtime_h", "pct_positivas", "reviews",
            "genero", ("Tempo médio de jogo (h)", "% de avaliações positivas"),
            max_grupos=20,
        )
        desenhar_chart(fig, "chart_generos")

with col_jogos:
    with st.container(border=True):
        st.markdown(
            "**Popularidade e satisfação dos jogos**  \n"
            "Cada ponto é um jogo · tamanho = % de avaliações positivas "
            "(escala linear recortada entre o p5 e o p95)"
        )
        jogos = foco[
            foco["estimated_owners_num"].notna()
            & (foco["average_playtime_forever"] > 0)
            & foco["num_reviews_total"].notna()
            & foco["pct_pos_total"].notna()
            & foco["name"].notna()
        ].sort_values("num_reviews_total", ascending=False).head(2500)
        fig = go.Figure()
        if not jogos.empty:
            pub_txt = jogos["publishers"].map(
                lambda s: ", ".join(parse_lista(s)[:3]) or "—"
            )
            dev_txt = jogos["developers"].map(
                lambda s: ", ".join(parse_lista(s)[:3]) or "—"
            )
            cores = [PALETA[i % len(PALETA)] for i in pd.factorize(jogos["name"])[0]]
            custom = pd.DataFrame(
                {
                    "_sel": [selecao_json("jogo", int(a)) for a in jogos["appid"]],
                    "nome": jogos["name"],
                    "pub": pub_txt,
                    "dev": dev_txt,
                    "pct": jogos["pct_pos_total"],
                    "reviews": jogos["num_reviews_total"],
                    "pop": jogos["estimated_owners_num"],
                    "play_h": jogos["average_playtime_forever"] / 60,
                }
            )
            fig.add_trace(
                go.Scatter(
                    x=jogos["estimated_owners_num"],
                    y=jogos["average_playtime_forever"] / 60,
                    mode="markers",
                    customdata=custom,
                    marker=dict(
                        size=tamanhos(
                            jogos["pct_pos_total"], 34, min_px=12,
                            escala=jogos["pct_pos_total"].quantile(0.95),
                            base=jogos["pct_pos_total"].quantile(0.05),
                            log=False,
                        ),
                        color=cores, opacity=0.7,
                        line=dict(width=0.4, color="#FFFFFF"),
                    ),
                    hovertemplate=(
                        "<b>%{customdata[1]}</b><br>"
                        "Publisher: %{customdata[2]}<br>"
                        "Developer: %{customdata[3]}<br>"
                        "% positivas: %{customdata[4]:.1%}<br>"
                        "Reviews: %{customdata[5]:,.0f}<br>"
                        "Popularidade: %{customdata[6]:,.0f}<br>"
                        "Tempo médio: %{customdata[7]:.1f} h"
                        "<extra></extra>"
                    ),
                    showlegend=False,
                )
            )
        fig.update_layout(
            xaxis_title="Popularidade estimada (jogadores)",
            yaxis_title="Tempo médio de jogo (h)",
        )
        desenhar_chart(estilo_fig(fig, 480), "chart_jogos")
        st.caption(
            "Esquerda abre o foco. Para excluir um outlier, ligue **Modo "
            "exclusão** na sidebar e clique no ponto ou use **Excluir … em "
            "foco** depois de clicar. Vale para jogos, publishers e "
            "desenvolvedores."
        )

with st.container(border=True):
    st.markdown(
        "**Dados brutos em detalhes**  \n"
        "Todas as colunas do parquet, ordenadas por volume de avaliações"
    )
    colunas = [
        "name", "ano_lancamento", "genero_principal", "genres", "categories",
        "developers", "publishers", "positive", "negative", "num_reviews_total",
        "pct_pos_total", "num_reviews_recent", "pct_pos_recent", "price",
        "estimated_owners_num", "average_playtime_forever", "appid",
    ]
    tabela = foco[colunas].copy()
    tabela = tabela.sort_values("num_reviews_total", ascending=False)
    st.caption(
        f"{fmt_int(len(tabela))} jogo(s) no foco · "
        "campos de texto longo (descrições, histórias, screenshots) "
        "não entram no parquet"
    )
    tabela = tabela.rename(
        columns={
            "name": "Jogo", "ano_lancamento": "Ano",
            "genero_principal": "Gênero principal", "genres": "Gêneros",
            "categories": "Categorias", "developers": "Developers",
            "publishers": "Publishers", "positive": "Positivas",
            "negative": "Negativas", "num_reviews_total": "Reviews",
            "pct_pos_total": "% positivas", "num_reviews_recent": "Reviews recentes",
            "pct_pos_recent": "% positivas recentes", "price": "Preço (US$)",
            "estimated_owners_num": "Popularidade",
            "average_playtime_forever": "Tempo médio (min)", "appid": "AppID",
        }
    )
    tabela["% positivas"] = tabela["% positivas"].map(fmt_pct)
    tabela["% positivas recentes"] = tabela["% positivas recentes"].map(fmt_pct)
    st.dataframe(tabela, hide_index=True, width="stretch", height=460)
