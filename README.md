# Projeto Integrado — Empresa de Gesso e Drywall

Projeto de extensão/Data Science para uma empresa de serviços de gesso e
drywall da região de São João da Boa Vista/SP.

- [Aprendizado de Máquina aplicado ao Projeto](#aprendizado-de-máquina-aplicado-ao-projeto)
- [Ambiente local: banco de dados e simulador](#ambiente-local-banco-de-dados-e-simulador-atividades-5-e-6)
- [Checkpoint 01 — DevOps e Infraestrutura Privada](#checkpoint-01--devops-e-infraestrutura-privada)

## Aprendizado de Máquina aplicado ao Projeto

Três modelos respondem às três perguntas do **ciclo comercial** da empresa.
O segmento descoberto no agrupamento entra como variável nos outros dois.

| Pergunta | Técnica | Algoritmo escolhido | Resultado (teste) | Referência |
|---|---|---|---|---|
| **Quem é o cliente?** | Agrupamento | K-Means (k = 4) | 4 segmentos, silhueta 0,37 | ARI 0,62 contra os perfis reais |
| **Vai fechar?** | Classificação | Regressão Logística | AUC 0,74 · acurácia 70% | Baseline: AUC 0,50 · 61% |
| **Quanto cobrar?** | Regressão | Regressão Linear (alvo em log) | Erro médio de 4,0% (R$ 3,08/unid.) | Tabela atual: 11,7% (R$ 9,01) |

Random Forest e Gradient Boosting também foram testados nos dois problemas
supervisionados e não superaram os modelos lineares, que ficaram por serem mais
simples de explicar e usar.

### Notebooks (abra no GitHub para ver gráficos e resultados)

| Notebook | Conteúdo |
|---|---|
| [01 · Preparação dos dados](notebooks/01_preparacao_dados.ipynb) | Diagnóstico e tratamento de 12 tipos de inconsistência; deduplicação de clientes |
| [02 · Segmentação de clientes](notebooks/02_segmentacao_clientes.ipynb) | K-Means: escolha de *k*, perfil dos segmentos, canais de aquisição |
| [03 · Fechamento de orçamentos](notebooks/03_fechamento_orcamentos.ipynb) | Classificação: o que faz um orçamento fechar; priorização dos pendentes |
| [04 · Estimativa de preço](notebooks/04_estimativa_preco.ipynb) | Regressão: ajustes de preço por cidade/segmento/volume; SHAP; preços "a combinar" |
| [05 · Conclusões e insights](notebooks/05_conclusoes_insights.ipynb) | Resumo, prova real contra o simulador, plano de ação e limitações |

### Principais insights

- **Visita técnica multiplica por ~3 a chance de fechar**, e cada dia de demora para enviar o orçamento reduz a chance em ~18%.
- **11% dos clientes (construtoras) geram 58% do faturamento.** O residencial econômico é 33% da base e só 4% do faturamento.
- **Cada canal traz um tipo de cliente:** Google/site → construtoras e comércio; indicação/Instagram → alto padrão; Facebook/panfleto → econômico.
- **O preço varia ~21 pontos entre cidades** (Poços de Caldas +13%, Itobi −8%), mas a tabela oficial é única.
- **Desconto acima de 10–12% não aumenta o fechamento.**

### Sobre os dados

Os dados são **sintéticos**, gerados por [`scripts/gerador_dados.py`](scripts/gerador_dados.py)
com regras de negócio plausíveis e **documentadas**, e com inconsistências propositais
(duplicatas, formatos divergentes, valores ausentes). O simulador também gera um gabarito
(`gabarito_perfis.csv`) que nunca é usado no treino. Ele serve só para a "prova real":
conferir se os modelos redescobriram as regras plantadas (notebook 05).

### Como reproduzir

```bash
make setup          # cria o .venv e instala as dependências (requirements.txt)
make up             # sobe Postgres + Adminer (Docker)
make reset          # só na 1ª vez nesta branch: recria o banco com o schema novo
make ml             # gera dados -> carrega no Postgres -> prepara -> executa os 5 notebooks
```

Fluxo: `gerador_dados.py → dados/raw/*.csv → carregar_dados.py → Postgres → preparar_dados.py → notebooks/`.
Sem o Docker, `scripts/preparar_dados.py` lê direto os CSVs de `dados/raw/` como plano B.

## Ambiente local: banco de dados e simulador (Atividades 5 e 6)

| Comando | O que faz |
|---|---|
| `make setup` | Ambiente virtual Python + dependências; cria `.env` a partir do `.env.example` |
| `make up` / `make down` | Sobe/derruba Postgres (porta 5432) e Adminer (http://localhost:8080) |
| `make reset` | Recria o banco do zero (o schema em `db/init/` roda de novo) |
| `make gerar` | Gera os CSVs brutos em `dados/raw/` |
| `make carregar` | Carrega os CSVs no Postgres |
| `make preparar` | Limpa os dados e monta as bases dos modelos em `dados/processed/` |

O mesmo provisionamento também está em `scripts/provisionar.sh` (`--reset` para reconstruir).

## Checkpoint 01 — DevOps e Infraestrutura Privada


Infraestrutura privada mínima para executar o simulador de dados do
Projeto Integrado (empresa de gesso/drywall), provisionada 100% por
código: **OpenTofu** cria as máquinas virtuais, **cloud-init** faz a
configuração inicial, e **Ansible** prepara o ambiente e instala o
simulador.

### Arquitetura

- **devops1**: roda o simulador (`/opt/datasci`), gera os dados em
  `/opt/datasci/dados/chamados_servico.csv` e os expõe por um nginx
  interno na porta 8080.
- **devops2**: só tem nginx, configurado como **proxy reverso na porta
  80**, repassando tudo para o devops1.

### Pré-requisitos (na máquina hospedeira)

> Precisa rodar num **Linux de verdade** (boot nativo ou dual-boot),
> **não dentro do WSL** — o WSL não garante acesso confiável à
> virtualização por hardware (KVM) que o libvirt precisa.

1. Linux com suporte a KVM:
```bash
   sudo apt update
   sudo apt install -y qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils virtinst
   sudo usermod -aG libvirt,kvm $USER
```
2. **OpenTofu**: https://opentofu.org/docs/intro/install/
3. **Ansible**: `sudo apt install -y ansible`
4. Par de chaves SSH: `ssh-keygen -t ed25519 -C "seu-nome" -f ~/.ssh/id_ed25519`

### Como reproduzir a infraestrutura

```bash
cd infraestrutura
cp terraform.tfvars.example terraform.tfvars
# edite terraform.tfvars e cole o conteúdo de `cat ~/.ssh/id_ed25519.pub`

tofu init
tofu plan
tofu apply       # cria as VMs e gera ansible/inventory.ini automaticamente

cd ansible
ansible-playbook playbook.yml   # instala tudo e sobe o pipeline do simulador
```

### Demonstração

```bash
ssh aluno@<ip-devops1> "cat /opt/datasci/dados/chamados_servico.csv"
curl http://<ip-devops2>/chamados_servico.csv   # via proxy reverso, porta 80
```

### Segurança

Nenhuma senha, chave privada ou `terraform.tfvars` real está neste
repositório — apenas os arquivos `.example`. Acesso às VMs é só por
chave pública SSH (login por senha desativado pelo cloud-init).