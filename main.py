import os
import json
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

load_dotenv()

app = FastAPI(title="Processador de NF - N2 Etapa 1")
templates = Jinja2Templates(directory="templates")

# Configuração do Cliente Gemini
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

# =====================================================================
# Modelos de Dados (Schemas para Contas a Pagar e Flexibilidade Futura)
# =====================================================================

class Fornecedor(BaseModel):
    razaoSocial: Optional[str] = Field(None, description="Razão Social do emitente")
    nomeFantasia: Optional[str] = Field(None, description="Nome Fantasia do emitente")
    cnpj: Optional[str] = Field(None, description="CNPJ do emitente formatado ou dígitos")

class Faturado(BaseModel):
    nomeCompleto: Optional[str] = Field(None, description="Nome completo ou Razão Social do destinatário")
    cpf: Optional[str] = Field(None, description="CPF ou CNPJ do faturado/destinatário")

class Parcela(BaseModel):
    numeroParcela: int = Field(1, description="Número identificador da parcela")
    dataVencimento: Optional[str] = Field(None, description="Data de vencimento no formato AAAA-MM-DD")
    valorParcela: Optional[float] = Field(None, description="Valor nominal da parcela")

class ClassificacaoDespesa(BaseModel):
    categoria: str = Field(
        description="Uma das categorias: INSUMOS AGRÍCOLAS, MANUTENÇÃO E OPERAÇÃO, RECURSOS HUMANOS, "
                    "SERVIÇOS OPERACIONAIS, INFRAESTRUTURA E UTILIDADES, ADMINISTRATIVAS, "
                    "SEGUROS E PROTEÇÃO, IMPOSTOS E TAXAS, INVESTIMENTOS, OUTROS"
    )
    justificativa: Optional[str] = Field(
        None, description="Breve justificativa baseada nos itens da nota"
    )

class NotaFiscalExtraida(BaseModel):
    numeroNotaFiscal: Optional[str] = Field(None, description="Número da NF-e / NFS-e")
    dataEmissao: Optional[str] = Field(None, description="Data de emissão no formato AAAA-MM-DD")
    fornecedor: Fornecedor
    faturado: Faturado
    descricaoProdutos: List[str] = Field(
        default_factory=list,
        description="Lista textual com a descrição de cada produto/serviço constante na nota"
    )
    quantidadeParcelas: int = Field(1, description="Quantidade total de parcelas")
    parcelas: List[Parcela] = Field(
        default_factory=list,
        description="Lista de parcelas da nota com data de vencimento e valor"
    )
    valorTotal: float = Field(0.0, description="Valor total da nota fiscal")
    classificacaoDespesa: List[ClassificacaoDespesa] = Field(
        default_factory=list,
        description="Classificações de despesa atribuídas com base nos produtos"
    )

# =====================================================================
# System Instructions e Categorias de Despesa Obrigatórias
# =====================================================================

SYSTEM_INSTRUCTION = """
Você é um agente especialista em processamento de Notas Fiscais e classificação contábil/financeira para agronegócio e empresas.
Sua missão é extrair com extrema precisão os dados da Nota Fiscal em anexo e classificar a DESPESA.

REGRAS DE CLASSIFICAÇÃO DE DESPESA (interprete com base nos produtos/serviços):
1. INSUMOS AGRÍCOLAS: Sementes, Fertilizantes, Adubos, Defensivos Agrícolas, Corretivos, Calcário, etc.
2. MANUTENÇÃO E OPERAÇÃO: Combustíveis (ex: Óleo Diesel, Gasolina), Lubrificantes, Peças, Parafusos, Componentes Mecânicos, Manutenção de Máquinas/Equipamentos, Pneus, Filtros, Correias, Ferramentas e Utensílios.
3. RECURSOS HUMANOS: Mão de Obra Temporária, Salários e Encargos, Diárias.
4. SERVIÇOS OPERACIONAIS: Frete e Transporte, Colheita Terceirizada, Secagem e Armazenagem, Pulverização e Aplicação Aérea/Terrestre.
5. INFRAESTRUTURA E UTILIDADES: Energia Elétrica, Arrendamento de Terras, Materiais de Construção, Material Hidráulico/Elétrico, Construções e Reformas.
6. ADMINISTRATIVAS: Honorários (Contábeis, Advocatícios, Agronômicos), Despesas Bancárias, Material de Escritório, Softwares.
7. SEGUROS E PROTEÇÃO: Seguro Agrícola, Seguro de Ativos (Máquinas/Veículos), Seguro Prestamista.
8. IMPOSTOS E TAXAS: ITR, IPTU, IPVA, INCRA-CCIR, Taxas Federais/Estaduais/Municipais.
9. INVESTIMENTOS: Aquisição de Máquinas e Implementos, Aquisição de Veículos, Aquisição de Imóveis, Infraestrutura Rural Permanente.

Instruções Adicionais:
- Extraia sempre a lista textual de 'descricaoProdutos'.
- Na falta de data de vencimento explícita para parcelas, utilize a data de emissão ou o prazo informado.
- Garanta que 'parcelas' e 'classificacaoDespesa' sejam retornadas em listas estruturadas.
"""

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.post("/api/extrair-nf")
async def extrair_nota_fiscal(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="O arquivo enviado deve ser um documento PDF.")
    
    if not client:
        raise HTTPException(status_code=500, detail="Chave GEMINI_API_KEY não configurada no servidor.")

    try:
        pdf_bytes = await file.read()

        # Chamada ao modelo Gemini 1.5 Flash usando suporte nativo a PDF (inline bytes)
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                "Analise este documento PDF de Nota Fiscal, extraia todos os campos obrigatórios e classifique a despesa conforme as regras."
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=NotaFiscalExtraida,
                temperature=0.1
            )
        )

        dados_json = json.loads(response.text)
        return JSONResponse(content={"status": "success", "dados": dados_json})

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Falha ao processar Nota Fiscal: {str(e)}"}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)