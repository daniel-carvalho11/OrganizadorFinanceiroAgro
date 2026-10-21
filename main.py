import os
import subprocess
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template

load_dotenv()

# Importação dos Agentes Inteligentes conforme arquitetura modular
from agents.agent1 import Agent1
from agents.agent2 import Agent2
from database import init_db, descrever_banco
import servico_cadastros
import servico_relatorios

app = Flask(__name__)
app.json.sort_keys = False

# Inicializa o banco de dados relacional e popula categorias se necessário
try:
    init_db()
except Exception as err:
    print(f"Aviso ao inicializar DB: {err}")

agent2 = Agent2()

def get_deploy_info():
    """Recupera informações do commit e ambiente de execução."""
    commit_hash = os.environ.get("RENDER_GIT_COMMIT")
    if not commit_hash:
        try:
            commit_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL
            ).decode("utf-8").strip()
        except Exception:
            commit_hash = "dev-local"
    else:
        commit_hash = commit_hash[:7]

    return {
        "commit": commit_hash,
        "env": "Produção (Render)" if os.environ.get("RENDER") else "Desenvolvimento Local",
        "banco": descrever_banco()
    }

@app.route("/")
def index():
    """Serve a interface web única com o layout de extração e gestão."""
    info = get_deploy_info()
    return render_template("index.html", deploy_info=info)

@app.route("/api/extrair-nf", methods=["POST"])
def extrair_nota_fiscal():
    """
    1. Agent 1: Extrai os dados do PDF de Nota Fiscal.
    2. Agent 2: Consulta se Fornecedor, Faturado e Despesa já existem no banco (sem gravar).
    Retorna os dados para conferência e confirmação do usuário na interface.
    """
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "Nenhum arquivo enviado."}), 400

    file = request.files["file"]
    api_key = (request.form.get("api_key") or "").strip()

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return jsonify({"status": "error", "message": "O arquivo enviado deve ser um documento PDF."}), 400

    if not api_key:
        return jsonify({"status": "error", "message": "A chave da API do Gemini é obrigatória."}), 400

    try:
        pdf_bytes = file.read()

        # Execução do Agent1 (Extração)
        agent1 = Agent1(api_key=api_key)
        dados_json = agent1.extrair_dados(pdf_bytes)

        # Execução do Agent2 (Consulta de existência no Banco sem gravar)
        resultado_consulta = agent2.consultar_dados_nota_fiscal(dados_json)

        return jsonify({
            "status": "success",
            "dados": dados_json,
            "consulta": resultado_consulta
        })

    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": f"Falha ao processar Nota Fiscal: {str(e)}"}), 500

