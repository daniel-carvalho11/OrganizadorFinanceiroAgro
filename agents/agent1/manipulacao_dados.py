import os
import json
from pathlib import Path
from typing import List, Optional, Union
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

load_dotenv()

# =====================================================================
# Modelos de Dados (Schemas para Contas a Pagar - Conforme Slides e Regras)
# =====================================================================

class Fornecedor(BaseModel):
    razaoSocial: Optional[str] = Field(None, description="Razão Social do emitente/fornecedor")
    fantasia: Optional[str] = Field(None, description="Nome Fantasia do emitente/fornecedor")
    cnpj: Optional[str] = Field(None, description="CNPJ do emitente/fornecedor")

class Faturado(BaseModel):
    nomeCompleto: Optional[str] = Field(None, description="Nome completo ou Razão Social do faturado/destinatário")
    cpf: Optional[str] = Field(None, description="CPF ou CNPJ do faturado/destinatário")

class Parcela(BaseModel):
    numeroParcela: int = Field(1, description="Número identificador da parcela")
    dataVencimento: Optional[str] = Field(None, description="Data de vencimento da parcela")
    valorParcela: Optional[float] = Field(None, description="Valor nominal da parcela")

class ClassificacaoDespesa(BaseModel):
    categoria: str = Field(
        description="Categoria da despesa conforme regras: INSUMOS AGRÍCOLAS, MANUTENÇÃO E OPERAÇÃO, "
                    "RECURSOS HUMANOS, SERVIÇOS OPERACIONAIS, INFRAESTRUTURA E UTILIDADES, "
                    "ADMINISTRATIVAS, SEGUROS E PROTEÇÃO, IMPOSTOS E TAXAS, INVESTIMENTOS"
    )
    justificativa: Optional[str] = Field(
        None, description="Breve justificativa baseada nos produtos da nota fiscal"
    )

class NotaFiscalExtraida(BaseModel):
    numeroNotaFiscal: Optional[str] = Field(None, description="Número da Nota Fiscal (ex: 000.084.682)")
    dataEmissao: Optional[str] = Field(None, description="Data de emissão (ex: 2025-09-19 ou 19/09/2025)")
    fornecedor: Fornecedor = Field(description="Dados do Fornecedor: Razão Social, Fantasia e CNPJ")
    faturado: Faturado = Field(description="Dados do Faturado: Nome Completo e CPF")
    descricaoProdutos: List[str] = Field(
        default_factory=list,
        description="Lista textual com a descrição de cada produto/serviço (sem criar entidade de produtos)"
    )
    quantidadeParcelas: int = Field(
        1, description="Quantidade total de parcelas (neste momento 1, com estrutura para mais)"
    )
    dataVencimento: Optional[str] = Field(
        None, description="Data de vencimento da fatura/parcela"
    )
    parcelas: List[Parcela] = Field(
        default_factory=list,
        description="Lista estruturada de parcelas com data de vencimento e valor"
    )
    valorTotal: float = Field(0.0, description="Valor total da nota fiscal")
    classificacaoDespesa: List[ClassificacaoDespesa] = Field(
        default_factory=list,
        description="Classificação da despesa (uma por registro, com estrutura para receber mais de uma)"
    )

# =====================================================================
# Instrução do Sistema para o Agente Gemini
# =====================================================================

