#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
carregar_dados.py

Atividade 5 (DevOps - Provisionamento e preparação dos serviços)

Carrega os CSVs brutos gerados pelo simulador (scripts/gerador_dados.py)
para dentro do serviço de banco de dados (Postgres) provisionado via
Docker Compose, completando o fluxo:

    gerador_dados.py  -->  dados/raw/*.csv  -->  carregar_dados.py  -->  Postgres

Uso:
    python scripts/carregar_dados.py
    python scripts/carregar_dados.py --dados-dir dados/raw --substituir
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

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
    parser.add_argument("--dados-dir", default="dados/raw", help="Pasta com os CSVs gerados.")
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
        print(f"ERRO: pasta '{dados_dir}' não encontrada. Rode antes: python scripts/gerador_dados.py")
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
            df.to_sql(nome_tabela, con=conn, if_exists="append", index=False)
            print(f"  {nome_tabela:<15} <- {len(df):>5} linhas ({caminho})")

    print("\nCarga concluída com sucesso.")


if __name__ == "__main__":
    main()
