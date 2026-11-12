#!/usr/bin/env Rscript
# =====================================================================
# tratar_dados.R  -  Tratamento (limpeza) dos dados gerados
# Projeto Integrado - Empresa de Gesso e Drywall
#
# Fluxo completo do projeto:
#
#   gerador_dados.py --> dados/raw/*.csv --> tratar_dados.R --> dados/tratado/*.csv --> carregar_dados.py --> Postgres
#   (simulador)          (data lake: bruto)  (limpeza em R)      (dado confiavel)        (banco)           (API/front)
#
# O gerador cria dados SUJOS de proposito (telefones em varios formatos,
# datas em dd/mm/aaaa e aaaa-mm-dd, status com grafias diferentes,
# clientes duplicados, precos ausentes, quantidade zero, fotos repetidas...).
# Este script corrige o que e corrigivel, sinaliza o que e duvidoso e NUNCA
# altera os arquivos de dados/raw (o bruto fica preservado, como num data lake).
#
# Usa somente o R base (nenhum pacote para instalar).
#
# Uso:
#   Rscript scripts/tratar_dados.R
#   Rscript scripts/tratar_dados.R --entrada dados/raw --saida dados/tratado
#
# Saidas (em dados/tratado/):
#   clientes.csv, preco_por_m.csv, servicos.csv, fotos.csv, manutencoes.csv
#       -> mesmas colunas do schema do banco (carregar_dados.py le direto)
#   servicos_qualidade.csv       -> flags por servico (preco imputado, outliers...)
#   clientes_mapa_duplicados.csv -> quem foi unificado com quem (rastreabilidade)
#   relatorio_qualidade.csv/.txt -> quantas correcoes de cada tipo foram feitas
# =====================================================================

# Garante leitura/escrita em UTF-8 mesmo em shell sem locale (ex.: SSH/Ansible).
invisible(suppressWarnings(try(Sys.setlocale("LC_CTYPE", "C.UTF-8"), silent = TRUE)))
options(stringsAsFactors = FALSE, warn = 1)

# ---------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------
args <- commandArgs(trailingOnly = TRUE)
pegar_arg <- function(nome, padrao) {
  i <- match(nome, args)
  if (!is.na(i) && i < length(args)) args[i + 1] else padrao
}
entrada <- pegar_arg("--entrada", "dados/raw")
saida   <- pegar_arg("--saida",   "dados/tratado")

if (!dir.exists(entrada)) {
  stop(sprintf("Pasta '%s' nao encontrada. Rode antes: python scripts/gerador_dados.py", entrada))
}
dir.create(saida, showWarnings = FALSE, recursive = TRUE)

# ---------------------------------------------------------------------
# Dicionarios de regras de negocio (acentos como \u para independer de locale)
# ---------------------------------------------------------------------
TIPOS_OFICIAIS <- c(
  "sanca"             = "Sanca",
  "divisoria drywall" = "Divisória Drywall",
  "forro drywall"     = "Forro Drywall",
  "gesso liso"        = "Gesso Liso",
  "moldura de gesso"  = "Moldura de Gesso",
  "gesso 3d"          = "Gesso 3D",
  "boiserie"          = "Boiserie"
)
UNIDADE_DO_TIPO <- c(
  "Sanca" = "metro linear", "Divisória Drywall" = "metro quadrado",
  "Forro Drywall" = "metro quadrado", "Gesso Liso" = "metro quadrado",
  "Moldura de Gesso" = "metro linear", "Gesso 3D" = "metro quadrado",
  "Boiserie" = "metro linear"
)
STATUS_SERVICO <- c(
  "orcado"       = "orçado",
  "em andamento" = "em andamento",
  "concluido"    = "concluído"
)
STATUS_MANUTENCAO <- c(
  "solicitada" = "solicitada",
  "agendada"   = "agendada",
  "concluida"  = "concluída"
)

# ---------------------------------------------------------------------
# Funcoes auxiliares
# ---------------------------------------------------------------------
LETRAS_COM_ACENTO <- paste0(
  "áàâãäéèêëíìîï",
  "óòôõöúùûüç",
  "ÁÀÂÃÄÉÈÊËÍÌÎÏ",
  "ÓÒÔÕÖÚÙÛÜÇ")
