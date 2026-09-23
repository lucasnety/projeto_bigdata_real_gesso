#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerador_dados.py

Atividade 6 (DevOps - Simulador Gerador de Dados)

Simulador que gera, de forma automática e reprodutível, um conjunto de
dados brutos (fictícios) compatível com a situação-problema do projeto:
uma empresa de montagem/execução de serviços de gesso e drywall.

O simulador produz 5 tabelas em CSV (o mesmo modelo relacional definido
na Entrega 01):

    clientes.csv      - cadastro de clientes
    preco_por_m.csv   - tabela oficial de preços por serviço
    servicos.csv      - serviços orçados/executados
    fotos.csv         - registros fotográficos dos serviços
    manutencoes.csv   - chamados de manutenção pós-serviço

IMPORTANTE - qualidade dos dados de propósito "suja":
Por pedido explícito da atividade, os dados gerados aqui são BRUTOS: o
simulador injeta, de forma controlada e documentada, os mesmos tipos de
inconsistência que uma captação real (WhatsApp, papel, planilhas soltas)
produziria. Essas inconsistências serão tratadas depois, na etapa de
Análise Exploratória de Dados (EDA):

    - valores ausentes        (telefone, e-mail, endereço, preço "a combinar"...)
    - duplicidades             (clientes quase-duplicados, fotos repetidas)
    - formatos inconsistentes  (telefone em 5 formatos, datas DD/MM/AAAA
                                 misturadas com AAAA-MM-DD, "m2" vs "metro quadrado")
    - categorias divergentes   (status/tipo de serviço com grafias diferentes:
                                 "concluído" / "CONCLUÍDO" / "Concluido")
    - preços fora da tabela    (Gesso 3D e Boiserie são vendidos mas não têm
                                 entrada oficial em preco_por_m)

Uso:
    python scripts/gerador_dados.py
    python scripts/gerador_dados.py --clientes 500 --servicos 2000 --seed 7
    python scripts/gerador_dados.py --out-dir dados/local   # não versionado
