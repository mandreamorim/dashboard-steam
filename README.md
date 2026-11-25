# Estúdio Competitivo — dashboard Streamlit

Recriação interativa do relatório Power BI (`trabalho com a teresa.pbix`) em Streamlit,
usando os dados originais do Steam. **O arquivo `.pbix` não é lido nem modificado**
pela aplicação: ele serviu apenas como referência das measures, visuais e paleta.

## Arquivos

- `preparar_dados.py` — lê o CSV em chunks e grava `data/jogos.parquet`.
- `app.py` — dashboard em **uma única tela**, com filtros globais e clique
  que comanda todos os painéis.
- `requirements.txt` — dependências.
- `plano.txt` — plano original (mantido como referência).

## Como rodar no Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# copie o CSV original para data/ (ou deixe na raiz do projeto)
mkdir -p data
cp games_march2025_cleaned.csv data/games_march2025_cleaned.csv

python preparar_dados.py        # opcional: o app faz isso na 1ª execução
streamlit run app.py --server.port 8501
```

Abra <http://localhost:8501>.

**GitHub / Streamlit Community Cloud:** commite `data/jogos.parquet` (5 MB) e
não o CSV original (447 MB, acima do limite de 100 MB do GitHub) nem o `.pbix`
(só referência). O app roda apenas com o parquet; o CSV só é necessário para
refazer `preparar_dados.py`, e pode ser baixado da fonte original em separado.

Se o CSV estiver em outro lugar:

```bash
export JOGOS_CSV=/caminho/para/games_march2025_cleaned.csv
```

## O que foi recriado do Power BI

| Power BI | Streamlit |
|---|---|
| Página "Página 1" — dispersão de publishers | Visão competitiva (topo da tela única) |
| Página "Estratégia e composição do portfólio" — barras + linha | Pizza de composição + evolução dos lançamentos |
| Página "Mercado, satisfação e jogadores" — 2 dispersões | Mapa de gêneros e jogos |
| Slicer "Visão por" (Publisher/Desenvolvedor) | Radio na sidebar, aplicado a todos os painéis |
| Medidas DAX | Recalculadas em pandas (ver abaixo) |
| Tema `EstudioCompetitivo.json` | CSS + template Plotly com a mesma paleta |

Medidas: **Qtd Jogos** = `nunique(appid)`; **% Avaliações Positivas** =
`soma(positive) / (soma(positive) + soma(negative))`; **Qtd Reviews** =
`soma(num_reviews_total)` ignorando `-1`; **Tempo Médio de Jogo** = média de
`average_playtime_forever > 0`; **Preço Médio** = média de `price > 0`;
**Participação %** = jogos da categoria / total após filtros; **Popularidade
Estimada** = **média** de `estimated_owners_num` (ponto médio da faixa textual
de proprietários da Steam). A popularidade de uma entidade é a média das
popularidades dos seus jogos — não a soma nem o máximo.

> Diferença intencional em relação ao `.pbix`: a measure original usa
> `MEDIAN(...)`. Aqui ela foi trocada por `mean()` (média simples) a pedido.
> A média inclui **todos** os jogos da entidade — inclusive o War Thunder
> (35 M), que é o maior hit da Gaijin e não é removido nem "suavizado". Na visão
> Publisher, `Gaijin Network Ltd` tem 6 jogos e popularidade média de
> 7.733.333 (a mediana do `.pbix` era 3,5 M).

Validação das medidas inalteradas: Qtd Jogos (89.618), % positivas (85,82%),
Qtd Reviews (117.928.014), Tempo Médio (1.285,7 min = 21,4 h) batem exatamente com o
modelo. O `.pbix` armazena `price` em centavos (e tem 578 linhas com o preço
divergente do CSV); aqui usamos os dólares do CSV, então o Preço Médio exibido
(US$ 8,68) é o valor correto para a base original.

## Interatividade

- A sidebar permite **escolher publishers ou developers específicos** para
  analisar num único seletor: basta digitar para buscar entre as ~50 mil /
  60 mil entidades. Sem busca, as maiores aparecem primeiro. Trocar "Visão
  por" limpa a seleção e o clique, já que os nomes são conjuntos diferentes.
- Há também filtro por **gênero** e por **categoria** (40 valores, como
  `Single-player`, `Co-op`, `Steam Achievements`). Ambos vêm de listas, então
  um jogo com vários rótulos é contado em cada um dos filtros.
- Tudo aparece em **uma única tela**, sem abas: a **visão competitiva** no
  topo e, logo abaixo, a **pizza de composição**, a **evolução dos
  lançamentos**, o **mapa de desempenho dos gêneros**, a dispersão
  **popularidade/satisfação dos jogos**, os 6 KPIs e a tabela de **dados
  brutos** (sem limite de jogos).
- Clicar em qualquer gráfico salva o foco em `st.session_state` e atualiza
  **todos** os painéis da mesma tela, sem troca de página.
- Sem seleção nem filtro, composição e evolução são **gerais** (toda a base).
  Com qualquer filtro ou seleção, passam a mostrar o grupo em análise: pub/dev,
  gênero, categoria, ano ou jogo. Se o foco for um **jogo**, cada painel mostra
  somente aquele título (a linha vira um único ponto, o ano de lançamento).
- A pizza usa o **gênero principal** de cada jogo, de forma que cada título
  entra uma única vez e as fatias somam 100% do grupo. Os 8 gêneros mais comuns
  têm fatia própria; o resto vai para "Outros". Um expander explica esses
  limites na própria tela.
- O parquet já exclui os campos de texto longo (`detailed_description`,
  `about_the_game`, `short_description`, screenshots etc.); a tabela bruta só
  traz as colunas analíticas, sem descrições e histórias.
- Clique com o **botão esquerdo** em um ponto abre o foco (jogo, publisher ou
  desenvolvedor). Para remover um outlier ou um pub/dev inteiro, há **dois
  caminhos**, com o mesmo efeito: todos os jogos do grupo saem dos gráficos,
  KPIs e da tabela.
  1. ligar o switch **Modo exclusão** na sidebar e clicar no jogo/pub/dev;
  2. clicar no ponto e usar o botão **Excluir … em foco**.
- Excluir um publisher ou desenvolvedor remove **todos** os jogos em que ele
  aparece, incluindo suas linhas nas tabelas longas usadas pelos filtros.
- A sidebar mostra os jogos e pubs/devs excluídos, a quantidade de jogos fora
  do recorte e oferece **Restaurar exclusões**. A exclusão vale apenas para a
  sessão atual; o parquet não é alterado.
- O clique comanda todos os painéis — não há mais checkbox de cross-filter.
  **Limpar clique** volta ao recorte da sidebar.
- Em **Visão competitiva** e no mapa de gêneros, o diâmetro das bolhas usa
  **escala logarítmica ancorada no menor valor exibido** (não no zero), com
  limites compartilhados por todos os grupos. Ancorar no zero deixava as
  bolhas quase iguais; assim o menor ponto fica em 10 px e o maior em 38 px,
  com outliers (ex.: CS2 com 8,6 M de reviews) comprimidos sem esmagar os
  demais.
- Em **Popularidade e satisfação dos jogos**, o tamanho é a **% de avaliações
  positivas** (não o número de reviews). Como esse indicador vai de 0 a 1 e
  fica concentrado entre 80% e 99%, a escala é linear com recorte nos
  percentis 5 e 95 — sem isso quase todas as bolhas ficariam do mesmo tamanho.
- O tempo médio de jogo é exibido em **horas** nos KPIs, tooltips e eixos.
- Os demais filtros da sidebar (ano, gênero, categoria, preço, mínimo de
  reviews, mínimo de % positivas e busca por nome) afetam todos os painéis.
- O slider de reviews usa escala logarítmica para permitir selecionar desde
  poucas dezenas até milhões de avaliações.

## Dados

O CSV original tem `publishers`, `developers`, `genres` e `categories` como
strings de lista. `preparar_dados.py` converte faixas de proprietários, troca
`-1` por `NaN` nos campos de reviews e divide os percentuais por 100. `app.py`
explode as listas (tabelas lógicas `gambiarra_pub` / `gambiarra_dev`, gêneros e
categorias) e calcula as agregações com `st.cache_data`.