LETRAS_SEM_ACENTO <- "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC"
stopifnot(nchar(LETRAS_COM_ACENTO) == nchar(LETRAS_SEM_ACENTO))

sem_acento <- function(x) chartr(LETRAS_COM_ACENTO, LETRAS_SEM_ACENTO, x)
chave_texto <- function(x) tolower(sem_acento(x))

# Remove espacos nas pontas, colapsa espacos repetidos e troca "" por NA
limpar_texto <- function(x) {
  x <- trimws(gsub("[[:space:]]+", " ", as.character(x)))
  x[!is.na(x) & x == ""] <- NA_character_
  x
}

num <- function(x) suppressWarnings(as.numeric(x))
conta <- function(l) sum(l, na.rm = TRUE)

# Le CSV como texto, em UTF-8, tolerando BOM (o gerador grava utf-8-sig)
ler_csv <- function(caminho) {
  if (!file.exists(caminho)) stop(sprintf("Arquivo nao encontrado: %s", caminho))
  bruto <- readBin(caminho, "raw", file.info(caminho)$size)
  if (length(bruto) >= 3 && all(bruto[1:3] == as.raw(c(0xef, 0xbb, 0xbf)))) bruto <- bruto[-(1:3)]
  tmp <- tempfile(fileext = ".csv")
  on.exit(unlink(tmp))
  writeBin(bruto, tmp)
  read.csv(tmp, colClasses = "character", na.strings = character(0),
           encoding = "UTF-8", check.names = FALSE, stringsAsFactors = FALSE)
}

# Grava CSV em UTF-8 (com BOM, para o Excel abrir os acentos) sem depender do locale
campo_csv <- function(x) {
  x <- as.character(x)
  vazio <- is.na(x)
  x[vazio] <- ""
  precisa_aspas <- !vazio & grepl("[\",\n\r]", x)
  x[precisa_aspas] <- paste0("\"", gsub("\"", "\"\"", x[precisa_aspas], fixed = TRUE), "\"")
  x
}
escrever_csv <- function(df, caminho) {
  colunas <- lapply(df, campo_csv)
  linhas <- c(paste(names(df), collapse = ","), do.call(paste, c(colunas, sep = ",")))
  con <- file(caminho, "wb")
  on.exit(close(con))
  writeBin(as.raw(c(0xef, 0xbb, 0xbf)), con)
  writeLines(enc2utf8(linhas), con, useBytes = TRUE)
}
fmt_dec <- function(x) ifelse(is.na(x), NA_character_, formatC(x, format = "f", digits = 2))
fmt_int <- function(x) ifelse(is.na(x), NA_character_, as.character(as.integer(x)))

# Datas: aceita aaaa-mm-dd e dd/mm/aaaa; devolve objeto Date (NA se invalida)
RE_ISO <- "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
RE_BR  <- "^[0-9]{2}/[0-9]{2}/[0-9]{4}$"
padronizar_data <- function(x) {
  x <- limpar_texto(x)
  d <- as.Date(rep(NA_character_, length(x)))
  iso <- !is.na(x) & grepl(RE_ISO, x)
  br  <- !is.na(x) & grepl(RE_BR, x)
  d[iso] <- as.Date(x[iso], format = "%Y-%m-%d")
  d[br]  <- as.Date(x[br],  format = "%d/%m/%Y")
  d
}
data_para_texto <- function(d) ifelse(is.na(d), NA_character_, format(d, "%Y-%m-%d"))

# Telefone brasileiro -> (DD) 9XXXX-XXXX (11 digitos) ou (DD) XXXX-XXXX (10 digitos)
padronizar_telefone <- function(x) {
  dig <- gsub("[^0-9]", "", x)
  dig[is.na(x)] <- NA_character_
  tem_ddi <- !is.na(dig) & nchar(dig) %in% c(12, 13) & substr(dig, 1, 2) == "55"
  dig[tem_ddi] <- substr(dig[tem_ddi], 3, nchar(dig[tem_ddi]))
  out <- rep(NA_character_, length(dig))
  k11 <- !is.na(dig) & nchar(dig) == 11 & substr(dig, 3, 3) == "9"
  k10 <- !is.na(dig) & nchar(dig) == 10
  out[k11] <- sprintf("(%s) %s-%s", substr(dig[k11], 1, 2), substr(dig[k11], 3, 7), substr(dig[k11], 8, 11))
  out[k10] <- sprintf("(%s) %s-%s", substr(dig[k10], 1, 2), substr(dig[k10], 3, 6), substr(dig[k10], 7, 10))
  list(valor = out, sem_nono_digito = k10, ddi_removido = tem_ddi)
}

