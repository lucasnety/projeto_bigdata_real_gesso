#!/usr/bin/env bash
# =====================================================================
# provisionar.sh
#
# Atividade 5 (DevOps - Provisionamento e preparação dos serviços)
#
# Script único e idempotente que cria (ou reconstrói) todo o ambiente
# necessário para rodar o simulador gerador de dados e armazenar os
# dados da empresa de gesso e drywall:
#
#   1. Verifica os pré-requisitos (Docker e Python 3)
#   2. Cria o arquivo .env a partir do .env.example (se não existir)
#   3. Cria o ambiente virtual Python e instala as dependências
#   4. Sobe os serviços via Docker Compose:
#        - Postgres  -> banco de dados (schema criado automaticamente)
#        - Adminer   -> interface web para inspecionar o banco
#   5. Aguarda o banco de dados ficar saudável (healthcheck)
#
# Uso:
#   ./scripts/provisionar.sh              # cria/atualiza o ambiente
#   ./scripts/provisionar.sh --reset      # reconstrói do zero (apaga
#                                           os dados do Postgres e recria)
# =====================================================================

set -euo pipefail
cd "$(dirname "$0")/.."   # garante que rodamos a partir da raiz do projeto

RESET=false
if [[ "${1:-}" == "--reset" ]]; then
    RESET=true
fi

echo "==> Verificando pré-requisitos..."
command -v docker >/dev/null 2>&1 || { echo "ERRO: Docker não encontrado. Instale o Docker Desktop antes de continuar."; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERRO: Docker Compose (plugin) não encontrado."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERRO: Python 3 não encontrado."; exit 1; }
echo "    Docker, Docker Compose e Python 3 disponíveis."

echo "==> Preparando arquivo de variáveis de ambiente (.env)..."
if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "    .env criado a partir de .env.example."
else
    echo "    .env já existe, mantendo o atual."
fi

echo "==> Criando ambiente virtual Python e instalando dependências..."
if [[ ! -d .venv ]]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
echo "    Dependências instaladas em .venv/"

if [[ "$RESET" == true ]]; then
    echo "==> --reset informado: derrubando containers e apagando o volume de dados..."
    docker compose down -v
fi

echo "==> Subindo os serviços (Postgres + Adminer) via Docker Compose..."
docker compose up -d

echo "==> Aguardando o banco de dados ficar saudável..."
tries=0
until [[ "$(docker inspect -f '{{.State.Health.Status}}' gesso_drywall_db 2>/dev/null)" == "healthy" ]]; do
    tries=$((tries + 1))
    if [[ $tries -gt 30 ]]; then
        echo "ERRO: o banco não ficou saudável a tempo. Verifique com: docker compose logs db"
        exit 1
    fi
    sleep 1
done

# shellcheck disable=SC1091
set -a; source .env; set +a

echo ""
echo "=========================================================="
echo " Ambiente provisionado com sucesso!"
echo "=========================================================="
echo " Postgres :  localhost:${POSTGRES_PORT:-5432}  (db: ${POSTGRES_DB:-gesso_drywall})"
echo " Adminer  :  http://localhost:${ADMINER_PORT:-8080}"
echo "             (sistema: PostgreSQL | servidor: db | usuário/senha: do .env)"
echo ""
echo " Próximos passos:"
echo "   source .venv/bin/activate"
echo "   python scripts/gerador_dados.py         # gera os dados brutos (Atividade 6)"
echo "   python scripts/carregar_dados.py         # carrega os CSVs no Postgres"
echo "=========================================================="
