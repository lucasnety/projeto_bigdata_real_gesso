#!/usr/bin/env bash
# =====================================================================
# verificar.sh - Evidências para a defesa (Checkpoint 01 - DevOps)
#
# Rode NO SEU PC (o host), depois de `tofu apply` e do playbook:
#
#     ./infraestrutura/verificar.sh                  # verifica tudo
#     ./infraestrutura/verificar.sh --idempotencia   # + roda o playbook de novo e exige changed=0
#
# O que ele prova, item por item do enunciado:
#   1. As VMs foram criadas pelo OpenTofu e respondem por SSH (chave pública)
#   2. O cloud-init foi aplicado: hostname, usuário, sudo, chave SSH, senha desativada
#   3. O Ansible instalou o que devia: diretórios, simulador, venv, timer, PostgreSQL, R, API
#   4. O simulador roda DENTRO da VM, gera >= 10 registros e uma nova rodada
#      NÃO perde os dados antigos (compara as linhas antes e depois)
#   5. O pipeline de dados rodou na VM: gerar -> tratar (R) -> carregar (Postgres)
#   6. O proxy reverso do devops2 (porta 80) entrega o sistema e os dados
#   7. (opcional) O playbook é idempotente: 2ª execução sem changed e sem failed
#
# A saída completa também é salva em infraestrutura/evidencias/ (pode ir no
# commit/relatório como prova).
# =====================================================================
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INV="$DIR/ansible/inventory.ini"
EVID_DIR="$DIR/evidencias"

IDEMPOTENCIA=0
for arg in "$@"; do
  case "$arg" in
    --idempotencia) IDEMPOTENCIA=1 ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "Opção desconhecida: $arg (use --help)"; exit 2 ;;
  esac
done

# Salva tudo que aparece na tela em um arquivo de evidência
if [ -z "${VERIFICAR_TEE:-}" ]; then
  mkdir -p "$EVID_DIR"
  ARQ="$EVID_DIR/verificacao_$(date +%Y%m%d_%H%M%S).txt"
  export VERIFICAR_TEE=1
  bash "${BASH_SOURCE[0]}" "$@" 2>&1 | tee "$ARQ"
  status=${PIPESTATUS[0]}
  echo "Evidência salva em: $ARQ"
  exit "$status"
fi

OKS=0
FALHAS=0
ok()    { echo "[ OK  ] $*"; OKS=$((OKS + 1)); }
falha() { echo "[FALHA] $*"; FALHAS=$((FALHAS + 1)); }
info()  { echo "[INFO ] $*"; }
secao() { echo; echo "=== $* ==="; }

echo "Verificação do ambiente - $(date '+%Y-%m-%d %H:%M:%S') - host: $(hostname)"

# ---------------------------------------------------------------------
# 0. Inventário gerado pelo OpenTofu
# ---------------------------------------------------------------------
secao "0. Inventário do Ansible (gerado pelo OpenTofu)"
if [ ! -f "$INV" ]; then
  falha "inventory.ini não encontrado em $INV (rode: cd infraestrutura && tofu apply)"
  exit 1
fi
ip_de() { sed -n "s/^$1[[:space:]]\{1,\}ansible_host=\([^[:space:]]*\).*/\1/p" "$INV" | head -1; }
IP1="$(ip_de devops1)"
IP2="$(ip_de devops2)"
USUARIO="$(sed -n 's/^ansible_user=//p' "$INV" | head -1)"
CHAVE="${SSH_KEY:-$(sed -n 's/^ansible_ssh_private_key_file=//p' "$INV" | head -1)}"
CHAVE="${CHAVE/#\~/$HOME}"
USUARIO="${USUARIO:-aluno}"
if [ -z "$IP1" ] || [ -z "$IP2" ]; then
  falha "não achei os IPs de devops1/devops2 no inventory.ini"
  exit 1
fi
ok "inventory.ini lido: devops1=$IP1  devops2=$IP2  usuário=$USUARIO"
if command -v virsh >/dev/null 2>&1; then
  info "VMs vistas pelo libvirt (virsh list):"
  virsh -c qemu:///system list --all 2>/dev/null | sed 's/^/        /'
fi

SSH_OPTS=(-i "$CHAVE" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=no
          -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)