# Outlier pela regra do IQR (1,5 x amplitude interquartil), calculada POR GRUPO.
# Se o IQR do grupo for 0 (quase todos os valores iguais) a regra degenera e
# marcaria como "outlier" qualquer variacao normal; nesse caso o grupo e ignorado.
flag_iqr <- function(x, grupo, minimo = 8) {
  flag <- rep(FALSE, length(x))
  for (g in unique(grupo[!is.na(grupo)])) {
    i <- which(grupo == g & !is.na(x))
    if (length(i) < minimo) next
    q <- quantile(x[i], c(0.25, 0.75), names = FALSE)
    iqr <- q[2] - q[1]
    if (iqr == 0) next
    flag[i] <- x[i] < q[1] - 1.5 * iqr | x[i] > q[2] + 1.5 * iqr
  }
  flag
}

# Relatorio de qualidade
rel <- list()
reg <- function(tabela, regra, qtd, acao) {
  rel[[length(rel) + 1]] <<- data.frame(tabela = tabela, regra = regra,
                                        quantidade = as.integer(qtd), acao = acao)
}

cat("=== Tratamento dos dados (R) ===\n")
cat("Entrada:", normalizePath(entrada), "\n")
cat("Saida  :", normalizePath(saida), "\n\n")

# =====================================================================
# 1) CLIENTES
# =====================================================================
cli <- ler_csv(file.path(entrada, "clientes.csv"))
cli$id_cliente <- as.integer(cli$id_cliente)
cli <- cli[order(cli$id_cliente), ]
n_cli_entrada <- nrow(cli)

nome_orig <- cli$nome_completo
cli$nome_completo <- limpar_texto(cli$nome_completo)
reg("clientes", "nome com espacos repetidos/nas pontas",
    conta(!is.na(nome_orig) & nome_orig != cli$nome_completo), "espacos normalizados")
reg("clientes", "nome vazio", conta(is.na(cli$nome_completo)), "registro mantido (revisar)")

tel_orig <- limpar_texto(cli$telefone)
tel <- padronizar_telefone(tel_orig)
cli$telefone <- tel$valor
reg("clientes", "telefone ausente", conta(is.na(tel_orig)), "mantido vazio (nao inventado)")
reg("clientes", "telefone fora do padrao (parenteses, +55, sem separador...)",
    conta(!is.na(tel_orig) & !is.na(tel$valor) & tel_orig != tel$valor), "padronizado")
reg("clientes", "telefone sem o 9o digito (10 digitos)", conta(tel$sem_nono_digito),
    "formatado como (DD) XXXX-XXXX; digito nao inventado")
reg("clientes", "telefone invalido/nao reconhecido", conta(!is.na(tel_orig) & is.na(tel$valor)),
    "descartado (vazio)")

email_orig <- limpar_texto(cli$email)
email <- tolower(email_orig)
email_valido <- !is.na(email) & grepl("^[^@ ]+@[^@ ]+\\.[^@ ]+$", email)
reg("clientes", "e-mail ausente", conta(is.na(email_orig)), "mantido vazio")
reg("clientes", "e-mail em maiusculas", conta(!is.na(email_orig) & email_orig != email), "convertido para minusculas")
reg("clientes", "e-mail invalido", conta(!is.na(email) & !email_valido), "descartado (vazio)")
email[!email_valido] <- NA_character_
cli$email <- email

