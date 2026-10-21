"""
Serviço dos cadastros (MANTER): Fornecedor, Cliente, Faturado (tabela PESSOAS)
e Tipo de Despesa / Tipo de Receita (tabela CLASSIFICACAO).

Regras de negócio:
- Cadastros não podem ser excluídos: o DELETE altera STATUS para 'inativo'.
- Deve ser possível REATIVAR um registro inativo.
- No CREATE o STATUS é sempre 'ativo'; no UPDATE o STATUS não é alterado.
"""
from typing import Dict, Any, List, Optional
from database import SessionLocal
from models import Pessoa, Classificacao
from servico_persistencia import (
    normalizar_documento, normalizar_tipo_classificacao, buscar_classificacao,
    filtro_multitermos, sem_mascara
)

TIPOS_PESSOA = ("CLIENTE-FORNECEDOR", "FORNECEDOR", "CLIENTE", "FATURADO")
STATUS_VALIDOS = ("ativo", "inativo")


def _validar_status(status: Optional[str]) -> Optional[str]:
    return status if status in STATUS_VALIDOS else None


# =====================================================================
# PESSOAS (Manter Fornecedor / Cliente / Faturado)
# =====================================================================

def listar_pessoas(termo: Optional[str] = None, tipos: Optional[List[str]] = None, status: Optional[str] = "ativo") -> List[Dict[str, Any]]:
    session = SessionLocal()
    try:
        query = session.query(Pessoa)
        if status and status != "todos":
            query = query.filter(Pessoa.status == status)
        if tipos:
            query = query.filter(Pessoa.tipo.in_(tipos))
        filtro = filtro_multitermos(termo, [Pessoa.razao_social, Pessoa.nome_fantasia, Pessoa.documento, Pessoa.tipo])
        if filtro is not None:
            query = query.filter(filtro)
        return [p.to_dict() for p in query.order_by(Pessoa.razao_social).all()]
    finally:
        session.close()


def _validar_pessoa(session, dados: Dict[str, Any], id_ignorar: Optional[int] = None) -> Optional[str]:
    if not (dados.get("razao_social") or "").strip():
        return "A Razão Social / Nome é obrigatória."
    if dados.get("tipo") not in TIPOS_PESSOA:
        return f"Tipo inválido. Use: {', '.join(TIPOS_PESSOA)}."
    doc = normalizar_documento(dados.get("documento"))
    if doc and len(doc) not in (11, 14):
        return "CPF deve ter 11 dígitos e CNPJ 14 dígitos."
    if doc:
        existente = session.query(Pessoa).filter(sem_mascara(Pessoa.documento) == doc)
        if id_ignorar:
            existente = existente.filter(Pessoa.id_pessoa != id_ignorar)
        existente = existente.first()
        if existente:
            situacao = " (INATIVO - reative o cadastro)" if existente.status == "inativo" else ""
            return f"Já existe pessoa com este CPF/CNPJ: ID {existente.id_pessoa} - {existente.razao_social}{situacao}."
    return None


def criar_pessoa(dados: Dict[str, Any]) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        erro = _validar_pessoa(session, dados)
        if erro:
            return {"status": "error", "message": erro}
        pessoa = Pessoa(
            tipo=dados["tipo"],
            razao_social=dados["razao_social"].strip(),
            nome_fantasia=(dados.get("nome_fantasia") or "").strip() or None,
            documento=normalizar_documento(dados.get("documento")),
            status="ativo"  # No CREATE campo STATUS oculto == ATIVO
        )
        session.add(pessoa)
        session.commit()
        session.refresh(pessoa)
        return {"status": "success", "message": f"Cadastro #{pessoa.id_pessoa} criado com sucesso.", "dados": pessoa.to_dict()}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": f"Erro ao criar cadastro: {e}"}
    finally:
        session.close()


def editar_pessoa(id_pessoa: int, dados: Dict[str, Any]) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        pessoa = session.get(Pessoa, id_pessoa)
        if not pessoa:
            return {"status": "error", "message": "Cadastro não encontrado."}
        erro = _validar_pessoa(session, dados, id_ignorar=id_pessoa)
        if erro:
            return {"status": "error", "message": erro}
        pessoa.tipo = dados["tipo"]
        pessoa.razao_social = dados["razao_social"].strip()
        pessoa.nome_fantasia = (dados.get("nome_fantasia") or "").strip() or None
        pessoa.documento = normalizar_documento(dados.get("documento"))
        # No UPDATE o STATUS permanece oculto e inalterado
        session.commit()
        session.refresh(pessoa)
        return {"status": "success", "message": f"Cadastro #{id_pessoa} atualizado com sucesso.", "dados": pessoa.to_dict()}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": f"Erro ao editar cadastro: {e}"}
    finally:
        session.close()


