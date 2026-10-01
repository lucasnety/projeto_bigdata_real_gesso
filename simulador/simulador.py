#!/usr/bin/env python3
"""
Simulador mínimo de dados — Projeto Integrado de Data Science
Checkpoint 01 (DevOps e Infraestrutura Privada)

Gera registros fictícios de "chamados de serviço" para a empresa de
gesso/drywall do Projeto Integrado (mesma situação-problema usada nas
demais atividades do grupo). Cada execução ANEXA novos registros ao
arquivo CSV de saída — nunca sobrescreve o que já foi gerado antes.

Uso:
    python simulador.py --out-dir /opt/datasci/dados
    python simulador.py --out-dir /opt/datasci/dados --n 20
    python simulador.py --out-dir /opt/datasci/dados --seed 42

Só usa a biblioteca padrão do Python (random, csv, uuid, datetime),
de propósito — assim ele roda em qualquer VM recém-provisionada sem
depender de internet para baixar pacotes externos durante a demo.
"""

import argparse
import csv
import os
import random
import uuid
from datetime import datetime, timezone

CIDADES = [
    "São João da Boa Vista", "Aguaí", "Águas da Prata", "Itobi",
    "Espírito Santo do Pinhal", "São José do Rio Pardo", "Poços de Caldas",
]

TIPOS_SERVICO = [
    "Forro Drywall", "Divisória Drywall", "Sanca", "Gesso Liso",
    "Moldura de Gesso", "Manutenção",
]

STATUS = ["orçado", "em andamento", "concluído", "cancelado"]

CAMPOS = [
    "id_chamado",
    "cliente",
    "cidade",
    "tipo_servico",
    "valor_estimado",
    "status",
    "data_hora_geracao",
]


def gerar_registro(contador: int) -> dict:
    """Gera um registro fictício de chamado de serviço."""
    return {
        "id_chamado": str(uuid.uuid4())[:8],
        "cliente": f"Cliente {contador:04d}",
        "cidade": random.choice(CIDADES),
        "tipo_servico": random.choice(TIPOS_SERVICO),
        "valor_estimado": round(random.uniform(150.0, 8000.0), 2),
        "status": random.choice(STATUS),
        # Informação temporal exigida pelo checkpoint: data/hora da geração
        "data_hora_geracao": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def proximo_contador(caminho_csv: str) -> int:
    """Continua a numeração a partir do que já existe no arquivo (se houver)."""
    if not os.path.exists(caminho_csv):
        return 1
    with open(caminho_csv, newline="", encoding="utf-8") as f:
        linhas = sum(1 for _ in f) - 1  # desconta o cabeçalho
    return max(linhas, 0) + 1


def main():
    parser = argparse.ArgumentParser(description="Simulador de chamados de serviço (gesso/drywall)")
    parser.add_argument("--out-dir", default="dados", help="Diretório onde salvar o CSV gerado")
    parser.add_argument("--n", type=int, default=15, help="Quantidade de registros a gerar nesta execução (mínimo 10)")
    parser.add_argument("--seed", type=int, default=None, help="Semente aleatória (opcional, para reprodutibilidade)")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    n = max(args.n, 10)  # o checkpoint exige pelo menos 10 registros por execução

    os.makedirs(args.out_dir, exist_ok=True)
    caminho_csv = os.path.join(args.out_dir, "chamados_servico.csv")

    arquivo_novo = not os.path.exists(caminho_csv)
    contador_inicial = proximo_contador(caminho_csv)

    with open(caminho_csv, "a", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=CAMPOS)
        if arquivo_novo:
            escritor.writeheader()
        for i in range(n):
            escritor.writerow(gerar_registro(contador_inicial + i))

    print(f"[simulador] {n} novos registros gerados em: {caminho_csv}")
    print(f"[simulador] Execução em: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
