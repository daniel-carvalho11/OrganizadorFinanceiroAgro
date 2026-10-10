import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy import or_, cast, String
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Pessoa, MovimentoContas, Parcela, Classificacao, MovimentoHasClassificacao
from servico_persistencia import salvar_nota_fiscal, parse_data, calcular_vencimento_parcela, ajustar_dia_util

class Agent2:
    """
    Agent 2 - Especialista em Persistência, Gestão Financeira e Validação Relacional.
    
    Funções Principais (Conforme especificações da UniRV - N2 2ª Etapa):
    1. Consultar se FORNECEDOR (CNPJ), FATURADO (CPF/CNPJ) e CLASSIFICAÇÃO DA DESPESA existem no banco.
    2. Exibir a resposta dessa consulta na tela (ex: FORNECEDOR: IGUAÇU MAQUINAS LTDA - NÃO EXISTE / EXISTE - ID: 19).
    3. Criar Novo Fornecedor, Novo Faturado e Nova Despesa (se for o caso).
    4. Criar o Novo Registro do MovimentoContas e suas Parcelas (com identificação única).
    5. Garantir a Regra da Exclusão Lógica (Soft Delete: altera status para 'inativo' sem apagar do banco).
    6. Suportar busca por mais de um elemento e botão TODOS (que carrega status == ATIVO).
    """

    def __init__(self, db_session: Optional[Session] = None):
        self.db_session = db_session

    def _get_session(self) -> Session:
        return self.db_session or SessionLocal()

    def verificar_pessoa_banco(
        self,
        razao_social: str,
        documento: Optional[str] = None,
        nome_fantasia: Optional[str] = None,
        tipo: str = "CLIENTE-FORNECEDOR",
        session: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Consulta se a Pessoa (Fornecedor ou Faturado) já existe no Banco de Dados.
        Retorna os dados da consulta (EXISTE - ID ou NÃO EXISTE) e a entidade Pessoa.
        """
        s = session or self._get_session()
        should_close = session is None and self.db_session is None

        try:
            doc_limpo = (documento or "").strip()
            razao_limpa = (razao_social or "Não Identificado").strip()

            pessoa = None
            if doc_limpo:
                pessoa = s.query(Pessoa).filter_by(documento=doc_limpo).first()
            if not pessoa and razao_limpa:
                pessoa = s.query(Pessoa).filter_by(razao_social=razao_limpa).first()

            if pessoa:
                status_banco = f"EXISTE – ID: {pessoa.id_pessoa}"
                ja_existia = True
            else:
                status_banco = "NÃO EXISTE"
                ja_existia = False
                tipo_pessoa = tipo
                if doc_limpo and len(doc_limpo) <= 14:
                    tipo_pessoa = "FATURADO"
                
                pessoa = Pessoa(
                    tipo=tipo_pessoa,
                    razao_social=razao_limpa,
                    nome_fantasia=nome_fantasia,
                    documento=doc_limpo,
                    status="ativo"
                )
                s.add(pessoa)
                s.flush()

            return {
                "pessoa": pessoa,
                "ja_existia": ja_existia,
                "status_banco": status_banco,
                "razao_social": razao_limpa,
                "documento": doc_limpo
            }
        finally:
            if should_close:
                s.close()

    def verificar_classificacao_banco(
        self,
        descricao_cat: str,
        tipo: str = "DESPESA",
        session: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Consulta se a classificação da Despesa/Receita já existe no Banco de Dados.
        """
        s = session or self._get_session()
        should_close = session is None and self.db_session is None

        try:
            nome_cat = (descricao_cat or "OUTRAS").strip()
            cat = s.query(Classificacao).filter_by(descricao=nome_cat).first()

            if cat:
                status_banco = f"EXISTE – ID: {cat.id_classificacao}"
                ja_existia = True
            else:
                status_banco = "NÃO EXISTE"
                ja_existia = False
                cat = Classificacao(tipo=tipo, descricao=nome_cat, status="ativo")
                s.add(cat)
                s.flush()

            return {
                "classificacao": cat,
                "ja_existia": ja_existia,
                "status_banco": status_banco,
                "descricao": nome_cat
            }
        finally:
            if should_close:
                s.close()

    def salvar_nota_fiscal(self, dados_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executa a ATIVIDADE 2ª Etapa conforme o documento oficial da UniRV:
        1. FORNECEDOR: Consulta no Banco e informa se existe ou não.
        2. FATURADO: Consulta no Banco e informa se existe ou não.
        3. DESPESA: Consulta no Banco e informa se a classificação existe ou não.
        4. Cria novo fornecedor/faturado/despesa (se for o caso) e salva o movimento e parcelas.
        """
        session = self._get_session()
        should_close = self.db_session is None
        try:
            # 1. Consulta e Cadastro de FORNECEDOR
            forn_data = dados_json.get("fornecedor", {})
            res_forn = self.verificar_pessoa_banco(
                razao_social=forn_data.get("razaoSocial") or forn_data.get("nome") or "FORNECEDOR",
                documento=forn_data.get("cnpj"),
                nome_fantasia=forn_data.get("fantasia"),
                tipo="CLIENTE-FORNECEDOR",
                session=session
            )

            # 2. Consulta e Cadastro de FATURADO
            fat_data = dados_json.get("faturado", {})
            res_fat = self.verificar_pessoa_banco(
                razao_social=fat_data.get("nomeCompleto") or fat_data.get("nome") or "FATURADO",
                documento=fat_data.get("cpf"),
                tipo="FATURADO",
                session=session
            )

            # 3. Consulta e Cadastro de DESPESA (Classificação)
            classificacoes_lista = dados_json.get("classificacaoDespesa", [])
            primeira_cat = classificacoes_lista[0].get("categoria") if classificacoes_lista else "INSUMOS AGRÍCOLAS"
            res_despesa = self.verificar_classificacao_banco(
                descricao_cat=primeira_cat,
                tipo="DESPESA",
                session=session
            )

            # 4. Executa a gravação do movimento e parcelas
            movimento = salvar_nota_fiscal(dados_json, session=session)

            # Monta o relatório de consulta idêntico ao exigido pela UniRV (Página 2)
            resposta_consulta = {
                "fornecedor": {
                    "nome": res_forn["razao_social"],
                    "cnpj": res_forn["documento"],
                    "status_banco": res_forn["status_banco"]
                },
                "faturado": {
                    "nome": res_fat["razao_social"],
                    "cpf": res_fat["documento"],
                    "status_banco": res_fat["status_banco"]
                },
                "despesa": {
                    "descricao": res_despesa["descricao"],
                    "status_banco": res_despesa["status_banco"]
                }
            }

            return {
                "status": "success",
                "message": "Registro de Movimento e suas Parcelas lançados com SUCESSO!",
                "id_movimento_contas": movimento.id_movimento_contas,
                "resposta_consulta": resposta_consulta,
                "dados": movimento.to_dict()
            }
        except Exception as e:
            session.rollback()
            return {
                "status": "error",
                "message": f"Erro ao persistir nota fiscal: {str(e)}"
            }
        finally:
            if should_close:
                session.close()

    def criar_movimento_manual(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria movimento manual (Regra g: No CREATE campo STATUS oculto == ATIVO).
        """
        session = self._get_session()
        should_close = self.db_session is None
        try:
            res_emit = self.verificar_pessoa_banco(
                dados.get("emitente_nome", "Emitente Geral"),
                dados.get("emitente_documento", ""),
                tipo="CLIENTE-FORNECEDOR",
                session=session
            )

            res_dest = self.verificar_pessoa_banco(
                dados.get("destinatario_nome", "Destinatário Geral"),
                dados.get("destinatario_documento", ""),
                tipo="FATURADO",
                session=session
            )

            valor_total = float(dados.get("valor_total") or 0.0)
            tipo_op = dados.get("tipo", "Despesa")

            movimento = MovimentoContas(
                tipo=tipo_op,
                numero_nota_fiscal=dados.get("numero_nota_fiscal"),
                data_emissao=parse_data(dados.get("data_emissao")),
                descricao_produtos=dados.get("descricao_produtos", ""),
                valor_total=valor_total,
                status="ativo",  # Regra g: No CREATE campo STATUS oculto == ATIVO
                id_pessoa_emitente=res_emit["pessoa"].id_pessoa,
                id_pessoa_destinatario=res_dest["pessoa"].id_pessoa
            )
            session.add(movimento)
            session.flush()

            # Gera parcelas com identificação única e vencimento mensal em dia útil
            qtd_parcelas = int(dados.get("quantidade_parcelas") or 1)
            val_parcela = round(valor_total / max(qtd_parcelas, 1), 2)
            data_base_venc = parse_data(dados.get("data_vencimento")) or parse_data(dados.get("data_emissao")) or datetime.now().date()

            for i in range(1, qtd_parcelas + 1):
                dt_venc = calcular_vencimento_parcela(data_base_venc, i)
                p = Parcela(
                    id_movimento_contas=movimento.id_movimento_contas,
                    identificacao=f"PARCELA_{movimento.id_movimento_contas}_{i}_{qtd_parcelas}",
                    data_vencimento=dt_venc,
                    valor_parcela=val_parcela,
                    valor_pago=0.0,
                    valor_saldo=val_parcela,
                    status="aberta"
                )
                session.add(p)

            cat_res = self.verificar_classificacao_banco(
                dados.get("categoria", "OUTRAS"),
                tipo="DESPESA" if tipo_op == "Despesa" else "RECEITA",
                session=session
            )

            assoc = MovimentoHasClassificacao(
                id_movimento_contas=movimento.id_movimento_contas,
                id_classificacao=cat_res["classificacao"].id_classificacao,
                justificativa=dados.get("justificativa", "Lançamento manual")
            )
            session.add(assoc)

            session.commit()
            session.refresh(movimento)
            return {
                "status": "success",
                "message": "Registro de Movimento e Parcelas lançados com SUCESSO!",
                "dados": movimento.to_dict()
            }
        except Exception as e:
            session.rollback()
            return {"status": "error", "message": f"Erro ao criar movimento: {str(e)}"}
        finally:
            if should_close:
                session.close()

    def editar_movimento(self, id_movimento_contas: int, dados: Dict[str, Any]) -> Dict[str, Any]:
        """
        Edita movimento (Regra h: No UPDATE campo STATUS oculto).
        """
        session = self._get_session()
        should_close = self.db_session is None
        try:
            movimento = session.query(MovimentoContas).filter_by(id_movimento_contas=id_movimento_contas).first()
            if not movimento:
                return {"status": "error", "message": "Registro não encontrado."}

            if "numero_nota_fiscal" in dados:
                movimento.numero_nota_fiscal = dados["numero_nota_fiscal"]
            if "data_emissao" in dados:
                movimento.data_emissao = parse_data(dados["data_emissao"])
            if "valor_total" in dados:
                movimento.valor_total = float(dados["valor_total"] or 0.0)
            if "descricao_produtos" in dados:
                movimento.descricao_produtos = dados["descricao_produtos"]
            if "tipo" in dados and dados["tipo"] in ("Despesa", "Receita"):
                movimento.tipo = dados["tipo"]

            # Regra h: No UPDATE campo STATUS oculto e inalterado

            session.commit()
            session.refresh(movimento)
            return {
                "status": "success",
                "message": "Lançamento atualizado com sucesso.",
                "dados": movimento.to_dict()
            }
        except Exception as e:
            session.rollback()
            return {"status": "error", "message": f"Erro ao editar lançamento: {str(e)}"}
        finally:
            if should_close:
                session.close()

    def alterar_status_movimento(self, id_movimento_contas: int, novo_status: str) -> Dict[str, Any]:
        """
        Regra i: No DELETE altera campo STATUS == INATIVO (Exclusão Lógica).
        """
        if novo_status not in ("ativo", "inativo"):
            return {"status": "error", "message": "Status deve ser 'ativo' ou 'inativo'."}

        session = self._get_session()
        should_close = self.db_session is None
        try:
            movimento = session.query(MovimentoContas).filter_by(id_movimento_contas=id_movimento_contas).first()
            if not movimento:
                return {"status": "error", "message": "Registro não encontrado."}

            movimento.status = novo_status
            session.commit()
            return {
                "status": "success",
                "message": f"Registro #{id_movimento_contas} atualizado para status '{novo_status}'.",
                "id_movimento_contas": id_movimento_contas,
                "status_atual": novo_status
            }
        except Exception as e:
            session.rollback()
            return {"status": "error", "message": f"Erro ao alterar status: {str(e)}"}
        finally:
            if should_close:
                session.close()

    def listar_movimentos(
        self,
        termo: Optional[str] = None,
        status: Optional[str] = "ativo",
        tipo: Optional[str] = None,
        data_inicio: Optional[str] = None,
        data_fim: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Busca dados conforme recomendações UniRV:
        b. Carregar dados através da Busca ou TODOS
        c. TODOS carrega status == ATIVO
        e. Busca por mais de um elemento
        """
        session = self._get_session()
        should_close = self.db_session is None
        try:
            query = session.query(MovimentoContas)

            if status and status != "todos":
                query = query.filter(MovimentoContas.status == status)

            if tipo and tipo != "todos":
                query = query.filter(MovimentoContas.tipo == tipo)

            d_ini = parse_data(data_inicio)
            if d_ini:
                query = query.filter(MovimentoContas.data_emissao >= d_ini)

            d_fim = parse_data(data_fim)
            if d_fim:
                query = query.filter(MovimentoContas.data_emissao <= d_fim)

            if termo and termo.strip():
                t = f"%{termo.strip()}%"
                query = query.join(Pessoa, or_(
                    MovimentoContas.id_pessoa_emitente == Pessoa.id_pessoa,
                    MovimentoContas.id_pessoa_destinatario == Pessoa.id_pessoa
                )).filter(
                    or_(
                        MovimentoContas.numero_nota_fiscal.ilike(t),
                        MovimentoContas.descricao_produtos.ilike(t),
                        Pessoa.razao_social.ilike(t),
                        Pessoa.nome_fantasia.ilike(t),
                        Pessoa.documento.ilike(t)
                    )
                ).distinct()

            movimentos = query.order_by(MovimentoContas.id_movimento_contas.desc()).all()
            return [m.to_dict() for m in movimentos]
        finally:
            if should_close:
                session.close()

    def obter_resumo_financeiro(self) -> Dict[str, Any]:
        """Retorna totais estatísticos."""
        session = self._get_session()
        should_close = self.db_session is None
        try:
            movs = session.query(MovimentoContas).filter_by(status="ativo").all()
            total_despesas = sum(float(m.valor_total) for m in movs if m.tipo == "Despesa")
            total_receitas = sum(float(m.valor_total) for m in movs if m.tipo == "Receita")
            parcelas_abertas = session.query(Parcela).filter_by(status="aberta").all()
            saldo_pendente = sum(float(p.valor_saldo) for p in parcelas_abertas)

            return {
                "total_registros_ativos": len(movs),
                "total_despesas": total_despesas,
                "total_receitas": total_receitas,
                "saldo_liquido": total_receitas - total_despesas,
                "total_parcelas_abertas": len(parcelas_abertas),
                "total_saldo_pendente": saldo_pendente
            }
        finally:
            if should_close:
                session.close()

    def registrar_pagamento_parcela(self, id_parcela: int, valor_pago: Optional[float] = None) -> Dict[str, Any]:
        """
        Registra a quitação (total ou parcial) de uma parcela na tabela 'parcelas'.
        Atualiza os campos valor_pago, valor_saldo e altera o status para 'quitada' quando quitada.
        """
        session = self._get_session()
        should_close = self.db_session is None
        try:
            parcela = session.query(Parcela).filter_by(id_parcela=id_parcela).first()
            if not parcela:
                return {"status": "error", "message": "Parcela não encontrada no banco."}

            val_total = float(parcela.valor_parcela or 0.0)
            val_ja_pago = float(parcela.valor_pago or 0.0)
            val_saldo_atual = float(parcela.valor_saldo if parcela.valor_saldo is not None else (val_total - val_ja_pago))

            val_a_pagar = float(valor_pago) if (valor_pago is not None and float(valor_pago) > 0) else val_saldo_atual
            if val_a_pagar <= 0:
                return {"status": "error", "message": "O valor do pagamento deve ser maior que zero."}

            novo_total_pago = min(val_total, val_ja_pago + val_a_pagar)
            novo_saldo = max(0.0, val_total - novo_total_pago)

            parcela.valor_pago = novo_total_pago
            parcela.valor_saldo = novo_saldo
            if novo_saldo == 0:
                parcela.status = "quitada"

            session.commit()
            session.refresh(parcela)
            return {
                "status": "success",
                "message": f"Pagamento de R$ {val_a_pagar:.2f} registrado com sucesso para a {parcela.identificacao}!",
                "parcela": parcela.to_dict()
            }
        except Exception as e:
            session.rollback()
            return {"status": "error", "message": f"Erro ao registrar pagamento: {str(e)}"}
        finally:
            if should_close:
                session.close()

