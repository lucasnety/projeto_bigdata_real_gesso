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