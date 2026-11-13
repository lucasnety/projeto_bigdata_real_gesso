#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api/main.py

Integração da Interface com a API (Projeto de Extensão - Real Gesso)

API REST (FastAPI) que expõe os dados do Postgres provisionado pelo
docker-compose (mesmo banco carregado por scripts/carregar_dados.py) e
serve também o front-end que está em frontend/.

    navegador (frontend/)  --fetch-->  API (/api/...)  --SQL-->  Postgres

Uso (a partir da raiz do projeto, com o banco no ar - make up):
    .venv/bin/uvicorn api.main:app --reload --port 8000
    # ou: make api
Depois abra http://localhost:8000  (documentação automática: /docs)
"""

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import create_engine, text

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não encontrada. Copie .env.example para .env.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Onde ler o resultado do job Hadoop (WebHDFS do NameNode)
HDFS_URL = os.getenv("HDFS_URL", "http://localhost:9870")
HADOOP_SAIDA = os.getenv("HADOOP_SAIDA", "/real_gesso/saida")

app = FastAPI(
    title="API Real Gesso",
    description="API do projeto de extensão (empresa de gesso e drywall).",
    version="1.0.0",
)

# ---------------------------------------------------------------------
# Listas de valores aceitos (mesmos usados pelo simulador de dados)
# ---------------------------------------------------------------------
CIDADES = [
    "São João da Boa Vista", "Aguaí", "Vargem Grande do Sul", "Mococa",
    "Casa Branca", "São José do Rio Pardo", "Espírito Santo do Pinhal",
    "Poços de Caldas", "Águas da Prata", "Itobi",
]
ORIGENS = ["Indicação", "Instagram", "Facebook", "Google", "Site", "Panfleto", "Cliente antigo"]
UNIDADES = ["metro linear", "metro quadrado"]
STATUS_SERVICO = ["orçado", "em andamento", "concluído", "cancelado"]
STATUS_MANUTENCAO = ["solicitada", "agendada", "concluída"]
# Serviços vendidos pela empresa que não têm preço oficial em preco_por_m
TIPOS_SEM_PRECO_OFICIAL = [
    {"tipo_servico": "Gesso 3D", "subtipo": "", "unidade_medida": "metro quadrado"},
    {"tipo_servico": "Boiserie", "subtipo": "", "unidade_medida": "metro linear"},
]

# Os dados brutos têm o mesmo status escrito de formas diferentes
# ("concluído", "CONCLUÍDO", "Concluido"). Esta expressão SQL padroniza
# para que filtros e contagens tratem todos como "concluído".
SQL_STATUS_SERVICO = (
    "CASE WHEN translate(lower(s.status), 'í', 'i') = 'concluido' THEN 'concluído' "
    "ELSE lower(s.status) END"
)

RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def _texto_limpo(v):
    """Remove espaços extras; string vazia vira None."""
    if v is None:
        return None
    v = re.sub(r"\s+", " ", str(v)).strip()
    return v or None


def _data(v: Optional[str], campo: str) -> Optional[str]:
    if v is None:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError(f"{campo} inválida. Use o formato AAAA-MM-DD.")


# ---------------------------------------------------------------------
# Respostas de erro padronizadas (em português) para o front-end
# ---------------------------------------------------------------------
MENSAGENS_PYDANTIC = {
    "missing": "Campo obrigatório.",
    # campos de texto/número que chegam vazios (null) após a limpeza
    "string_type": "Campo obrigatório.",
    "int_type": "Campo obrigatório.",
    "float_type": "Campo obrigatório.",
    "int_parsing": "Informe um número inteiro.",
    "float_parsing": "Informe um número válido.",
}


@app.exception_handler(RequestValidationError)
async def erro_validacao(request: Request, exc: RequestValidationError):
    erros = {}
    for e in exc.errors():
        campo = str(e["loc"][-1]) if e["loc"] and e["loc"][-1] != "body" else "geral"
        msg = MENSAGENS_PYDANTIC.get(e["type"], e["msg"])
        erros[campo] = msg.removeprefix("Value error, ")
    return JSONResponse(
        status_code=422,
        content={"detail": "Existem campos inválidos. Corrija e tente novamente.", "erros": erros},
    )


def erro_campo(campo: str, mensagem: str, status: int = 422):
    """Erro de validação que depende do banco (ex.: cliente inexistente)."""
    raise HTTPException(status_code=status, detail={"detail": mensagem, "erros": {campo: mensagem}})


@app.exception_handler(HTTPException)
async def erro_http(request: Request, exc: HTTPException):
    corpo = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
    return JSONResponse(status_code=exc.status_code, content=corpo)


def paginar(pagina: int, por_pagina: int):
    return {"limite": por_pagina, "offset": (pagina - 1) * por_pagina}


# =====================================================================
# Painel e tabelas auxiliares
# =====================================================================
@app.get("/api/resumo", tags=["Painel"])
def resumo():
    """Indicadores gerais usados no painel do front-end."""
    with engine.connect() as conn:
        totais = conn.execute(text(f"""
            SELECT
              (SELECT COUNT(*) FROM clientes)                         AS clientes,
              (SELECT COUNT(*) FROM servicos)                         AS servicos,
              (SELECT COUNT(*) FROM manutencoes)                      AS manutencoes,
              (SELECT COALESCE(SUM(valor_total), 0) FROM servicos s
                 WHERE {SQL_STATUS_SERVICO} = 'concluído')            AS faturamento,
              (SELECT COUNT(*) FROM manutencoes
                 WHERE status <> 'concluída')                         AS manutencoes_abertas
        """)).mappings().one()
        por_tipo = conn.execute(text("""
            -- agrupa grafias diferentes ("sanca" / "Sanca") e exibe a mais comum
            SELECT mode() WITHIN GROUP (ORDER BY tipo_servico) AS tipo, COUNT(*) AS quantidade,
                   COALESCE(SUM(valor_total), 0) AS valor
            FROM servicos GROUP BY lower(tipo_servico) ORDER BY quantidade DESC
        """)).mappings().all()
        por_status = conn.execute(text(f"""
            SELECT {SQL_STATUS_SERVICO} AS status, COUNT(*) AS quantidade
            FROM servicos s GROUP BY 1 ORDER BY quantidade DESC
        """)).mappings().all()
    return {
        "totais": {k: float(v) if k == "faturamento" else v for k, v in totais.items()},
        "por_tipo": [{**r, "valor": float(r["valor"])} for r in por_tipo],
        "por_status": [dict(r) for r in por_status],
    }


@app.get("/api/hadoop/servicos-por-tipo", tags=["Painel"])
def hadoop_servicos_por_tipo():
    """
    Resultado do job Hadoop Streaming (scripts/hadoop/mapper.py + reducer.py),
    lido direto do HDFS pela WebHDFS (API HTTP do próprio Hadoop).
    O job precisa ter sido executado antes (make hadoop).
    """
    base = f"{HDFS_URL}/webhdfs/v1{HADOOP_SAIDA}"
    try:
        with urlopen(f"{base}?op=LISTSTATUS", timeout=5) as r:
            arquivos = json.load(r)["FileStatuses"]["FileStatus"]
    except HTTPError as e:
        if e.code == 404:
            raise HTTPException(404, f"O job do Hadoop ainda não foi executado ({HADOOP_SAIDA} não existe). Rode: make hadoop")
        raise HTTPException(503, f"Erro ao consultar o HDFS: {e}")
    except (URLError, OSError):
        raise HTTPException(503, "Hadoop (HDFS) fora do ar. Ligue os serviços do Hadoop e tente de novo.")

    partes = [a for a in arquivos if a["pathSuffix"].startswith("part-")]
    if not partes:
        raise HTTPException(404, "O resultado do Hadoop está vazio. Rode: make hadoop")

    itens = []
    for parte in partes:
        # op=OPEN redireciona para o DataNode que guarda o bloco; urlopen segue sozinho
        with urlopen(f"{base}/{parte['pathSuffix']}?op=OPEN", timeout=10) as r:
            for linha in r.read().decode("utf-8").splitlines():
                if "\t" in linha:
                    tipo, qtd = linha.rsplit("\t", 1)
                    itens.append({"tipo": tipo, "quantidade": int(qtd)})

    itens.sort(key=lambda x: x["quantidade"], reverse=True)
    gerado_em = max(p["modificationTime"] for p in partes) / 1000  # epoch em ms -> s
    return {
        "fonte": f"HDFS {HADOOP_SAIDA}",
        "gerado_em": datetime.fromtimestamp(gerado_em, tz=timezone.utc).isoformat(),
        "total": sum(i["quantidade"] for i in itens),
        "itens": itens,
    }


@app.get("/api/precos", tags=["Tabelas auxiliares"])
def listar_precos():
    """Tabela oficial de preços (preco_por_m)."""
    with engine.connect() as conn:
        linhas = conn.execute(text(
            "SELECT id_preco, tipo_servico, subtipo, unidade_medida, valor, data_atualizacao "
            "FROM preco_por_m ORDER BY tipo_servico, valor"
        )).mappings().all()
    return [{**r, "valor": float(r["valor"])} for r in linhas]


@app.get("/api/opcoes", tags=["Tabelas auxiliares"])
def opcoes():
    """Valores aceitos nos formulários (para montar os campos de seleção)."""
    return {
        "cidades": CIDADES,
        "origens": ORIGENS,
        "unidades": UNIDADES,
        "status_servico": STATUS_SERVICO,
        "status_manutencao": STATUS_MANUTENCAO,
        "tipos_sem_preco_oficial": TIPOS_SEM_PRECO_OFICIAL,
    }


# =====================================================================
# Clientes
# =====================================================================
class ClienteEntrada(BaseModel):
    nome_completo: str
    telefone: Optional[str] = None
    email: Optional[str] = None
    endereco: Optional[str] = None
    cidade: Optional[str] = None
    origem_contato: Optional[str] = None

    @field_validator("nome_completo", "telefone", "email", "endereco", "cidade", "origem_contato", mode="before")
    @classmethod
    def limpar(cls, v):
        return _texto_limpo(v)

    @field_validator("nome_completo")
    @classmethod
    def validar_nome(cls, v):
        if not v:
            raise ValueError("Informe o nome do cliente.")
        if len(v) > 150:
            raise ValueError("O nome pode ter no máximo 150 caracteres.")
        if len(v.split(" ")) < 2:
            raise ValueError("Informe nome e sobrenome.")
        return v

    @field_validator("telefone")
    @classmethod
    def validar_telefone(cls, v):
        if v is None:
            return v
        digitos = re.sub(r"\D", "", v)
        if digitos.startswith("55") and len(digitos) in (12, 13):
            digitos = digitos[2:]
        if len(digitos) not in (10, 11):
            raise ValueError("Telefone inválido. Use DDD + número, ex.: (19) 99999-9999.")
        # Padroniza no formato (DD) 9XXXX-XXXX
        return f"({digitos[:2]}) {digitos[2:-4]}-{digitos[-4:]}"

    @field_validator("email")
    @classmethod
    def validar_email(cls, v):
        if v is not None and (len(v) > 100 or not RE_EMAIL.match(v)):
            raise ValueError("E-mail inválido.")
        return v.lower() if v else v

    @field_validator("endereco")
    @classmethod
    def validar_endereco(cls, v):
        if v is not None and len(v) > 200:
            raise ValueError("O endereço pode ter no máximo 200 caracteres.")
        return v

    @field_validator("cidade")
    @classmethod
    def validar_cidade(cls, v):
        if v is not None and v not in CIDADES:
            raise ValueError("Cidade fora da área de atendimento.")
        return v

    @field_validator("origem_contato")
    @classmethod
    def validar_origem(cls, v):
        if v is not None and v not in ORIGENS:
            raise ValueError("Origem de contato inválida.")
        return v

    @model_validator(mode="after")
    def exigir_contato(self):
        if not self.telefone and not self.email:
            raise ValueError("Informe pelo menos um contato: telefone ou e-mail.")
        return self


COLUNAS_CLIENTE = "id_cliente, nome_completo, telefone, email, endereco, cidade, origem_contato, data_cadastro"


def _buscar_cliente(conn, id_cliente: int):
    linha = conn.execute(
        text(f"SELECT {COLUNAS_CLIENTE} FROM clientes WHERE id_cliente = :id"), {"id": id_cliente}
    ).mappings().first()
    if not linha:
        raise HTTPException(404, f"Cliente {id_cliente} não encontrado.")
    return dict(linha)


@app.get("/api/clientes", tags=["Clientes"])
def listar_clientes(
    busca: Optional[str] = Query(None, description="Parte do nome, e-mail ou telefone"),
    cidade: Optional[str] = None,
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=500),
):
    filtros, params = [], paginar(pagina, por_pagina)
    if busca:
        filtros.append("(nome_completo ILIKE :busca OR email ILIKE :busca OR telefone ILIKE :busca)")
        params["busca"] = f"%{busca.strip()}%"
    if cidade:
        filtros.append("cidade = :cidade")
        params["cidade"] = cidade
    where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM clientes {where}"), params).scalar_one()
        itens = conn.execute(text(f"""
            SELECT {COLUNAS_CLIENTE},
                   (SELECT COUNT(*) FROM servicos s WHERE s.id_cliente = c.id_cliente) AS qtd_servicos
            FROM clientes c {where}
            ORDER BY id_cliente DESC LIMIT :limite OFFSET :offset
        """), params).mappings().all()
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": [dict(r) for r in itens]}


@app.get("/api/clientes/{id_cliente}", tags=["Clientes"])
def obter_cliente(id_cliente: int):
    with engine.connect() as conn:
        return _buscar_cliente(conn, id_cliente)


@app.post("/api/clientes", status_code=201, tags=["Clientes"])
def criar_cliente(dados: ClienteEntrada):
    with engine.begin() as conn:
        if dados.email and conn.execute(
            text("SELECT 1 FROM clientes WHERE lower(email) = :e"), {"e": dados.email}
        ).first():
            erro_campo("email", "Já existe um cliente com este e-mail.", 409)
        novo_id = conn.execute(text("""
            INSERT INTO clientes (nome_completo, telefone, email, endereco, cidade, origem_contato, data_cadastro)
            VALUES (:nome_completo, :telefone, :email, :endereco, :cidade, :origem_contato, :data_cadastro)
            RETURNING id_cliente
        """), {**dados.model_dump(), "data_cadastro": date.today().isoformat()}).scalar_one()
        return _buscar_cliente(conn, novo_id)


@app.put("/api/clientes/{id_cliente}", tags=["Clientes"])
def atualizar_cliente(id_cliente: int, dados: ClienteEntrada):
    with engine.begin() as conn:
        _buscar_cliente(conn, id_cliente)
        if dados.email and conn.execute(
            text("SELECT 1 FROM clientes WHERE lower(email) = :e AND id_cliente <> :id"),
            {"e": dados.email, "id": id_cliente},
        ).first():
            erro_campo("email", "Já existe outro cliente com este e-mail.", 409)
        conn.execute(text("""
            UPDATE clientes SET nome_completo = :nome_completo, telefone = :telefone, email = :email,
                   endereco = :endereco, cidade = :cidade, origem_contato = :origem_contato
            WHERE id_cliente = :id
        """), {**dados.model_dump(), "id": id_cliente})
        return _buscar_cliente(conn, id_cliente)


@app.delete("/api/clientes/{id_cliente}", tags=["Clientes"])
def excluir_cliente(id_cliente: int):
    with engine.begin() as conn:
        _buscar_cliente(conn, id_cliente)
        vinculos = conn.execute(text("""
            SELECT (SELECT COUNT(*) FROM servicos WHERE id_cliente = :id) AS servicos,
                   (SELECT COUNT(*) FROM manutencoes WHERE id_cliente = :id) AS manutencoes
        """), {"id": id_cliente}).mappings().one()
        if vinculos["servicos"] or vinculos["manutencoes"]:
            raise HTTPException(409, (
                f"Não é possível excluir: o cliente tem {vinculos['servicos']} serviço(s) e "
                f"{vinculos['manutencoes']} manutenção(ões) registrados."
            ))
        conn.execute(text("DELETE FROM clientes WHERE id_cliente = :id"), {"id": id_cliente})
    return {"detail": f"Cliente {id_cliente} excluído."}


# =====================================================================
# Serviços
# =====================================================================
class ServicoEntrada(BaseModel):
    id_cliente: int
    tipo_servico: str
    subtipo: Optional[str] = ""
    descricao_detalhada: Optional[str] = None
    unidade_medida: str
    quantidade: float
    valor_unitario_aplicado: Optional[float] = None  # vazio = usa a tabela oficial
    data_execucao: str
    status: str

    @field_validator("tipo_servico", "subtipo", "descricao_detalhada", "unidade_medida", "status", mode="before")
    @classmethod
    def limpar(cls, v):
        return _texto_limpo(v)

    @field_validator("tipo_servico")
    @classmethod
    def validar_tipo(cls, v):
        if not v:
            raise ValueError("Selecione o tipo de serviço.")
        return v

    @field_validator("subtipo")
    @classmethod
    def validar_subtipo(cls, v):
        return v or ""

    @field_validator("unidade_medida")
    @classmethod
    def validar_unidade(cls, v):
        if v not in UNIDADES:
            raise ValueError("Unidade deve ser 'metro linear' ou 'metro quadrado'.")
        return v

    @field_validator("quantidade")
    @classmethod
    def validar_quantidade(cls, v):
        if v <= 0:
            raise ValueError("A quantidade deve ser maior que zero.")
        if v > 10000:
            raise ValueError("Quantidade muito alta. Confira o valor.")
        return round(v, 2)

    @field_validator("valor_unitario_aplicado")
    @classmethod
    def validar_valor(cls, v):
        if v is not None and v <= 0:
            raise ValueError("O valor unitário deve ser maior que zero.")
        return round(v, 2) if v is not None else v

    @field_validator("data_execucao", mode="before")
    @classmethod
    def validar_data(cls, v):
        v = _texto_limpo(v)
        if not v:
            raise ValueError("Informe a data de execução.")
        return _data(v, "Data de execução")

    @field_validator("status")
    @classmethod
    def validar_status(cls, v):
        if v not in STATUS_SERVICO:
            raise ValueError("Status inválido.")
        return v


def _preco_oficial(conn, tipo: str, subtipo: str):
    return conn.execute(text(
        "SELECT valor, unidade_medida FROM preco_por_m "
        "WHERE lower(tipo_servico) = lower(:t) AND COALESCE(subtipo, '') = :s"
    ), {"t": tipo, "s": subtipo or ""}).mappings().first()


def _preparar_servico(conn, dados: ServicoEntrada) -> dict:
    """Validações que dependem do banco + cálculo do valor total."""
    if not conn.execute(text("SELECT 1 FROM clientes WHERE id_cliente = :id"), {"id": dados.id_cliente}).first():
        erro_campo("id_cliente", f"Cliente {dados.id_cliente} não existe.")
    valores = dados.model_dump()
    oficial = _preco_oficial(conn, dados.tipo_servico, dados.subtipo)
    if oficial and oficial["unidade_medida"] != dados.unidade_medida:
        erro_campo("unidade_medida", f"Este serviço é cobrado por {oficial['unidade_medida']}.")
    if valores["valor_unitario_aplicado"] is None:
        if not oficial:
            erro_campo("valor_unitario_aplicado",
                       "Este serviço não tem preço na tabela oficial. Informe o valor unitário.")
        valores["valor_unitario_aplicado"] = float(oficial["valor"])
    valores["valor_total"] = round(valores["quantidade"] * valores["valor_unitario_aplicado"], 2)
    return valores


SELECT_SERVICO = f"""
    SELECT s.id_servico, s.id_cliente, c.nome_completo AS cliente, s.tipo_servico, s.subtipo,
           s.descricao_detalhada, s.unidade_medida, s.quantidade, s.valor_unitario_aplicado,
           s.valor_total, s.data_execucao, s.status, {SQL_STATUS_SERVICO} AS status_padronizado
    FROM servicos s JOIN clientes c ON c.id_cliente = s.id_cliente
