"""Agent3 (RAG simples e RAG com embeddings) e a rota /api/rag/consulta, com o Gemini simulado."""
import unicodedata
from types import SimpleNamespace

import pytest

from agents.agent3 import agent_RAG
from agents.agent3 import Agent3
from models import RagEmbedding
from database import SessionLocal

VOCABULARIO = ["diesel", "combustivel", "trator", "peca", "rolamento", "soja", "milho", "venda", "semente", "adubo"]


def _normalizar(texto):
    sem_acento = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return sem_acento.replace("pecas", "peca").replace("combustiveis", "combustivel")


class GeminiFalso:
    """Imita client.models: embeddings por contagem de palavras e geração que devolve o prompt."""

    def __init__(self):
        self.textos_vetorizados = []
        self.prompts = []
        self.models = self

    def embed_content(self, model, contents, config):
        self.textos_vetorizados.extend(contents)
        vetores = []
        for texto in contents:
            t = _normalizar(texto)
            vetores.append(SimpleNamespace(values=[float(t.count(p)) for p in VOCABULARIO] + [0.01]))
        return SimpleNamespace(embeddings=vetores)

    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        return SimpleNamespace(text="Resposta gerada com base nos dados.")


@pytest.fixture
def gemini(monkeypatch):
    falso = GeminiFalso()
    monkeypatch.setattr(agent_RAG.genai, "Client", lambda api_key: falso)
    return falso


def _lancar(client, nf, emitente, produtos, valor=100, tipo="Despesa", data="2025-09-10", categorias=None):
    padrao = ["MANUTENÇÃO E OPERAÇÃO"] if tipo == "Despesa" else ["VENDA DE PRODUÇÃO AGRÍCOLA"]
    res = client.post("/api/movimentos", json={
        "tipo": tipo, "numero_nota_fiscal": nf, "valor_total": valor, "emitente_nome": emitente,
        "destinatario_nome": "Fazenda Boa Vista", "quantidade_parcelas": 1, "data_emissao": data,
        "descricao_produtos": produtos, "categorias": categorias or padrao,
    })
    assert res.status_code == 201, res.get_json()
    return res.get_json()["dados"]["id_movimento_contas"]


def test_rag_simples_limita_a_20_ativos_e_monta_prompt(client, gemini):
    ids = [_lancar(client, f"NF{i}", f"Fornecedor {i}", "Peças diversas", data=f"2025-01-{i + 1:02d}") for i in range(22)]
    client.patch(f"/api/movimentos/{ids[-1]}/status", json={"status": "inativo"})

    resultado = Agent3(api_key="teste").run_query("Quanto gastei com peças?", "simples")

    assert resultado["resposta"] == "Resposta gerada com base nos dados."
    assert len(resultado["fontes"]) == 20
    usados = [f["id_movimento_contas"] for f in resultado["fontes"]]
    assert ids[-1] not in usados                    # inativo fica fora
    assert usados[0] == ids[-2]                      # mais recente primeiro
    prompt = gemini.prompts[0]
    assert "Pergunta: Quanto gastei com peças?" in prompt
    assert "Despesas (Contas a Pagar): 21 lançamentos ativos" in prompt
    assert gemini.textos_vetorizados == []           # modo simples não usa embeddings


def test_rag_embeddings_recupera_por_similaridade(client, gemini):
    id_diesel = _lancar(client, "1", "Posto Rio Verde", "Óleo diesel S10 para trator", valor=850)
    _lancar(client, "2", "Agro Sementes", "Semente de soja e adubo")
    _lancar(client, "3", "Cerealista", "Venda de milho", tipo="Receita")

    resultado = Agent3(api_key="teste").run_query("Quanto gastei de diesel?", "embeddings")

    assert resultado["fontes"][0]["id_movimento_contas"] == id_diesel
    assert resultado["fontes"][0]["similaridade"] > resultado["fontes"][1]["similaridade"]
    assert resultado["indice"] == {"total_indexados": 3, "atualizados_agora": 3, "removidos_agora": 0}
    assert "busca semântica" in gemini.prompts[0]

    session = SessionLocal()
    assert session.query(RagEmbedding).count() == 3
    session.close()


