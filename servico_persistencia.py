import re
import calendar
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import Session
from models import Pessoa, MovimentoContas, Parcela, Classificacao, MovimentoHasClassificacao

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



# =====================================================================
# Normalização de dados (evita duplicidade por diferença de máscara/caixa)
# =====================================================================

def normalizar_documento(documento: Optional[str]) -> str:
    """Remove máscara de CPF/CNPJ, mantendo apenas os dígitos."""
    return re.sub(r"\D", "", documento or "")

def normalizar_numero_nf(numero: Optional[str]) -> str:
    """Normaliza o número da NF para comparação (000.084.682 == 84682)."""
    return normalizar_documento(numero).lstrip("0")

def normalizar_tipo_classificacao(tipo: Optional[str]) -> str:
    """Padroniza o tipo da classificação para 'Despesa' ou 'Receita'."""
    return "Receita" if (tipo or "").strip().upper() == "RECEITA" else "Despesa"

def identificacao_parcela(indice: int, total: int) -> str:
    """Parcela única recebe 'ÚNICA'; demais seguem o padrão '1/3', '2/3'..."""
    return "ÚNICA" if total <= 1 else f"{indice}/{total}"

def sem_mascara(coluna):
    """Expressão SQL que remove '.', '/', '-' e espaços de uma coluna (SQLite e PostgreSQL)."""
    expr = coluna
    for ch in (".", "/", "-", " "):
        expr = func.replace(expr, ch, "")
    return expr

def filtro_multitermos(termo: Optional[str], colunas: list):
    """
    Busca por mais de um elemento: cada palavra digitada deve aparecer em
    pelo menos uma das colunas (ex.: 'iguaçu 84682' ou 'beltrano 999').
    """
    if not termo or not termo.strip():
        return None
    condicoes = []
    for palavra in termo.split():
        like = f"%{palavra}%"
        alternativas = [c.ilike(like) for c in colunas]
        digitos = normalizar_documento(palavra)
        if digitos and digitos != palavra:
            alternativas += [sem_mascara(c).ilike(f"%{digitos}%") for c in colunas]
        condicoes.append(or_(*alternativas))
    return and_(*condicoes)


# =====================================================================
# Consultas de existência no banco
# =====================================================================

def buscar_pessoa(db: Session, documento: Optional[str], razao_social: Optional[str]) -> Optional[Pessoa]:
    """Procura a pessoa pelo CPF/CNPJ (ignorando máscara) e, na falta dele, pela razão social."""
    doc = normalizar_documento(documento)
    if doc:
        pessoa = db.query(Pessoa).filter(sem_mascara(Pessoa.documento) == doc).first()
        if pessoa:
            return pessoa
    nome = (razao_social or "").strip()
    if nome:
        return db.query(Pessoa).filter(func.upper(Pessoa.razao_social) == nome.upper()).first()
    return None

def buscar_classificacao(db: Session, descricao: Optional[str]) -> Optional[Classificacao]:
    """Procura a classificação pela descrição, sem diferenciar maiúsculas/minúsculas."""
    nome = (descricao or "").strip()
    if not nome:
        return None
    return db.query(Classificacao).filter(func.upper(Classificacao.descricao) == nome.upper()).first()

def buscar_movimento_duplicado(
    db: Session, numero_nf: Optional[str], tipo: Optional[str], id_emitente: Optional[int],
    ignorar_id: Optional[int] = None
) -> Optional[MovimentoContas]:
    """
    Retorna um movimento ATIVO que conflita com o número de NF informado:
    - Contas a Pagar (Despesa): mesma NF do mesmo fornecedor (a numeração é de cada emitente).
    - Contas a Receber (Receita): mesma NF em qualquer receita (a numeração é da própria fazenda).
    """
    numero = normalizar_numero_nf(numero_nf)
    tipo = normalizar_tipo_classificacao(tipo)
    if not numero or (tipo == "Despesa" and not id_emitente):
        return None
    candidatos = db.query(MovimentoContas).filter(
        MovimentoContas.tipo == tipo,
        MovimentoContas.status == "ativo",
    )
    if tipo == "Despesa":
        candidatos = candidatos.filter(MovimentoContas.id_pessoa_emitente == id_emitente)
    if ignorar_id:
        candidatos = candidatos.filter(MovimentoContas.id_movimento_contas != ignorar_id)
    for mov in candidatos.all():
        if normalizar_numero_nf(mov.numero_nota_fiscal) == numero:
            return mov
    return None


