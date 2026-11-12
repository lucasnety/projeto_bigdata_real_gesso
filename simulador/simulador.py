#!/usr/bin/env python3
"""
Simulador mínimo de dados — Projeto Integrado de Data Science
Checkpoint 01 (DevOps e Infraestrutura Privada)

Gera registros fictícios de "chamados de serviço" para a empresa de
gesso/drywall do Projeto Integrado (mesma situação-problema usada nas
demais atividades do grupo). Cada execução ANEXA novos registros ao
arquivo CSV de saída — nunca sobrescreve o que já foi gerado antes.

Papel no projeto (dois geradores, dois objetivos):
  * simulador/simulador.py  -> fluxo CONTÍNUO de chamados, leve (só biblioteca
    padrão), executado DENTRO da VM a cada rodada (systemd timer / Ansible).
    É o dado do Checkpoint 01 (DevOps): prova que a VM gera e preserva dados.
  * scripts/gerador_dados.py -> carga HISTÓRICA relacional (clientes, serviços,
    fotos, manutenções), propositalmente suja, que passa pelo tratamento em R
    (scripts/tratar_dados.R) antes de entrar no Postgres.
Os dois usam o MESMO vocabulário: as mesmas cidades, tipos de serviço e status.

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

# Mesmas cidades do gerador (scripts/gerador_dados.py)
CIDADES = [
    "São João da Boa Vista", "Aguaí", "Vargem Grande do Sul", "Mococa",
    "Casa Branca", "São José do Rio Pardo", "Espírito Santo do Pinhal",
    "Poços de Caldas", "Águas da Prata", "Itobi",
]

# tipo de serviço -> (preço de referência por m ou m², quantidade mínima, quantidade máxima)
# Preços da tabela oficial (preco_por_m); Gesso Liso e Moldura usam a média dos subtipos.
TIPOS_SERVICO = {
    "Sanca":             (95.00, 3, 40),
    "Divisória Drywall": (130.00, 4, 85),
    "Forro Drywall":     (95.00, 4, 85),
    "Gesso Liso":        (24.00, 4, 85),
    "Moldura de Gesso":  (16.00, 3, 40),
    "Gesso 3D":          (180.00, 4, 85),
    "Boiserie":          (150.00, 3, 40),
}

# Mesmos status de serviço do banco de dados
STATUS = ["orçado", "em andamento", "concluído"]

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
    tipo = random.choice(list(TIPOS_SERVICO))
    preco, qtd_min, qtd_max = TIPOS_SERVICO[tipo]
    quantidade = random.uniform(qtd_min, qtd_max)
    return {
        "id_chamado": str(uuid.uuid4())[:8],
        "cliente": f"Cliente {contador:04d}",
        "cidade": random.choice(CIDADES),
        "tipo_servico": tipo,
        # valor estimado = metragem sorteada x preço de referência (± 15% de negociação)
        "valor_estimado": round(quantidade * preco * random.uniform(0.85, 1.10), 2),
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
