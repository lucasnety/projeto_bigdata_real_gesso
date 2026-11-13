# =====================================================================
# Projeto de Extensão - Empresa de Gesso e Drywall
# Atalhos padronizados para provisionar e operar o ambiente.
#
# Uso:  make <alvo>          ex.: make up
# Se preferir sem "make", os mesmos passos estão em scripts/provisionar.sh
# =====================================================================

.PHONY: setup up down reset logs status psql gerar tratar carregar ml pipeline pipeline-100k api hadoop hadoop-ligar vm-up vm-config vm-verificar vm-down

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

# ---------------------------------------------------------------------
# Pipeline de dados:  gerar (bruto) -> tratar (R) -> carregar (Postgres)
# ---------------------------------------------------------------------
# 1) Simulador gerador de dados BRUTOS (sujos de propósito) -> dados/raw
gerar:
	.venv/bin/python scripts/gerador_dados.py

# 2) Tratamento em R: limpa dados/raw e grava dados/tratado + relatório de qualidade
#    (requer R: sudo apt install r-base-core)
tratar:
	Rscript scripts/tratar_dados.R --entrada dados/raw --saida dados/tratado

# 3) Carrega os CSVs TRATADOS para dentro do Postgres
carregar:
	.venv/bin/python scripts/carregar_dados.py --substituir

# 4) Machine Learning: treina a segmentação de clientes e o estimador de orçamento
#    (lê o Postgres e grava em dados/modelos; a API mostra na aba "Insights (ML)")
ml:
	.venv/bin/python scripts/modelos_ml.py

# Os 4 passos em sequência
pipeline: gerar tratar carregar ml

# Volume grande (pedido do professor: 100.000 serviços). Usa pastas próprias
# (dados/raw_100k e dados/tratado_100k, fora do Git) para não mexer no lote
# pequeno versionado em dados/tratado. Ajuste os números pelas variáveis:
#   make pipeline-100k N_SERVICOS=250000 N_CLIENTES=50000
N_SERVICOS    ?= 100000
N_CLIENTES    ?= 20000
N_MANUTENCOES ?= 12000
pipeline-100k:
	.venv/bin/python scripts/gerador_dados.py --clientes $(N_CLIENTES) --servicos $(N_SERVICOS) --manutencoes $(N_MANUTENCOES) --out-dir dados/raw_100k
	Rscript scripts/tratar_dados.R --entrada dados/raw_100k --saida dados/tratado_100k
	.venv/bin/python scripts/carregar_dados.py --dados-dir dados/tratado_100k --substituir
	.venv/bin/python scripts/modelos_ml.py

# Sobe a API + front-end (Integração da Interface com a API)
# Abra http://localhost:8000  |  documentação da API: http://localhost:8000/docs
api:
	.venv/bin/uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# ---------------------------------------------------------------------
# Hadoop (instalado em ~/opt) - MapReduce que conta os serviços por tipo
# O resultado fica no HDFS e é lido pela API para o gráfico do Painel.
# ---------------------------------------------------------------------
HADOOP_HOME ?= $(HOME)/opt/hadoop
JAVA_HOME   ?= $(HOME)/opt/jdk11
export HADOOP_HOME JAVA_HOME
HDFS   = $(HADOOP_HOME)/bin/hdfs
YARN   = $(HADOOP_HOME)/bin/yarn
HADOOP = $(HADOOP_HOME)/bin/hadoop

# Liga HDFS + YARN (necessário depois de reiniciar o PC)
hadoop-ligar:
	-$(HDFS) --daemon start namenode
	-$(HDFS) --daemon start datanode
	-$(YARN) --daemon start resourcemanager
	-$(YARN) --daemon start nodemanager
	@echo "Aguardando o HDFS sair do modo de segurança..."
	@$(HDFS) dfsadmin -safemode wait
	@echo "Hadoop no ar: HDFS http://localhost:9870 | YARN http://localhost:8088"

# Envia dados/tratado/servicos.csv ao HDFS e roda o job (mapper.py + reducer.py)
hadoop:
	$(HDFS) dfs -mkdir -p /real_gesso/entrada
	$(HDFS) dfs -put -f dados/tratado/servicos.csv /real_gesso/entrada/
	$(HDFS) dfs -rm -r -f /real_gesso/saida
	$(HADOOP) jar $(HADOOP_HOME)/share/hadoop/tools/lib/hadoop-streaming-*.jar \
		-files scripts/hadoop/mapper.py,scripts/hadoop/reducer.py \
		-mapper "python3 mapper.py" -reducer "python3 reducer.py" \
		-input /real_gesso/entrada/servicos.csv -output /real_gesso/saida
	@echo ""
	@echo "=== Resultado (serviços por tipo) ==="
	@$(HDFS) dfs -cat /real_gesso/saida/part-*

# ---------------------------------------------------------------------
# VMs (OpenTofu + cloud-init + Ansible) - Checkpoint 01 (DevOps)
# Requer KVM/libvirt, OpenTofu e Ansible instalados (ver README) e o
# arquivo infraestrutura/terraform.tfvars com a sua chave pública SSH.
# ---------------------------------------------------------------------
# 1) Cria as 2 VMs (o cloud-init configura usuario + chave SSH) e gera o inventory.ini
vm-up:
	cd infraestrutura && tofu init && tofu apply -auto-approve

# 2) Configura as VMs e sobe o sistema completo (Ansible)
vm-config:
	cd infraestrutura/ansible && ansible-playbook playbook.yml

# 3) Gera as evidencias para a defesa (salvas em infraestrutura/evidencias/)
vm-verificar:
	./infraestrutura/verificar.sh --idempotencia

# Destroi as VMs
vm-down:
	cd infraestrutura && tofu destroy -auto-approve