"""


def _servico_json(r) -> dict:
    d = dict(r)
    for k in ("quantidade", "valor_unitario_aplicado", "valor_total"):
        d[k] = float(d[k]) if d[k] is not None else None
    return d


def _buscar_servico(conn, id_servico: int):
    linha = conn.execute(text(f"{SELECT_SERVICO} WHERE s.id_servico = :id"), {"id": id_servico}).mappings().first()
    if not linha:
        raise HTTPException(404, f"Serviço {id_servico} não encontrado.")
    return _servico_json(linha)


@app.get("/api/servicos", tags=["Serviços"])
def listar_servicos(
    busca: Optional[str] = Query(None, description="Parte do nome do cliente ou da descrição"),
    tipo: Optional[str] = None,
    status: Optional[str] = None,
    id_cliente: Optional[int] = None,
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=500),
):
    filtros, params = [], paginar(pagina, por_pagina)
    if busca:
        filtros.append("(c.nome_completo ILIKE :busca OR s.descricao_detalhada ILIKE :busca)")
        params["busca"] = f"%{busca.strip()}%"
    if tipo:
        filtros.append("lower(s.tipo_servico) = lower(:tipo)")
        params["tipo"] = tipo
    if status:
        filtros.append(f"{SQL_STATUS_SERVICO} = :status")
        params["status"] = status
    if id_cliente:
        filtros.append("s.id_cliente = :id_cliente")
        params["id_cliente"] = id_cliente
    where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    with engine.connect() as conn:
        total = conn.execute(text(
            f"SELECT COUNT(*) FROM servicos s JOIN clientes c ON c.id_cliente = s.id_cliente {where}"
        ), params).scalar_one()
        itens = conn.execute(text(
            f"{SELECT_SERVICO} {where} ORDER BY s.id_servico DESC LIMIT :limite OFFSET :offset"
        ), params).mappings().all()
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": [_servico_json(r) for r in itens]}


@app.get("/api/servicos/{id_servico}", tags=["Serviços"])
def obter_servico(id_servico: int):
    with engine.connect() as conn:
        return _buscar_servico(conn, id_servico)


@app.post("/api/servicos", status_code=201, tags=["Serviços"])
def criar_servico(dados: ServicoEntrada):
    with engine.begin() as conn:
        valores = _preparar_servico(conn, dados)
        novo_id = conn.execute(text("""
            INSERT INTO servicos (id_cliente, tipo_servico, subtipo, descricao_detalhada, unidade_medida,
                                  quantidade, valor_unitario_aplicado, valor_total, data_execucao, status)
            VALUES (:id_cliente, :tipo_servico, :subtipo, :descricao_detalhada, :unidade_medida,
                    :quantidade, :valor_unitario_aplicado, :valor_total, :data_execucao, :status)
            RETURNING id_servico
        """), valores).scalar_one()
        return _buscar_servico(conn, novo_id)


@app.put("/api/servicos/{id_servico}", tags=["Serviços"])
def atualizar_servico(id_servico: int, dados: ServicoEntrada):
    with engine.begin() as conn:
        _buscar_servico(conn, id_servico)
        valores = _preparar_servico(conn, dados)
        conn.execute(text("""
            UPDATE servicos SET id_cliente = :id_cliente, tipo_servico = :tipo_servico, subtipo = :subtipo,
                   descricao_detalhada = :descricao_detalhada, unidade_medida = :unidade_medida,
                   quantidade = :quantidade, valor_unitario_aplicado = :valor_unitario_aplicado,
                   valor_total = :valor_total, data_execucao = :data_execucao, status = :status
            WHERE id_servico = :id
        """), {**valores, "id": id_servico})
        return _buscar_servico(conn, id_servico)


@app.delete("/api/servicos/{id_servico}", tags=["Serviços"])
def excluir_servico(id_servico: int):
    with engine.begin() as conn:
        _buscar_servico(conn, id_servico)
        qtd_manut = conn.execute(
            text("SELECT COUNT(*) FROM manutencoes WHERE id_servico_origem = :id"), {"id": id_servico}
        ).scalar_one()
        if qtd_manut:
            raise HTTPException(409, f"Não é possível excluir: há {qtd_manut} manutenção(ões) ligadas a este serviço.")
        # As fotos pertencem ao serviço, então saem junto com ele
        fotos = conn.execute(text("DELETE FROM fotos WHERE id_servico = :id"), {"id": id_servico}).rowcount
        conn.execute(text("DELETE FROM servicos WHERE id_servico = :id"), {"id": id_servico})
    return {"detail": f"Serviço {id_servico} excluído (junto com {fotos} foto(s))."}


# =====================================================================
# Manutenções
# =====================================================================
class ManutencaoEntrada(BaseModel):
    id_cliente: int
    id_servico_origem: Optional[int] = None
    descricao: str
    preco: Optional[float] = None  # vazio = garantia / a combinar
    data_solicitacao: str
    data_execucao: Optional[str] = None
    status: str

    @field_validator("id_servico_origem", "preco", mode="before")
    @classmethod
    def vazio_vira_none(cls, v):
        return None if v == "" else v

    @field_validator("descricao", "status", mode="before")
    @classmethod
    def limpar(cls, v):
        return _texto_limpo(v)

    @field_validator("descricao")
    @classmethod
    def validar_descricao(cls, v):
        if not v or len(v) < 5:
            raise ValueError("Descreva o problema (mínimo 5 caracteres).")
        return v

    @field_validator("preco")
    @classmethod
    def validar_preco(cls, v):
        if v is not None and v < 0:
            raise ValueError("O preço não pode ser negativo.")
        return round(v, 2) if v is not None else v

    @field_validator("data_solicitacao", mode="before")
    @classmethod
    def validar_data_sol(cls, v):
        v = _texto_limpo(v)
        if not v:
            raise ValueError("Informe a data da solicitação.")
        return _data(v, "Data da solicitação")

    @field_validator("data_execucao", mode="before")
    @classmethod
    def validar_data_exec(cls, v):
        return _data(_texto_limpo(v), "Data de execução")

    @field_validator("status")
    @classmethod
    def validar_status(cls, v):
        if v not in STATUS_MANUTENCAO:
            raise ValueError("Status inválido.")
        return v

    @model_validator(mode="after")
    def coerencia_datas(self):
        if self.data_execucao and self.data_execucao < self.data_solicitacao:
            raise ValueError("A data de execução não pode ser antes da solicitação.")
        if self.status == "concluída" and not self.data_execucao:
            raise ValueError("Manutenção concluída precisa da data de execução.")
        return self


SELECT_MANUTENCAO = """
    SELECT m.id_manutencao, m.id_cliente, c.nome_completo AS cliente, m.id_servico_origem,
           s.tipo_servico AS servico_origem, m.descricao, m.preco, m.data_solicitacao,
           m.data_execucao, m.status
    FROM manutencoes m
    JOIN clientes c ON c.id_cliente = m.id_cliente
    LEFT JOIN servicos s ON s.id_servico = m.id_servico_origem
