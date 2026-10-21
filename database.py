import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base, Classificacao

# Carrega o .env da pasta do projeto ANTES de ler a DATABASE_URL.
# Não sobrescreve variáveis já definidas: no Render vale a variável configurada no painel.
PASTA_PROJETO = Path(__file__).resolve().parent
load_dotenv(PASTA_PROJETO / ".env")

# DATABASE_URL definida -> PostgreSQL (local via .env ou produção no Render)
# DATABASE_URL ausente  -> SQLite em arquivo (fallback; também usado pelos testes)
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{PASTA_PROJETO / 'financeiro.db'}"

# Ajuste no prefixo postgres:// se necessário (para compatibilidade com SQLAlchemy 2.0)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True  # descarta conexões derrubadas pelo servidor (comum em bancos gerenciados)
)


def descrever_banco() -> str:
    """Descrição do banco em uso para exibir na tela (sem usuário ou senha)."""
    url = engine.url
    if url.get_backend_name() == "sqlite":
        return "SQLite (arquivo local)"
    local = url.host in ("localhost", "127.0.0.1", "::1")
    return f"PostgreSQL {'local' if local else 'remoto'} ({url.database})"

SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

def init_db():
    """Cria todas as tabelas no banco de dados e popula as categorias iniciais de despesa e receita."""
    Base.metadata.create_all(bind=engine)
    
    session = SessionLocal()
    try:
        categorias_padrao = {
            "Despesa": [
                "INSUMOS AGRÍCOLAS",
                "MANUTENÇÃO E OPERAÇÃO",
                "RECURSOS HUMANOS",
                "SERVIÇOS OPERACIONAIS",
                "INFRAESTRUTURA E UTILIDADES",
                "ADMINISTRATIVAS",
                "SEGUROS E PROTEÇÃO",
                "IMPOSTOS E TAXAS",
                "INVESTIMENTOS"
            ],
            "Receita": [
                "VENDA DE PRODUÇÃO AGRÍCOLA",
                "VENDA DE ANIMAIS",
                "PRESTAÇÃO DE SERVIÇOS",
                "ARRENDAMENTO RECEBIDO",
                "OUTRAS RECEITAS"
            ]
        }

        for tipo, nomes in categorias_padrao.items():
            for cat_nome in nomes:
                existente = session.query(Classificacao).filter_by(descricao=cat_nome).first()
                if not existente:
                    session.add(Classificacao(tipo=tipo, descricao=cat_nome, status="ativo"))

        # Padroniza o tipo das classificações gravadas em caixa alta por versões anteriores
        for tipo in ("Despesa", "Receita"):
            session.query(Classificacao).filter(
                Classificacao.tipo != tipo, func.upper(Classificacao.tipo) == tipo.upper()
            ).update({Classificacao.tipo: tipo}, synchronize_session=False)

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