def test_indice_vetorial_so_recalcula_o_que_mudou(client, gemini):
    id_a = _lancar(client, "1", "Posto", "Diesel")
    id_b = _lancar(client, "2", "Loja", "Rolamento")
    agente = Agent3(api_key="teste")

    agente.run_query("diesel", "embeddings")
    segunda = agente.run_query("diesel", "embeddings")
    assert segunda["indice"]["atualizados_agora"] == 0

    client.put(f"/api/movimentos/{id_b}", json={"descricao_produtos": "Rolamento e peças de trator"})
    client.patch(f"/api/movimentos/{id_a}/status", json={"status": "inativo"})
    terceira = agente.run_query("diesel", "embeddings")

    assert terceira["indice"] == {"total_indexados": 1, "atualizados_agora": 1, "removidos_agora": 1}
    assert [f["id_movimento_contas"] for f in terceira["fontes"]] == [id_b]


def test_sem_lancamentos_nao_chama_o_modelo(gemini):
    resultado = Agent3(api_key="teste").run_query("Quais contas estão vencidas?", "embeddings")
    assert resultado["fontes"] == []
    assert "Não há lançamentos ativos" in resultado["resposta"]
    assert gemini.prompts == []


def test_rota_rag_consulta(client, gemini):
    _lancar(client, "1", "Posto", "Diesel")

    res = client.post("/api/rag/consulta", json={"pergunta": "Gastos com diesel?", "modo": "embeddings", "api_key": "teste"})
    corpo = res.get_json()
    assert res.status_code == 200, corpo
    assert corpo["status"] == "success" and corpo["modo"] == "embeddings"
    assert corpo["resposta"] and len(corpo["fontes"]) == 1


@pytest.mark.parametrize("corpo, mensagem", [
    ({"pergunta": "", "api_key": "teste"}, "Digite uma pergunta"),
    ({"pergunta": "Oi", "modo": "vetorial", "api_key": "teste"}, "Modo de busca inválido"),
])
def test_rota_rag_valida_entrada(client, gemini, corpo, mensagem):
    res = client.post("/api/rag/consulta", json=corpo)
    assert res.status_code == 400
    assert mensagem in res.get_json()["message"]


def test_rota_rag_sem_chave(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    res = client.post("/api/rag/consulta", json={"pergunta": "Oi"})
    assert res.status_code == 400
    assert "GEMINI_API_KEY" in res.get_json()["message"]


def test_tela_principal_tem_categoria_de_pesquisa_rag(client):
    res = client.get("/")
    html = res.get_data(as_text=True)
    assert res.status_code == 200
    assert 'name="categoriaPesquisa" value="embeddings"' in html and 'id="ragPainel"' in html


def test_contexto_separa_compras_e_vendas_com_subtotais(client, gemini):
    _lancar(client, "1", "Posto", "Diesel", valor=850)
    _lancar(client, "2", "Loja", "Rolamento", valor=150)
    _lancar(client, "3", "Cerealista", "Venda de soja", valor=5000, tipo="Receita")

    Agent3(api_key="teste").run_query("Resumo de compras e vendas", "simples")
    prompt = gemini.prompts[0]

    compras = prompt.index("=== COMPRAS (Despesas / Contas a Pagar): 2 lançamento(s), subtotal R$ 1.000,00 ===")
    vendas = prompt.index("=== VENDAS (Receitas / Contas a Receber): 1 lançamento(s), subtotal R$ 5.000,00 ===")
    assert compras < prompt.index("Posto") < vendas < prompt.index("Cerealista")
    assert "compras R$ 1.000,00 | vendas R$ 5.000,00 | saldo (vendas - compras) R$ 4.000,00" in prompt