cli$endereco <- limpar_texto(cli$endereco)
cli$cidade <- limpar_texto(cli$cidade)
cli$origem_contato <- limpar_texto(cli$origem_contato)
reg("clientes", "endereco ausente", conta(is.na(cli$endereco)), "mantido vazio")
reg("clientes", "cidade ausente", conta(is.na(cli$cidade)), "mantido vazio (cidade nao e deduzida)")

dc_orig <- limpar_texto(cli$data_cadastro)
dc <- padronizar_data(dc_orig)
reg("clientes", "data de cadastro em dd/mm/aaaa", conta(grepl(RE_BR, dc_orig)), "convertida para aaaa-mm-dd")
reg("clientes", "data de cadastro invalida/ausente", conta(is.na(dc)), "mantida vazia")
reg("clientes", "data de cadastro no futuro", conta(dc > Sys.Date()), "mantida (revisar)")
cli$data_cadastro <- data_para_texto(dc)

# --- Duplicidade: mesmo nome (sem diferenca de espacos/caixa), e-mail, endereco e cidade
chave_cli <- paste(chave_texto(ifelse(is.na(cli$nome_completo), "", cli$nome_completo)),
                   ifelse(is.na(cli$email), "", cli$email),
                   chave_texto(ifelse(is.na(cli$endereco), "", cli$endereco)),
                   chave_texto(ifelse(is.na(cli$cidade), "", cli$cidade)), sep = "|")
id_mantido <- as.integer(tapply(cli$id_cliente, chave_cli, min)[chave_cli])
eh_duplicado <- cli$id_cliente != id_mantido

# Se o registro mantido nao tem telefone e o duplicado tem, aproveita o do duplicado
for (i in which(eh_duplicado & !is.na(cli$telefone))) {
  alvo <- which(cli$id_cliente == id_mantido[i])
  if (length(alvo) == 1 && is.na(cli$telefone[alvo])) cli$telefone[alvo] <- cli$telefone[i]
}
mapa_dup <- data.frame(id_duplicado = cli$id_cliente[eh_duplicado], id_mantido = id_mantido[eh_duplicado])
reg("clientes", "clientes duplicados (mesmo nome+e-mail+endereco+cidade)", nrow(mapa_dup),
    "unificados no menor id; servicos/manutencoes reapontados")
cli_final <- cli[!eh_duplicado, ]

# =====================================================================
# 2) PRECO_POR_M (tabela oficial de precos)
# =====================================================================
pre <- ler_csv(file.path(entrada, "preco_por_m.csv"))
pre$id_preco <- as.integer(pre$id_preco)
pre$tipo_servico <- unname(TIPOS_OFICIAIS[chave_texto(limpar_texto(pre$tipo_servico))])
pre$subtipo <- limpar_texto(pre$subtipo)
pre$unidade_medida <- unname(UNIDADE_DO_TIPO[pre$tipo_servico])
pre$valor <- num(pre$valor)
pre$data_atualizacao <- data_para_texto(padronizar_data(pre$data_atualizacao))
chave_tabela <- paste(pre$tipo_servico, ifelse(is.na(pre$subtipo), "", pre$subtipo), sep = "|")

# =====================================================================
# 3) SERVICOS
# =====================================================================
srv <- ler_csv(file.path(entrada, "servicos.csv"))
n_srv_entrada <- nrow(srv)
srv$id_servico <- as.integer(srv$id_servico)
srv$id_cliente <- as.integer(srv$id_cliente)
srv <- srv[order(srv$id_servico), ]

# 3.1 cliente (reaponta duplicados)
pos <- match(srv$id_cliente, mapa_dup$id_duplicado)
reg("servicos", "servicos ligados a cliente duplicado", conta(!is.na(pos)), "id_cliente reapontado ao cliente mantido")
srv$id_cliente[!is.na(pos)] <- mapa_dup$id_mantido[pos[!is.na(pos)]]
reg("servicos", "servicos com cliente inexistente (orfaos)", conta(!(srv$id_cliente %in% cli_final$id_cliente)),
    "mantidos e sinalizados (revisar)")

# 3.2 tipo de servico
tipo_orig <- limpar_texto(srv$tipo_servico)
tipo <- unname(TIPOS_OFICIAIS[chave_texto(tipo_orig)])
reg("servicos", "tipo_servico com grafia diferente (ex.: minusculas)", conta(!is.na(tipo) & tipo != tipo_orig),
    "padronizado para o nome oficial")
