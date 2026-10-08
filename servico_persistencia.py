from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from models import Pessoa, MovimentoContas, Parcela, Classificacao, MovimentoHasClassificacao
from database import SessionLocal

def parse_data(data_str: Optional[str]):
    """Converte string de data (YYYY-MM-DD ou DD/MM/YYYY) em objeto date."""
    if not data_str:
        return None
    data_str = str(data_str).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(data_str, fmt).date()
        except ValueError:
            continue
    return None

def salvar_nota_fiscal(dados_json: Dict[str, Any], session: Optional[Session] = None) -> MovimentoContas:
    """
    Recebe os dados JSON extraídos pelo Agent1 e os persiste no Banco de Dados Relacional
    respeitando todas as regras de negócio (Pessoas, MovimentoContas, Parcelas, Classificação).
    """
    db = session or SessionLocal()
    should_close = session is None

    try:
        # 1. Processa ou busca Pessoa Emitente (Fornecedor)
        fornecedor_dados = dados_json.get("fornecedor", {})
        doc_fornecedor = (fornecedor_dados.get("cnpj") or "").strip()
        razao_fornecedor = (fornecedor_dados.get("razaoSocial") or "Fornecedor Não Identificado").strip()
        fantasia_fornecedor = fornecedor_dados.get("fantasia")

        emitente = None
        if doc_fornecedor:
            emitente = db.query(Pessoa).filter_by(documento=doc_fornecedor).first()
        if not emitente:
            emitente = db.query(Pessoa).filter_by(razao_social=razao_fornecedor).first()
        
        if not emitente:
            emitente = Pessoa(
                tipo="Jurídica",
                razao_social=razao_fornecedor,
                nome_fantasia=fantasia_fornecedor,
                documento=doc_fornecedor,
                status="ativo"
            )
            db.add(emitente)
            db.flush()

        # 2. Processa ou busca Pessoa Destinatário (Faturado)
        faturado_dados = dados_json.get("faturado", {})
        doc_faturado = (faturado_dados.get("cpf") or "").strip()
        nome_faturado = (faturado_dados.get("nomeCompleto") or "Destinatário Não Identificado").strip()

        destinatario = None
        if doc_faturado:
            destinatario = db.query(Pessoa).filter_by(documento=doc_faturado).first()
        if not destinatario:
            destinatario = db.query(Pessoa).filter_by(razao_social=nome_faturado).first()

        if not destinatario:
            tipo_doc = "Física" if len(doc_faturado) <= 14 else "Jurídica"
            destinatario = Pessoa(
                tipo=tipo_doc,
                razao_social=nome_faturado,
                nome_fantasia=None,
                documento=doc_faturado,
                status="ativo"
            )
            db.add(destinatario)
            db.flush()

        # 3. Prepara a descrição concatenada dos produtos (Regra de Negócio: Sem Entidade de Produtos)
        produtos_lista = dados_json.get("descricaoProdutos", [])
        descricao_produtos = "\n".join(produtos_lista) if isinstance(produtos_lista, list) else str(produtos_lista)

        # 4. Cria o MovimentoContas
        data_emissao = parse_data(dados_json.get("dataEmissao"))
        movimento = MovimentoContas(
            tipo="Despesa",
            numero_nota_fiscal=dados_json.get("numeroNotaFiscal"),
            data_emissao=data_emissao,
            descricao_produtos=descricao_produtos,
            valor_total=float(dados_json.get("valorTotal") or 0.0),
            status="ativo",
            id_pessoa_emitente=emitente.id_pessoa,
            id_pessoa_destinatario=destinatario.id_pessoa
        )
        db.add(movimento)
        db.flush()

        # 5. Processa as Parcelas
        parcelas_lista = dados_json.get("parcelas", [])
        if not parcelas_lista:
            # Cria parcela única se a lista estiver vazia
            data_venc = parse_data(dados_json.get("dataVencimento"))
            val = float(dados_json.get("valorTotal") or 0.0)
            p = Parcela(
                id_movimento_contas=movimento.id_movimento_contas,
                identificacao="Parcela 1",
                data_vencimento=data_venc,
                valor_parcela=val,
                valor_pago=0.0,
                valor_saldo=val,
                status="aberta"
            )
            db.add(p)
        else:
            for item_p in parcelas_lista:
                num_p = item_p.get("numeroParcela", 1)
                data_venc = parse_data(item_p.get("dataVencimento"))
                val_p = float(item_p.get("valorParcela") or 0.0)
                p = Parcela(
                    id_movimento_contas=movimento.id_movimento_contas,
                    identificacao=f"Parcela {num_p}",
                    data_vencimento=data_venc,
                    valor_parcela=val_p,
                    valor_pago=0.0,
                    valor_saldo=val_p,
                    status="aberta"
                )
                db.add(p)

        # 6. Processa as Classificações de Despesa (Relacionamento N:M)
        classificacoes_lista = dados_json.get("classificacaoDespesa", [])
        for c in classificacoes_lista:
            cat_nome = (c.get("categoria") or "OUTRAS").strip()
            justificativa = c.get("justificativa")

            # Busca ou cria a categoria na tabela classificacao
            cat_db = db.query(Classificacao).filter_by(descricao=cat_nome).first()
            if not cat_db:
                cat_db = Classificacao(tipo="Despesa", descricao=cat_nome, status="ativo")
                db.add(cat_db)
                db.flush()

            # Cria o vínculo N:M na tabela movimento_has_classificacao
            assoc = MovimentoHasClassificacao(
                id_movimento_contas=movimento.id_movimento_contas,
                id_classificacao=cat_db.id_classificacao,
                justificativa=justificativa
            )
            db.add(assoc)

        db.commit()
        db.refresh(movimento)
        return movimento

    except Exception as e:
        db.rollback()
        raise e
    finally:
        if should_close:
            db.close()
