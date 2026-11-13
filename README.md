# Projeto Integrado de Data Science — Real Gesso

Sistema de gestão (clientes, serviços e manutenções) de uma empresa de
gesso e drywall, com infraestrutura **100% provisionada por código**:
**OpenTofu** cria as máquinas virtuais, **cloud-init** faz a configuração
inicial e **Ansible** instala e configura tudo dentro delas.

O fluxo de dados completo, executado **dentro da VM**, é:

```
simulador ──► dados brutos ──► tratamento em R ──► dados tratados ──► PostgreSQL ──► API + front-end
(Python)      dados/raw         scripts/            dados/tratado      (devops1)      (via proxy no devops2)
                                tratar_dados.R                             │
                                                                           └──► Machine Learning (scikit-learn) ──► aba "Insights (ML)"
                                                                                scripts/modelos_ml.py → dados/modelos
```

## Arquitetura

```
host (Linux + KVM)
  │  OpenTofu (provider libvirt) cria 2 VMs na rede NAT datasci-net
  ▼
┌─────────────────────────────┐   HTTP :8000 (sistema)  ┌──────────────────────────────┐
│ devops2  (proxy reverso)     │ ──────────────────────► │ devops1  (aplicação)          │
│  nginx :80                   │   HTTP :8080 (dados)    │  PostgreSQL (só localhost)    │
│   /        -> devops1:8000   │ ──────────────────────► │  API FastAPI + front-end :8000│
│   /dados/  -> devops1:8080   │                         │  simulador + timer (5 min)    │
└─────────────────────────────┘                         │  nginx :8080 (CSV do simulador)│
                                                          └──────────────────────────────┘
```

- **devops1** (`/opt/datasci`): roda o **sistema completo** — PostgreSQL,
  R, API (FastAPI) e front-end, em `/opt/datasci/sistema`, como serviço
  systemd (`gesso-api`) — e também o **simulador** do Checkpoint 01, que
  gera `/opt/datasci/dados/chamados_servico.csv` a cada 5 minutos (timer
  systemd), exposto por um nginx interno na porta 8080.
- **devops2**: só nginx, como **proxy reverso na porta 80**. É o único
  ponto de acesso "público": `/` abre o sistema; `/dados/` mostra os
  arquivos do simulador.

## Pré-requisitos (na máquina hospedeira)

> Precisa rodar num **Linux de verdade** (boot nativo ou dual-boot),
> **não dentro do WSL** — o WSL não garante acesso confiável à
> virtualização por hardware (KVM) que o libvirt precisa.

1. Linux com suporte a KVM (Ubuntu / Linux Mint):
```bash
   sudo apt install -y qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils virtinst cpu-checker genisoimage git curl
   sudo usermod -aG libvirt,kvm $USER      # depois: reiniciar o PC
```
2. **OpenTofu**: https://opentofu.org/docs/intro/install/
3. **Ansible**: `sudo apt install -y ansible`
4. Par de chaves SSH: `ssh-keygen -t ed25519 -C "seu-nome" -f ~/.ssh/id_ed25519`

## Como reproduzir a infraestrutura

```bash
cd infraestrutura
cp terraform.tfvars.example terraform.tfvars
# edite terraform.tfvars e cole o conteúdo de `cat ~/.ssh/id_ed25519.pub`

tofu init
tofu plan
tofu apply -auto-approve     # cria as 2 VMs e gera ansible/inventory.ini sozinho
```

Depois do `apply`, o Ansible configura as VMs (o primeiro passo espera o
cloud-init terminar, e a instalação do sistema leva alguns minutos):

```bash
cd ansible
ansible-playbook playbook.yml
```

O `ansible/inventory.ini` é **gerado pelo OpenTofu** (recurso `local_file`
+ modelo `inventory.ini.tpl`) com o IP real de cada VM e **fica versionado**
no repositório: depois do `apply`, faça `git add infraestrutura/ansible/inventory.ini`
e commit para registrar as VMs usadas na entrega.

O playbook é **idempotente**: pode rodar quantas vezes quiser, não recria
o que já existe e não apaga dados já gerados ou cadastrados — na 2ª execução
o resumo final mostra `changed=0` e `failed=0` (o nginx só reinicia quando a
configuração muda). Detalhes úteis:

```bash
DATASCI_DB_PASSWORD='outrasenha' ansible-playbook playbook.yml   # senha do banco fora do repositório
ansible-playbook playbook.yml -e recarregar_dados=true           # refaz gerar -> tratar -> carregar -> ML
ansible-playbook playbook.yml --tags dados                       # só o pipeline de dados
```

Atalhos equivalentes pelo `Makefile`: `make vm-up`, `make vm-config`,
`make vm-verificar`, `make vm-down`.

## Pipeline de dados (gerar → tratar em R → carregar → ML)

| Etapa | Script | Entrada → saída |
|---|---|---|
| 1. Gerar | `scripts/gerador_dados.py` (Python, Faker, seed fixa) | → `dados/raw/*.csv` (bruto, **sujo de propósito**) |
| 2. Tratar | `scripts/tratar_dados.R` (**R base**, sem pacotes extras) | `dados/raw` → `dados/tratado/*.csv` + relatório de qualidade |
| 3. Carregar | `scripts/carregar_dados.py` | `dados/tratado` → tabelas do PostgreSQL |
| 4. Machine Learning | `scripts/modelos_ml.py` (scikit-learn) | PostgreSQL → `dados/modelos/` (segmentos, estimador, métricas) |

Na VM o Ansible executa as 4 etapas sozinho (só se o banco estiver vazio, com
`-e recarregar_dados=true`, ou se os modelos de ML ainda não existirem).
Na sua máquina: `make pipeline` (precisa de R: `sudo apt install r-base-core`);
só o passo 4: `make ml`.

### Machine Learning (aba "Insights (ML)" do sistema)

O passo 4 lê o PostgreSQL e gera dois resultados, mostrados no front-end
(aba **Insights (ML)**) e servidos pela API em `/api/ml/*`:

1. **Segmentação de clientes (K-Means sobre RFM).** Cada cliente é descrito por
   recência (dias desde o último serviço), frequência (nº de serviços) e valor
   (total gasto); as variáveis passam por `log1p` + padronização e o K-Means
   (k = 4, semente 42) as separa em 4 grupos, nomeados por regra a partir do
   perfil médio: *Grandes clientes*, *Clientes frequentes*, *Clientes inativos*
   e o que sobra (*Clientes ocasionais*, ou *recentes* se for o que comprou há
   menos tempo). A aba mostra o gráfico de
   clientes e de faturamento por grupo, a tabela do perfil de cada grupo e os
   10 maiores clientes. Qualidade medida pelo coeficiente de silhueta.
2. **Estimador de orçamento (Random Forest).** O usuário escolhe serviço,
   quantidade e cidade; o modelo prevê o **preço unitário** (valor = preço × quantidade),
   mostra a **faixa de 90%** (quantis 5%–95% do erro em dados de teste) e compara com a
   tabela oficial de preços. Treino 80% / teste 20%, comparado com um modelo
   de referência simples ("média do tipo de serviço").

> **Resultado honesto:** os dados são **simulados** e o preço depende quase só do
> tipo/subtipo do serviço (mais ±15% de ruído aleatório). Por isso o Random Forest
> (erro médio ≈ 1,8%, R² ≈ 0,998) **empata** com a média simples do tipo
> (≈ 1,75%) e cidade/quantidade têm importância ≈ 0% — a aba mostra isso
> abertamente. Com dados reais da empresa (preço variando com região, volume,
> sazonalidade) é onde o modelo passaria a ter vantagem. Valores medidos com o lote de 100.000 serviços.

Os modelos ficam em `dados/modelos/` (ignorado pelo Git, são regenerados pelo passo 4).
A API os carrega sob demanda e recarrega sozinha quando os arquivos mudam; se ainda
não foram treinados, a aba avisa "rode `make ml`" em vez de dar erro.

O que o tratamento em R corrige (a contagem exata de cada regra sai em
`dados/tratado/relatorio_qualidade.txt`, e `dados/raw` nunca é alterado):