"""


def _manutencao_json(r) -> dict:
    d = dict(r)
    d["preco"] = float(d["preco"]) if d["preco"] is not None else None
    return d


def _buscar_manutencao(conn, id_manutencao: int):
    linha = conn.execute(
        text(f"{SELECT_MANUTENCAO} WHERE m.id_manutencao = :id"), {"id": id_manutencao}
    ).mappings().first()
    if not linha:
        raise HTTPException(404, f"Manutenção {id_manutencao} não encontrada.")
    return _manutencao_json(linha)


def _validar_vinculos_manutencao(conn, dados: ManutencaoEntrada):
    if not conn.execute(text("SELECT 1 FROM clientes WHERE id_cliente = :id"), {"id": dados.id_cliente}).first():
        erro_campo("id_cliente", f"Cliente {dados.id_cliente} não existe.")
    if dados.id_servico_origem is not None:
        dono = conn.execute(
            text("SELECT id_cliente FROM servicos WHERE id_servico = :id"), {"id": dados.id_servico_origem}
        ).scalar()
        if dono is None:
            erro_campo("id_servico_origem", f"Serviço {dados.id_servico_origem} não existe.")
        if dono != dados.id_cliente:
            erro_campo("id_servico_origem", "Este serviço pertence a outro cliente.")


@app.get("/api/manutencoes", tags=["Manutenções"])
def listar_manutencoes(
    busca: Optional[str] = Query(None, description="Parte do nome do cliente ou da descrição"),
    status: Optional[str] = None,
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(20, ge=1, le=500),
):
    filtros, params = [], paginar(pagina, por_pagina)
    if busca:
        filtros.append("(c.nome_completo ILIKE :busca OR m.descricao ILIKE :busca)")
        params["busca"] = f"%{busca.strip()}%"
    if status:
        filtros.append("m.status = :status")
        params["status"] = status
    where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    with engine.connect() as conn:
        total = conn.execute(text(
            f"SELECT COUNT(*) FROM manutencoes m JOIN clientes c ON c.id_cliente = m.id_cliente {where}"
        ), params).scalar_one()
        itens = conn.execute(text(
            f"{SELECT_MANUTENCAO} {where} ORDER BY m.id_manutencao DESC LIMIT :limite OFFSET :offset"
        ), params).mappings().all()
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": [_manutencao_json(r) for r in itens]}


@app.post("/api/manutencoes", status_code=201, tags=["Manutenções"])
def criar_manutencao(dados: ManutencaoEntrada):
    with engine.begin() as conn:
        _validar_vinculos_manutencao(conn, dados)
        novo_id = conn.execute(text("""
            INSERT INTO manutencoes (id_cliente, id_servico_origem, descricao, preco,
                                     data_solicitacao, data_execucao, status)
            VALUES (:id_cliente, :id_servico_origem, :descricao, :preco,
                    :data_solicitacao, :data_execucao, :status)
            RETURNING id_manutencao
        """), dados.model_dump()).scalar_one()
        return _buscar_manutencao(conn, novo_id)


@app.put("/api/manutencoes/{id_manutencao}", tags=["Manutenções"])
def atualizar_manutencao(id_manutencao: int, dados: ManutencaoEntrada):
    with engine.begin() as conn:
        _buscar_manutencao(conn, id_manutencao)
        _validar_vinculos_manutencao(conn, dados)
        conn.execute(text("""
            UPDATE manutencoes SET id_cliente = :id_cliente, id_servico_origem = :id_servico_origem,
                   descricao = :descricao, preco = :preco, data_solicitacao = :data_solicitacao,
                   data_execucao = :data_execucao, status = :status
            WHERE id_manutencao = :id
        """), {**dados.model_dump(), "id": id_manutencao})
        return _buscar_manutencao(conn, id_manutencao)


@app.delete("/api/manutencoes/{id_manutencao}", tags=["Manutenções"])
def excluir_manutencao(id_manutencao: int):
    with engine.begin() as conn:
        _buscar_manutencao(conn, id_manutencao)
        conn.execute(text("DELETE FROM manutencoes WHERE id_manutencao = :id"), {"id": id_manutencao})
    return {"detail": f"Manutenção {id_manutencao} excluída."}


# =====================================================================
# Machine Learning (modelos treinados por scripts/modelos_ml.py)
# =====================================================================
# O script grava em dados/modelos/ (passo 4 do pipeline). A API só LÊ esses
# arquivos; quando o script roda de novo, a API percebe a mudança (data do
# arquivo) e recarrega sozinha, sem precisar reiniciar.
MODELOS_DIR = Path(os.getenv("MODELOS_DIR", RAIZ / "dados" / "modelos"))
_cache_ml: dict = {}


def _arquivo_ml(nome: str) -> Path:
    caminho = MODELOS_DIR / nome
    if not caminho.exists():
        raise HTTPException(404, "Os modelos de ML ainda não foram treinados. Rode: make ml")
    return caminho


def _json_ml(nome: str):
    caminho = _arquivo_ml(nome)
    mtime = caminho.stat().st_mtime
    em_cache = _cache_ml.get(nome)
    if em_cache and em_cache[0] == mtime:
        return em_cache[1]
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    _cache_ml[nome] = (mtime, dados)
    return dados


def _modelo_estimador():
    caminho = _arquivo_ml("modelo_estimador.joblib")
    mtime = caminho.stat().st_mtime
    em_cache = _cache_ml.get("modelo")
    if em_cache and em_cache[0] == mtime:
        return em_cache[1]
    try:
        import joblib  # importado só aqui: a API sobe mesmo sem scikit-learn instalado
        modelo = joblib.load(caminho)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"Não foi possível carregar o modelo (scikit-learn instalado? "
                                 f"rode: pip install -r requirements.txt): {e}")
    _cache_ml["modelo"] = (mtime, modelo)
    return modelo


@app.get("/api/ml/segmentos", tags=["Machine Learning"])
def ml_segmentos():
    """Segmentação de clientes (K-Means sobre recência, frequência e valor)."""
    return _json_ml("segmentos.json")


@app.get("/api/ml/estimador", tags=["Machine Learning"])
def ml_estimador():
    """Dados do estimador de orçamento: catálogo de serviços, métricas e importância das variáveis."""
    return _json_ml("estimador.json")


@app.get("/api/ml/estimar", tags=["Machine Learning"])
def ml_estimar(tipo_servico: str, quantidade: float, subtipo: str = "", cidade: Optional[str] = None):
    """Estima o valor de um orçamento: preço unitário previsto pelo modelo x quantidade."""
    meta = _json_ml("estimador.json")
    modelo = _modelo_estimador()
    subtipo = _texto_limpo(subtipo) or ""

    item = next((c for c in meta["catalogo"]
                 if c["tipo_servico"].lower() == tipo_servico.strip().lower()
                 and c["subtipo"].lower() == subtipo.lower()), None)
    if item is None:
        erro_campo("tipo_servico", "Serviço não reconhecido pelo modelo. Escolha um da lista.")
    if not (0 < quantidade <= 100000):
        erro_campo("quantidade", "Informe uma quantidade maior que zero (até 100.000).")

    import pandas as pd
    entrada = pd.DataFrame([{
        "servico": f"{item['tipo_servico']}|{item['subtipo']}",
        "cidade": _texto_limpo(cidade) or "Não informada",
        "quantidade": float(quantidade),
    }])
    preco_unitario = float(modelo.predict(entrada)[0])
    valor = preco_unitario * quantidade
    faixa_min, faixa_max = meta["faixa_90"]

    with engine.connect() as conn:
        tabela = conn.execute(text(
            "SELECT valor FROM preco_por_m WHERE lower(tipo_servico) = lower(:t) "
            "AND lower(COALESCE(subtipo, '')) = lower(:s) LIMIT 1"
        ), {"t": item["tipo_servico"], "s": item["subtipo"]}).scalar()

    return {
        "tipo_servico": item["tipo_servico"], "subtipo": item["subtipo"], "unidade": item["unidade"],
        "quantidade": quantidade, "cidade": entrada.at[0, "cidade"],
        "preco_unitario": round(preco_unitario, 2),
        "valor_estimado": round(valor, 2),
        "faixa_min": round(valor * faixa_min, 2), "faixa_max": round(valor * faixa_max, 2),
        "preco_tabela": float(tabela) if tabela is not None else None,
        "modelo_gerado_em": meta["gerado_em"],
    }


# ---------------------------------------------------------------------
# Front-end (arquivos estáticos). Fica por último para não "engolir"
# as rotas /api acima.
# ---------------------------------------------------------------------
app.mount("/", StaticFiles(directory=RAIZ / "frontend", html=True), name="frontend")