reg("servicos", "tipo_servico nao reconhecido", conta(is.na(tipo)), "mantido o original (revisar)")
tipo[is.na(tipo)] <- tipo_orig[is.na(tipo)]
srv$tipo_servico <- tipo
srv$subtipo <- limpar_texto(srv$subtipo)
srv$descricao_detalhada <- limpar_texto(srv$descricao_detalhada)

# 3.3 unidade de medida
un_orig <- limpar_texto(srv$unidade_medida)
un_chave <- chave_texto(un_orig)
un <- rep(NA_character_, nrow(srv))
un[un_chave %in% c("metro linear", "m linear", "ml", "m")] <- "metro linear"
un[un_chave %in% c("metro quadrado", "m2", "m^2", "m²")] <- "metro quadrado"
reg("servicos", "unidade_medida abreviada (m linear / m2)", conta(!is.na(un) & un != un_orig), "padronizada (metro linear / metro quadrado)")
esperada <- unname(UNIDADE_DO_TIPO[srv$tipo_servico])
reg("servicos", "unidade ausente/desconhecida", conta(is.na(un)), "preenchida pela unidade padrao do tipo")
un[is.na(un)] <- esperada[is.na(un)]
reg("servicos", "unidade incompativel com o tipo (ex.: sanca em m2)", conta(!is.na(esperada) & un != esperada), "mantida (revisar)")
srv$unidade_medida <- un

# 3.4 status
st_orig <- limpar_texto(srv$status)
st <- unname(STATUS_SERVICO[chave_texto(st_orig)])
reg("servicos", "status com grafia diferente (Concluido/CONCLUIDO...)", conta(!is.na(st) & st != st_orig),
    "padronizado (orcado / em andamento / concluido, com acento)")
reg("servicos", "status nao reconhecido", conta(is.na(st)), "mantido vazio (revisar)")
srv$status <- st

# 3.5 data de execucao
de_orig <- limpar_texto(srv$data_execucao)
de <- padronizar_data(de_orig)
reg("servicos", "data_execucao em dd/mm/aaaa", conta(grepl(RE_BR, de_orig)), "convertida para aaaa-mm-dd")
reg("servicos", "data_execucao invalida/ausente", conta(is.na(de)), "mantida vazia")
reg("servicos", "data_execucao no futuro", conta(de > Sys.Date()), "mantida (revisar)")
srv$data_execucao <- data_para_texto(de)

# 3.6 quantidade
qtd_orig <- num(srv$quantidade)
qtd_invalida <- !is.na(qtd_orig) & qtd_orig <= 0
reg("servicos", "quantidade zero/negativa (erro de digitacao)", conta(qtd_invalida),
    "quantidade e valor_total ficam vazios; sinalizado em servicos_qualidade.csv")
qtd <- qtd_orig
qtd[qtd_invalida] <- NA_real_
reg("servicos", "quantidade ausente", conta(is.na(qtd_orig)), "mantida vazia")

# 3.7 preco unitario (ausente = "a combinar")
chave_preco <- paste(srv$tipo_servico, ifelse(is.na(srv$subtipo), "", srv$subtipo), sep = "|")
preco_inf <- num(srv$valor_unitario_aplicado)
preco_tab <- pre$valor[match(chave_preco, chave_tabela)]
# tipos sem linha na tabela oficial (Gesso 3D, Boiserie): mediana dos precos informados do proprio tipo
med_tipo <- tapply(preco_inf, chave_preco, median, na.rm = TRUE)
preco_med <- as.numeric(med_tipo[chave_preco])
origem_preco <- rep(NA_character_, nrow(srv))
preco <- preco_inf
origem_preco[!is.na(preco_inf)] <- "informado"
usar_tab <- is.na(preco) & !is.na(preco_tab)
preco[usar_tab] <- preco_tab[usar_tab]; origem_preco[usar_tab] <- "tabela_oficial"
usar_med <- is.na(preco) & !is.na(preco_med)
preco[usar_med] <- preco_med[usar_med]; origem_preco[usar_med] <- "mediana_do_tipo"
preco_imputado <- !is.na(preco) & is.na(preco_inf)
reg("servicos", "valor unitario ausente (\"a combinar\")", conta(is.na(preco_inf)),
    "imputado e sinalizado (preco_imputado)")