@app.route("/api/confirmar-lancamento", methods=["POST"])
def confirmar_lancamento():
    """
    Confirma e grava a Nota Fiscal no banco de dados relacional (Agent 2):
    1. Criar fornecedor (se não existir)
    2. Criar faturado (se não existir)
    3. Criar despesa (se não existir)
    4. Criar movimento e parcelas
    5. Retorna sucesso do lançamento.
    """
    req_data = request.get_json() or {}
    dados_json = req_data.get("dados")

    if not dados_json:
        return jsonify({"status": "error", "message": "Dados da nota fiscal não informados para gravação."}), 400

    try:
        resultado_persistencia = agent2.salvar_nota_fiscal(dados_json)
        if resultado_persistencia.get("status") != "success":
            return jsonify({
                "status": "error",
                "message": resultado_persistencia.get("message"),
                "persistencia": resultado_persistencia
            }), 400
        return jsonify({
            "status": "success",
            "persistencia": resultado_persistencia
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Falha ao persistir lançamento: {str(e)}"}), 500

@app.route("/api/movimentos", methods=["GET"])
def listar_movimentos():
    """
    Lista lançamentos com busca multi-elemento (Nome, CPF/CNPJ, Nº NF) e filtros por tipo/período/status.
    """
    termo = request.args.get("termo") or request.args.get("q")
    status = request.args.get("status", "ativo")
    tipo = request.args.get("tipo")
    data_inicio = request.args.get("data_inicio")
    data_fim = request.args.get("data_fim")

    movimentos = agent2.listar_movimentos(
        termo=termo,
        status=status,
        tipo=tipo,
        data_inicio=data_inicio,
        data_fim=data_fim
    )
    return jsonify({"status": "success", "total": len(movimentos), "dados": movimentos})

@app.route("/api/movimentos/<int:id_movimento>", methods=["GET"])
def obter_movimento(id_movimento: int):
    """Retorna os dados detalhados de um movimento específico, incluindo parcelas e classificação."""
    movimento = agent2.obter_movimento(id_movimento)
    if not movimento:
        return jsonify({"status": "error", "message": f"Movimento #{id_movimento} não encontrado."}), 404
    return jsonify({"status": "success", "dados": movimento})

@app.route("/api/movimentos", methods=["POST"])
def criar_movimento():
    """Cria um novo movimento manual (salvo como 'ativo' por padrão)."""
    dados = request.get_json() or {}
    resultado = agent2.criar_movimento_manual(dados)
    code = 201 if resultado.get("status") == "success" else 400
    return jsonify(resultado), code

@app.route("/api/movimentos/<int:id_movimento>", methods=["PUT"])
def editar_movimento(id_movimento):
    """Edita os campos de um movimento existente (status permanece oculto e inalterado)."""
    dados = request.get_json() or {}
    resultado = agent2.editar_movimento(id_movimento, dados)
    code = 200 if resultado.get("status") == "success" else 400
    return jsonify(resultado), code

@app.route("/api/movimentos/<int:id_movimento>/status", methods=["PATCH", "PUT"])
def alterar_status_movimento(id_movimento):
    """Exclusão Lógica ('inativo') ou Reativação ('ativo') do registro."""
    dados_req = request.get_json() or {}
    novo_status = dados_req.get("status")

    if not novo_status:
        return jsonify({"status": "error", "message": "O campo 'status' é obrigatório (ativo/inativo)."}), 400

    resultado = agent2.alterar_status_movimento(id_movimento, novo_status)
    code = 200 if resultado.get("status") == "success" else 400
    return jsonify(resultado), code

@app.route("/api/resumo", methods=["GET"])
def resumo_financeiro():
    """Resumo estatístico para os cards do painel."""
    try:
        resumo = agent2.obter_resumo_financeiro()
    except Exception as e:
        return jsonify({"status": "error", "message": f"Falha ao calcular resumo: {str(e)}"}), 500
    return jsonify({"status": "success", "dados": resumo})

@app.route("/api/parcelas/<int:id_parcela>/pagar", methods=["POST", "PATCH"])
def registrar_pagamento_parcela(id_parcela):
    """Endpoint para registrar o pagamento/quitação de uma parcela no banco relacional."""
    dados_req = request.get_json() or {}
    valor_pago = dados_req.get("valor_pago")
    resultado = agent2.registrar_pagamento_parcela(id_parcela, valor_pago=valor_pago)
    code = 200 if resultado.get("status") == "success" else 400
    return jsonify(resultado), code

# =====================================================================
# CADASTROS (MANTER): Pessoas e Classificações
# Exclusão é sempre lógica (status 'inativo') e pode ser revertida (status 'ativo')
# =====================================================================

def _resposta(resultado, code_sucesso=200):
    return jsonify(resultado), (code_sucesso if resultado.get("status") == "success" else 400)

@app.route("/api/pessoas", methods=["GET"])
def listar_pessoas():
    """Lista pessoas. Parâmetros: termo, tipo (pode repetir ou separar por vírgula), status (ativo/inativo/todos)."""
    tipos = [t for valor in request.args.getlist("tipo") for t in valor.split(",") if t]
    dados = servico_cadastros.listar_pessoas(
        termo=request.args.get("termo"),
        tipos=tipos or None,
        status=request.args.get("status", "ativo")
    )
    return jsonify({"status": "success", "total": len(dados), "dados": dados})

@app.route("/api/pessoas", methods=["POST"])
def criar_pessoa():
    return _resposta(servico_cadastros.criar_pessoa(request.get_json() or {}), 201)

@app.route("/api/pessoas/<int:id_pessoa>", methods=["PUT"])
def editar_pessoa(id_pessoa):
    return _resposta(servico_cadastros.editar_pessoa(id_pessoa, request.get_json() or {}))

@app.route("/api/pessoas/<int:id_pessoa>/status", methods=["PATCH", "PUT"])
def alterar_status_pessoa(id_pessoa):
    return _resposta(servico_cadastros.alterar_status_pessoa(id_pessoa, (request.get_json() or {}).get("status")))

@app.route("/api/classificacoes", methods=["GET"])
def listar_classificacoes():
    """Lista classificações. Parâmetros: termo, tipo (Despesa/Receita), status (ativo/inativo/todos)."""
    dados = servico_cadastros.listar_classificacoes(
        termo=request.args.get("termo"),
        tipo=request.args.get("tipo"),
        status=request.args.get("status", "ativo")
    )
    return jsonify({"status": "success", "total": len(dados), "dados": dados})

@app.route("/api/classificacoes", methods=["POST"])
def criar_classificacao():
    return _resposta(servico_cadastros.criar_classificacao(request.get_json() or {}), 201)

@app.route("/api/classificacoes/<int:id_classificacao>", methods=["PUT"])
def editar_classificacao(id_classificacao):
    return _resposta(servico_cadastros.editar_classificacao(id_classificacao, request.get_json() or {}))

@app.route("/api/classificacoes/<int:id_classificacao>/status", methods=["PATCH", "PUT"])
def alterar_status_classificacao(id_classificacao):
    return _resposta(servico_cadastros.alterar_status_classificacao(id_classificacao, (request.get_json() or {}).get("status")))

# =====================================================================
# RELATÓRIOS: Contas a Pagar (despesa) e Contas a Receber (receita)
# =====================================================================

@app.route("/api/relatorios/<tipo>", methods=["GET"])
def relatorio_contas(tipo):
    """tipo: 'pagar' ou 'receber'. Filtros: data_inicio, data_fim, situacao (todas/abertas/vencidas/quitadas), natureza."""
    tipos = {"pagar": "Despesa", "receber": "Receita"}
    if tipo not in tipos:
        return jsonify({"status": "error", "message": "Relatório deve ser 'pagar' ou 'receber'."}), 404
    try:
        dados = servico_relatorios.gerar_relatorio(
            tipos[tipo],
            data_inicio=request.args.get("data_inicio"),
            data_fim=request.args.get("data_fim"),
            situacao=request.args.get("situacao", "todas"),
            natureza=request.args.get("natureza") or None,
        )
    except Exception as e:
        return jsonify({"status": "error", "message": f"Falha ao gerar relatório: {str(e)}"}), 500
    return jsonify({"status": "success", "dados": dados})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False if os.environ.get("RENDER") else True)
