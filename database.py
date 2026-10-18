import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base, Classificacao

# Suporta DATABASE_URL para Render/PostgreSQL ou SQLite como fallback local
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///financeiro.db")

# Ajuste no prefixo postgres:// se necessário (para compatibilidade com SQLAlchemy 2.0)
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

def init_db():
    """Cria todas as tabelas no banco de dados e popula as categorias iniciais de despesa."""
    Base.metadata.create_all(bind=engine)
    
    session = SessionLocal()
    try:
        categorias_padrao = [
            "INSUMOS AGRÍCOLAS",
            "MANUTENÇÃO E OPERAÇÃO",
            "RECURSOS HUMANOS",
            "SERVIÇOS OPERACIONAIS",
            "INFRAESTRUTURA E UTILIDADES",
            "ADMINISTRATIVAS",
            "SEGUROS E PROTEÇÃO",
            "IMPOSTOS E TAXAS",
            "INVESTIMENTOS"
        ]

        for cat_nome in categorias_padrao:
            existente = session.query(Classificacao).filter_by(descricao=cat_nome).first()
            if not existente:
                nova_cat = Classificacao(tipo="Despesa", descricao=cat_nome, status="ativo")
                session.add(nova_cat)
        
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Erro ao inicializar banco de dados: {e}")
    finally:
        session.close()

def get_db():
    """Gerenciador de contexto para obter uma sessão do banco de dados."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
