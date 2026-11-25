# Estúdio Competitivo — dashboard Streamlit

Recriação interativa do relatório Power BI (`trabalho com a teresa.pbix`) em Streamlit,
usando os dados originais do Steam. **O arquivo `.pbix` não é lido nem modificado**
pela aplicação: ele serviu apenas como referência das measures, visuais e paleta.

## Arquivos

- `preparar_dados.py` — lê o CSV em chunks e grava `data/jogos.parquet`.
- `app.py` — dashboard com 4 telas, filtros globais, clique nos gráficos e detalhes.
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
| Página "Página 1" — dispersão de publishers | Tela **Visão competitiva** |
| Página "Estratégia e composição do portfólio" — barras + linha | Tela **Portfólio** |
| Página "Mercado, satisfação e jogadores" — 2 dispersões | Tela **Mercado e jogadores** |
| Slicer "Visão por" (Publisher/Desenvolvedor) | Radio na sidebar, aplicado a todas as telas |
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
> `MEDIAN(...)`. Aqui ela foi trocada por `mean()` a pedido, para que um título
> muito popular (ex.: War Thunder, 35 M) não seja "escondido" pela quantidade de
> jogos menores da mesma editora. Na visão Publisher, `Gaijin Network Ltd`
> passa de 3,5 M (mediana) para ~7,7 M (média dos 6 jogos).

Validação das medidas inalteradas: Qtd Jogos (89.618), % positivas (85,82%),
Qtd Reviews (117.928.014), Tempo Médio (1.285,7 min = 21,4 h) batem exatamente com o
modelo. O `.pbix` armazena `price` em centavos (e tem 578 linhas com o preço
divergente do CSV); aqui usamos os dólares do CSV, então o Preço Médio exibido
(US$ 8,68) é o valor correto para a base original.

## Interatividade

- A sidebar permite **escolher publishers ou developers específicos** para
  analisar num único seletor: basta digitar para buscar entre as ~50 mil /
  60 mil entidades. Sem busca, as maiores aparecem primeiro. Trocar "Visão
  por" limpa a seleção, já que os nomes são conjuntos diferentes. As entidades
  escolhidas filtram todas as telas e ganham prioridade nos gráficos (mesmo
  quando não estão no topo por reviews/jogos).
- Há também filtro por **gênero** e por **categoria** (40 valores, como
  `Single-player`, `Co-op`, `Steam Achievements`). Ambos vêm de listas, então
  um jogo com vários rótulos é contado em cada um.
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
- Os demais filtros da sidebar (ano, preço, mínimo de reviews, mínimo de %
  positivas e busca por nome) afetam todas as telas.
- O slider de reviews usa escala logarítmica para permitir selecionar desde
  poucas dezenas até milhões de avaliações.
- Clicar em um ponto/barra salva a seleção em `st.session_state` e abre a tela
  **Detalhes**, com 6 KPIs e a lista de **todos** os jogos da seleção.
- A tela **Portfólio** traz um expander explicando como as barras e a linha são
  calculadas e quais são os cortes (top 12 entidades, top 8 gêneros, "Outros").
- O checkbox **Aplicar clique como filtro nos gráficos** liga/desliga o
  cross-filter global por clique.
- **Limpar seleção** volta à visão filtrada.

> Nota: a navegação usa `st.segmented_control` em vez de `st.tabs` porque o
> Streamlit não permite trocar de aba programaticamente; assim o clique no
> gráfico consegue abrir de fato a tela "Detalhes".

## Dados

O CSV original tem `publishers`, `developers`, `genres` e `categories` como
strings de lista. `preparar_dados.py` converte faixas de proprietários, troca
`-1` por `NaN` nos campos de reviews e divide os percentuais por 100. `app.py`
explode as listas (tabelas lógicas `gambiarra_pub` / `gambiarra_dev`, gêneros e
categorias) e calcula as agregações com `st.cache_data`.