def mensagem_duplicidade(duplicado: MovimentoContas) -> str:
    """Texto padrão exibido quando a NF já está lançada."""
    if duplicado.tipo == "Receita":
        return f"A NF {duplicado.numero_nota_fiscal} já está lançada em Contas a Receber (lançamento #{duplicado.id_movimento_contas})."
    return f"A NF {duplicado.numero_nota_fiscal} deste fornecedor já está lançada em Contas a Pagar (lançamento #{duplicado.id_movimento_contas})."


def validar_documento(documento: Optional[str], rotulo: str) -> Optional[str]:
    """CPF/CNPJ é opcional, mas quando informado precisa ter 11 ou 14 dígitos."""
    digitos = normalizar_documento(documento)
    if digitos and len(digitos) not in (11, 14):
        return f"{rotulo}: CPF deve ter 11 dígitos e CNPJ 14 dígitos (informado: {len(digitos)})."
    return None


# =====================================================================
# Gravação do movimento extraído da Nota Fiscal
# =====================================================================

def salvar_nota_fiscal(
    dados_json: Dict[str, Any],
    emitente: Pessoa,
    destinatario: Pessoa,
    classificacoes: List[Tuple[Classificacao, Optional[str]]],
    db: Session,
) -> MovimentoContas:
    """
    Persiste o MovimentoContas (APAGAR), suas Parcelas e o vínculo N:M com as classificações.
    Fornecedor, Faturado e Classificações já devem ter sido resolvidos (consultados/criados)
    pelo Agent2. Não faz commit: o chamador controla a transação.
    """
    produtos_lista = dados_json.get("descricaoProdutos", [])
    descricao_produtos = "\n".join(produtos_lista) if isinstance(produtos_lista, list) else str(produtos_lista or "")

    data_emissao = parse_data(dados_json.get("dataEmissao"))
    valor_total = float(dados_json.get("valorTotal") or 0.0)
    movimento = MovimentoContas(
        tipo="Despesa",
        numero_nota_fiscal=dados_json.get("numeroNotaFiscal"),
        data_emissao=data_emissao,
        descricao_produtos=descricao_produtos,
        valor_total=valor_total,
        status="ativo",
        id_pessoa_emitente=emitente.id_pessoa,
        id_pessoa_destinatario=destinatario.id_pessoa
    )
    db.add(movimento)
    db.flush()

    # Parcelas: usa as da fatura; se não houver, gera parcela única com o valor total
    parcelas_lista = dados_json.get("parcelas") or [{"numeroParcela": 1, "valorParcela": valor_total}]
    data_base_venc = parse_data(dados_json.get("dataVencimento")) or data_emissao or date.today()
    total = len(parcelas_lista)

    for idx, item_p in enumerate(parcelas_lista, start=1):
        data_venc_raw = parse_data(item_p.get("dataVencimento"))
        if data_venc_raw:
            # Data explícita da fatura: ajusta para dia útil se cair em fds ou feriado
            data_venc = ajustar_dia_util(data_venc_raw)
        else:
            # Calcula mensalmente no mesmo dia + dia útil
            data_venc = calcular_vencimento_parcela(data_base_venc, idx)

        val_p = float(item_p.get("valorParcela") or (valor_total if total == 1 else 0.0))
        db.add(Parcela(
            id_movimento_contas=movimento.id_movimento_contas,
            identificacao=identificacao_parcela(item_p.get("numeroParcela") or idx, total),
            data_vencimento=data_venc,
            valor_parcela=val_p,
            valor_pago=0.0,
            valor_saldo=val_p,
            status="aberta"
        ))

    # Classificações de Despesa (Relacionamento N:M), sem repetir a mesma categoria
    ids_vinculados = set()
    for cat_db, justificativa in classificacoes:
        if cat_db.id_classificacao in ids_vinculados:
            continue
        ids_vinculados.add(cat_db.id_classificacao)
        db.add(MovimentoHasClassificacao(
            id_movimento_contas=movimento.id_movimento_contas,
            id_classificacao=cat_db.id_classificacao,
            justificativa=justificativa
        ))

    db.flush()
    return movimento
