"""
Relatórios de Contas a Pagar (Despesa) e Contas a Receber (Receita).

Lista as NFs ativas do período com sua natureza (classificação), situação de
pagamento e totais consolidados por natureza.
"""
from datetime import date
from typing import Dict, Any, Optional
from database import SessionLocal
from models import MovimentoContas
from servico_persistencia import parse_data, normalizar_tipo_classificacao

SITUACOES = ("todas", "abertas", "vencidas", "quitadas")


def _situacao_nota(parcelas, hoje: date) -> str:
    """QUITADA, VENCIDA (alguma parcela aberta já venceu), PARCIAL (algo pago) ou EM ABERTO."""
    if not parcelas or all(p.status == "quitada" for p in parcelas):
        return "QUITADA"
    if any(p.status != "quitada" and p.data_vencimento and p.data_vencimento < hoje for p in parcelas):
        return "VENCIDA"
    if any(float(p.valor_pago or 0) > 0 for p in parcelas):
        return "PARCIAL"
    return "EM ABERTO"


def gerar_relatorio(
    tipo: str,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
    situacao: str = "todas",
    natureza: Optional[str] = None,
    hoje: Optional[date] = None,
) -> Dict[str, Any]:
    tipo = normalizar_tipo_classificacao(tipo)
    situacao = situacao if situacao in SITUACOES else "todas"
    hoje = hoje or date.today()

    session = SessionLocal()
    try:
        query = session.query(MovimentoContas).filter(
            MovimentoContas.tipo == tipo, MovimentoContas.status == "ativo"
        )
        d_ini, d_fim = parse_data(data_inicio), parse_data(data_fim)
        if d_ini:
            query = query.filter(MovimentoContas.data_emissao >= d_ini)
        if d_fim:
            query = query.filter(MovimentoContas.data_emissao <= d_fim)

        notas, por_natureza = [], {}
        totais = {"quantidade_nfs": 0, "valor_total": 0.0, "valor_pago": 0.0, "saldo_aberto": 0.0, "saldo_vencido": 0.0}

        for mov in query.order_by(MovimentoContas.data_emissao, MovimentoContas.id_movimento_contas).all():
            naturezas = [a.classificacao.descricao for a in mov.classificacoes_associadas if a.classificacao]
            if natureza and natureza not in naturezas:
                continue

            parcelas = sorted(mov.parcelas, key=lambda p: (p.data_vencimento or date.max, p.id_parcela))
            sit = _situacao_nota(parcelas, hoje)
            if situacao == "abertas" and sit == "QUITADA":
                continue
            if situacao == "vencidas" and sit != "VENCIDA":
                continue
            if situacao == "quitadas" and sit != "QUITADA":
                continue

            valor_total = float(mov.valor_total or 0)
            valor_pago = sum(float(p.valor_pago or 0) for p in parcelas)
            saldo = sum(float(p.valor_saldo or 0) for p in parcelas if p.status != "quitada")
            vencido = sum(
                float(p.valor_saldo or 0) for p in parcelas
                if p.status != "quitada" and p.data_vencimento and p.data_vencimento < hoje
            )
            proxima = next((p for p in parcelas if p.status != "quitada"), None)

            notas.append({
                "id_movimento_contas": mov.id_movimento_contas,
                "numero_nota_fiscal": mov.numero_nota_fiscal,
                "data_emissao": str(mov.data_emissao) if mov.data_emissao else None,
                "emitente": mov.emitente.razao_social if mov.emitente else None,
                "emitente_documento": mov.emitente.to_dict()["documento"] if mov.emitente else None,
                "destinatario": mov.destinatario.razao_social if mov.destinatario else None,
                "naturezas": naturezas,
                "valor_total": valor_total,
                "valor_pago": round(valor_pago, 2),
                "saldo": round(saldo, 2),
                "situacao": sit,
                "parcelas_quitadas": sum(1 for p in parcelas if p.status == "quitada"),
                "parcelas_total": len(parcelas),
                "proximo_vencimento": str(proxima.data_vencimento) if proxima and proxima.data_vencimento else None,
            })

            totais["quantidade_nfs"] += 1
            totais["valor_total"] += valor_total
            totais["valor_pago"] += valor_pago
            totais["saldo_aberto"] += saldo
            totais["saldo_vencido"] += vencido

            # NF com mais de uma natureza: o valor é rateado igualmente entre elas
            for nome in naturezas or ["SEM CLASSIFICAÇÃO"]:
                item = por_natureza.setdefault(nome, {"natureza": nome, "quantidade_nfs": 0, "valor": 0.0, "saldo": 0.0})
                fator = 1 / max(len(naturezas), 1)
                item["quantidade_nfs"] += 1
                item["valor"] += valor_total * fator
                item["saldo"] += saldo * fator

        resumo_naturezas = sorted(
            ({**n, "valor": round(n["valor"], 2), "saldo": round(n["saldo"], 2)} for n in por_natureza.values()),
            key=lambda n: n["valor"], reverse=True
        )
        return {
            "tipo": tipo,
            "titulo": "Contas a Pagar" if tipo == "Despesa" else "Contas a Receber",
            "filtros": {"data_inicio": data_inicio, "data_fim": data_fim, "situacao": situacao, "natureza": natureza},
            "gerado_em": str(hoje),
            "totais": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in totais.items()},
            "por_natureza": resumo_naturezas,
            "notas": notas,
        }
    finally:
        session.close()