- **Telefones** em 5 formatos → `(DD) 9XXXX-XXXX` (sem o 9º dígito vira `(DD) XXXX-XXXX`; dígito não é inventado).
- **Datas** `dd/mm/aaaa` e `aaaa-mm-dd` misturadas → `aaaa-mm-dd`.
- **Status** (`Concluido`, `CONCLUÍDO`, `concluído`) e **tipo de serviço** (`gesso 3d` → `Gesso 3D`) → grafia oficial.
- **Unidade** (`m linear`, `m2`) → `metro linear` / `metro quadrado`.
- **Clientes duplicados** (mesmo nome + e-mail + endereço + cidade, com espaço a mais): unificados no menor id e os serviços/manutenções são reapontados (`clientes_mapa_duplicados.csv` guarda quem foi unificado).
- **Fotos duplicadas** removidas.
- **Quantidade 0** (erro de digitação) → vazia e sinalizada; `valor_total` recalculado como quantidade × valor unitário.
- **Valor unitário ausente ("a combinar")** → imputado pela tabela oficial (ou, para Gesso 3D e Boiserie, que não têm preço oficial, pela mediana do tipo) **e sinalizado** em `servicos_qualidade.csv` (`preco_imputado`, `origem_preco`).
- **Outliers**: apenas **sinalizados** (IQR por tipo para quantidade e valor total; preço > 20% distante da referência) — não são removidos. Campos ausentes (e-mail, endereço, cidade, telefone) ficam vazios, não são inventados.

### Gerar um volume grande (ex.: 100.000 serviços)

Os números são parâmetros do gerador (`--clientes`, `--servicos`, `--manutencoes`).
Medido com 100.000 serviços (+ 20.000 clientes, ~126 mil fotos, 12.000 manutenções):
gerar ≈ 4 s, tratar em R ≈ 9 s (pico de ~424 MB de RAM), carregar no PostgreSQL ≈ 15 s;
a API e o painel continuam respondendo em menos de 0,3 s (listagens paginadas).

```bash
# Na máquina hospedeira (pastas próprias, não mexem no lote versionado)
make pipeline-100k                      # 100 mil serviços
make pipeline-100k N_SERVICOS=250000 N_CLIENTES=50000 N_MANUTENCOES=30000

# Dentro das VMs, pelo Ansible (a partir de infraestrutura/ansible/)
ansible-playbook -i inventory.ini playbook.yml --tags dados -e recarregar_dados=true \
  -e qtd_clientes=20000 -e qtd_servicos=100000 -e qtd_manutencoes=12000
```

Os CSVs grandes (`dados/raw_*`, `dados/tratado_*`) são ignorados pelo Git; para voltar ao
lote pequeno basta repetir o comando do Ansible sem os `-e qtd_*` (ou `make pipeline`).

> Sem R (ex.: o PC com Windows da demonstração): `dados/tratado/` já vem
> versionado com um lote pronto (seed 42), então `python scripts/carregar_dados.py --substituir`
> funciona sem rodar o R.

## Demonstração e evidências

O script `infraestrutura/verificar.sh` roda **no host** e prova, com saída
legível (salva em `infraestrutura/evidencias/`), cada item exigido:

```bash
./infraestrutura/verificar.sh                  # verifica tudo
./infraestrutura/verificar.sh --idempotencia   # + reexecuta o playbook e exige changed=0 / failed=0
```

Ele mostra: VMs e IPs; SSH por chave; **cloud-init aplicado** (hostname, usuário
`aluno`, sudo, chave em `authorized_keys`, login por senha desativado e o arquivo
`/etc/datasci-cloud-init.txt`); o que o Ansible instalou; uma **rodada do
simulador** dentro da VM (≥ 10 registros novos e linhas antigas intactas); o
relatório do tratamento em R e as tabelas no PostgreSQL; o proxy do devops2
respondendo `/`, `/api/resumo`, `/dados/` e `/chamados_servico.csv`; e o **Machine
Learning** no ar (`/api/ml/segmentos`, `/api/ml/estimador` e uma estimativa de orçamento
em `/api/ml/estimar`). A aba fica em `http://<ip-devops2>/#insights`.

```bash
cd infraestrutura
tofu output                       # IPs das VMs e a URL do proxy
```

- **Sistema completo pelo proxy (porta 80 do devops2):** abra no
  navegador do host a URL mostrada em `url_proxy` (ex.: `http://10.20.30.x/`).
  A documentação da API fica em `/docs`.
- **Dados do simulador pelo proxy:**
  `curl http://<ip-devops2>/chamados_servico.csv | head`
