---

# Checkpoint 01 — DevOps e Infraestrutura Privada (Projeto Integrado)

Infraestrutura privada mínima para executar o simulador de dados do
Projeto Integrado (empresa de gesso/drywall), provisionada 100% por
código: **OpenTofu** cria as máquinas virtuais, **cloud-init** faz a
configuração inicial, e **Ansible** prepara o ambiente e instala o
simulador.

## Arquitetura

- **devops1**: roda o simulador (`/opt/datasci`), gera os dados em
  `/opt/datasci/dados/chamados_servico.csv` e os expõe por um nginx
  interno na porta 8080.
- **devops2**: só tem nginx, configurado como **proxy reverso na porta
  80**, repassando tudo para o devops1.

## Pré-requisitos (na máquina hospedeira)

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

## Como reproduzir a infraestrutura

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

## Demonstração

```bash
ssh aluno@<ip-devops1> "cat /opt/datasci/dados/chamados_servico.csv"
curl http://<ip-devops2>/chamados_servico.csv   # via proxy reverso, porta 80
```

## Segurança

Nenhuma senha, chave privada ou `terraform.tfvars` real está neste
repositório — apenas os arquivos `.example`. Acesso às VMs é só por
chave pública SSH (login por senha desativado pelo cloud-init).
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
.venv/bin/python scripts/gerador_dados.py      # gera dados/raw/*.csv
.venv/bin/python scripts/carregar_dados.py --substituir
make hadoop-ligar                              # liga HDFS + YARN (após reiniciar o PC)
make hadoop                                    # envia servicos.csv ao HDFS e roda o MapReduce
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
- Regras de negócio: preço puxado da tabela oficial, total calculado
  automaticamente, serviços sem preço oficial (Gesso 3D, Boiserie) exigem valor.
