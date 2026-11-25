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
ABAS = ["Visão competitiva", "Portfólio", "Mercado e jogadores", "Detalhes"]

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
        # Média (e não mediana): um título muito popular não fica "escondido"
        # pela quantidade de jogos pequenos da mesma entidade.
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


# ---------------------------------------------------------------------------
# Interatividade: clique nos gráficos
# ---------------------------------------------------------------------------


def callback_selecao(chave: str):
    """Callback de on_select: grava o ponto clicado e abre a aba Detalhes."""

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
        if objeto.get("tipo") not in {
            "publisher", "developer", "genero", "ano", "jogo"
        }:
            return
        st.session_state["selecionado"] = objeto
        st.session_state["aba_ativa"] = "Detalhes"

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


def limpar_entidades() -> None:
    """Callback do toggle: nomes de publisher não servem como developer."""
    st.session_state["entidades_sel"] = []


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Steam Dashboard", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

if "selecionado" not in st.session_state:
    st.session_state["selecionado"] = None

base = carregar_base()
longas = carregar_tabelas_longas()

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
        key="visao_radio", on_change=limpar_entidades,
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
    cross_filter = st.checkbox("Aplicar clique como filtro nos gráficos", value=False)
    st.caption(
        f"Base: {fmt_int(len(base))} jogos · origem: "
        f"`{SAIDA.relative_to(BASE)}`"
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
        f'<span class="selecao-chip">Seleção: {selecao["tipo"]} · '
        f'{selecao["valor"]}</span>',
        unsafe_allow_html=True,
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

base_filtrada = base[mask].copy()
if cross_filter:
    base_filtrada = aplicar_selecao(base_filtrada, longas, selecao)

ids_filtrados = set(base_filtrada["appid"])
long_ent = longas[tipo_entidade]
long_ent = long_ent[long_ent["appid"].isin(ids_filtrados)].copy()
long_gen = longas["genero"]
long_gen = long_gen[long_gen["appid"].isin(ids_filtrados)].copy()

ent_agg = agregar(long_ent, ent_col)
ent_agg_ano = agregar(
    long_ent, ["ano_lancamento", ent_col]
).dropna(subset=["ano_lancamento"])

# -------------------------- navegação -------------------------------------
aba = st.segmented_control(
    "Tela", ABAS, key="aba_ativa", default=ABAS[0], width="stretch"
)

if aba == ABAS[0]:
    # 1) Visão competitiva --------------------------------------------------
    st.header("Visão competitiva")
    st.markdown(
        '<div class="subtitulo">Desempenho competitivo por '
        f'{visao.lower()} · tamanho da bolha por popularidade média estimada, '
        'em escala logarítmica.</div>',
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        competitivo = ent_agg.dropna(subset=["pct_positivas"])
        grupos_comp = entidades_grafico(
            competitivo, ent_col, 30, entidades_sel, "reviews"
        )
        fig = scatter_agrupado(
            competitivo,
            ent_col, "qtd_jogos", "pct_positivas", "popularidade",
            tipo_entidade,
            ("Qtd. de jogos", "% de avaliações positivas"),
            grupos=grupos_comp,
        )
        desenhar_chart(fig, "chart_competitivo")
    st.caption("Clique em um ponto para ver os detalhes da entidade.")

elif aba == ABAS[1]:
    # 2) Portfólio ----------------------------------------------------------
    st.header("Portfólio")
    st.markdown(
        '<div class="subtitulo">Composição dos portfólios e evolução dos '
        f'lançamentos por {visao.lower()}.</div>',
        unsafe_allow_html=True,
    )
    with st.expander("Como funciona e onde o gráfico é limitado"):
        st.markdown(
            """
            **Barras empilhadas — composição dos portfólios**
            - Cada barra é uma editora/desenvolvedora (conforme "Visão por").
            - Cada cor é um gênero; o comprimento é a quantidade de **jogos
              distintos** da entidade naquele gênero.
            - Um jogo com vários gêneros entra em **cada um** deles, então a
              soma das cores pode ultrapassar o total de jogos da entidade.
            - O tooltip mostra a participação: jogos daquele gênero dividido
              pelo total de jogos **após os filtros**.

            **Linha — evolução dos lançamentos**
            - Cada linha é uma entidade; no eixo X está o ano de lançamento e
              no eixo Y, a quantidade de jogos lançados naquele ano.

            **Limitações**
            - Para manter a leitura possível, o gráfico mostra no máximo
              **12 entidades nas barras** e **8 na linha**, escolhidas pelas
              que têm mais jogos. Entidades marcadas na sidebar entram mesmo
              quando ficam fora desse topo.
            - Somente os **8 gêneros** mais comuns têm cor própria; os demais
              são agrupados em "Outros".
            - Gênero e categoria são listas: a mesma partilha é contada em
              cada item da lista, logo as somas não são exclusivas.
            - Anos sem lançamento não viram ponto (não são zeros explícitos).
            """
        )
    pares = long_ent[["appid", ent_col]].merge(
        long_gen[["appid", "genero"]], on="appid", how="inner"
    )
    contagem = (
        pares.groupby([ent_col, "genero"])["appid"].nunique().reset_index(name="qtd")
    )
    ranking_ent = contagem.groupby(ent_col)["qtd"].sum().reset_index(name="total")
    top_ent = entidades_grafico(ranking_ent, ent_col, 12, entidades_sel, "total")
    top_gen = (
        contagem.groupby("genero")["qtd"].sum().sort_values(ascending=False).head(8).index.tolist()
    )
    contagem["genero_plot"] = contagem["genero"].where(
        contagem["genero"].isin(top_gen), "Outros"
    )
    mat = (
        contagem[contagem[ent_col].isin(top_ent)]
        .pivot_table(index=ent_col, columns="genero_plot", values="qtd", aggfunc="sum", fill_value=0)
    )
    if "Outros" not in mat.columns:
        mat["Outros"] = 0
    ordem = [g for g in top_gen if g in mat.columns] + ["Outros"]
    mat = mat[ordem].loc[top_ent[::-1]]

    with st.container(border=True):
        st.markdown("**Composição dos portfólios**  \nQuantidade de jogos por gênero")
        fig = go.Figure()
        total_jogos = max(base_filtrada["appid"].nunique(), 1)
        for i, genero in enumerate(mat.columns):
            custom_barras = pd.DataFrame(
                {
                    "_sel": [selecao_json(tipo_entidade, e) for e in mat.index],
                    "part": mat[genero].to_numpy() / total_jogos,
                }
            )
            fig.add_trace(
                go.Bar(
                    y=mat.index.astype(str), x=mat[genero], name=genero,
                    orientation="h",
                    customdata=custom_barras,
                    hovertemplate=(
                        "<b>%{y}</b><br>Gênero: " + genero
                        + "<br>Qtd. jogos: %{x:,.0f}"
                        + "<br>Participação: %{customdata[1]:.1%}"
                        + "<extra></extra>"
                    ),
                    marker=dict(
                        color=PALETA[i % len(PALETA)],
                        line=dict(width=0.5, color="#FFFFFF"),
                    ),
                )
            )
        fig.update_layout(barmode="stack", xaxis_title="Qtd. de jogos", yaxis_title="")
        desenhar_chart(estilo_fig(fig, 480), "chart_portfolio_barras")

    with st.container(border=True):
        st.markdown("**Evolução dos lançamentos**  \nAno de lançamento × quantidade de jogos")
        entes_linha = entidades_grafico(
            ent_agg, ent_col, 8, entidades_sel, "qtd_jogos"
        )
        lin = ent_agg_ano[ent_agg_ano[ent_col].isin(entes_linha)].sort_values(
            "ano_lancamento"
        )
        presentes = set(lin[ent_col])
        nomes_linha = [e for e in entes_linha if e in presentes]
        fig = go.Figure()
        for i, nome in enumerate(nomes_linha):
            g = lin[lin[ent_col] == nome]
            fig.add_trace(
                go.Scatter(
                    x=g["ano_lancamento"].astype(int), y=g["qtd_jogos"],
                    mode="lines+markers", name=str(nome),
                    line=dict(width=3, color=PALETA[i % len(PALETA)]),
                    marker=dict(size=6, color=PALETA[i % len(PALETA)]),
                    customdata=[selecao_json(tipo_entidade, nome)] * len(g),
                    hovertemplate=(
                        "<b>" + str(nome) + "</b><br>Ano: %{x}<br>"
                        "Qtd. jogos: %{y:,.0f}<extra></extra>"
                    ),
                )
            )
        fig.update_layout(xaxis_title="Ano de lançamento", yaxis_title="Qtd. de jogos")
        desenhar_chart(estilo_fig(fig, 420), "chart_portfolio_linha")
    st.caption("Clique em uma barra ou ponto para ver os detalhes.")

elif aba == ABAS[2]:
    # 3) Mercado e jogadores ------------------------------------------------
    st.header("Mercado e jogadores")
    st.markdown(
        '<div class="subtitulo">Relação entre tempo de jogo, satisfação, '
        'popularidade e volume de avaliações.</div>',
        unsafe_allow_html=True,
    )
    gen_agg = agregar(base_filtrada, "genero_principal").dropna(
        subset=["pct_positivas", "playtime", "reviews"]
    ).assign(playtime_h=lambda d: d["playtime"] / 60)
    with st.container(border=True):
        st.markdown(
            "**Mapa de desempenho dos gêneros**  \n"
            "Tempo médio de jogo (h) × satisfação · tamanho = reviews (escala log)"
        )
        fig = scatter_agrupado(
            gen_agg, "genero_principal", "playtime_h", "pct_positivas", "reviews",
            "genero", ("Tempo médio de jogo (h)", "% de avaliações positivas"),
            max_grupos=20,
        )
        desenhar_chart(fig, "chart_generos")

    jogos = base_filtrada[
        base_filtrada["estimated_owners_num"].notna()
        & (base_filtrada["average_playtime_forever"] > 0)
        & base_filtrada["num_reviews_total"].notna()
        & base_filtrada["pct_pos_total"].notna()
        & base_filtrada["name"].notna()
    ].sort_values("num_reviews_total", ascending=False).head(2500)

    with st.container(border=True):
        st.markdown(
            "**Popularidade e satisfação dos jogos**  \n"
            "Cada ponto é um jogo · tamanho = % de avaliações positivas "
            "(escala linear recortada entre o p5 e o p95)"
        )
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
    st.caption("Clique em um ponto da segunda dispersão para abrir o jogo em Detalhes.")

else:
    # 4) Detalhes -----------------------------------------------------------
    st.header("Detalhes")
    if selecao:
        selecionados = aplicar_selecao(base, longas, selecao)
        st.markdown(
            f'<div class="subtitulo">Seleção atual: <b>{selecao["tipo"]}</b> — '
            f'{selecao["valor"]}</div>',
            unsafe_allow_html=True,
        )
        if st.button("Limpar seleção", type="primary"):
            st.session_state["selecionado"] = None
            st.rerun()
    else:
        selecionados = base_filtrada
        st.markdown(
            '<div class="subtitulo">Nenhum item selecionado — exibindo os '
            'dados filtrados. Clique em um gráfico para explorar.</div>',
            unsafe_allow_html=True,
        )

    m = medidas(selecionados)
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

    with st.container(border=True):
        st.markdown("**Jogos da seleção**  \nTodos os jogos, ordenados por volume de avaliações")
        colunas = [
            "name", "ano_lancamento", "genero_principal", "publishers",
            "num_reviews_total", "pct_pos_total", "price", "estimated_owners_num",
        ]
        tabela = selecionados[colunas].copy()
        tabela = tabela.sort_values("num_reviews_total", ascending=False)
        st.caption(f"{fmt_int(len(tabela))} jogo(s) na seleção")
        tabela = tabela.rename(
            columns={
                "name": "Jogo", "ano_lancamento": "Ano",
                "genero_principal": "Gênero principal", "publishers": "Publishers",
                "num_reviews_total": "Reviews", "pct_pos_total": "% positivas",
                "price": "Preço (US$)", "estimated_owners_num": "Popularidade",
            }
        )
        tabela["% positivas"] = tabela["% positivas"].map(fmt_pct)
        st.dataframe(tabela, hide_index=True, width="stretch", height=460)
