import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template
import subprocess
from datetime import datetime
# Importação do Agent1 conforme estrutura especificada na aula
from agents.agent1.manipulacao_dados import Agent1


def get_deploy_info():
    """Recupera automaticamente o commit e data de build."""
    # 1. No Render, o commit vem injetado automaticamente nesta variável:
    commit_hash = os.environ.get("RENDER_GIT_COMMIT")
    
    # 2. Se estiver rodando localmente no seu computador:
    if not commit_hash:
        try:
            commit_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL
            ).decode("utf-8").strip()
        except Exception:
            commit_hash = "dev-local"
    else:
        commit_hash = commit_hash[:7]  # Apenas os 7 primeiros caracteres

    return {
        "commit": commit_hash,
        "env": "Produção (Render)" if os.environ.get("RENDER") else "Desenvolvimento Local"
    }

load_dotenv()

# Convenções nativas do Flask:
#   - pasta "templates/" → HTMLs (index.html funciona como está)
#   - pasta "static/"    → JS/CSS (servida automaticamente em /static/)
app = Flask(__name__)

# Pode ler a variável sem problemas, ela apenas ficará como None por enquanto
DATABASE_URL = os.environ.get("DATABASE_URL")

app.json.sort_keys = False

@app.route("/")
def index():
    info = get_deploy_info()
    """Serve a interface web."""
    return render_template("index.html", deploy_info=info)

@app.route("/api/extrair-nf", methods=["POST"])
def extrair_nota_fiscal():
    """
    Recebe o PDF da Nota Fiscal e a chave da API do Gemini (via interface),
    chama o Agent1 e devolve os dados extraídos em JSON (Figura 2 do documento).
    """
    # Validação 1: o arquivo veio no formulário?
    if "file" not in request.files:
        return jsonify({
            "status": "error",
            "message": "Nenhum arquivo enviado."
        }), 400

    file = request.files["file"]
    # Chave da API fornecida via interface (campo do formulário)
    api_key = (request.form.get("api_key") or "").strip()

    # Validação 2: é um PDF?
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return jsonify({
            "status": "error",
            "message": "O arquivo enviado deve ser um documento PDF."
        }), 400

    # Validação 3: a chave da API foi informada?
    if not api_key:
        return jsonify({
            "status": "error",
            "message": "A chave da API do Gemini é obrigatória."
        }), 400

    try:
        pdf_bytes = file.read()

        # Instancia o Agent1 passando a chave da API fornecida via interface
        agent1 = Agent1(api_key=api_key)

        # Execução do agente de extração 
        # Nota: o Flask é síncrono — não precisa de asyncio.to_thread
        dados_json = agent1.extrair_dados(pdf_bytes)

        return jsonify({"status": "success", "dados": dados_json})

    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 500
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Falha ao processar Nota Fiscal: {str(e)}"
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)