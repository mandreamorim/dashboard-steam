"""Prepara a base do dashboard: CSV original -> data/jogos.parquet.

Equivale às transformações feitas nas consultas M do .pbix. O arquivo .pbix
serve apenas como referência: ele nunca é lido nem modificado por este script.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
DADOS = BASE / "data"
SAIDA = DADOS / "jogos.parquet"

CHUNK_SIZE = 100_000

# Usamos apenas as colunas necessárias para as medidas e visuais. As colunas de
# texto longo (descrições, screenshots, etc.) são ignoradas para não estourar
# a memória com um CSV de ~468 MB.
USECOLS = {
    "appid": "string",
    "name": "string",
    "release_date": "string",
    "price": "float64",
    "genres": "string",
    "categories": "string",
    "developers": "string",
    "publishers": "string",
    "positive": "float64",
    "negative": "float64",
    "estimated_owners": "string",
    "average_playtime_forever": "float64",
    "num_reviews_total": "float64",
    "pct_pos_total": "float64",
    "num_reviews_recent": "float64",
    "pct_pos_recent": "float64",
}

REVIEW_COLS = [
    "num_reviews_total",
    "pct_pos_total",
    "num_reviews_recent",
    "pct_pos_recent",
]

_FAIXA = re.compile(r"([\d,]+)\s*-\s*([\d,]+)")


def caminho_csv() -> Path:
    """CSV informado por JOGOS_CSV, ou o cópia local em data/ / raiz do projeto."""
    override = os.environ.get("JOGOS_CSV")
    if override:
        return Path(override).expanduser().resolve()

    candidatos = [
        DADOS / "games_march2025_cleaned.csv",
        BASE / "games_march2025_cleaned.csv",
    ]
    for candidato in candidatos:
        if candidato.exists():
            return candidato
    return candidatos[0]


def owners_mediana(valores: pd.Series) -> pd.Series:
    """Converte '10,000-20,000' na mediana da faixa (15.000)."""
    texto = valores.fillna("").astype(str).str.replace(",", "", regex=False)
    partes = texto.str.extract(_FAIXA)
    inf = pd.to_numeric(partes[0], errors="coerce")
    sup = pd.to_numeric(partes[1], errors="coerce")
    return (inf + sup) / 2


def transformar(chunk: pd.DataFrame) -> pd.DataFrame:
    """Aplica as mesmas regras do modelo Power BI a um pedaço do CSV."""
    chunk = chunk.copy()

    chunk["appid"] = pd.to_numeric(chunk["appid"], errors="coerce").astype("Int64")
    chunk = chunk.dropna(subset=["appid"]).drop_duplicates(subset=["appid"])
    chunk["appid"] = chunk["appid"].astype("int64")

    data = pd.to_datetime(chunk["release_date"], errors="coerce", format="%Y-%m-%d")
    chunk["ano_lancamento"] = data.dt.year.astype("Int64")

    chunk["estimated_owners_num"] = owners_mediana(chunk["estimated_owners"])

    for coluna in REVIEW_COLS:
        # -1 é o sentinela "sem dado" do CSV do Steam.
        chunk[coluna] = chunk[coluna].mask(chunk[coluna] == -1).astype("float64")

    chunk["pct_pos_total"] = chunk["pct_pos_total"] / 100
    chunk["pct_pos_recent"] = chunk["pct_pos_recent"] / 100

    return chunk[
        [
            "appid",
            "name",
            "ano_lancamento",
            "price",
            "genres",
            "categories",
            "developers",
            "publishers",
            "positive",
            "negative",
            "estimated_owners_num",
            "average_playtime_forever",
            "num_reviews_total",
            "pct_pos_total",
            "num_reviews_recent",
            "pct_pos_recent",
        ]
    ]


def preparar(verbose: bool = True) -> Path:
    csv = caminho_csv()
    if not csv.exists():
        raise FileNotFoundError(
            f"CSV não encontrado: {csv}\n"
            "Copie o CSV para data/games_march2025_cleaned.csv ou defina JOGOS_CSV."
        )

    DADOS.mkdir(parents=True, exist_ok=True)
    partes: list[pd.DataFrame] = []
    total = 0
    for chunk in pd.read_csv(
        csv,
        usecols=USECOLS.keys(),
        dtype=USECOLS,
        chunksize=CHUNK_SIZE,
        low_memory=False,
    ):
        partes.append(transformar(chunk))
        total += len(chunk)
        if verbose:
            print(f"\rLendo CSV... {total:,} linhas", end="", flush=True)

    jogos = pd.concat(partes, ignore_index=True)
    jogos = jogos.drop_duplicates(subset=["appid"]).reset_index(drop=True)
    jogos.to_parquet(SAIDA, index=False, compression="snappy")

    if verbose:
        print(f"\nPronto: {len(jogos):,} jogos -> {SAIDA.relative_to(BASE)}")
    return SAIDA


if __name__ == "__main__":
    preparar()
