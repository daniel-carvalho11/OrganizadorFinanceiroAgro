import os
from dotenv import load_dotenv
import subprocess
from flask import Flask, request, jsonify, render_template

# Importação dos Agentes Inteligentes conforme arquitetura modular
from agents.agent1 import Agent1
from agents.agent2 import Agent2
from database import init_db

load_dotenv()

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
        "env": "Produção (Render)" if os.environ.get("RENDER") else "Desenvolvimento Local"
    }

@app.route("/")
def index():
    """Serve a interface web única com o layout de extração e gestão."""
    info = get_deploy_info()
    return render_template("index.html", deploy_info=info)

@app.route("/api/extrair-nf", methods=["POST"])
def extrair_nota_fiscal():
    """
    Fluxo Agent-to-Agent (A2A):
    1. Agent 1: Extrai os dados do PDF de Nota Fiscal.
    2. Agent 2: Consulta se Fornecedor e Faturado já existem no banco e persiste o lançamento.
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

        # Execução do Agent2 (Verificação de Pessoas e Persistência no Banco)
        resultado_persistencia = agent2.salvar_nota_fiscal(dados_json)

        return jsonify({
            "status": "success",
            "dados": dados_json,
            "persistencia": resultado_persistencia
        })

    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": f"Falha ao processar Nota Fiscal: {str(e)}"}), 500

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
    resumo = agent2.obter_resumo_financeiro()
    return jsonify({"status": "success", "dados": resumo})

@app.route("/api/parcelas/<int:id_parcela>/pagar", methods=["POST", "PATCH"])
def registrar_pagamento_parcela(id_parcela):
    """Endpoint para registrar o pagamento/quitação de uma parcela no banco relacional."""
    dados_req = request.get_json() or {}
    valor_pago = dados_req.get("valor_pago")
    resultado = agent2.registrar_pagamento_parcela(id_parcela, valor_pago=valor_pago)
    code = 200 if resultado.get("status") == "success" else 400
    return jsonify(resultado), code

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

