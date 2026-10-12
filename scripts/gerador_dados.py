#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerador_dados.py

Atividade 6 (DevOps - Simulador Gerador de Dados)
Atualizado para a atividade de Aprendizado de Máquina.

Simulador que gera, de forma automática e reprodutível, um conjunto de
dados brutos (fictícios) compatível com a situação-problema do projeto:
uma empresa de montagem/execução de serviços de gesso e drywall.

O simulador produz 5 tabelas em CSV (o mesmo modelo relacional definido
na Entrega 01) + 1 arquivo de gabarito:

    clientes.csv         - cadastro de clientes
    preco_por_m.csv      - tabela oficial de preços por serviço
    servicos.csv         - orçamentos/serviços (fechados ou não)
    fotos.csv            - registros fotográficos dos serviços
    manutencoes.csv      - chamados de manutenção pós-serviço
    gabarito_perfis.csv  - perfil "verdadeiro" de cada cliente (NÃO vai
                           para o banco; serve só para validar, no fim,
                           se o agrupamento redescobriu os perfis)

PADRÕES DE NEGÓCIO EMBUTIDOS (para a etapa de Machine Learning)
Dados 100% aleatórios não têm nada a ser descoberto. Por isso o simulador
segue regras plausíveis e DOCUMENTADAS, que os modelos devem redescobrir:

    1. Perfis de cliente (-> agrupamento)
       construtora           poucos clientes, muitos orçamentos, drywall em
                             grande metragem, imóvel comercial/industrial
       alto_padrao           residencial, vem por indicação, sanca/gesso
                             3D/boiserie/moldura, paga preço cheio
       residencial_economico maioria da base, vem por redes sociais/panfleto,
                             gesso liso, pouca metragem, sensível a preço
       pequeno_comercio      lojas/escritórios, vem pelo Google/site,
                             divisória e forro drywall

    2. Fechamento do orçamento (-> classificação)
       Chance de fechar SOBE com: indicação/cliente antigo, visita técnica,
       resposta rápida, cliente que já fechou antes, desconto até ~10%.
       Chance CAI com: demora para enviar o orçamento, redes sociais/
       panfleto, valor alto (forte no perfil econômico). Desconto acima de
       10% não traz ganho adicional.

    3. Preço praticado (-> regressão)
       preço cheio = tabela x fator da cidade x desconto por volume
                     x ajuste do perfil x tipo de imóvel x ruído (~3,5%)
       O desconto concedido é aplicado por cima do preço cheio.

