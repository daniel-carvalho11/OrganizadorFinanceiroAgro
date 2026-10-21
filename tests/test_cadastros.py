"""Manter Fornecedor/Cliente/Faturado/Tipos e Contas a Pagar/Receber (exclusão lógica + reativação)."""


def test_crud_pessoa_com_inativacao_e_reativacao(client):
    res = client.post("/api/pessoas", json={"tipo": "CLIENTE", "razao_social": "Fulano Agro", "documento": "123.456.789-01"})
    assert res.status_code == 201
    pessoa = res.get_json()["dados"]
    assert pessoa["status"] == "ativo" and pessoa["documento"] == "123.456.789-01"

    duplicada = client.post("/api/pessoas", json={"tipo": "CLIENTE", "razao_social": "Outro", "documento": "12345678901"})
    assert duplicada.status_code == 400

    pid = pessoa["id_pessoa"]
    client.put(f"/api/pessoas/{pid}", json={"tipo": "CLIENTE-FORNECEDOR", "razao_social": "Fulano Agro LTDA", "documento": "12345678901"})
    client.patch(f"/api/pessoas/{pid}/status", json={"status": "inativo"})

    assert client.get("/api/pessoas").get_json()["total"] == 0  # TODOS = somente ativos
    inativos = client.get("/api/pessoas?status=inativo").get_json()["dados"]
    assert inativos[0]["razao_social"] == "Fulano Agro LTDA"

    client.patch(f"/api/pessoas/{pid}/status", json={"status": "ativo"})
    assert client.get("/api/pessoas?tipo=CLIENTE,CLIENTE-FORNECEDOR").get_json()["total"] == 1


def test_busca_por_mais_de_um_elemento(client):
    client.post("/api/pessoas", json={"tipo": "FATURADO", "razao_social": "Beltrano da Silva", "documento": "99999999999"})
    client.post("/api/pessoas", json={"tipo": "FATURADO", "razao_social": "Beltrano Souza"})

    assert client.get("/api/pessoas?termo=beltrano silva").get_json()["total"] == 1
    assert client.get("/api/pessoas?termo=beltrano 999.999").get_json()["total"] == 1
    assert client.get("/api/pessoas?termo=beltrano").get_json()["total"] == 2


def test_crud_tipo_receita(client):
    res = client.post("/api/classificacoes", json={"tipo": "Receita", "descricao": "Venda de soja"})
    assert res.status_code == 201
    cid = res.get_json()["dados"]["id_classificacao"]
    assert client.post("/api/classificacoes", json={"tipo": "Receita", "descricao": "VENDA DE SOJA"}).status_code == 400

    client.patch(f"/api/classificacoes/{cid}/status", json={"status": "inativo"})
    receitas = client.get("/api/classificacoes?tipo=Receita").get_json()["dados"]
    assert "VENDA DE SOJA" not in [c["descricao"] for c in receitas]


def test_conta_a_receber_com_varias_receitas_e_parcelas(client):
    res = client.post("/api/movimentos", json={
        "tipo": "Receita", "numero_nota_fiscal": "77", "data_emissao": "2025-09-01", "valor_total": 100,
        "emitente_nome": "Cooperativa X", "destinatario_nome": "Fazenda Y",
        "quantidade_parcelas": 3, "categorias": ["VENDA DE PRODUÇÃO AGRÍCOLA", "OUTRAS RECEITAS"],
    })
    assert res.status_code == 201, res.get_json()
    mov = res.get_json()["dados"]

    assert [p["identificacao"] for p in mov["parcelas"]] == ["1/3", "2/3", "3/3"]
    assert round(sum(p["valor_parcela"] for p in mov["parcelas"]), 2) == 100.0
    assert {c["tipo"] for c in mov["classificacoes"]} == {"Receita"}

    mid = mov["id_movimento_contas"]
    client.patch(f"/api/movimentos/{mid}/status", json={"status": "inativo"})
    assert client.get("/api/movimentos").get_json()["total"] == 0
    assert client.get("/api/movimentos?status=inativo").get_json()["total"] == 1
    client.patch(f"/api/movimentos/{mid}/status", json={"status": "ativo"})
    assert client.get("/api/resumo").get_json()["dados"]["total_receitas"] == 100.0


def test_editar_movimento_troca_classificacoes(client):
    mov = client.post("/api/movimentos", json={
        "tipo": "Despesa", "valor_total": 50, "emitente_nome": "Posto", "destinatario_nome": "Fazenda",
        "categorias": ["MANUTENÇÃO E OPERAÇÃO"],
    }).get_json()["dados"]
    res = client.put(f"/api/movimentos/{mov['id_movimento_contas']}", json={"categorias": ["INSUMOS AGRÍCOLAS", "ADMINISTRATIVAS"]})
    assert {c["categoria"] for c in res.get_json()["dados"]["classificacoes"]} == {"INSUMOS AGRÍCOLAS", "ADMINISTRATIVAS"}
