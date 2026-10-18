import calendar
from datetime import datetime, date, timedelta
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

def ajustar_dia_util(dt: Optional[date]) -> Optional[date]:
    """Ajusta a data para o próximo dia útil se cair em final de semana ou feriado nacional fixo."""
    if not dt:
        return None
    if isinstance(dt, datetime):
        dt = dt.date()
        
    feriados_fixos = {
        (1, 1),   # Ano Novo
        (4, 21),  # Tiradentes
        (5, 1),   # Dia do Trabalho
        (9, 7),   # Independência
        (10, 12), # Nossa Senhora Aparecida
        (11, 2),  # Finados
        (11, 15), # Proclamação da República
        (11, 20), # Consciência Negra
        (12, 25), # Natal
    }
    while dt.weekday() in (5, 6) or (dt.month, dt.day) in feriados_fixos:
        dt += timedelta(days=1)
    return dt

def calcular_vencimento_parcela(data_base: Optional[date], indice_parcela: int = 1) -> date:
    """
    Calcula a data de vencimento para a parcela (indice_parcela 1, 2, 3...).
    - Mantém o mesmo dia do mês da data base.
    - Avança (indice_parcela - 1) meses.
    - Se o dia exceder os dias do mês alvo (ex: 31 de fev), usa o último dia do mês.
    - Ajusta a data para o próximo dia útil se for final de semana ou feriado.
    """
    if not data_base:
        data_base = date.today()
    if isinstance(data_base, datetime):
        data_base = data_base.date()
        
    meses_a_adicionar = max(0, indice_parcela - 1)
    ano = data_base.year + (data_base.month - 1 + meses_a_adicionar) // 12
    mes = (data_base.month - 1 + meses_a_adicionar) % 12 + 1
    
    ultimo_dia_mes = calendar.monthrange(ano, mes)[1]
    dia = min(data_base.day, ultimo_dia_mes)
    
    dt_alvo = date(ano, mes, dia)
    return ajustar_dia_util(dt_alvo)

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
                tipo="CLIENTE-FORNECEDOR",
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
            destinatario = Pessoa(
                tipo="FATURADO",
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
        data_base_venc = parse_data(dados_json.get("dataVencimento")) or data_emissao or date.today()

        if not parcelas_lista:
            # Cria parcela única se a lista estiver vazia
            data_venc = calcular_vencimento_parcela(data_base_venc, 1)
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
            for idx, item_p in enumerate(parcelas_lista, start=1):
                num_p = item_p.get("numeroParcela", idx)
                data_venc_raw = parse_data(item_p.get("dataVencimento"))
                if data_venc_raw:
                    # Data explícita da fatura: ajusta para dia útil se cair em fds ou feriado
                    data_venc = ajustar_dia_util(data_venc_raw)
                else:
                    # Calcula mensalmente no mesmo dia + dia útil
                    data_venc = calcular_vencimento_parcela(data_base_venc, idx)

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
