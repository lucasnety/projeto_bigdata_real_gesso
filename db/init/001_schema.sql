-- =====================================================================
-- Projeto de Extensão - Empresa de Gesso e Drywall
-- Script de criação do schema do banco de dados
--
-- Este arquivo é executado AUTOMATICAMENTE pelo container do Postgres
-- na primeira inicialização (mecanismo padrão da imagem oficial:
-- tudo que está em /docker-entrypoint-initdb.d é rodado em ordem
-- alfabética quando o volume de dados está vazio).
--
-- Baseado no dicionário de dados definido na Entrega 01
-- (Definição da Fonte e Fluxo de Dados).
--
-- Observação: colunas de data que recebem valores diretamente dos CSVs
-- gerados (dados/raw/) ficam como VARCHAR, e não DATE/TIMESTAMP,
-- porque o gerador cria formatos de data propositalmente inconsistentes
-- (dd/mm/aaaa, aaaa-mm-dd, etc.) para serem padronizados na etapa de
-- Análise Exploratória de Dados (AED) — ver dados/README.md.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Tabela: clientes
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clientes (
    id_cliente        SERIAL PRIMARY KEY,
    nome_completo     VARCHAR(150) NOT NULL,
    telefone          VARCHAR(30),
    email             VARCHAR(100),
    endereco          VARCHAR(200),
    cidade            VARCHAR(80),
    origem_contato    VARCHAR(50),
    data_cadastro     VARCHAR(20)
);

-- ---------------------------------------------------------------------
-- Tabela: preco_por_m (tabela de referência de preços)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS preco_por_m (
    id_preco          SERIAL PRIMARY KEY,
    tipo_servico      VARCHAR(50) NOT NULL,
    subtipo           VARCHAR(50) DEFAULT '',
    unidade_medida    VARCHAR(20) NOT NULL,
    valor             NUMERIC(10,2) NOT NULL,
    data_atualizacao  DATE
);

-- ---------------------------------------------------------------------
-- Tabela: servicos
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS servicos (
    id_servico                SERIAL PRIMARY KEY,
    id_cliente                INTEGER NOT NULL REFERENCES clientes(id_cliente),
    tipo_servico               VARCHAR(50) NOT NULL,
    subtipo                    VARCHAR(50) DEFAULT '',
    descricao_detalhada        TEXT,
    unidade_medida              VARCHAR(20),
    quantidade                  NUMERIC(10,2),
    valor_unitario_aplicado     NUMERIC(10,2),
    valor_total                 NUMERIC(12,2),
    data_execucao                VARCHAR(20),
    status                       VARCHAR(20)
);

CREATE INDEX IF NOT EXISTS idx_servicos_cliente ON servicos(id_cliente);
CREATE INDEX IF NOT EXISTS idx_servicos_tipo ON servicos(tipo_servico);

-- ---------------------------------------------------------------------
-- Tabela: fotos
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fotos (
    id_foto           SERIAL PRIMARY KEY,
    id_servico        INTEGER NOT NULL REFERENCES servicos(id_servico),
    caminho_arquivo   VARCHAR(255),
    descricao         VARCHAR(150),
    data_upload       VARCHAR(30)
);

CREATE INDEX IF NOT EXISTS idx_fotos_servico ON fotos(id_servico);

-- ---------------------------------------------------------------------
-- Tabela: manutencoes
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS manutencoes (
    id_manutencao      SERIAL PRIMARY KEY,
    id_cliente         INTEGER NOT NULL REFERENCES clientes(id_cliente),
    id_servico_origem  INTEGER REFERENCES servicos(id_servico),
    descricao          TEXT,
    preco              NUMERIC(10,2),
    data_solicitacao   VARCHAR(20),
    data_execucao      VARCHAR(20),
    status             VARCHAR(20)
);

CREATE INDEX IF NOT EXISTS idx_manutencoes_cliente ON manutencoes(id_cliente);

-- ---------------------------------------------------------------------
-- Carga inicial (seed) da tabela oficial de preços
-- ---------------------------------------------------------------------
INSERT INTO preco_por_m (tipo_servico, subtipo, unidade_medida, valor, data_atualizacao) VALUES
    ('Sanca',             '',                 'metro linear',   95.00, CURRENT_DATE),
    ('Divisória Drywall',  '',                 'metro quadrado', 130.00, CURRENT_DATE),
    ('Forro Drywall',      '',                 'metro quadrado', 95.00, CURRENT_DATE),
    ('Gesso Liso',         'Parede Rebocada',  'metro quadrado', 20.00, CURRENT_DATE),
    ('Gesso Liso',         'Parede de Tijolo', 'metro quadrado', 30.00, CURRENT_DATE),
    ('Gesso Liso',         'Parede Pintada',   'metro quadrado', 22.00, CURRENT_DATE),
    ('Moldura de Gesso',   '7cm',              'metro linear',   12.00, CURRENT_DATE),
    ('Moldura de Gesso',   '10cm',             'metro linear',   15.00, CURRENT_DATE),
    ('Moldura de Gesso',   '15cm',             'metro linear',   17.00, CURRENT_DATE),
    ('Moldura de Gesso',   '20cm',             'metro linear',   20.00, CURRENT_DATE)
ON CONFLICT DO NOTHING;