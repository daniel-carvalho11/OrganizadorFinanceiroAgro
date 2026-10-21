"""2ª Etapa: consulta de existência, criação dos cadastros e lançamento do movimento."""
import copy


def test_consulta_nao_grava_nada(client, nota_fiscal):
    from agents.agent2 import Agent2
    consulta = Agent2().consultar_dados_nota_fiscal(nota_fiscal)["resposta_consulta"]

    assert consulta["fornecedor"]["status_banco"] == "NÃO EXISTE"
    assert consulta["faturado"]["status_banco"] == "NÃO EXISTE"
    assert consulta["despesa"]["status_banco"].startswith("EXISTE – ID:")
    assert consulta["nota_fiscal"]["duplicada"] is False
    assert client.get("/api/pessoas?status=todos").get_json()["total"] == 0


def test_confirmar_cria_cadastros_movimento_e_parcela_unica(client, nota_fiscal):
    res = client.post("/api/confirmar-lancamento", json={"dados": nota_fiscal})
    assert res.status_code == 200, res.get_json()
    mov = res.get_json()["persistencia"]["dados"]

    assert mov["tipo"] == "Despesa"
    assert mov["emitente"]["tipo"] == "CLIENTE-FORNECEDOR"
    assert mov["destinatario"]["tipo"] == "FATURADO"
    assert [p["identificacao"] for p in mov["parcelas"]] == ["ÚNICA"]
    assert mov["classificacoes"][0]["categoria"] == "MANUTENÇÃO E OPERAÇÃO"

    # Depois de gravado, a nova consulta passa a informar EXISTE – ID
    from agents.agent2 import Agent2
    consulta = Agent2().consultar_dados_nota_fiscal(nota_fiscal)["resposta_consulta"]
    assert consulta["fornecedor"]["status_banco"] == f"EXISTE – ID: {mov['emitente']['id_pessoa']}"
    assert consulta["faturado"]["status_banco"] == f"EXISTE – ID: {mov['destinatario']['id_pessoa']}"
    assert consulta["nota_fiscal"]["duplicada"] is True


def test_mesma_nf_nao_e_lancada_duas_vezes(client, nota_fiscal):
    assert client.post("/api/confirmar-lancamento", json={"dados": nota_fiscal}).status_code == 200
    segunda = client.post("/api/confirmar-lancamento", json={"dados": nota_fiscal})

    assert segunda.status_code == 400
    assert "já está lançada em Contas a Pagar" in segunda.get_json()["message"]
    assert client.get("/api/movimentos").get_json()["total"] == 1


def test_cnpj_sem_mascara_reconhece_fornecedor_existente(client, nota_fiscal):
    client.post("/api/confirmar-lancamento", json={"dados": nota_fiscal})

    outra = copy.deepcopy(nota_fiscal)
    outra["numeroNotaFiscal"] = "000.099.001"
    outra["fornecedor"]["cnpj"] = "11111111000100"
    outra["faturado"]["cpf"] = "99999999999"
    res = client.post("/api/confirmar-lancamento", json={"dados": outra})

    assert res.status_code == 200
    consulta = res.get_json()["persistencia"]["resposta_consulta"]
    assert consulta["fornecedor"]["existe"] and consulta["faturado"]["existe"]
    assert client.get("/api/pessoas?status=todos").get_json()["total"] == 2


def test_fornecedor_inativo_e_sinalizado_e_reativado_ao_lancar(client, nota_fiscal):
    client.post("/api/confirmar-lancamento", json={"dados": nota_fiscal})
    forn = client.get("/api/pessoas?tipo=CLIENTE-FORNECEDOR").get_json()["dados"][0]
    client.patch(f"/api/pessoas/{forn['id_pessoa']}/status", json={"status": "inativo"})

    outra = dict(nota_fiscal, numeroNotaFiscal="123")
    from agents.agent2 import Agent2
    consulta = Agent2().consultar_dados_nota_fiscal(outra)["resposta_consulta"]
    assert consulta["fornecedor"]["status_banco"].endswith("(INATIVO)")

    res = client.post("/api/confirmar-lancamento", json={"dados": outra}).get_json()
    assert forn["razao_social"] in res["persistencia"]["reativados"]
    assert client.get("/api/pessoas?tipo=CLIENTE-FORNECEDOR").get_json()["total"] == 1


def test_varias_classificacoes_e_parcelas(client, nota_fiscal):
    nf = copy.deepcopy(nota_fiscal)
    nf["classificacaoDespesa"].append({"categoria": "Categoria Nova Teste"})
    nf["parcelas"] = [
        {"numeroParcela": 1, "dataVencimento": "2025-10-20", "valorParcela": 175.0},
        {"numeroParcela": 2, "dataVencimento": "2025-11-20", "valorParcela": 175.0},
    ]
    mov = client.post("/api/confirmar-lancamento", json={"dados": nf}).get_json()["persistencia"]["dados"]

    assert {c["categoria"] for c in mov["classificacoes"]} == {"MANUTENÇÃO E OPERAÇÃO", "CATEGORIA NOVA TESTE"}
    assert [p["identificacao"] for p in mov["parcelas"]] == ["1/2", "2/2"]
    nova = client.get("/api/classificacoes?termo=nova").get_json()["dados"][0]
    assert nova["tipo"] == "Despesa"