- **Por dentro das VMs (SSH com chave):**
```bash
ssh aluno@<ip-devops1> "systemctl status gesso-api --no-pager"
ssh aluno@<ip-devops1> "systemctl list-timers | grep datasci"
ssh aluno@<ip-devops1> "tail -3 /opt/datasci/dados/chamados_servico.csv"
ssh aluno@<ip-devops1> "sudo -u postgres psql -d gesso_drywall -c 'SELECT COUNT(*) FROM clientes;'"
```

> No Painel do sistema, o gráfico "Serviços por tipo" avisa
> "Hadoop indisponível" e usa os dados do Postgres: o Hadoop não é
> instalado nas VMs (ver seção abaixo sobre o job MapReduce).

Para desmontar tudo: `cd infraestrutura && tofu destroy -auto-approve`.

## Problemas comuns (Ubuntu / Linux Mint)

| Sintoma | Causa e solução |
|---|---|
| `tofu apply` falha com `Could not open '...qcow2': Permission denied` | O AppArmor bloqueia o QEMU no pool do OpenTofu. Rode `sudo sed -i 's/^#\?security_driver.*/security_driver = "none"/' /etc/libvirt/qemu.conf && sudo systemctl restart libvirtd` e repita o `apply`. |
| `tofu apply` falha com `domain 'devops1' already exists` | Sobrou uma VM criada pela metade de uma tentativa anterior. Remova: `for d in devops1 devops2; do virsh -c qemu:///system destroy $d; virsh -c qemu:///system undefine $d --nvram; done` e repita o `apply`. |
| `Could not access KVM kernel module` | Virtualização desligada na BIOS (Intel VT-x / SVM) ou faltou reiniciar após o `usermod`. |
| `libvirt_cloudinit_disk` falha | Falta o `genisoimage` (`sudo apt install genisoimage`). |
| Ansible: `UNREACHABLE` ou lock do `dpkg` | A VM ainda está iniciando/atualizando. Espere 1 minuto e rode o playbook de novo. |
| `verificar.sh` mostra "arquivo de prova do cloud-init ausente" | A VM foi criada antes desta versão do `cloud_init.cfg` (o cloud-init só roda no 1º boot). Recrie: `cd infraestrutura && tofu destroy -auto-approve && tofu apply -auto-approve`. |
| `verificar.sh --idempotencia` acusa `changed` só no "cache do apt" | Passou mais de 1 h desde o último `apt update` da VM; rode de novo e some. |
| `Rscript: command not found` no `make tratar` | Instale o R no host: `sudo apt install r-base-core`. Na VM o Ansible já instala. |
| `apt update` do host reclama de repositórios (Grafana, Jenkins...) | São repositórios de terceiros do seu PC, sem relação com o projeto. |

## Segurança

- Nenhuma senha, chave privada, `terraform.tfvars` ou `.env` real está
  neste repositório — apenas os arquivos `.example`/modelos. O `.env` de
  cada VM é gerado pelo Ansible a partir de um template.
- O `.gitignore` também exclui o estado do OpenTofu
  (`terraform.tfstate*`, `.terraform/`) e `terraform.tfvars`. O `inventory.ini`
  **é versionado** (só contém IPs privados da rede NAT e o caminho da chave,
  nunca a chave).
- Acesso às VMs só por chave pública SSH (login por senha desativado
  pelo cloud-init: `ssh_pwauth: false`). O PostgreSQL escuta apenas em
  `localhost` dentro do devops1.

## Checklist do enunciado (Checkpoint 01 - DevOps e Infraestrutura Privada)

| Requisito | Onde está |
|---|---|
| ≥ 1 VM criada por OpenTofu | `infraestrutura/main.tf` (2 VMs: devops1 e devops2), `variables.tf`, `outputs.tf` |
| cloud-init com usuário + chave SSH, com prova de que foi aplicado | `infraestrutura/cloud_init.cfg`; prova em `verificar.sh` (seção 1/2) |
| Inventory **e** playbooks do Ansible versionados | `infraestrutura/ansible/inventory.ini`, `inventory.ini.tpl`, `playbook.yml`, `templates/` |
| Playbook instala dependências, cria diretórios e é reexecutável sem erro | `playbook.yml` (idempotente; `verificar.sh --idempotencia`) |
| Simulador transferido por SSH/SCP e executado dentro da VM | tarefa `copy` do playbook + timer systemd (5 min); `simulador/simulador.py` |
| ≥ 10 registros por execução, com id + ≥ 3 variáveis + data/hora | `simulador.py` (7 campos; `--n` mínimo 10); `dados/exemplo_dados.csv` |
| Dados em CSV dentro da VM, sem perder os antigos | `/opt/datasci/dados/chamados_servico.csv` (modo *append*); `verificar.sh` seção 4 |
| Estrutura do repositório e `README` com comandos de reprodução | este arquivo |
| Sem segredos / `tfstate` / chave privada no repositório | `.gitignore` (`.env`, `terraform.tfvars`, `*.tfstate*`, chaves) |
| Próximas etapas: análise exploratória e Big Data | `scripts/gerador_dados.py` → `tratar_dados.R` → PostgreSQL; `scripts/hadoop/` (MapReduce) |