remoto() { local ip="$1"; shift; ssh "${SSH_OPTS[@]}" "$USUARIO@$ip" "$@"; }

# ---------------------------------------------------------------------
# 1 e 2. SSH + cloud-init, em cada VM
# ---------------------------------------------------------------------
verifica_vm() {
  local nome="$1" ip="$2" saida
  secao "1/2. $nome ($ip) - acesso SSH e cloud-init"
  if ! remoto "$ip" true 2>/dev/null; then
    falha "$nome: sem acesso SSH com a chave $CHAVE (a VM está ligada? o IP do inventory.ini está certo?)"
    return 1
  fi
  ok "$nome: SSH por chave pública funcionando (usuário $USUARIO, sem senha)"

  saida="$(remoto "$ip" hostname 2>/dev/null)"
  if [ "$saida" = "$nome" ]; then ok "$nome: hostname definido pelo cloud-init = $saida"
  else falha "$nome: hostname esperado '$nome', encontrado '$saida'"; fi

  saida="$(remoto "$ip" 'cloud-init status 2>&1 | head -1' 2>/dev/null)"
  case "$saida" in
    *done*) ok "$nome: cloud-init concluído  ($saida)" ;;
    *)      falha "$nome: cloud-init não concluído  ($saida)" ;;
  esac

  if remoto "$ip" 'sudo -n true' 2>/dev/null; then ok "$nome: usuário $USUARIO com sudo sem senha"
  else falha "$nome: usuário $USUARIO sem sudo"; fi

  if remoto "$ip" 'test -s ~/.ssh/authorized_keys' 2>/dev/null; then
    ok "$nome: chave pública instalada em ~/.ssh/authorized_keys"
  else falha "$nome: ~/.ssh/authorized_keys vazio ou ausente"; fi

  saida="$(remoto "$ip" 'sudo sshd -T 2>/dev/null | grep -i "^passwordauthentication"' 2>/dev/null)"
  if [ "$saida" = "passwordauthentication no" ]; then ok "$nome: login por senha desativado no SSH ($saida)"
  else falha "$nome: login por senha NÃO está desativado ('$saida')"; fi

  saida="$(remoto "$ip" 'cat /etc/datasci-cloud-init.txt' 2>/dev/null)"
  if [ -n "$saida" ]; then
    ok "$nome: arquivo de prova do cloud-init (/etc/datasci-cloud-init.txt):"
    echo "$saida" | sed 's/^/        /'
  else
    info "$nome: /etc/datasci-cloud-init.txt ausente (VM criada antes desta versão do cloud_init.cfg; recrie com tofu destroy + apply)"
  fi
  return 0
}

verifica_vm devops1 "$IP1" && VM1_OK=1 || VM1_OK=0
verifica_vm devops2 "$IP2" && VM2_OK=1 || VM2_OK=0