QUALIDADE DOS DADOS PROPOSITALMENTE "SUJA"
Os dados continuam BRUTOS, com as inconsistências que uma captação real
(WhatsApp, papel, planilhas soltas) produziria, para serem tratadas na
preparação dos dados:

    - valores ausentes        (telefone, e-mail, endereço, preço "a combinar"...)
    - duplicidades             (clientes quase-duplicados, fotos repetidas)
    - formatos inconsistentes  (telefone em 5 formatos, datas DD/MM/AAAA
                                 misturadas com AAAA-MM-DD, "m2" vs "metro
                                 quadrado", desconto "10%" vs "10")
    - categorias divergentes   (status/tipo de serviço com grafias diferentes:
                                 "concluído" / "CONCLUÍDO" / "Concluido")
    - preços fora da tabela    (Gesso 3D e Boiserie são vendidos mas não têm
                                 entrada oficial em preco_por_m)
    - erros de digitação       (quantidade = 0)

Uso:
    python scripts/gerador_dados.py
    python scripts/gerador_dados.py --clientes 500 --servicos 2000 --seed 7
    python scripts/gerador_dados.py --out-dir dados/local   # não versionado
"""

import argparse
import math
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

# Fator de preço por cidade (custo de deslocamento + poder de compra local)
FATOR_CIDADE = {
    "São João da Boa Vista": 1.00, "Aguaí": 0.95, "Vargem Grande do Sul": 0.97,
    "Mococa": 1.02, "Casa Branca": 0.95, "São José do Rio Pardo": 1.00,
    "Espírito Santo do Pinhal": 0.98, "Poços de Caldas": 1.12,
    "Águas da Prata": 1.05, "Itobi": 0.92,
}

# Efeito da origem do contato na chance de fechar o orçamento (escala logit)
EFEITO_ORIGEM = {
    "Indicação": 0.7, "Cliente antigo": 0.8, "Google": 0.0, "Site": 0.0,
    "Instagram": -0.3, "Facebook": -0.4, "Panfleto": -0.6,
}

AMBIENTES = {
    "residencial": ["sala de estar", "quarto principal", "cozinha", "corredor", "área externa"],
    "comercial": ["recepção da loja", "sala comercial", "escritório", "fachada comercial"],
    "industrial": ["galpão industrial", "área de produção", "refeitório da fábrica"],
}

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
# como referência de preço ao gerar servicos).
# (tipo_servico, subtipo, unidade_medida, valor)
CATALOGO = [
    ("Sanca",             "",                 "metro linear",   95.00),
    ("Divisória Drywall",  "",                 "metro quadrado", 130.00),
    ("Forro Drywall",      "",                 "metro quadrado", 95.00),
    ("Gesso Liso",         "Parede Rebocada",  "metro quadrado", 20.00),
    ("Gesso Liso",         "Parede de Tijolo", "metro quadrado", 30.00),
    ("Gesso Liso",         "Parede Pintada",   "metro quadrado", 22.00),
    ("Moldura de Gesso",   "7cm",              "metro linear",   12.00),
    ("Moldura de Gesso",   "10cm",             "metro linear",   15.00),
    ("Moldura de Gesso",   "15cm",             "metro linear",   17.00),
    ("Moldura de Gesso",   "20cm",             "metro linear",   20.00),
    # Sem entrada oficial em preco_por_m -> inconsistência proposital
    ("Gesso 3D",            "",                "metro quadrado", 180.00),
    ("Boiserie",             "",                "metro linear",   150.00),
]
SERVICOS_COM_PRECO_OFICIAL = CATALOGO[:10]  # os 2 últimos ficam de fora do preco_por_m

# Perfis de cliente (o "padrão escondido" que o agrupamento deve encontrar)
#   peso          participação na base de clientes
#   origens       como esse tipo de cliente costuma chegar até a empresa
#   frequencia    quantos orçamentos pede, em relação aos demais
#   mix           que serviços costuma pedir
#   imovel        tipo de imóvel
#   metragem      multiplicador da quantidade (m² ou metro linear)
#   ajuste_preco  multiplicador sobre o preço (negociação típica do perfil)
#   propensao     facilidade em fechar (escala logit)
#   sensib_preco  quanto o valor alto do orçamento reduz a chance de fechar
#   chance_desc   probabilidade de pedir/receber desconto
PERFIS = {
    "construtora": {
        "peso": 12,
        "origens": {"Google": 3, "Site": 3, "Cliente antigo": 3, "Indicação": 1},
        "frequencia": 5.0,
        "mix": {"Forro Drywall": 6, "Divisória Drywall": 6, "Gesso Liso": 2, "Sanca": 1},
        "imovel": {"comercial": 5, "industrial": 5},
        "metragem": 2.6,
        "ajuste_preco": 0.90,
        "propensao": 0.6,
        "sensib_preco": 0.1,
        "chance_desc": 0.45,
    },
    "alto_padrao": {
        "peso": 18,
        "origens": {"Indicação": 6, "Instagram": 2, "Cliente antigo": 2},
        "frequencia": 2.2,
        "mix": {"Sanca": 5, "Moldura de Gesso": 4, "Gesso 3D": 3, "Boiserie": 3, "Forro Drywall": 2},
        "imovel": {"residencial": 1},
        "metragem": 1.0,
        "ajuste_preco": 1.08,
        "propensao": 0.5,
        "sensib_preco": 0.1,
        "chance_desc": 0.10,
    },
    "residencial_economico": {
        "peso": 45,
        "origens": {"Instagram": 4, "Facebook": 4, "Panfleto": 2, "Google": 1},
        "frequencia": 1.0,
        "mix": {"Gesso Liso": 6, "Forro Drywall": 3, "Moldura de Gesso": 3, "Sanca": 1},
        "imovel": {"residencial": 1},
        "metragem": 0.7,
        "ajuste_preco": 0.97,
        "propensao": -0.4,
        "sensib_preco": 0.9,
        "chance_desc": 0.40,
    },
    "pequeno_comercio": {
        "peso": 25,
        "origens": {"Google": 4, "Site": 2, "Indicação": 2, "Facebook": 1},
        "frequencia": 1.6,
        "mix": {"Divisória Drywall": 5, "Forro Drywall": 5, "Sanca": 2, "Gesso Liso": 1},
        "imovel": {"comercial": 1},
        "metragem": 1.3,
        "ajuste_preco": 1.00,
        "propensao": 0.0,
        "sensib_preco": 0.4,
        "chance_desc": 0.25,
    },
}


# ---------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------
def random_date(d0: date, d1: date) -> date:
    delta = (d1 - d0).days
    return d0 + timedelta(days=random.randint(0, max(delta, 0)))


def fmt_date(d, alt_format: bool = False) -> str:
    if d is None:
        return ""
    return d.strftime("%d/%m/%Y") if alt_format else d.strftime("%Y-%m-%d")


def sortear(pesos: dict):
    """Sorteia uma chave de um dicionário {opção: peso}."""
    return random.choices(list(pesos), weights=list(pesos.values()), k=1)[0]


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


def fator_volume(quantidade: float, unidade: str) -> float:
    """Desconto progressivo por volume: até 10% em obras grandes."""
    inicio, fim = (10, 70) if unidade == "metro linear" else (20, 120)
    proporcao = min(1.0, max(0.0, (quantidade - inicio) / (fim - inicio)))
    return 1 - 0.10 * proporcao


def chance_fechar(perfil: dict, origem: str, visita: bool, prazo_dias: int,
                  desconto: float, valor_ref: float, ja_fechou_antes: bool) -> float:
    """Probabilidade de o orçamento ser aceito (regra escondida do simulador)."""
    logit = (
        perfil["propensao"]
        + EFEITO_ORIGEM[origem]
        + (0.9 if visita else 0.0)
        - 0.22 * prazo_dias
        + 0.05 * min(desconto, 10)
        - perfil["sensib_preco"] * 0.8 * math.log(max(valor_ref, 100) / 2500)
        + (0.6 if ja_fechou_antes else 0.0)
        - 0.6
    )
    return 1 / (1 + math.exp(-logit))


# ---------------------------------------------------------------------
# Geração de cada tabela
# ---------------------------------------------------------------------
def gerar_clientes(fake, n: int, data_inicio: date, data_fim: date):
    """Retorna (lista de clientes, gabarito {id_cliente: (perfil, id_original)})."""
    pesos_perfil = {nome: p["peso"] for nome, p in PERFIS.items()}
    clientes, gabarito = [], {}
    for i in range(1, n + 1):
        perfil = sortear(pesos_perfil)
        nome = fake.name()
        email = ""
        if random.random() > 0.12:  # ~12% sem e-mail
            base = nome.lower().split()
            email = f"{base[0]}.{base[-1]}{random.randint(1, 99)}@{random.choice(['gmail.com', 'hotmail.com', 'yahoo.com.br', 'outlook.com'])}"
        clientes.append({
            "id_cliente": i,
            "nome_completo": nome,
            "telefone": dirty_phone(fake) if random.random() > 0.03 else "",
            "email": email,
            "endereco": fake.street_address() if random.random() > 0.06 else "",
            "cidade": random.choice(CIDADES) if random.random() > 0.04 else "",
            "origem_contato": sortear(PERFIS[perfil]["origens"]),
            # provisório: ajustado depois para logo antes do 1º orçamento
            "data_cadastro": random_date(data_inicio - timedelta(days=180), data_fim),
        })
        gabarito[i] = (perfil, i)

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
            "data_cadastro": random_date(data_inicio, data_fim),
        })
        gabarito[novo_id] = (gabarito[original["id_cliente"]][0], original["id_cliente"])

    return clientes, gabarito


def gerar_preco_por_m() -> pd.DataFrame:
    precos = []
    for idx, (tipo, subtipo, unidade, valor) in enumerate(SERVICOS_COM_PRECO_OFICIAL, start=1):
        precos.append({
            "id_preco": idx,
            "tipo_servico": tipo,
            "subtipo": subtipo,
            "unidade_medida": unidade,
            "valor": valor,
            "data_atualizacao": fmt_date(random_date(date(2023, 6, 1), date(2024, 3, 1))),
        })
    return pd.DataFrame(precos)


def distribuir_orcamentos(clientes: list, gabarito: dict, n: int,
                          data_inicio: date, data_fim: date) -> list:
    """Decide QUEM pediu cada orçamento e QUANDO, em ordem cronológica.

    Todo cliente original pede ao menos 1 orçamento; o restante é
    distribuído conforme a frequência típica do perfil.
    """
    originais = [c for c in clientes if gabarito[c["id_cliente"]][1] == c["id_cliente"]]
    pedidos = [c["id_cliente"] for c in originais][:n]

    pesos = []
    for c in clientes:
        perfil, id_original = gabarito[c["id_cliente"]]
        peso = PERFIS[perfil]["frequencia"] * random.lognormvariate(0, 0.35)
        if id_original != c["id_cliente"]:
            peso *= 0.3  # o cadastro duplicado é usado de vez em quando
        pesos.append(peso)
    ids = [c["id_cliente"] for c in clientes]
    pedidos += random.choices(ids, weights=pesos, k=max(0, n - len(pedidos)))

    datas = [random_date(data_inicio, data_fim) for _ in pedidos]
    return sorted(zip(datas, pedidos))


def gerar_servicos(clientes: list, gabarito: dict, n: int,
                   data_inicio: date, data_fim: date) -> list:
    por_id = {c["id_cliente"]: c for c in clientes}
    catalogo_por_tipo = {}
    for tipo, subtipo, unidade, valor in CATALOGO:
        catalogo_por_tipo.setdefault(tipo, []).append((subtipo, unidade, valor))

    ja_fechou = set()  # clientes (pelo id original) que já fecharam algum serviço
    servicos = []
    for i, (data_orc, id_cliente) in enumerate(
            distribuir_orcamentos(clientes, gabarito, n, data_inicio, data_fim), start=1):
        cliente = por_id[id_cliente]
        nome_perfil, id_original = gabarito[id_cliente]
        perfil = PERFIS[nome_perfil]

        # --- o que foi pedido -------------------------------------------
        tipo = sortear(perfil["mix"])
        subtipo, unidade, valor_tabela = random.choice(catalogo_por_tipo[tipo])
        imovel = sortear(perfil["imovel"])
        base = random.uniform(3, 30) if unidade == "metro linear" else random.uniform(4, 60)
        quantidade = round(base * perfil["metragem"] * random.lognormvariate(0, 0.25), 2)

        # --- preço (regra escondida para a regressão) --------------------
        preco_cheio = (
            valor_tabela
            * FATOR_CIDADE.get(cliente["cidade"], 1.0)
            * fator_volume(quantidade, unidade)
            * perfil["ajuste_preco"]
            * (0.97 if imovel == "industrial" else 1.0)
            * random.gauss(1, 0.035)
        )
        desconto = 0
        if random.random() < perfil["chance_desc"]:
            desconto = random.choice([5, 5, 8, 10, 10, 12, 15, 20])
        valor_aplicado = round(preco_cheio * (1 - desconto / 100), 2)

        # --- processo comercial ------------------------------------------
        visita = random.random() < (0.75 if quantidade > 40 else 0.45)
        prazo_dias = min(10, int(random.expovariate(1 / 2.5)))
        data_envio = data_orc + timedelta(days=prazo_dias)
        p = chance_fechar(perfil, cliente["origem_contato"], visita, prazo_dias,
                          desconto, valor_tabela * quantidade, id_original in ja_fechou)

        data_exec = None
        if (data_fim - data_envio).days < 15:
            status = "orçado"  # ainda aguardando resposta do cliente
        elif random.random() < p:
            ja_fechou.add(id_original)
            data_exec = data_envio + timedelta(days=random.randint(5, 40))
            if data_exec > data_fim - timedelta(days=7):
                status = "em andamento"
            else:
                status = random.choices(["concluído", "Concluido", "CONCLUÍDO"], weights=[85, 10, 5])[0]
        else:
            status = random.choices(
                ["recusado", "Recusado", "RECUSADO", "sem resposta", "s/ resposta", "Sem retorno"],
                weights=[40, 10, 5, 30, 10, 5])[0]

        # --- sujeira proposital ------------------------------------------
        if random.random() < 0.01:
            quantidade = 0  # erro de digitação
        a_combinar = random.random() < 0.08  # preço "a combinar", não registrado
        valor_total = "" if (a_combinar or not quantidade) else round(quantidade * valor_aplicado, 2)
        unidade_txt = unidade
        if random.random() < 0.05:
            unidade_txt = {"metro linear": "m linear", "metro quadrado": "m2"}[unidade]
        tipo_txt = tipo.lower() if random.random() < 0.03 else tipo
        if desconto == 0:
            desconto_txt = random.choices(["0", ""], weights=[85, 15])[0]
        else:
            desconto_txt = f"{desconto}%" if random.random() < 0.6 else str(desconto)
        visita_txt = ("sim" if visita else "não") if random.random() > 0.06 else ("S" if visita else "N")
        imovel_txt = imovel if random.random() > 0.03 else ""

        ambiente = random.choice(AMBIENTES[imovel])
        descricoes = [
            f"Execução de {tipo.lower()} em {ambiente}.",
            f"Serviço de {tipo.lower()} solicitado para {ambiente}, imóvel {imovel}.",
            f"{tipo} - {ambiente}, conforme orçamento.",
        ]

        servicos.append({
            "id_servico": i,
            "id_cliente": id_cliente,
            "tipo_servico": tipo_txt,
            "subtipo": subtipo,
            "descricao_detalhada": random.choice(descricoes),
            "tipo_imovel": imovel_txt,
            "unidade_medida": unidade_txt,
            "quantidade": quantidade,
            "valor_unitario_aplicado": "" if a_combinar else valor_aplicado,
            "desconto_concedido": desconto_txt,
            "valor_total": valor_total,
            "data_orcamento": fmt_date(data_orc, alt_format=(random.random() < 0.03)),
            "prazo_retorno_dias": prazo_dias,
            "visita_tecnica": visita_txt,
            "data_execucao": fmt_date(data_exec, alt_format=(random.random() < 0.02)) if data_exec else "",
            "status": status,
        })

    # Data de cadastro do cliente = pouco antes do primeiro orçamento
    primeiro = {}
    for s in servicos:
        d = datetime.strptime(s["data_orcamento"], "%Y-%m-%d").date() \
            if "-" in s["data_orcamento"] else datetime.strptime(s["data_orcamento"], "%d/%m/%Y").date()
        primeiro[s["id_cliente"]] = min(primeiro.get(s["id_cliente"], d), d)
    for c in clientes:
        if c["id_cliente"] in primeiro:
            c["data_cadastro"] = primeiro[c["id_cliente"]] - timedelta(days=random.randint(0, 20))

    return servicos


def gerar_fotos(servicos: list, data_fim: date) -> pd.DataFrame:
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
                    data_up = data_fim  # data da foto perdida -> registrada no fechamento
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


def gerar_manutencoes(servicos: list, n: int, data_fim: date) -> pd.DataFrame:
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
        data_sol = random_date(data_origem, data_fim)

        r = random.random()
        if r < 0.6:
            status = "concluída"
            data_exec_str = fmt_date(random_date(data_sol, min(data_sol + timedelta(days=20), data_fim)))
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

    clientes, gabarito = gerar_clientes(fake, n_clientes, data_inicio, data_fim)
    df_precos = gerar_preco_por_m()
    servicos = gerar_servicos(clientes, gabarito, n_servicos, data_inicio, data_fim)
    for c in clientes:  # data de cadastro com ~3% no formato DD/MM/AAAA
        c["data_cadastro"] = fmt_date(c["data_cadastro"], alt_format=(random.random() < 0.03))
    df_clientes = pd.DataFrame(clientes)
    df_servicos = pd.DataFrame(servicos)
    df_fotos = gerar_fotos(servicos, data_fim)
    df_manutencoes = gerar_manutencoes(servicos, n_manutencoes, data_fim)
    df_gabarito = pd.DataFrame(
        [(i, perfil, original) for i, (perfil, original) in gabarito.items()],
        columns=["id_cliente", "perfil_real", "id_cliente_original"])

    os.makedirs(out_dir, exist_ok=True)
    df_clientes.to_csv(os.path.join(out_dir, "clientes.csv"), index=False, encoding="utf-8-sig")
    df_precos.to_csv(os.path.join(out_dir, "preco_por_m.csv"), index=False, encoding="utf-8-sig")
    df_servicos.to_csv(os.path.join(out_dir, "servicos.csv"), index=False, encoding="utf-8-sig")
    df_fotos.to_csv(os.path.join(out_dir, "fotos.csv"), index=False, encoding="utf-8-sig")
    df_manutencoes.to_csv(os.path.join(out_dir, "manutencoes.csv"), index=False, encoding="utf-8-sig")
    df_gabarito.to_csv(os.path.join(out_dir, "gabarito_perfis.csv"), index=False, encoding="utf-8-sig")

    print("Arquivos gerados em:", out_dir)
    print(f"  clientes.csv         {len(df_clientes):>6} linhas")
    print(f"  preco_por_m.csv      {len(df_precos):>6} linhas")
    print(f"  servicos.csv         {len(df_servicos):>6} linhas")
    print(f"  fotos.csv            {len(df_fotos):>6} linhas")
    print(f"  manutencoes.csv      {len(df_manutencoes):>6} linhas")
    print(f"  gabarito_perfis.csv  {len(df_gabarito):>6} linhas  (só para validação, não vai ao banco)")

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
        "fotos": df_fotos, "manutencoes": df_manutencoes, "gabarito": df_gabarito,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Simulador gerador de dados brutos - empresa de gesso e drywall.")
    parser.add_argument("--clientes", type=int, default=330, help="Quantidade de clientes a gerar.")
    parser.add_argument("--servicos", type=int, default=1600, help="Quantidade de orçamentos/serviços a gerar.")
    parser.add_argument("--manutencoes", type=int, default=190, help="Quantidade de manutenções a gerar.")
    parser.add_argument("--seed", type=int, default=42, help="Semente para reprodutibilidade.")
    parser.add_argument("--data-inicio", default="2024-01-01", help="Data inicial (AAAA-MM-DD).")
    # Data final fixa: com "hoje" como padrão, a mesma seed geraria dados
    # diferentes a cada dia e os resultados dos modelos mudariam.
    parser.add_argument("--data-fim", default="2026-09-30", help="Data final (AAAA-MM-DD).")
    parser.add_argument("--out-dir", default="dados/raw", help="Pasta de saída dos CSVs.")
    args = parser.parse_args()

    data_inicio = datetime.strptime(args.data_inicio, "%Y-%m-%d").date()
    data_fim = datetime.strptime(args.data_fim, "%Y-%m-%d").date()

    gerar_tudo(args.clientes, args.servicos, args.manutencoes, args.seed,
               data_inicio, data_fim, args.out_dir)


if __name__ == "__main__":
    main()