---

# Integração da Interface com a API

Front-end (`frontend/`) integrado a uma API REST em Python/FastAPI
(`api/main.py`) que lê e grava no mesmo Postgres do docker-compose.

```
navegador (frontend/)  --fetch-->  API /api/...  --SQL-->  Postgres
```

## Como rodar

```bash
./scripts/provisionar.sh                       # sobe Postgres + Adminer e instala dependências
make pipeline                                  # gerar (dados/raw) -> tratar em R (dados/tratado) -> carregar no Postgres -> ML (dados/modelos)
# (sem R no PC? use o lote já tratado e versionado:  .venv/bin/python scripts/carregar_dados.py --substituir)
make hadoop-ligar                              # liga HDFS + YARN (após reiniciar o PC)
make hadoop                                    # envia dados/tratado/servicos.csv ao HDFS e roda o MapReduce
make api                                       # sobe API + front-end
```

O gráfico **Serviços por tipo** do Painel usa o resultado do job Hadoop
(`scripts/hadoop/mapper.py` + `reducer.py`), lido do HDFS pela WebHDFS.
Depois de gerar/carregar dados novos, rode `make hadoop` de novo — o Painel
avisa quando o resultado do Hadoop está desatualizado em relação ao banco.

- Interface: http://localhost:8000
- Documentação interativa da API (Swagger): http://localhost:8000/docs

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/resumo` | Indicadores do painel |
| GET | `/api/hadoop/servicos-por-tipo` | Resultado do MapReduce (lido do HDFS) |
| GET | `/api/ml/segmentos` | Segmentação de clientes (K-Means/RFM): grupos, silhueta, top clientes |
| GET | `/api/ml/estimador` | Métricas do estimador de orçamento, importância das variáveis e catálogo |
| GET | `/api/ml/estimar` | Estimativa de orçamento: `tipo_servico`, `quantidade`, `subtipo`, `cidade` → valor + faixa de 90% |
| GET | `/api/precos` | Tabela oficial de preços |
| GET | `/api/opcoes` | Valores aceitos nos formulários |
| GET/POST | `/api/clientes` | Lista (busca, cidade, paginação) / cadastra |
| GET/PUT/DELETE | `/api/clientes/{id}` | Detalha / edita / exclui (bloqueado se houver serviços) |
| GET/POST | `/api/servicos` | Lista (busca, tipo, status, cliente) / cadastra |
| GET/PUT/DELETE | `/api/servicos/{id}` | Detalha / edita / exclui |
| GET/POST | `/api/manutencoes` | Lista (busca, status) / cadastra |
| GET/PUT/DELETE | `/api/manutencoes/{id}` | Detalha / edita / exclui |

## O que a interface demonstra

- **Formulários com validação** no navegador e na API (obrigatórios, e-mail,
  telefone com DDD, quantidade > 0, datas coerentes, status permitido).
- **Consumo dos endpoints** com `fetch` (GET, POST, PUT, DELETE).
- **Tratamento das respostas**: sucesso (aviso + linha destacada), erros de
  validação exibidos no campo correspondente (422), conflitos (409, ex.: excluir
  cliente com serviços), não encontrado (404) e API fora do ar.
- **Atualização da interface** após cada operação (lista, painel e selects).
- **Aba "Insights (ML)"**: segmentação de clientes (gráfico + tabela + top 10) e
  estimador de orçamento interativo, com a explicação de como o modelo decide.
- Regras de negócio: preço puxado da tabela oficial, total calculado
  automaticamente, serviços sem preço oficial (Gesso 3D, Boiserie) exigem valor.