# ---------------------------------------------------------------------
# 3, 4 e 5. devops1: Ansible, simulador e pipeline de dados
# ---------------------------------------------------------------------
if [ "$VM1_OK" -eq 1 ]; then
  secao "3. devops1 - o que o Ansible instalou"
  for item in /opt/datasci/app/simulador.py /opt/datasci/app/requirements.txt \
              /opt/datasci/venv/bin/python /opt/datasci/dados \
              /opt/datasci/sistema/api/main.py /opt/datasci/sistema/scripts/tratar_dados.R; do
    if remoto "$IP1" "test -e $item" 2>/dev/null; then ok "existe: $item"; else falha "não existe: $item"; fi
  done
  for servico in datasci-pipeline.timer postgresql gesso-api nginx; do
    saida="$(remoto "$IP1" "systemctl is-active $servico" 2>/dev/null)"
    if [ "$saida" = "active" ]; then ok "serviço ativo: $servico"; else falha "serviço $servico: '$saida'"; fi
  done
  saida="$(remoto "$IP1" 'Rscript --version 2>&1 | head -1' 2>/dev/null)"
  if [ -n "$saida" ]; then ok "R instalado: $saida"; else falha "R (Rscript) não instalado"; fi
  info "próximas execuções do timer:"
  remoto "$IP1" 'systemctl list-timers datasci-pipeline.timer --no-pager 2>/dev/null | head -3' 2>/dev/null | sed 's/^/        /'

  secao "4. devops1 - simulador: >= 10 registros por rodada e sem perder dados antigos"
  CSV=/opt/datasci/dados/chamados_servico.csv
  ANTES="$(remoto "$IP1" "wc -l < $CSV" 2>/dev/null | tr -d ' ')"
  if [ -z "$ANTES" ]; then
    falha "CSV do simulador não encontrado ($CSV)"
  else
    HASH_ANTES="$(remoto "$IP1" "head -n $ANTES $CSV | md5sum" 2>/dev/null)"
    info "antes da rodada: $ANTES linhas (inclui cabeçalho)"
    info "disparando uma rodada do pipeline: systemctl start datasci-pipeline.service"
    if remoto "$IP1" 'sudo systemctl start datasci-pipeline.service' 2>/dev/null; then
      DEPOIS="$(remoto "$IP1" "wc -l < $CSV" 2>/dev/null | tr -d ' ')"
      HASH_DEPOIS="$(remoto "$IP1" "head -n $ANTES $CSV | md5sum" 2>/dev/null)"
      info "depois da rodada: $DEPOIS linhas"
      NOVOS=$((DEPOIS - ANTES))
      if [ "$NOVOS" -ge 10 ]; then ok "a rodada gerou $NOVOS registros novos (mínimo exigido: 10)"
      else falha "a rodada gerou só $NOVOS registros (mínimo exigido: 10)"; fi
      if [ "$HASH_ANTES" = "$HASH_DEPOIS" ]; then ok "dados antigos preservados (as $ANTES primeiras linhas continuam idênticas)"
      else falha "os dados antigos foram alterados/perdidos"; fi
      info "últimas linhas do CSV:"
      remoto "$IP1" "tail -n 3 $CSV" 2>/dev/null | sed 's/^/        /'
    else
      falha "não consegui iniciar datasci-pipeline.service"
    fi
    info "cabeçalho (id + variáveis + data/hora): $(remoto "$IP1" "head -n 1 $CSV" 2>/dev/null)"
  fi

  secao "5. devops1 - pipeline de dados: gerar (Python) -> tratar (R) -> carregar (PostgreSQL)"
  REL=/opt/datasci/sistema/dados/tratado/relatorio_qualidade.txt
  if remoto "$IP1" "test -s $REL" 2>/dev/null; then
    ok "o tratamento em R rodou e deixou o relatório de qualidade ($REL):"
    remoto "$IP1" "sed -n '4,8p' $REL" 2>/dev/null | sed 's/^/        /'
  else
    falha "relatório de qualidade do R não encontrado ($REL)"
  fi
  CONSULTA="$(remoto "$IP1" 'sudo -u postgres env PGCLIENTENCODING=UTF8 psql -d gesso_drywall -tA -F"|"' 2>/dev/null <<'EOSQL'
SELECT 'clientes', COUNT(*) FROM clientes
UNION ALL SELECT 'servicos', COUNT(*) FROM servicos
UNION ALL SELECT 'fotos', COUNT(*) FROM fotos
UNION ALL SELECT 'manutencoes', COUNT(*) FROM manutencoes
UNION ALL SELECT 'status_fora_do_padrao', COUNT(*) FROM servicos WHERE status NOT IN ('orçado','em andamento','concluído')
UNION ALL SELECT 'telefone_fora_do_padrao', COUNT(*) FROM clientes WHERE telefone IS NOT NULL AND telefone !~ '^\([0-9]{2}\) 9?[0-9]{4}-[0-9]{4}$'
UNION ALL SELECT 'tipos_distintos', COUNT(DISTINCT tipo_servico) FROM servicos
UNION ALL SELECT 'servicos_valor_total_inconsistente', COUNT(*) FROM servicos WHERE quantidade IS NOT NULL AND valor_unitario_aplicado IS NOT NULL AND ABS(valor_total - ROUND(quantidade * valor_unitario_aplicado, 2)) > 0.01;
EOSQL
)"
  if [ -z "$CONSULTA" ]; then
    falha "não consegui consultar o PostgreSQL da VM"
  else
    valor() { echo "$CONSULTA" | sed -n "s/^$1|//p" | head -1; }
    for t in clientes servicos fotos manutencoes; do
      n="$(valor "$t")"
      if [ "${n:-0}" -gt 0 ] 2>/dev/null; then ok "tabela $t carregada: $n linhas"; else falha "tabela $t vazia"; fi
    done
    [ "$(valor status_fora_do_padrao)" = "0" ] && ok "status dos serviços padronizados (0 fora do padrão)" || falha "há status de serviço fora do padrão: $(valor status_fora_do_padrao)"
    [ "$(valor telefone_fora_do_padrao)" = "0" ] && ok "telefones padronizados (0 fora do padrão)" || falha "há telefones fora do padrão: $(valor telefone_fora_do_padrao)"
    [ "$(valor tipos_distintos)" = "7" ] && ok "7 tipos de serviço (sem grafias duplicadas)" || falha "tipos de serviço distintos = $(valor tipos_distintos) (esperado 7)"
    [ "$(valor servicos_valor_total_inconsistente)" = "0" ] && ok "valor_total = quantidade x valor unitário em todos os serviços" || falha "valor_total inconsistente em $(valor servicos_valor_total_inconsistente) serviços"
  fi