def alterar_status_pessoa(id_pessoa: int, status: Optional[str]) -> Dict[str, Any]:
    if not _validar_status(status):
        return {"status": "error", "message": "Status deve ser 'ativo' ou 'inativo'."}
    session = SessionLocal()
    try:
        pessoa = session.get(Pessoa, id_pessoa)
        if not pessoa:
            return {"status": "error", "message": "Cadastro não encontrado."}
        pessoa.status = status
        session.commit()
        acao = "reativado" if status == "ativo" else "inativado"
        return {"status": "success", "message": f"Cadastro #{id_pessoa} {acao} com sucesso.", "dados": pessoa.to_dict()}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": f"Erro ao alterar status: {e}"}
    finally:
        session.close()


# =====================================================================
# CLASSIFICAÇÃO (Manter Tipo de Despesa / Tipo de Receita)
# =====================================================================

def listar_classificacoes(termo: Optional[str] = None, tipo: Optional[str] = None, status: Optional[str] = "ativo") -> List[Dict[str, Any]]:
    session = SessionLocal()
    try:
        query = session.query(Classificacao)
        if status and status != "todos":
            query = query.filter(Classificacao.status == status)
        if tipo and tipo != "todos":
            query = query.filter(Classificacao.tipo == normalizar_tipo_classificacao(tipo))
        filtro = filtro_multitermos(termo, [Classificacao.descricao])
        if filtro is not None:
            query = query.filter(filtro)
        return [c.to_dict() for c in query.order_by(Classificacao.descricao).all()]
    finally:
        session.close()


def _validar_classificacao(session, dados: Dict[str, Any], id_ignorar: Optional[int] = None) -> Optional[str]:
    descricao = (dados.get("descricao") or "").strip()
    if not descricao:
        return "A descrição é obrigatória."
    if (dados.get("tipo") or "").strip().upper() not in ("DESPESA", "RECEITA"):
        return "Tipo deve ser 'Despesa' ou 'Receita'."
    existente = buscar_classificacao(session, descricao)
    if existente and existente.id_classificacao != id_ignorar:
        situacao = " (INATIVO - reative o cadastro)" if existente.status == "inativo" else ""
        return f"Já existe a classificação '{existente.descricao}' (ID {existente.id_classificacao}){situacao}."
    return None


def criar_classificacao(dados: Dict[str, Any]) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        erro = _validar_classificacao(session, dados)
        if erro:
            return {"status": "error", "message": erro}
        cat = Classificacao(
            tipo=normalizar_tipo_classificacao(dados["tipo"]),
            descricao=dados["descricao"].strip().upper(),
            status="ativo"
        )
        session.add(cat)
        session.commit()
        session.refresh(cat)
        return {"status": "success", "message": f"Classificação #{cat.id_classificacao} criada com sucesso.", "dados": cat.to_dict()}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": f"Erro ao criar classificação: {e}"}
    finally:
        session.close()


def editar_classificacao(id_classificacao: int, dados: Dict[str, Any]) -> Dict[str, Any]:
    session = SessionLocal()
    try:
        cat = session.get(Classificacao, id_classificacao)
        if not cat:
            return {"status": "error", "message": "Classificação não encontrada."}
        erro = _validar_classificacao(session, dados, id_ignorar=id_classificacao)
        if erro:
            return {"status": "error", "message": erro}
        cat.tipo = normalizar_tipo_classificacao(dados["tipo"])
        cat.descricao = dados["descricao"].strip().upper()
        session.commit()
        session.refresh(cat)
        return {"status": "success", "message": f"Classificação #{id_classificacao} atualizada com sucesso.", "dados": cat.to_dict()}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": f"Erro ao editar classificação: {e}"}
    finally:
        session.close()


def alterar_status_classificacao(id_classificacao: int, status: Optional[str]) -> Dict[str, Any]:
    if not _validar_status(status):
        return {"status": "error", "message": "Status deve ser 'ativo' ou 'inativo'."}
    session = SessionLocal()
    try:
        cat = session.get(Classificacao, id_classificacao)
        if not cat:
            return {"status": "error", "message": "Classificação não encontrada."}
        cat.status = status
        session.commit()
        acao = "reativada" if status == "ativo" else "inativada"
        return {"status": "success", "message": f"Classificação #{id_classificacao} {acao} com sucesso.", "dados": cat.to_dict()}
    except Exception as e:
        session.rollback()
        return {"status": "error", "message": f"Erro ao alterar status: {e}"}
    finally:
        session.close()