SYSTEM_INSTRUCTION = """
Você é um agente especialista em processamento de Notas Fiscais (CONTAS A PAGAR) e classificação financeira.
Sua missão é analisar com extrema precisão o documento PDF da Nota Fiscal fornecida e extrair os dados estruturados no formato JSON especificado.

REGRAS OBRIGATÓRIAS DE EXTRAÇÃO:
1. Fornecedor:
   - razaoSocial: Razão Social do emitente (ex: IGUACU MAQUINAS AGRICOLAS LTDA).
   - fantasia: Nome Fantasia (se houver, ou derivado da razão social).
   - cnpj: CNPJ do fornecedor emitente.
2. Faturado:
   - nomeCompleto: Nome Completo do destinatário (ex: CICLANO DA SILVA).
   - cpf: CPF ou CNPJ do faturado/destinatário.
3. Número da Nota Fiscal: Número da NF-e / DANFE (ex: 000.084.682).
4. Data de Emissão: Data em que a nota fiscal foi emitida.
5. Descrição dos produtos: Lista contendo APENAS a descrição textual de cada item constante na nota fiscal (NÃO crie uma entidade separada de produtos).
6. Quantidade de Parcelas: Quantidade total de parcelas encontradas no quadro de Fatura / Duplicatas (ex: 1).
7. Data de Vencimento: Data de vencimento principal constante na fatura/duplicata da nota fiscal.
8. Parcelas: Lista contendo cada parcela com seu número identificador, data de vencimento e valor nominal.
9. ValorTotal: Valor total da nota fiscal constante no campo VALOR TOTAL DA NOTA.

REGRAS DE CLASSIFICAÇÃO DA DESPESA (ATENÇÃO: A despesa NÃO é um campo extraído do documento, ela deve ser INTERPRETADA com base nos produtos/serviços da nota fiscal):
- INSUMOS AGRÍCOLAS:
  * Sementes, Fertilizantes, Defensivos Agrícolas, Corretivos
- MANUTENÇÃO E OPERAÇÃO:
  * Combustíveis e Lubrificantes (ex: Óleo Diesel, Gasolina, Graxas)
  * Peças, Parafusos, Componentes Mecânicos (ex: Rolamentos, Buchas, Anéis, Apoios)
  * Manutenção de Máquinas e Equipamentos
  * Pneus, Filtros, Correias
  * Ferramentas e Utensílios
  * Materiais de limpeza mecânica (ex: Estopa, Panos de limpeza, Limpadores)
- RECURSOS HUMANOS:
  * Mão de Obra Temporária, Salários e Encargos
- SERVIÇOS OPERACIONAIS:
  * Frete e Transporte, Colheita Terceirizada, Secagem e Armazenagem, Pulverização e Aplicação
- INFRAESTRUTURA E UTILIDADES:
  * Energia Elétrica, Arrendamento de Terras, Construções e Reformas, Materiais de Construção (ex: Material Hidráulico, Elétrico)
- ADMINISTRATIVAS:
  * Honorários (Contábeis, Advocatícios, Agronômicos), Despesas Bancárias e Financeiras
- SEGUROS E PROTEÇÃO:
  * Seguro Agrícola, Seguro de Ativos (Máquinas/Veículos), Seguro Prestamista
- IMPOSTOS E TAXAS:
  * ITR, IPTU, IPVA, INCRA-CCIR
- INVESTIMENTOS:
  * Aquisição de Máquinas e Implementos, Aquisição de Veículos, Aquisição de Imóveis, Infraestrutura Rural
"""

# =====================================================================
# Classe do Agente 1 (conforme Slides 14, 15 e 16 da aula)
# =====================================================================

class Agent1:
    """
    Agent responsável por processar e extrair dados de documentos fiscais (PDF),
    classificando as despesas com auxílio de IA Generativa (Gemini).
    """

    def __init__(self, api_key: Optional[str] = None):
        load_dotenv()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def extrair_dados(self, file_input: Union[str, bytes, Path]) -> dict:
        """
        Extrai os dados da Nota Fiscal e retorna o dicionário estruturado.
        
        Aceita tanto o caminho do arquivo (str / Path) conforme exemplo do Slide 16,
        quanto os bytes diretamente (para uso em APIs web).
        """
        if not self.client:
            raise ValueError("Chave GEMINI_API_KEY não configurada no ambiente ou no agente.")

        # Se for caminho de arquivo, lê os bytes
        if isinstance(file_input, (str, Path)):
            with open(file_input, "rb") as f:
                pdf_bytes = f.read()
        elif isinstance(file_input, bytes):
            pdf_bytes = file_input
        else:
            raise TypeError("O parâmetro file_input deve ser um caminho de arquivo ou bytes.")

        # Modelos suportados na versão atual da API Gemini
        modelos = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]
        ultimo_erro = None

        for modelo in modelos:
            try:
                response = self.client.models.generate_content(
                    model=modelo,
                    contents=[
                        types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                        "Analise este documento PDF de Nota Fiscal, extraia com precisão todos os campos obrigatórios e classifique a despesa conforme as regras especificadas."
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        response_mime_type="application/json",
                        response_schema=NotaFiscalExtraida,
                        temperature=0.1,
                        thinking_config=types.ThinkingConfig(
                        thinking_budget=0  # 0 = desativa o raciocínio interno → resposta muito mais rápida
                        ),
                        # Desativa o AFC para suprimir o aviso informativo de terminal
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        )
                    )
                )
                dados_json = json.loads(response.text)
                return dados_json
            except Exception as e:
                ultimo_erro = e
                continue

        if ultimo_erro:
            raise ultimo_erro
