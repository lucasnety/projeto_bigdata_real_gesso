# =====================================================================
# Projeto de Extensão - Empresa de Gesso e Drywall
# Atalhos padronizados para provisionar e operar o ambiente.
#
# Uso:  make <alvo>          ex.: make up
# Se preferir sem "make", os mesmos passos estão em scripts/provisionar.sh
# =====================================================================

.PHONY: setup up down reset logs status psql gerar carregar preparar ml

# Cria o ambiente virtual Python e instala as dependências
setup:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt
	@test -f .env || cp .env.example .env
	@echo ""
	@echo "Ambiente Python pronto. Ative com: source .venv/bin/activate"

# Sobe os serviços (Postgres + Adminer) em segundo plano
up:
	docker compose up -d
	@echo "Aguardando o banco ficar saudável..."
	@until [ "$$(docker inspect -f '{{.State.Health.Status}}' gesso_drywall_db 2>/dev/null)" = "healthy" ]; do sleep 1; done
	@echo "Serviços no ar:"
	@echo "  - Postgres:  localhost:$${POSTGRES_PORT:-5432}"
	@echo "  - Adminer:   http://localhost:$${ADMINER_PORT:-8080}"

# Derruba os serviços mantendo os dados (volume preservado)
down:
	docker compose down

# Reconstrói o ambiente do ZERO: remove containers + volume de dados
# e sobe tudo de novo (o schema em db/init roda automaticamente de novo)
reset:
	docker compose down -v
	$(MAKE) up

logs:
	docker compose logs -f

status:
	docker compose ps

# Abre um psql interativo dentro do container do banco
psql:
	docker compose exec db psql -U $${POSTGRES_USER:-gesso_user} -d $${POSTGRES_DB:-gesso_drywall}

# Executa o simulador gerador de dados (Atividade 6)
gerar:
	.venv/bin/python scripts/gerador_dados.py

# Carrega os CSVs gerados para dentro do Postgres
carregar:
	.venv/bin/python scripts/carregar_dados.py

# Limpa os dados brutos e monta as bases dos modelos (dados/processed)
preparar:
	.venv/bin/python scripts/preparar_dados.py

# Aprendizado de Máquina de ponta a ponta: gera os dados, recarrega o
# banco, prepara as bases e executa os 5 notebooks (salvando os resultados).
# Requer o banco no ar (make up). Se o schema mudou, rode antes: make reset
ml:
	.venv/bin/python scripts/gerador_dados.py
	.venv/bin/python scripts/carregar_dados.py --substituir
	.venv/bin/python scripts/preparar_dados.py
	cd notebooks && for nb in 0*.ipynb; do \
		../.venv/bin/jupyter nbconvert --to notebook --execute --inplace $$nb || exit 1; \
	done
	@echo "Notebooks executados em notebooks/ - resultados em dados/processed/"