reg("servicos", "  -> imputado pela tabela oficial de precos", conta(origem_preco == "tabela_oficial"), "origem_preco = tabela_oficial")
reg("servicos", "  -> imputado pela mediana do tipo (sem preco oficial)", conta(origem_preco == "mediana_do_tipo"), "origem_preco = mediana_do_tipo")
reg("servicos", "tipos de servico sem linha na tabela oficial de precos",
    length(unique(srv$tipo_servico[!(chave_preco %in% chave_tabela)])),
    "tipos distintos (ex.: Gesso 3D, Boiserie) - recomenda-se cadastrar na tabela")
srv$valor_unitario_aplicado <- preco

# 3.8 valor total = quantidade x preco unitario (recalculado)
total_orig <- num(srv$valor_total)
total <- ifelse(!is.na(qtd) & !is.na(preco), round(qtd * preco, 2), NA_real_)
reg("servicos", "valor_total divergente de quantidade x valor unitario (>R$0,01)",
    conta(!is.na(total_orig) & !preco_imputado & !is.na(total) & abs(total_orig - total) > 0.01), "recalculado")
reg("servicos", "valor_total ausente que pode ser calculado", conta(is.na(total_orig) & !is.na(total)), "calculado")
reg("servicos", "valor_total continua vazio (sem quantidade valida)", conta(is.na(total)), "mantido vazio")
srv$valor_total <- total

# 3.9 outliers (IQR por tipo+subtipo) - apenas SINALIZA, nao remove
grupo <- chave_preco
out_qtd <- flag_iqr(qtd, grupo)
out_total <- flag_iqr(total, grupo)
# Preco unitario: a maioria dos servicos usa o preco de tabela (IQR = 0), entao o IQR
# nao serve. A regra de negocio e: preco informado mais de 20% distante da referencia
# (tabela oficial; ou mediana do tipo quando nao ha preco oficial).
referencia <- ifelse(!is.na(preco_tab), preco_tab, preco_med)
fora_faixa <- !is.na(preco_inf) & !is.na(referencia) & abs(preco_inf / referencia - 1) > 0.20
reg("servicos", "outlier de quantidade (IQR por tipo)", conta(out_qtd), "sinalizado, nao removido")
reg("servicos", "outlier de valor_total (IQR por tipo)", conta(out_total), "sinalizado, nao removido")
reg("servicos", "preco informado >20% distante da referencia (tabela/mediana)", conta(fora_faixa), "sinalizado, nao removido")

qualidade <- data.frame(
  id_servico = srv$id_servico,
  preco_imputado = preco_imputado,
  origem_preco = origem_preco,
  quantidade_invalida = qtd_invalida,
  outlier_quantidade = out_qtd,
  preco_fora_da_faixa = fora_faixa,
  outlier_valor_total = out_total
)
qualidade$preco_imputado <- ifelse(qualidade$preco_imputado, "true", "false")
qualidade$quantidade_invalida <- ifelse(qualidade$quantidade_invalida, "true", "false")
qualidade$outlier_quantidade <- ifelse(qualidade$outlier_quantidade, "true", "false")
qualidade$preco_fora_da_faixa <- ifelse(qualidade$preco_fora_da_faixa, "true", "false")
qualidade$outlier_valor_total <- ifelse(qualidade$outlier_valor_total, "true", "false")

srv$quantidade <- qtd
srv_saida <- data.frame(
  id_servico = fmt_int(srv$id_servico), id_cliente = fmt_int(srv$id_cliente),
  tipo_servico = srv$tipo_servico, subtipo = srv$subtipo,
  descricao_detalhada = srv$descricao_detalhada, unidade_medida = srv$unidade_medida,
  quantidade = fmt_dec(srv$quantidade), valor_unitario_aplicado = fmt_dec(srv$valor_unitario_aplicado),
  valor_total = fmt_dec(srv$valor_total), data_execucao = srv$data_execucao, status = srv$status)

