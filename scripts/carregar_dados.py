#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
carregar_dados.py

Atividade 5 (DevOps - Provisionamento e preparação dos serviços)

Carrega no Postgres os CSVs JÁ TRATADOS (dados/tratado), completando o fluxo:

    gerador_dados.py --> dados/raw --> tratar_dados.R --> dados/tratado --> carregar_dados.py --> Postgres

O banco funciona tanto no Docker Compose quanto num PostgreSQL instalado
(VM provisionada pelo OpenTofu + Ansible, ou PostgreSQL portátil no Windows):
basta a DATABASE_URL do .env apontar para ele.

Para carregar os dados BRUTOS (sem tratamento), use --dados-dir dados/raw.

Uso:
    python scripts/carregar_dados.py
    python scripts/carregar_dados.py --dados-dir dados/tratado --substituir
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

# Ordem de carga respeita as dependências de chave estrangeira:
# clientes -> servicos -> fotos / manutencoes
TABELAS_EM_ORDEM = [
    ("clientes.csv", "clientes"),
    ("servicos.csv", "servicos"),
    ("fotos.csv", "fotos"),
    ("manutencoes.csv", "manutencoes"),
]


def main():
    parser = argparse.ArgumentParser(description="Carrega os CSVs gerados para o Postgres.")
    parser.add_argument("--dados-dir", default="dados/tratado",
                        help="Pasta com os CSVs a carregar (padrão: dados/tratado, saída do tratar_dados.R).")
    parser.add_argument(
        "--substituir",
        action="store_true",
        help="Se informado, esvazia as tabelas (TRUNCATE) antes de carregar novamente.",
    )
    args = parser.parse_args()

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERRO: variável DATABASE_URL não encontrada. Copie .env.example para .env.")
        sys.exit(1)

    dados_dir = Path(args.dados_dir)
    if not dados_dir.exists():
        print(f"ERRO: pasta '{dados_dir}' não encontrada. Rode antes o pipeline: "
              "python scripts/gerador_dados.py && Rscript scripts/tratar_dados.R  (ou: make pipeline)")
        sys.exit(1)

    engine = create_engine(database_url)

    with engine.begin() as conn:
        if args.substituir:
            print("Limpando tabelas existentes (TRUNCATE ... CASCADE)...")
            conn.execute(text(
                "TRUNCATE TABLE fotos, manutencoes, servicos, clientes RESTART IDENTITY CASCADE;"
            ))

        for nome_arquivo, nome_tabela in TABELAS_EM_ORDEM:
            caminho = dados_dir / nome_arquivo
            if not caminho.exists():
                print(f"  [aviso] {caminho} não encontrado, pulando.")
                continue
            df = pd.read_csv(caminho, encoding="utf-8-sig")
            # Só carrega as colunas que existem na tabela (arquivos de apoio do
            # tratamento, como servicos_qualidade.csv, ficam fora do banco).
            colunas_tabela = {c["name"] for c in inspect(conn).get_columns(nome_tabela)}
            df = df[[c for c in df.columns if c in colunas_tabela]]
            df.to_sql(nome_tabela, con=conn, if_exists="append", index=False)
            print(f"  {nome_tabela:<15} <- {len(df):>5} linhas ({caminho})")

        # Os CSVs trazem os IDs prontos, então o contador (SERIAL) de cada
        # tabela não avança sozinho. Sem isto, o próximo INSERT feito pela
        # API tentaria usar o id 1 e falharia com chave duplicada.
        for tabela, coluna in [("clientes", "id_cliente"), ("servicos", "id_servico"),
                               ("fotos", "id_foto"), ("manutencoes", "id_manutencao")]:
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{tabela}', '{coluna}'), "
                f"COALESCE((SELECT MAX({coluna}) FROM {tabela}), 0) + 1, false)"
            ))

    print("\nCarga concluída com sucesso.")


if __name__ == "__main__":
    main()