"""

import argparse
import os
import random
from datetime import date, datetime, timedelta

import pandas as pd
from faker import Faker

# ---------------------------------------------------------------------
# Configuração de listas fixas usadas na geração
# ---------------------------------------------------------------------
CIDADES = [
    "São João da Boa Vista", "Aguaí", "Vargem Grande do Sul", "Mococa",
    "Casa Branca", "São José do Rio Pardo", "Espírito Santo do Pinhal",
    "Poços de Caldas", "Águas da Prata", "Itobi",
]

ORIGENS = (
    ["Indicação"] * 5 + ["Instagram"] * 3 + ["Facebook"] * 2 +
    ["Google"] * 2 + ["Site"] * 1 + ["Panfleto"] * 1 + ["Cliente antigo"] * 2
)

AMBIENTES = [
    "sala de estar", "quarto principal", "cozinha", "escritório", "fachada comercial",
    "galpão industrial", "recepção da loja", "corredor", "sala comercial", "área externa",
]

DESCRICOES_FOTO = ["Antes", "Depois", "Detalhe do acabamento", "Ambiente geral", ""]

PROBLEMAS_MANUTENCAO = [
    "Trinca no rodateto após acomodação da estrutura",
    "Infiltração próxima à sanca",
    "Ajuste/realinhamento de moldura",
    "Reparo em divisória drywall após passagem de fiação elétrica",
    "Retoque de pintura no gesso 3D",
    "Substituição de placa de drywall danificada por umidade",
    "Reforço de fixação do forro",
    "Pequeno reparo estético solicitado pelo cliente",
]

# Tabela oficial de preços (usada tanto para popular preco_por_m quanto
# como referência de preço "correto" ao gerar servicos).
# (tipo_servico, subtipo, unidade_medida, valor, peso_de_sorteio)
CATALOGO = [
    ("Sanca",             "",                 "metro linear",   95.00, 6),
    ("Divisória Drywall",  "",                 "metro quadrado", 130.00, 6),
    ("Forro Drywall",      "",                 "metro quadrado", 95.00, 8),
    ("Gesso Liso",         "Parede Rebocada",  "metro quadrado", 20.00, 3),
    ("Gesso Liso",         "Parede de Tijolo", "metro quadrado", 30.00, 3),
    ("Gesso Liso",         "Parede Pintada",   "metro quadrado", 22.00, 3),
    ("Moldura de Gesso",   "7cm",              "metro linear",   12.00, 2),
    ("Moldura de Gesso",   "10cm",             "metro linear",   15.00, 2),
    ("Moldura de Gesso",   "15cm",             "metro linear",   17.00, 2),
    ("Moldura de Gesso",   "20cm",             "metro linear",   20.00, 2),
    # Sem entrada oficial em preco_por_m -> inconsistência proposital
    ("Gesso 3D",            "",                "metro quadrado", 180.00, 2),
    ("Boiserie",             "",                "metro linear",   150.00, 2),
]
SERVICOS_COM_PRECO_OFICIAL = CATALOGO[:10]  # os 2 últimos ficam de fora do preco_por_m


# ---------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------
def random_date(fake, d0: date, d1: date) -> date:
    delta = (d1 - d0).days
    return d0 + timedelta(days=random.randint(0, max(delta, 0)))


def fmt_date(d, alt_format: bool = False) -> str:
    if d is None:
        return ""
    return d.strftime("%d/%m/%Y") if alt_format else d.strftime("%Y-%m-%d")


def dirty_phone(fake) -> str:
    """Gera telefone em um de vários formatos - inconsistência proposital."""
    ddd = random.choice(["19", "35", "11", "16"])
    n8 = fake.msisdn()[-8:]
    n9 = "9" + n8
    estilo = random.random()
    if estilo < 0.35:
        return f"({ddd}) {n9[:5]}-{n9[5:]}"
    elif estilo < 0.55:
        return f"{ddd}{n9}"
    elif estilo < 0.70:
        return f"({ddd}){n9[:5]}-{n9[5:]}"
    elif estilo < 0.85:
        return f"+55 {ddd} {n9[:5]}-{n9[5:]}"
    else:
        return f"{ddd} {n8}"  # sem o 9º dígito


# ---------------------------------------------------------------------
# Geração de cada tabela
# ---------------------------------------------------------------------
def gerar_clientes(fake, n: int, data_inicio: date, data_fim: date) -> pd.DataFrame:
    clientes = []
    for i in range(1, n + 1):
        nome = fake.name()
        email = ""
        if random.random() > 0.12:  # ~12% sem e-mail
            base = nome.lower().split()
            email = f"{base[0]}.{base[-1]}{random.randint(1, 99)}@{random.choice(['gmail.com', 'hotmail.com', 'yahoo.com.br', 'outlook.com'])}"
        endereco = fake.street_address() if random.random() > 0.06 else ""
        cidade = random.choice(CIDADES) if random.random() > 0.04 else ""
        origem = random.choice(ORIGENS)
        cadastro = random_date(fake, data_inicio - timedelta(days=180), data_fim)
        clientes.append({
            "id_cliente": i,
            "nome_completo": nome,
            "telefone": dirty_phone(fake) if random.random() > 0.03 else "",
            "email": email,
            "endereco": endereco,
            "cidade": cidade,
            "origem_contato": origem,
            "data_cadastro": fmt_date(cadastro, alt_format=(random.random() < 0.03)),
        })

    # ~4% de clientes "quase duplicados" (mesmo cliente cadastrado 2x
    # com pequenas variações) - inconsistência proposital.
    n_dup = max(1, round(n * 0.04))
    for i in range(n_dup):
        original = random.choice(clientes[:n])
        novo_id = n + i + 1
        nome_variado = original["nome_completo"]
        if random.random() < 0.5:
            nome_variado = nome_variado.replace(" ", "  ", 1)  # espaço duplo
        clientes.append({
            "id_cliente": novo_id,
            "nome_completo": nome_variado,
            "telefone": dirty_phone(fake),
            "email": original["email"],
            "endereco": original["endereco"],
            "cidade": original["cidade"],
            "origem_contato": original["origem_contato"],
            "data_cadastro": fmt_date(random_date(fake, data_inicio, data_fim)),
        })

    return pd.DataFrame(clientes)


def gerar_preco_por_m() -> pd.DataFrame:
    precos = []
    for idx, (tipo, subtipo, unidade, valor, _peso) in enumerate(SERVICOS_COM_PRECO_OFICIAL, start=1):
        precos.append({
            "id_preco": idx,
            "tipo_servico": tipo,
            "subtipo": subtipo,
            "unidade_medida": unidade,
            "valor": valor,
            "data_atualizacao": fmt_date(random_date(None, date(2023, 6, 1), date(2024, 3, 1))),
        })
    return pd.DataFrame(precos)


def gerar_servicos(fake, n: int, total_clientes: int, data_inicio: date, data_fim: date) -> list:
    pesos = [c[4] for c in CATALOGO]
    servicos = []
    for i in range(1, n + 1):
        tipo, subtipo, unidade, valor_ref, _peso = random.choices(CATALOGO, weights=pesos, k=1)[0]
        id_cliente = random.randint(1, total_clientes)

        if unidade == "metro linear":
            quantidade = round(random.uniform(3, 40), 2)
        else:
            quantidade = round(random.uniform(4, 85), 2)
        if random.random() < 0.01:
            quantidade = 0  # erro de digitação proposital

        r = random.random()
        if r < 0.72:
            valor_aplicado = valor_ref
        elif r < 0.92:
            valor_aplicado = round(valor_ref * random.uniform(0.85, 1.10), 2)  # negociação
        else:
            valor_aplicado = ""  # "a combinar", ainda não definido

        valor_total = round(quantidade * valor_aplicado, 2) if (valor_aplicado != "" and quantidade) else ""

        data_exec = random_date(fake, data_inicio, data_fim)
        dias_para_hoje = (data_fim - data_exec).days
        if dias_para_hoje < 10:
            status = random.choice(["orçado", "em andamento", "concluído"])
        elif dias_para_hoje < 25:
            status = random.choice(["em andamento", "concluído", "concluído"])
        else:
            status = random.choices(["concluído", "Concluido", "CONCLUÍDO"], weights=[85, 10, 5])[0]

        unidade_txt = unidade
        if random.random() < 0.05:
            unidade_txt = {"metro linear": "m linear", "metro quadrado": "m2"}[unidade]

        tipo_txt = tipo.lower() if random.random() < 0.03 else tipo

        ambiente = random.choice(AMBIENTES)
        descricoes = [
            f"Execução de {tipo.lower()} em {ambiente}.",
            f"Serviço de {tipo.lower()} solicitado para {ambiente}, imóvel {'residencial' if random.random() < 0.75 else 'industrial'}.",
            f"{tipo} - {ambiente}, conforme orçamento aprovado.",
        ]

        servicos.append({
            "id_servico": i,
            "id_cliente": id_cliente,
            "tipo_servico": tipo_txt,
            "subtipo": subtipo,
            "descricao_detalhada": random.choice(descricoes),
            "unidade_medida": unidade_txt,
            "quantidade": quantidade,
            "valor_unitario_aplicado": valor_aplicado,
            "valor_total": valor_total,
            "data_execucao": fmt_date(data_exec, alt_format=(random.random() < 0.02)),
            "status": status,
        })
    return servicos


def gerar_fotos(servicos: list) -> pd.DataFrame:
    fotos = []
    foto_id = 1
    for s in servicos:
        if s["status"].strip().lower().startswith("conclu") and random.random() > 0.15:
            n_fotos = random.choices([1, 2, 3, 0], weights=[45, 30, 15, 10])[0]
            for n in range(n_fotos):
                try:
                    base = datetime.strptime(s["data_execucao"], "%Y-%m-%d").date()
                    data_up = base + timedelta(days=random.randint(0, 4))
                except ValueError:
                    data_up = date.today()
                fotos.append({
                    "id_foto": foto_id,
                    "id_servico": s["id_servico"],
                    "caminho_arquivo": f"/fotos/servicos/{s['id_servico']}/foto_{n + 1}.jpg",
                    "descricao": random.choice(DESCRICOES_FOTO),
                    "data_upload": fmt_date(data_up),
                })
                foto_id += 1

    # Duplicações propositais (arquivo repetido/corrompido)
    for _ in range(min(15, max(1, len(fotos) // 100))):
        if not fotos:
            break
        f = random.choice(fotos).copy()
        f["id_foto"] = foto_id
        fotos.append(f)
        foto_id += 1

    return pd.DataFrame(fotos)


def gerar_manutencoes(fake, servicos: list, n: int, data_fim: date) -> pd.DataFrame:
    servicos_concluidos = [s for s in servicos if s["status"].strip().lower().startswith("conclu")]
    if not servicos_concluidos:
        return pd.DataFrame(columns=[
            "id_manutencao", "id_cliente", "id_servico_origem", "descricao",
            "preco", "data_solicitacao", "data_execucao", "status",
        ])

    manutencoes = []
    for i in range(1, n + 1):
        origem = random.choice(servicos_concluidos)
        id_cliente = origem["id_cliente"]
        tem_vinculo = random.random() > 0.15
        try:
            data_origem = datetime.strptime(origem["data_execucao"], "%Y-%m-%d").date()
        except ValueError:
            data_origem = data_fim - timedelta(days=365)
        data_sol = random_date(fake, data_origem, data_fim)

        r = random.random()
        if r < 0.6:
            status = "concluída"
            data_exec_str = fmt_date(random_date(fake, data_sol, min(data_sol + timedelta(days=20), data_fim)))
        elif r < 0.8:
            status = "agendada"
            data_exec_str = ""
        else:
            status = "solicitada"
            data_exec_str = ""

        preco = round(random.uniform(50, 420), 2)
        if random.random() < 0.15:
            preco = ""  # garantia / a combinar

        manutencoes.append({
            "id_manutencao": i,
            "id_cliente": id_cliente,
            "id_servico_origem": origem["id_servico"] if tem_vinculo else "",
            "descricao": random.choice(PROBLEMAS_MANUTENCAO),
            "preco": preco,
            "data_solicitacao": fmt_date(data_sol),
            "data_execucao": data_exec_str,
            "status": status,
        })

    return pd.DataFrame(manutencoes)


# ---------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------
def gerar_tudo(n_clientes: int, n_servicos: int, n_manutencoes: int, seed: int,
               data_inicio: date, data_fim: date, out_dir: str):
    random.seed(seed)
    fake = Faker("pt_BR")
    Faker.seed(seed)

    print(f"Semente (seed) usada: {seed}  ->  execução 100% reprodutível")
    print(f"Período simulado: {data_inicio} a {data_fim}\n")

    df_clientes = gerar_clientes(fake, n_clientes, data_inicio, data_fim)
    df_precos = gerar_preco_por_m()
    servicos = gerar_servicos(fake, n_servicos, len(df_clientes), data_inicio, data_fim)
    df_servicos = pd.DataFrame(servicos)
    df_fotos = gerar_fotos(servicos)
    df_manutencoes = gerar_manutencoes(fake, servicos, n_manutencoes, data_fim)

    os.makedirs(out_dir, exist_ok=True)
    df_clientes.to_csv(os.path.join(out_dir, "clientes.csv"), index=False, encoding="utf-8-sig")
    df_precos.to_csv(os.path.join(out_dir, "preco_por_m.csv"), index=False, encoding="utf-8-sig")
    df_servicos.to_csv(os.path.join(out_dir, "servicos.csv"), index=False, encoding="utf-8-sig")
    df_fotos.to_csv(os.path.join(out_dir, "fotos.csv"), index=False, encoding="utf-8-sig")
    df_manutencoes.to_csv(os.path.join(out_dir, "manutencoes.csv"), index=False, encoding="utf-8-sig")

    print("Arquivos gerados em:", out_dir)
    print(f"  clientes.csv      {len(df_clientes):>6} linhas")
    print(f"  preco_por_m.csv   {len(df_precos):>6} linhas")
    print(f"  servicos.csv      {len(df_servicos):>6} linhas")
    print(f"  fotos.csv         {len(df_fotos):>6} linhas")
    print(f"  manutencoes.csv   {len(df_manutencoes):>6} linhas")

    # Painel-resumo das inconsistências propositalmente injetadas
    print("\nResumo de inconsistências propositais nesta geração:")
    print(f"  clientes sem e-mail...................... {(df_clientes['email'] == '').sum()}")
    print(f"  clientes sem telefone..................... {(df_clientes['telefone'] == '').sum()}")
    print(f"  status de serviço com grafias diferentes.. {sorted(df_servicos['status'].unique())}")
    print(f"  serviços sem valor aplicado (a combinar)... {(df_servicos['valor_unitario_aplicado'] == '').sum()}")
    tipos_sem_preco_oficial = set(df_servicos['tipo_servico'].str.lower()) - set(df_precos['tipo_servico'].str.lower())
    print(f"  tipos de serviço sem preço oficial......... {tipos_sem_preco_oficial}")
    print(f"  serviços concluídos sem nenhuma foto....... "
          f"{len(df_servicos[df_servicos['status'].str.lower().str.startswith('conclu')]) - df_fotos['id_servico'].nunique()}")
    print(f"  manutenções sem serviço de origem vinculado {(df_manutencoes['id_servico_origem'] == '').sum()}")

    return {
        "clientes": df_clientes, "precos": df_precos, "servicos": df_servicos,
        "fotos": df_fotos, "manutencoes": df_manutencoes,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Simulador gerador de dados brutos - empresa de gesso e drywall.")
    parser.add_argument("--clientes", type=int, default=330, help="Quantidade de clientes a gerar.")
    parser.add_argument("--servicos", type=int, default=1600, help="Quantidade de serviços a gerar.")
    parser.add_argument("--manutencoes", type=int, default=190, help="Quantidade de manutenções a gerar.")
    parser.add_argument("--seed", type=int, default=42, help="Semente para reprodutibilidade.")
    parser.add_argument("--data-inicio", default="2024-01-01", help="Data inicial (AAAA-MM-DD).")
    parser.add_argument("--data-fim", default=None, help="Data final (AAAA-MM-DD). Padrão: hoje.")
    parser.add_argument("--out-dir", default="dados/raw", help="Pasta de saída dos CSVs.")
    args = parser.parse_args()

    data_inicio = datetime.strptime(args.data_inicio, "%Y-%m-%d").date()
    data_fim = (datetime.strptime(args.data_fim, "%Y-%m-%d").date()
                if args.data_fim else date.today())

    gerar_tudo(args.clientes, args.servicos, args.manutencoes, args.seed,
               data_inicio, data_fim, args.out_dir)


if __name__ == "__main__":
    main()
