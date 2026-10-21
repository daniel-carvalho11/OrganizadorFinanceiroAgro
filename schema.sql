-- =====================================================================
-- SCRIPT DE CRIAÇÃO DO BANCO DE DADOS RELACIONAL
-- Projeto: Gestão Financeira Rural / Processador de Notas Fiscais
-- Modelo baseado nas especificações da aula (Prática - documento n1)
-- =====================================================================

-- 1. TABELA: pessoas (Centraliza Fornecedores/Emitentes e Clientes/Destinatários)
CREATE TABLE IF NOT EXISTS pessoas (
    id_pessoa SERIAL PRIMARY KEY,
    tipo VARCHAR(30) NOT NULL CHECK (tipo IN ('CLIENTE-FORNECEDOR', 'FATURADO', 'FORNECEDOR', 'CLIENTE', 'Física', 'Jurídica')),
    razao_social VARCHAR(255) NOT NULL,
    nome_fantasia VARCHAR(255),
    documento VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo'))
);

-- 2. TABELA: movimento_contas (Registros de Notas Fiscais e Lançamentos)
CREATE TABLE IF NOT EXISTS movimento_contas (
    id_movimento_contas SERIAL PRIMARY KEY,
    tipo VARCHAR(20) NOT NULL DEFAULT 'Despesa' CHECK (tipo IN ('Despesa', 'Receita')),
    numero_nota_fiscal VARCHAR(50),
    data_emissao DATE,
    descricao_produtos TEXT,
    valor_total DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    status VARCHAR(20) NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo')),
    id_pessoa_emitente INT NOT NULL REFERENCES pessoas(id_pessoa) ON DELETE RESTRICT,
    id_pessoa_destinatario INT NOT NULL REFERENCES pessoas(id_pessoa) ON DELETE RESTRICT
);

-- 3. TABELA: parcelas (Controle de Prazos e Pagamentos por Lançamento)
CREATE TABLE IF NOT EXISTS parcelas (
    id_parcela SERIAL PRIMARY KEY,
    id_movimento_contas INT NOT NULL REFERENCES movimento_contas(id_movimento_contas) ON DELETE CASCADE,
    identificacao VARCHAR(50) NOT NULL,
    data_vencimento DATE,
    valor_parcela DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    valor_pago DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    valor_saldo DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    status VARCHAR(20) NOT NULL DEFAULT 'aberta' CHECK (status IN ('aberta', 'quitada'))
);

-- 4. TABELA: classificacao (Categorias Financeiras de Despesas e Receitas)
CREATE TABLE IF NOT EXISTS classificacao (
    id_classificacao SERIAL PRIMARY KEY,
    tipo VARCHAR(20) NOT NULL DEFAULT 'Despesa' CHECK (tipo IN ('Despesa', 'Receita')),
    descricao VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'ativo' CHECK (status IN ('ativo', 'inativo'))
);

-- 5. TABELA: movimento_has_classificacao (Relacionamento N:M entre Movimento e Classificação)
CREATE TABLE IF NOT EXISTS movimento_has_classificacao (
    id_movimento_contas INT NOT NULL REFERENCES movimento_contas(id_movimento_contas) ON DELETE CASCADE,
    id_classificacao INT NOT NULL REFERENCES classificacao(id_classificacao) ON DELETE RESTRICT,
    justificativa TEXT,
    PRIMARY KEY (id_movimento_contas, id_classificacao)
);

-- =====================================================================
-- POPULAÇÃO INICIAL: Categorias Padrão de Despesas e Receitas Rurais
-- =====================================================================
INSERT INTO classificacao (tipo, descricao, status) VALUES
    ('Despesa', 'INSUMOS AGRÍCOLAS', 'ativo'),
    ('Despesa', 'MANUTENÇÃO E OPERAÇÃO', 'ativo'),
    ('Despesa', 'RECURSOS HUMANOS', 'ativo'),
    ('Despesa', 'SERVIÇOS OPERACIONAIS', 'ativo'),
    ('Despesa', 'INFRAESTRUTURA E UTILIDADES', 'ativo'),
    ('Despesa', 'ADMINISTRATIVAS', 'ativo'),
    ('Despesa', 'SEGUROS E PROTEÇÃO', 'ativo'),
    ('Despesa', 'IMPOSTOS E TAXAS', 'ativo'),
    ('Despesa', 'INVESTIMENTOS', 'ativo'),
    ('Receita', 'VENDA DE PRODUÇÃO AGRÍCOLA', 'ativo'),
    ('Receita', 'VENDA DE ANIMAIS', 'ativo'),
    ('Receita', 'PRESTAÇÃO DE SERVIÇOS', 'ativo'),
    ('Receita', 'ARRENDAMENTO RECEBIDO', 'ativo'),
    ('Receita', 'OUTRAS RECEITAS', 'ativo')
ON CONFLICT (descricao) DO NOTHING;
