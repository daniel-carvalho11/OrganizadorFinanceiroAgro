import os
import sys
import tempfile
from pathlib import Path

import pytest

# Banco dos testes: SQLite temporário por padrão, ou um PostgreSQL DESCARTÁVEL via TEST_DATABASE_URL
# (atenção: as tabelas são apagadas a cada teste, nunca aponte para o banco local de uso nem produção)
_DB_DIR = tempfile.mkdtemp(prefix="agro_testes_")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_DB_DIR}/teste.db"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import engine, init_db, SessionLocal  # noqa: E402
from models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def banco_limpo():
    """Recria as tabelas antes de cada teste."""
    SessionLocal.remove()
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    SessionLocal.remove()


@pytest.fixture
def client():
    from main import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def nota_fiscal():
    """JSON no formato devolvido pelo Agent1 (sem chamar o Gemini)."""
    return {
        "numeroNotaFiscal": "000.084.682",
        "dataEmissao": "19/09/2025",
        "fornecedor": {"razaoSocial": "IGUAÇU MAQUINAS LTDA", "fantasia": "IGUAÇU", "cnpj": "11.111.111/0001-00"},
        "faturado": {"nomeCompleto": "BELTRANO DA SILVA", "cpf": "999.999.999-99"},
        "descricaoProdutos": ["ROLAMENTO 6205", "BUCHA"],
        "quantidadeParcelas": 1,
        "parcelas": [{"numeroParcela": 1, "dataVencimento": "2025-10-20", "valorParcela": 350.0}],
        "valorTotal": 350.0,
        "classificacaoDespesa": [{"categoria": "MANUTENÇÃO E OPERAÇÃO", "justificativa": "Peças mecânicas"}],
    }
