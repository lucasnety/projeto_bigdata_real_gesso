# Projeto de Extensão — Big Data (Gesso e Drywall)

Projeto integrado da UNIFEOB (disciplinas de DevOps / AED / Análise e
Visualização de Dados) para uma empresa de montagem e execução de
serviços residenciais e industriais em **gesso e drywall**.

Grupo:
- João Victor Rocha Avello Correia — RA 24001368
- Lucas Eduardo Cruz Alves — RA 25002040
- Lucas Guimarães Castro Nunes — RA 23000143
- Vitor Alexandre Rocetti Rinke — RA 25001968

## Estrutura do projeto

```
.
├── db/init/001_schema.sql   # schema Postgres (criado automaticamente no 1º up)
├── docker-compose.yml       # serviços: Postgres + Adminer
├── Makefile                 # atalhos (make up / down / reset / gerar / carregar)
├── requirements.txt         # dependências Python
├── .env.example              # modelo de variáveis de ambiente
├── scripts/
│   ├── provisionar.sh        # script único de provisionamento (Atividade 5)
│   ├── gerador_dados.py      # simulador gerador de dados (Atividade 6)
│   └── carregar_dados.py     # carrega os CSVs gerados no Postgres
├── dados/
│   └── raw/                  # 1º lote de dados brutos gerado pelo simulador
└── docs/                     # documentos das entregas (.docx)
```

## Pré-requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (inclui o Docker Compose)
- Python 3.10+

## Como provisionar o ambiente (Atividade 5)

Tudo é feito por um único script, documentado e idempotente:

```bash
./scripts/provisionar.sh
```

Isso cria o `.env`, o ambiente virtual Python, instala as dependências e
sobe os serviços via Docker Compose (Postgres com o schema já criado +
Adminer para inspecionar o banco pelo navegador).

Para **reconstruir o ambiente do zero** (apaga os dados do Postgres e
recria tudo):

```bash
./scripts/provisionar.sh --reset
```

Alternativa equivalente usando `make` (ver `Makefile`):

```bash
make setup    # cria venv + instala dependências
make up       # sobe Postgres + Adminer
make reset    # derruba tudo (incl. volume) e sobe de novo, do zero
make down     # derruba os serviços
```

Depois de subir os serviços:
- Postgres: `localhost:5432` (ver credenciais no `.env`)
- Adminer (interface web do banco): http://localhost:8080
  - Sistema: `PostgreSQL` · Servidor: `db` · Usuário/senha: os do `.env`

## Como gerar os dados brutos (Atividade 6)

```bash
source .venv/bin/activate
python scripts/gerador_dados.py
```

Isso gera (ou regenera, de forma reprodutível — mesma *seed* = mesmos
dados) os arquivos em `dados/raw/`: `clientes.csv`, `preco_por_m.csv`,
`servicos.csv`, `fotos.csv` e `manutencoes.csv`.

Parâmetros disponíveis:

```bash
python scripts/gerador_dados.py --clientes 500 --servicos 2000 --seed 7
```

Para carregar os CSVs gerados dentro do Postgres provisionado:

```bash
python scripts/carregar_dados.py
```

## Documentação das entregas

Os documentos acadêmicos de cada entrega semanal estão em `docs/`.
