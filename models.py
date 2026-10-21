import datetime
from sqlalchemy import Column, Integer, String, Date, Numeric, Text, ForeignKey, ForeignKeyConstraint
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def formatar_documento(documento):
    """Exibe CPF (11 dígitos) ou CNPJ (14 dígitos) com máscara; demais valores ficam como estão."""
    d = "".join(ch for ch in (documento or "") if ch.isdigit())
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return documento

class Pessoa(Base):
    __tablename__ = "pessoas"

    id_pessoa = Column(Integer, primary_key=True, autoincrement=True)
    tipo = Column(String(30), nullable=False, default="CLIENTE-FORNECEDOR")  # 'CLIENTE-FORNECEDOR', 'FATURADO', 'FORNECEDOR', 'CLIENTE', 'Física' ou 'Jurídica'
    razao_social = Column(String(255), nullable=False)
    nome_fantasia = Column(String(255), nullable=True)
    documento = Column(String(20), nullable=True)  # CPF ou CNPJ
    status = Column(String(20), nullable=False, default="ativo")  # 'ativo' ou 'inativo'

    # Relacionamentos
    movimentos_emitidos = relationship(
        "MovimentoContas",
        foreign_keys="MovimentoContas.id_pessoa_emitente",
        back_populates="emitente"
    )
    movimentos_recebidos = relationship(
        "MovimentoContas",
        foreign_keys="MovimentoContas.id_pessoa_destinatario",
        back_populates="destinatario"
    )

    def to_dict(self):
        return {
            "id_pessoa": self.id_pessoa,
            "tipo": self.tipo,
            "razao_social": self.razao_social,
            "nome_fantasia": self.nome_fantasia,
            "documento": formatar_documento(self.documento),
            "status": self.status
        }


class MovimentoContas(Base):
    __tablename__ = "movimento_contas"

    id_movimento_contas = Column(Integer, primary_key=True, autoincrement=True)
    tipo = Column(String(20), nullable=False, default="Despesa")  # 'Despesa' ou 'Receita'
    numero_nota_fiscal = Column(String(50), nullable=True)
    data_emissao = Column(Date, nullable=True)
    descricao_produtos = Column(Text, nullable=True)
    valor_total = Column(Numeric(12, 2), nullable=False, default=0.00)
    status = Column(String(20), nullable=False, default="ativo")  # 'ativo' ou 'inativo'

    # Chaves Estrangeiras apontando duas vezes para a tabela de Pessoas
    id_pessoa_emitente = Column(Integer, ForeignKey("pessoas.id_pessoa", ondelete="RESTRICT"), nullable=False)
    id_pessoa_destinatario = Column(Integer, ForeignKey("pessoas.id_pessoa", ondelete="RESTRICT"), nullable=False)

    # Relacionamentos ORM
    emitente = relationship("Pessoa", foreign_keys=[id_pessoa_emitente], back_populates="movimentos_emitidos")
    destinatario = relationship("Pessoa", foreign_keys=[id_pessoa_destinatario], back_populates="movimentos_recebidos")
    parcelas = relationship("Parcela", back_populates="movimento", cascade="all, delete-orphan")
    classificacoes_associadas = relationship("MovimentoHasClassificacao", back_populates="movimento", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id_movimento_contas": self.id_movimento_contas,
            "tipo": self.tipo,
            "numero_nota_fiscal": self.numero_nota_fiscal,
            "data_emissao": str(self.data_emissao) if self.data_emissao else None,
            "descricao_produtos": self.descricao_produtos,
            "valor_total": float(self.valor_total) if self.valor_total else 0.0,
            "status": self.status,
            "emitente": self.emitente.to_dict() if self.emitente else None,
            "destinatario": self.destinatario.to_dict() if self.destinatario else None,
            "parcelas": [p.to_dict() for p in self.parcelas],
            "classificacoes": [c.to_dict() for c in self.classificacoes_associadas]
        }


class Parcela(Base):
    __tablename__ = "parcelas"

    id_parcela = Column(Integer, primary_key=True, autoincrement=True)
    id_movimento_contas = Column(Integer, ForeignKey("movimento_contas.id_movimento_contas", ondelete="CASCADE"), nullable=False)
    identificacao = Column(String(50), nullable=False, default="Parcela 1")
    data_vencimento = Column(Date, nullable=True)
    valor_parcela = Column(Numeric(12, 2), nullable=False, default=0.00)
    valor_pago = Column(Numeric(12, 2), nullable=False, default=0.00)
    valor_saldo = Column(Numeric(12, 2), nullable=False, default=0.00)
    status = Column(String(20), nullable=False, default="aberta")  # 'aberta' ou 'quitada'

    movimento = relationship("MovimentoContas", back_populates="parcelas")

    def to_dict(self):
        return {
            "id_parcela": self.id_parcela,
            "id_movimento_contas": self.id_movimento_contas,
            "identificacao": self.identificacao,
            "data_vencimento": str(self.data_vencimento) if self.data_vencimento else None,
            "valor_parcela": float(self.valor_parcela) if self.valor_parcela else 0.0,
            "valor_pago": float(self.valor_pago) if self.valor_pago else 0.0,
            "valor_saldo": float(self.valor_saldo) if self.valor_saldo else 0.0,
            "status": self.status
        }


class Classificacao(Base):
    __tablename__ = "classificacao"

    id_classificacao = Column(Integer, primary_key=True, autoincrement=True)
    tipo = Column(String(20), nullable=False, default="Despesa")  # 'Despesa' ou 'Receita'
    descricao = Column(String(255), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="ativo")  # 'ativo' ou 'inativo'

    movimentos_associados = relationship("MovimentoHasClassificacao", back_populates="classificacao")

    def to_dict(self):
        return {
            "id_classificacao": self.id_classificacao,
            "tipo": self.tipo,
            "descricao": self.descricao,
            "status": self.status
        }


class MovimentoHasClassificacao(Base):
    __tablename__ = "movimento_has_classificacao"

    id_movimento_contas = Column(Integer, ForeignKey("movimento_contas.id_movimento_contas", ondelete="CASCADE"), primary_key=True)
    id_classificacao = Column(Integer, ForeignKey("classificacao.id_classificacao", ondelete="RESTRICT"), primary_key=True)
    justificativa = Column(Text, nullable=True)

    movimento = relationship("MovimentoContas", back_populates="classificacoes_associadas")
    classificacao = relationship("Classificacao", back_populates="movimentos_associados")

    def to_dict(self):
        return {
            "id_classificacao": self.id_classificacao,
            "categoria": self.classificacao.descricao if self.classificacao else None,
            "tipo": self.classificacao.tipo if self.classificacao else None,
            "justificativa": self.justificativa
        }
