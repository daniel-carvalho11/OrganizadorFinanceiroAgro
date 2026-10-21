"""
Popula o banco de dados LOCAL com dados de exemplo (fornecedores, clientes,
faturados, contas a pagar e a receber, com parcelas quitadas, em aberto e vencidas).

Uso:  python seed_demo.py
Pode ser executado mais de uma vez: NFs já lançadas são ignoradas.
Por segurança, recusa rodar no Render (variável RENDER definida).
"""
import os
import sys
from datetime import date, timedelta

from database import init_db, descrever_banco, SessionLocal
from agents.agent2 import Agent2
import servico_cadastros
from models import MovimentoContas, Parcela

HOJE = date.today()


def _dia(delta_dias: int) -> str:
    return (HOJE + timedelta(days=delta_dias)).isoformat()


PESSOAS = [
    {"tipo": "CLIENTE-FORNECEDOR", "razao_social": "IGUACU MAQUINAS AGRICOLAS LTDA", "nome_fantasia": "IGUAÇU MÁQUINAS", "documento": "33656729002385"},
    {"tipo": "FORNECEDOR", "razao_social": "AGROPEÇAS DO CERRADO LTDA", "nome_fantasia": "AGROPEÇAS", "documento": "12345678000190"},
    {"tipo": "FORNECEDOR", "razao_social": "POSTO RIO VERDE COMBUSTIVEIS LTDA", "nome_fantasia": "POSTO RIO VERDE", "documento": "45987321000155"},
    {"tipo": "CLIENTE", "razao_social": "COOPERATIVA AGROINDUSTRIAL DO SUDOESTE", "nome_fantasia": "COOPERSUL", "documento": "11222333000181"},
    {"tipo": "CLIENTE", "razao_social": "CEREALISTA BOA SAFRA LTDA", "nome_fantasia": "BOA SAFRA", "documento": "22333444000172"},
    {"tipo": "FATURADO", "razao_social": "CICLANO DA SILVA", "documento": "99999999999"},
]

# (tipo, nº NF, emitente, documento do emitente, dias desde a emissão, valor, parcelas, classificações, produtos)
LANCAMENTOS = [
    ("Despesa", "000.084.682", "IGUACU MAQUINAS AGRICOLAS LTDA", "33656729002385", -40, 3086.75, 1,
     ["MANUTENÇÃO E OPERAÇÃO"], "GRAXA DE POLIUREIA, ROLAMENTO DE ESFERAS, ESTOPA"),
    ("Despesa", "000.123.456", "AGROPEÇAS DO CERRADO LTDA", "12345678000190", -20, 4500.00, 3,
     ["MANUTENÇÃO E OPERAÇÃO", "INVESTIMENTOS"], "KIT EMBREAGEM, IMPLEMENTO GRADE ARADORA"),
    ("Despesa", "58231", "POSTO RIO VERDE COMBUSTIVEIS LTDA", "45987321000155", -5, 1890.40, 1,
     ["MANUTENÇÃO E OPERAÇÃO"], "ÓLEO DIESEL S10"),
    ("Despesa", "7781", "AGROPEÇAS DO CERRADO LTDA", "12345678000190", -60, 12800.00, 2,
     ["INSUMOS AGRÍCOLAS"], "SEMENTE DE SOJA, FERTILIZANTE NPK 20-05-20"),
    ("Receita", "1001", "COOPERATIVA AGROINDUSTRIAL DO SUDOESTE", "11222333000181", -30, 48000.00, 2,
     ["VENDA DE PRODUÇÃO AGRÍCOLA"], "SOJA EM GRÃOS - 400 SACAS"),
    ("Receita", "1002", "CEREALISTA BOA SAFRA LTDA", "22333444000172", -10, 21500.00, 3,
     ["VENDA DE PRODUÇÃO AGRÍCOLA", "PRESTAÇÃO DE SERVIÇOS"], "MILHO EM GRÃOS E SECAGEM"),
    ("Receita", "1003", "COOPERATIVA AGROINDUSTRIAL DO SUDOESTE", "11222333000181", -2, 6000.00, 1,
     ["ARRENDAMENTO RECEBIDO"], "ARRENDAMENTO DE PASTAGEM"),
]

# NFs cuja primeira parcela será marcada como paga/recebida (a NF 7781 fica VENCIDA de propósito)
PRIMEIRA_PARCELA_QUITADA = {"000.084.682", "1001"}


def main():
    if os.environ.get("RENDER"):
        sys.exit("seed_demo.py é apenas para bancos locais. Abortado.")

    init_db()
    print(f"Banco em uso: {descrever_banco()}")

    for pessoa in PESSOAS:
        res = servico_cadastros.criar_pessoa(pessoa)
        print(f"  pessoa  {pessoa['razao_social'][:40]:<40} {'criada' if res['status'] == 'success' else 'já existe'}")

    agent2 = Agent2()
    for tipo, nf, emitente, doc, dias, valor, parcelas, categorias, produtos in LANCAMENTOS:
        res = agent2.criar_movimento_manual({
            "tipo": tipo, "numero_nota_fiscal": nf, "data_emissao": _dia(dias), "valor_total": valor,
            "emitente_nome": emitente, "emitente_documento": doc,
            "destinatario_nome": "CICLANO DA SILVA", "destinatario_documento": "99999999999",
            "quantidade_parcelas": parcelas, "categorias": categorias, "descricao_produtos": produtos,
            "data_vencimento": _dia(dias + 30),
        })
        print(f"  {tipo:<7} NF {nf:<12} {'lançada' if res['status'] == 'success' else 'ignorada: ' + res['message']}")
        if res["status"] == "success" and nf in PRIMEIRA_PARCELA_QUITADA:
            agent2.registrar_pagamento_parcela(res["dados"]["parcelas"][0]["id_parcela"])

    session = SessionLocal()
    try:
        print(f"Total: {session.query(MovimentoContas).count()} lançamentos, {session.query(Parcela).count()} parcelas.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
