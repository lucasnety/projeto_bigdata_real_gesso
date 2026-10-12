#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preparar_dados.py

Atividade de Aprendizado de Máquina - Preparação dos dados

Lê os dados brutos (do Postgres, ou dos CSVs em dados/raw como plano B),
trata as inconsistências injetadas pelo simulador e monta as duas bases
usadas pelos modelos:

    dados/processed/orcamentos.csv  - 1 linha por orçamento (classificação
                                      e regressão)
    dados/processed/clientes.csv    - 1 linha por cliente, já sem
                                      duplicados (agrupamento)

    gerador_dados.py -> Postgres -> preparar_dados.py -> notebooks/

Uso:
    python scripts/preparar_dados.py
    python scripts/preparar_dados.py --fonte csv --dados-dir dados/raw
"""

import argparse
import os
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
DIR_RAW = RAIZ / "dados" / "raw"
DIR_PROCESSED = RAIZ / "dados" / "processed"

TABELAS = ["clientes", "servicos", "preco_por_m", "fotos", "manutencoes"]

TIPOS_SERVICO = [
    "Sanca", "Divisória Drywall", "Forro Drywall", "Gesso Liso",
    "Moldura de Gesso", "Gesso 3D", "Boiserie",
]
GRUPO_SERVICO = {
    "Forro Drywall": "drywall", "Divisória Drywall": "drywall",
    "Sanca": "decorativo", "Moldura de Gesso": "decorativo",
    "Gesso 3D": "decorativo", "Boiserie": "decorativo",
    "Gesso Liso": "gesso_liso",
}

# Palavras da descrição que revelam o tipo de imóvel (usadas para
# preencher tipo_imovel quando ele veio em branco)
PISTAS_IMOVEL = {
    "residencial": ["residencial", "sala de estar", "quarto", "cozinha", "corredor", "área externa"],
    "comercial": ["comercial", "loja", "escritório"],
    "industrial": ["industrial", "galpão", "produção", "fábrica"],
}

STATUS_FECHADO = {"concluído", "em andamento"}
STATUS_PERDIDO = {"recusado", "sem resposta"}


# ---------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------
def carregar_brutos(fonte: str = "auto", dados_dir: Path = DIR_RAW) -> dict:
    """Lê as tabelas brutas do Postgres (DATABASE_URL) ou dos CSVs.

    fonte="auto" tenta o banco e, se ele não estiver no ar, usa os CSVs -
    assim os notebooks rodam mesmo sem o Docker ligado.
    """
    if fonte in ("auto", "postgres"):
        try:
            from dotenv import load_dotenv
            from sqlalchemy import create_engine

            load_dotenv(RAIZ / ".env")
            engine = create_engine(os.environ["DATABASE_URL"])
            with engine.connect() as conn:
                dados = {t: pd.read_sql_table(t, conn) for t in TABELAS}
            print(f"Dados brutos lidos do Postgres ({engine.url.database}).")
            return dados
        except Exception as erro:  # banco fora do ar, sem .env, etc.
            if fonte == "postgres":
                raise
            print(f"Postgres indisponível ({type(erro).__name__}); lendo os CSVs brutos.")

    dados = {t: pd.read_csv(Path(dados_dir) / f"{t}.csv", encoding="utf-8-sig") for t in TABELAS}
    print(f"Dados brutos lidos dos CSVs ({Path(dados_dir).name}/).")
    return dados


# ---------------------------------------------------------------------
# Funções de padronização
# ---------------------------------------------------------------------
def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def chave_texto(serie: pd.Series) -> pd.Series:
    """minúsculas, sem acento e sem espaços repetidos - para comparar textos."""
    return (serie.fillna("").astype(str)
            .map(sem_acento).str.lower()
            .str.replace(r"\s+", " ", regex=True).str.strip())


def parse_datas(serie: pd.Series) -> pd.Series:
    """Aceita AAAA-MM-DD e DD/MM/AAAA misturados na mesma coluna."""
    texto = serie.astype("string")
    iso = pd.to_datetime(texto, format="%Y-%m-%d", errors="coerce")
    br = pd.to_datetime(texto, format="%d/%m/%Y", errors="coerce")
    return iso.fillna(br)


def padronizar_telefone(valor) -> str:
    """Formata como (DD) 9XXXX-XXXX; números sem o 9º dígito recebem o 9."""
    digitos = re.sub(r"\D", "", str(valor)) if pd.notna(valor) else ""
    if digitos.startswith("55") and len(digitos) > 11:
        digitos = digitos[2:]
    if len(digitos) == 10:  # DDD + 8 dígitos (celular antigo, sem o 9)
        digitos = digitos[:2] + "9" + digitos[2:]
    if len(digitos) != 11:
        return ""
    return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"


def padronizar_status(serie: pd.Series) -> pd.Series:
    chave = chave_texto(serie)
    mapa = [
        ("conclu", "concluído"), ("em andamento", "em andamento"), ("orcado", "orçado"),
        ("recusado", "recusado"), ("sem resposta", "sem resposta"),
        ("s/ resposta", "sem resposta"), ("sem retorno", "sem resposta"),
    ]
    resultado = pd.Series(pd.NA, index=serie.index, dtype="object")
    for prefixo, valor in mapa:
        resultado[chave.str.startswith(prefixo) & resultado.isna()] = valor
    return resultado


def padronizar_tipo_servico(serie: pd.Series) -> pd.Series:
    canonico = {sem_acento(t).lower(): t for t in TIPOS_SERVICO}
    return chave_texto(serie).map(canonico)


def inferir_imovel(descricao: str):
    texto = str(descricao).lower()
    for imovel, pistas in PISTAS_IMOVEL.items():
        if any(p in texto for p in pistas):
            return imovel
    return np.nan


# ---------------------------------------------------------------------
# Limpeza das tabelas
# ---------------------------------------------------------------------
def limpar_clientes(clientes: pd.DataFrame):
    """Padroniza o cadastro e une clientes duplicados.

    Duplicado = mesmo nome (ignorando acentos/espaços) + mesmo e-mail, ou
    mesmo nome + mesmo endereço quando não há e-mail. O cadastro mais
    antigo (menor id) é mantido como o "oficial".

    Retorna (clientes_limpos, mapa {id_cliente -> id_cliente_oficial}).
    """
    df = clientes.copy()
    df["nome_completo"] = df["nome_completo"].str.replace(r"\s+", " ", regex=True).str.strip()
    df["telefone"] = df["telefone"].map(padronizar_telefone)
    df["cidade"] = df["cidade"].fillna("").replace("", "Não informada")
    df["data_cadastro"] = parse_datas(df["data_cadastro"])

    nome = chave_texto(df["nome_completo"])
    email = chave_texto(df["email"])
    endereco = chave_texto(df["endereco"])
    contato = email.where(email != "", "end:" + endereco)
    grupo = nome + "|" + contato
    df["id_cliente_oficial"] = df.groupby(grupo)["id_cliente"].transform("min")

    mapa = dict(zip(df["id_cliente"], df["id_cliente_oficial"]))
    oficiais = (df.sort_values("id_cliente")
                  .groupby("id_cliente_oficial", as_index=False)
                  .agg(nome_completo=("nome_completo", "first"),
                       telefone=("telefone", lambda s: next((t for t in s if t), "")),
                       email=("email", "first"),
                       cidade=("cidade", "first"),
                       origem_contato=("origem_contato", "first"),
                       data_cadastro=("data_cadastro", "min"))
                  .rename(columns={"id_cliente_oficial": "id_cliente"}))
    return oficiais, mapa


def limpar_servicos(servicos: pd.DataFrame, precos: pd.DataFrame, mapa_clientes: dict) -> pd.DataFrame:
    df = servicos.copy()
    df["id_cliente"] = df["id_cliente"].map(mapa_clientes)
    df["tipo_servico"] = padronizar_tipo_servico(df["tipo_servico"])
    df["subtipo"] = df["subtipo"].fillna("")
    df["grupo_servico"] = df["tipo_servico"].map(GRUPO_SERVICO)
    df["unidade_medida"] = chave_texto(df["unidade_medida"]).replace(
        {"m2": "metro quadrado", "m linear": "metro linear"})

    imovel = chave_texto(df["tipo_imovel"]).replace("", np.nan)
    df["tipo_imovel"] = imovel.fillna(df["descricao_detalhada"].map(inferir_imovel))

    df["status"] = padronizar_status(df["status"])
    df["situacao"] = np.select(
        [df["status"].isin(STATUS_FECHADO), df["status"].isin(STATUS_PERDIDO)],
        ["fechado", "perdido"], default="pendente")
    df["fechou"] = df["situacao"].map({"fechado": 1, "perdido": 0})  # NaN = pendente

    df["data_orcamento"] = parse_datas(df["data_orcamento"])
    df["data_execucao"] = parse_datas(df["data_execucao"])

    df["visita_tecnica"] = chave_texto(df["visita_tecnica"]).map(
        {"sim": 1, "s": 1, "nao": 0, "n": 0})
    df["desconto_pct"] = pd.to_numeric(
        df["desconto_concedido"].astype("string").str.replace("%", "").str.strip(),
        errors="coerce").fillna(0)

    df["quantidade"] = pd.to_numeric(df["quantidade"], errors="coerce").replace(0, np.nan)
    df["valor_unitario_aplicado"] = pd.to_numeric(df["valor_unitario_aplicado"], errors="coerce")
    df["preco_a_combinar"] = df["valor_unitario_aplicado"].isna().astype(int)
    # preço cheio = preço antes do desconto concedido (alvo da regressão)
    df["preco_cheio"] = (df["valor_unitario_aplicado"] / (1 - df["desconto_pct"] / 100)).round(2)
    df["valor_total"] = (df["quantidade"] * df["valor_unitario_aplicado"]).round(2)

    # Preço de tabela. Gesso 3D e Boiserie não estão na tabela oficial:
    # usa-se a mediana do preço cheio praticado como referência.
    tabela = precos.assign(subtipo=precos["subtipo"].fillna(""))
    tabela = tabela.set_index(["tipo_servico", "subtipo"])["valor"]
    df["valor_tabela"] = [tabela.get((t, s), np.nan) for t, s in zip(df["tipo_servico"], df["subtipo"])]
    df["tabela_oficial"] = df["valor_tabela"].notna().astype(int)
    mediana = df.groupby("tipo_servico")["preco_cheio"].transform("median")
    df["valor_tabela"] = df["valor_tabela"].fillna(mediana).round(2)
    df["valor_referencia"] = (df["quantidade"] * df["valor_tabela"]).round(2)
    return df


# ---------------------------------------------------------------------
# Bases para os modelos
# ---------------------------------------------------------------------
def montar_orcamentos(servicos: pd.DataFrame, clientes: pd.DataFrame) -> pd.DataFrame:
    """Base com 1 linha por orçamento + histórico do cliente até aquela data."""
    df = servicos.merge(clientes[["id_cliente", "cidade", "origem_contato"]], on="id_cliente", how="left")
    df = df.sort_values(["id_cliente", "data_orcamento", "id_servico"]).reset_index(drop=True)
    grupo = df.groupby("id_cliente")
    df["n_orcamentos_anteriores"] = grupo.cumcount()
    df["n_fechados_anteriores"] = grupo["fechou"].transform(
        lambda s: s.fillna(0).cumsum().shift(fill_value=0)).astype(int)
    df["cliente_recorrente"] = (df["n_fechados_anteriores"] > 0).astype(int)
    df["mes_orcamento"] = df["data_orcamento"].dt.month

    colunas = [
        "id_servico", "id_cliente", "data_orcamento", "mes_orcamento", "cidade", "origem_contato",
        "tipo_servico", "subtipo", "grupo_servico", "tipo_imovel", "unidade_medida",
        "quantidade", "valor_tabela", "tabela_oficial", "valor_referencia",
        "valor_unitario_aplicado", "preco_cheio", "desconto_pct", "preco_a_combinar", "valor_total",
        "prazo_retorno_dias", "visita_tecnica", "n_orcamentos_anteriores",
        "n_fechados_anteriores", "cliente_recorrente", "data_execucao", "status", "situacao", "fechou",
    ]
    return df[colunas].sort_values("id_servico").reset_index(drop=True)


def montar_clientes(orcamentos: pd.DataFrame, clientes: pd.DataFrame) -> pd.DataFrame:
    """Base com 1 linha por cliente: comportamento de compra (para o agrupamento)."""
    data_ref = orcamentos["data_orcamento"].max()
    o = orcamentos.assign(
        drywall=(orcamentos["grupo_servico"] == "drywall").astype(int),
        decorativo=(orcamentos["grupo_servico"] == "decorativo").astype(int),
        gesso_liso=(orcamentos["grupo_servico"] == "gesso_liso").astype(int),
        residencial=(orcamentos["tipo_imovel"] == "residencial").astype(int),
        valor_fechado=orcamentos["valor_total"].where(orcamentos["fechou"] == 1),
    )
    base = o.groupby("id_cliente").agg(
        n_orcamentos=("id_servico", "size"),
        n_fechados=("fechou", "sum"),
        n_decididos=("fechou", "count"),
        ticket_medio=("valor_referencia", "median"),
        faturamento_total=("valor_fechado", "sum"),
        pct_drywall=("drywall", "mean"),
        pct_decorativo=("decorativo", "mean"),
        pct_gesso_liso=("gesso_liso", "mean"),
        pct_residencial=("residencial", "mean"),
        desconto_medio=("desconto_pct", "mean"),
        ultimo_orcamento=("data_orcamento", "max"),
    ).reset_index()
    base["n_fechados"] = base["n_fechados"].astype(int)
    base["taxa_conversao"] = (base["n_fechados"] / base["n_decididos"]).fillna(0)
    base["recencia_dias"] = (data_ref - base["ultimo_orcamento"]).dt.days
    base = base.drop(columns=["n_decididos", "ultimo_orcamento"])
    return clientes.merge(base, on="id_cliente", how="inner")


def relatorio_qualidade(brutos: dict, clientes: pd.DataFrame, orcamentos: pd.DataFrame) -> pd.DataFrame:
    """Resumo do que foi encontrado e tratado - vai para o notebook."""
    s, c = brutos["servicos"], brutos["clientes"]
    vazio = lambda serie: serie.isna() | (serie.astype("string").str.strip() == "")
    linhas = [
        ("Clientes duplicados unidos", len(c) - len(clientes)),
        ("Telefones em formatos diferentes padronizados", int((~vazio(c["telefone"])).sum())),
        ("Clientes sem cidade", int(vazio(c["cidade"]).sum())),
        ("Grafias de status diferentes", f"{s['status'].nunique()} -> {orcamentos['status'].nunique()}"),
        ("Tipos de serviço com grafia errada", int((s["tipo_servico"] != padronizar_tipo_servico(s["tipo_servico"])).sum())),
        ("Unidades abreviadas (m2 / m linear)", int(s["unidade_medida"].isin(["m2", "m linear"]).sum())),
        ("Datas de orçamento em DD/MM/AAAA", int(s["data_orcamento"].astype("string").str.contains("/").sum())),
        ("Desconto escrito com '%'", int(s["desconto_concedido"].astype("string").str.contains("%").sum())),
        ("Tipo de imóvel em branco (inferido pela descrição)", int(vazio(s["tipo_imovel"]).sum())),
        ("Quantidade = 0 (erro de digitação -> ausente)", int((pd.to_numeric(s["quantidade"]) == 0).sum())),
        ("Preço 'a combinar' (sem valor)", int(orcamentos["preco_a_combinar"].sum())),
        ("Serviços sem preço na tabela oficial", int((orcamentos["tabela_oficial"] == 0).sum())),
    ]
    return pd.DataFrame(linhas, columns=["Problema", "Ocorrências"])


def preparar(fonte: str = "auto", dados_dir: Path = DIR_RAW, salvar: bool = True) -> dict:
    brutos = carregar_brutos(fonte, dados_dir)
    clientes, mapa = limpar_clientes(brutos["clientes"])
    servicos = limpar_servicos(brutos["servicos"], brutos["preco_por_m"], mapa)
    orcamentos = montar_orcamentos(servicos, clientes)
    base_clientes = montar_clientes(orcamentos, clientes)
    qualidade = relatorio_qualidade(brutos, clientes, orcamentos)

    if salvar:
        DIR_PROCESSED.mkdir(parents=True, exist_ok=True)
        orcamentos.to_csv(DIR_PROCESSED / "orcamentos.csv", index=False)
        base_clientes.to_csv(DIR_PROCESSED / "clientes.csv", index=False)
        pd.Series(mapa, name="id_cliente_oficial").rename_axis("id_cliente").to_csv(
            DIR_PROCESSED / "mapa_clientes_duplicados.csv")
        print(f"Bases salvas em {DIR_PROCESSED.relative_to(RAIZ)}/: {len(orcamentos)} orçamentos, "
              f"{len(base_clientes)} clientes.")

    return {"brutos": brutos, "orcamentos": orcamentos, "clientes": base_clientes,
            "mapa_clientes": mapa, "qualidade": qualidade}


def ler_processados() -> dict:
    """Atalho para os notebooks: lê as bases já preparadas."""
    datas = ["data_orcamento", "data_execucao"]
    return {
        "orcamentos": pd.read_csv(DIR_PROCESSED / "orcamentos.csv", parse_dates=datas),
        "clientes": pd.read_csv(DIR_PROCESSED / "clientes.csv", parse_dates=["data_cadastro"]),
    }


def main():
    parser = argparse.ArgumentParser(description="Limpa os dados brutos e monta as bases dos modelos.")
    parser.add_argument("--fonte", choices=["auto", "postgres", "csv"], default="auto")
    parser.add_argument("--dados-dir", default=str(DIR_RAW), help="Pasta dos CSVs brutos (fonte csv).")
    args = parser.parse_args()
    resultado = preparar(args.fonte, Path(args.dados_dir))
    print("\n" + resultado["qualidade"].to_string(index=False))


if __name__ == "__main__":
    main()