# =====================================================================
# 4) FOTOS
# =====================================================================
fot <- ler_csv(file.path(entrada, "fotos.csv"))
n_fot_entrada <- nrow(fot)
fot$id_foto <- as.integer(fot$id_foto)
fot$id_servico <- as.integer(fot$id_servico)
fot <- fot[order(fot$id_foto), ]
fot$caminho_arquivo <- limpar_texto(fot$caminho_arquivo)
fot$descricao <- limpar_texto(fot$descricao)
du_orig <- limpar_texto(fot$data_upload)
du <- padronizar_data(du_orig)
reg("fotos", "data_upload em dd/mm/aaaa", conta(grepl(RE_BR, du_orig)), "convertida para aaaa-mm-dd")
reg("fotos", "data_upload invalida/ausente", conta(is.na(du)), "mantida vazia")
fot$data_upload <- data_para_texto(du)
reg("fotos", "descricao ausente", conta(is.na(fot$descricao)), "mantida vazia")
dup_foto <- duplicated(paste(fot$id_servico, fot$caminho_arquivo, sep = "|"))
reg("fotos", "fotos duplicadas (mesmo servico + mesmo arquivo)", conta(dup_foto), "removidas (mantida a 1a)")
fot <- fot[!dup_foto, ]
reg("fotos", "fotos de servico inexistente (orfas)", conta(!(fot$id_servico %in% srv$id_servico)), "mantidas e sinalizadas (revisar)")
fot_saida <- data.frame(id_foto = fmt_int(fot$id_foto), id_servico = fmt_int(fot$id_servico),
                        caminho_arquivo = fot$caminho_arquivo, descricao = fot$descricao,
                        data_upload = fot$data_upload)

# =====================================================================
# 5) MANUTENCOES
# =====================================================================
man <- ler_csv(file.path(entrada, "manutencoes.csv"))
n_man_entrada <- nrow(man)
man$id_manutencao <- as.integer(man$id_manutencao)
man$id_cliente <- as.integer(man$id_cliente)
man$id_servico_origem <- as.integer(ifelse(limpar_texto(man$id_servico_origem) %in% NA, NA, man$id_servico_origem))
man <- man[order(man$id_manutencao), ]

pos <- match(man$id_cliente, mapa_dup$id_duplicado)
reg("manutencoes", "manutencoes ligadas a cliente duplicado", conta(!is.na(pos)), "id_cliente reapontado ao cliente mantido")
man$id_cliente[!is.na(pos)] <- mapa_dup$id_mantido[pos[!is.na(pos)]]
reg("manutencoes", "sem servico de origem vinculado", conta(is.na(man$id_servico_origem)), "mantido vazio (garantia sem vinculo)")
reg("manutencoes", "servico de origem inexistente", conta(!is.na(man$id_servico_origem) & !(man$id_servico_origem %in% srv$id_servico)),
    "mantido e sinalizado (revisar)")
cli_do_servico <- srv$id_cliente[match(man$id_servico_origem, srv$id_servico)]
reg("manutencoes", "cliente diferente do cliente do servico de origem",
    conta(!is.na(cli_do_servico) & cli_do_servico != man$id_cliente), "mantido (revisar)")

man$descricao <- limpar_texto(man$descricao)
man$preco <- num(man$preco)
reg("manutencoes", "preco ausente (garantia / a combinar)", conta(is.na(man$preco)), "mantido vazio (nao imputado)")
reg("manutencoes", "preco zero ou negativo", conta(!is.na(man$preco) & man$preco <= 0), "mantido (revisar)")

ds_orig <- limpar_texto(man$data_solicitacao)
dx_orig <- limpar_texto(man$data_execucao)
ds <- padronizar_data(ds_orig)
dx <- padronizar_data(dx_orig)
reg("manutencoes", "datas em dd/mm/aaaa", conta(grepl(RE_BR, ds_orig)) + conta(grepl(RE_BR, dx_orig)), "convertidas para aaaa-mm-dd")
reg("manutencoes", "data_execucao anterior a data_solicitacao", conta(!is.na(ds) & !is.na(dx) & dx < ds), "mantida (revisar)")

