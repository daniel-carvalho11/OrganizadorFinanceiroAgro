"""Regras de duplicidade por tipo de operação e relatórios de Contas a Pagar / a Receber."""
from datetime import date

import servico_relatorios


def _lancar(client, tipo, nf, emitente, valor=100, categorias=None, parcelas=1, **extra):
    padrao = ["MANUTENÇÃO E OPERAÇÃO"] if tipo == "Despesa" else ["VENDA DE PRODUÇÃO AGRÍCOLA"]
    return client.post("/api/movimentos", json={
        "tipo": tipo, "numero_nota_fiscal": nf, "valor_total": valor, "emitente_nome": emitente,
        "destinatario_nome": "Fazenda Boa Vista", "quantidade_parcelas": parcelas,
        "categorias": categorias or padrao, **extra,
    })


def test_receita_nao_repete_numero_mesmo_com_clientes_diferentes(client):
    assert _lancar(client, "Receita", "456789", "Daniel Teste").status_code == 201
    segunda = _lancar(client, "Receita", "000.456.789", "Eduardo")

    assert segunda.status_code == 400
    assert "Contas a Receber" in segunda.get_json()["message"]


def test_despesa_permite_mesmo_numero_de_fornecedores_diferentes(client):
    assert _lancar(client, "Despesa", "2534", "AgroBom").status_code == 201
    assert _lancar(client, "Despesa", "2534", "Posto Rio Verde").status_code == 201
    assert _lancar(client, "Despesa", "2534", "AgroBom").status_code == 400


def test_mesmo_numero_em_tipos_diferentes_e_permitido(client):
    assert _lancar(client, "Despesa", "777", "Cooperativa").status_code == 201
    assert _lancar(client, "Receita", "777", "Cooperativa").status_code == 201


def test_receita_inativa_libera_numero_e_reativacao_respeita_regra(client):
    primeira = _lancar(client, "Receita", "10", "Cliente A").get_json()["dados"]
    client.patch(f"/api/movimentos/{primeira['id_movimento_contas']}/status", json={"status": "inativo"})
    assert _lancar(client, "Receita", "10", "Cliente B").status_code == 201

    reativar = client.patch(f"/api/movimentos/{primeira['id_movimento_contas']}/status", json={"status": "ativo"})
    assert reativar.status_code == 400


def test_documento_com_tamanho_invalido_e_recusado(client):
    res = _lancar(client, "Receita", "11", "Eduardo", emitente_documento="144444471123")
    assert res.status_code == 400
    assert "11 dígitos" in res.get_json()["message"]


def test_relatorio_contas_a_pagar_com_naturezas_e_situacao(client):
    _lancar(client, "Despesa", "1", "Fornecedor A", valor=300, data_emissao="2025-09-01",
            categorias=["MANUTENÇÃO E OPERAÇÃO", "INSUMOS AGRÍCOLAS"])
    pago = _lancar(client, "Despesa", "2", "Fornecedor B", valor=100, data_emissao="2025-09-10").get_json()["dados"]
    client.post(f"/api/parcelas/{pago['parcelas'][0]['id_parcela']}/pagar", json={})
    _lancar(client, "Receita", "3", "Cliente", valor=999, data_emissao="2025-09-05")

    rel = servico_relatorios.gerar_relatorio("Despesa", hoje=date(2026, 1, 1))
    assert rel["titulo"] == "Contas a Pagar"
    assert rel["totais"] == {"quantidade_nfs": 2, "valor_total": 400.0, "valor_pago": 100.0,
                             "saldo_aberto": 300.0, "saldo_vencido": 300.0}
    assert {n["numero_nota_fiscal"]: n["situacao"] for n in rel["notas"]} == {"1": "VENCIDA", "2": "QUITADA"}
    naturezas = {n["natureza"]: n["valor"] for n in rel["por_natureza"]}
    assert naturezas == {"MANUTENÇÃO E OPERAÇÃO": 250.0, "INSUMOS AGRÍCOLAS": 150.0}

    so_quitadas = servico_relatorios.gerar_relatorio("Despesa", situacao="quitadas", hoje=date(2026, 1, 1))
    assert [n["numero_nota_fiscal"] for n in so_quitadas["notas"]] == ["2"]


def test_rota_relatorio_contas_a_receber(client):
    _lancar(client, "Receita", "50", "Cliente", valor=200, parcelas=2, data_emissao="2025-09-05")
    res = client.get("/api/relatorios/receber?data_inicio=2025-09-01&data_fim=2025-09-30").get_json()["dados"]

    assert res["titulo"] == "Contas a Receber"
    assert res["notas"][0]["parcelas_total"] == 2
    assert res["por_natureza"][0]["natureza"] == "VENDA DE PRODUÇÃO AGRÍCOLA"
    assert client.get("/api/relatorios/outro").status_code == 404