fi

# ---------------------------------------------------------------------
# 6. devops2: proxy reverso
# ---------------------------------------------------------------------
secao "6. devops2 ($IP2) - proxy reverso na porta 80"
if ! command -v curl >/dev/null 2>&1; then
  falha "curl não está instalado no host"
else
  http() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1" 2>/dev/null; }
  c="$(http "http://$IP2/")";                      [ "$c" = "200" ] && ok "GET http://$IP2/  -> 200 (front-end do sistema via proxy)" || falha "GET http://$IP2/ -> $c"
  c="$(http "http://$IP2/api/resumo")";            [ "$c" = "200" ] && ok "GET /api/resumo  -> 200 (API via proxy)" || falha "GET /api/resumo -> $c"
  c="$(http "http://$IP2/dados/")";                [ "$c" = "200" ] && ok "GET /dados/  -> 200 (arquivos do simulador via proxy)" || falha "GET /dados/ -> $c"
  c="$(http "http://$IP2/chamados_servico.csv")";  [ "$c" = "200" ] && ok "GET /chamados_servico.csv  -> 200" || falha "GET /chamados_servico.csv -> $c"
  resumo="$(curl -s --max-time 10 "http://$IP2/api/resumo" 2>/dev/null | head -c 160)"
  [ -n "$resumo" ] && info "resposta de /api/resumo: $resumo ..."
fi

# ---------------------------------------------------------------------
# 7. Idempotência do playbook (opcional)
# ---------------------------------------------------------------------
if [ "$IDEMPOTENCIA" -eq 1 ]; then
  secao "7. Idempotência: reexecutando o playbook"
  if ! command -v ansible-playbook >/dev/null 2>&1; then
    falha "ansible-playbook não encontrado no host"
  else
    SAIDA="$(cd "$DIR/ansible" && ansible-playbook playbook.yml 2>&1)"
    RECAP="$(echo "$SAIDA" | grep -E '^(devops1|devops2) +:')"
    echo "$RECAP" | sed 's/^/        /'
    if [ -z "$RECAP" ]; then
      falha "o playbook não chegou ao resumo final (PLAY RECAP). Últimas linhas:"
      echo "$SAIDA" | tail -n 15 | sed 's/^/        /'
    elif echo "$RECAP" | grep -Eq 'failed=[1-9]|unreachable=[1-9]'; then
      falha "a reexecução do playbook teve falhas"
    elif echo "$RECAP" | grep -Eq 'changed=[1-9]'; then
      falha "a reexecução alterou algo (changed > 0) - veja quais tarefas acima. (Se passou mais de 1h desde o 1º apt update, o 'cache do apt' conta como changed.)"
    else
      ok "playbook reexecutado: changed=0 e failed=0 (idempotente)"
    fi
  fi
fi

# ---------------------------------------------------------------------
secao "Resumo"
echo "Verificações OK: $OKS   Falhas: $FALHAS"
if [ "$FALHAS" -eq 0 ]; then echo "RESULTADO: tudo certo para a demonstração."; exit 0
else echo "RESULTADO: há itens a corrigir (veja as linhas [FALHA])."; exit 1; fi