stm_orig <- limpar_texto(man$status)
stm <- unname(STATUS_MANUTENCAO[chave_texto(stm_orig)])
reg("manutencoes", "status com grafia diferente", conta(!is.na(stm) & stm != stm_orig), "padronizado")
reg("manutencoes", "status nao reconhecido", conta(is.na(stm)), "mantido vazio (revisar)")
reg("manutencoes", "concluida sem data_execucao", conta(!is.na(stm) & stm == "concluída" & is.na(dx)), "mantida (revisar)")

man_saida <- data.frame(id_manutencao = fmt_int(man$id_manutencao), id_cliente = fmt_int(man$id_cliente),
                        id_servico_origem = fmt_int(man$id_servico_origem), descricao = man$descricao,
                        preco = fmt_dec(man$preco), data_solicitacao = data_para_texto(ds),
                        data_execucao = data_para_texto(dx), status = stm)

# =====================================================================
# 6) Gravacao
# =====================================================================
cli_saida <- data.frame(id_cliente = fmt_int(cli_final$id_cliente), nome_completo = cli_final$nome_completo,
                        telefone = cli_final$telefone, email = cli_final$email, endereco = cli_final$endereco,
                        cidade = cli_final$cidade, origem_contato = cli_final$origem_contato,
                        data_cadastro = cli_final$data_cadastro)
pre_saida <- data.frame(id_preco = fmt_int(pre$id_preco), tipo_servico = pre$tipo_servico, subtipo = pre$subtipo,
                        unidade_medida = pre$unidade_medida, valor = fmt_dec(pre$valor),
                        data_atualizacao = pre$data_atualizacao)

escrever_csv(cli_saida, file.path(saida, "clientes.csv"))
escrever_csv(pre_saida, file.path(saida, "preco_por_m.csv"))
escrever_csv(srv_saida, file.path(saida, "servicos.csv"))
escrever_csv(fot_saida, file.path(saida, "fotos.csv"))
escrever_csv(man_saida, file.path(saida, "manutencoes.csv"))
escrever_csv(data.frame(id_duplicado = fmt_int(mapa_dup$id_duplicado), id_mantido = fmt_int(mapa_dup$id_mantido)),
             file.path(saida, "clientes_mapa_duplicados.csv"))
escrever_csv(qualidade, file.path(saida, "servicos_qualidade.csv"))

relatorio <- do.call(rbind, rel)
escrever_csv(relatorio, file.path(saida, "relatorio_qualidade.csv"))

# Relatorio legivel
linhas <- c(
  "RELATORIO DE QUALIDADE DOS DADOS (gerado por scripts/tratar_dados.R)",
  paste0("Data/hora: ", format(Sys.time(), "%Y-%m-%d %H:%M:%S")),
  "",
  "Linhas por tabela (entrada -> saida):",
  sprintf("  clientes     %5d -> %5d", n_cli_entrada, nrow(cli_saida)),
  sprintf("  servicos     %5d -> %5d", n_srv_entrada, nrow(srv_saida)),
  sprintf("  fotos        %5d -> %5d", n_fot_entrada, nrow(fot_saida)),
  sprintf("  manutencoes  %5d -> %5d", n_man_entrada, nrow(man_saida)),
  "",
  "Correcoes e sinalizacoes:")
atual <- ""
for (i in seq_len(nrow(relatorio))) {
  if (relatorio$tabela[i] != atual) {
    atual <- relatorio$tabela[i]
    linhas <- c(linhas, "", paste0("[", toupper(atual), "]"))
  }
  linhas <- c(linhas, sprintf("  %5d  %s  ->  %s", relatorio$quantidade[i], relatorio$regra[i], relatorio$acao[i]))
}
linhas <- c(linhas, "", "Os arquivos de dados/raw NAO foram alterados.")
con <- file(file.path(saida, "relatorio_qualidade.txt"), "wb")
writeLines(enc2utf8(linhas), con, useBytes = TRUE)
close(con)

cat(paste(linhas, collapse = "\n"), "\n\n", sep = "")
cat("Arquivos tratados gravados em:", normalizePath(saida), "\n")
