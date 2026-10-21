from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session, aliased
from database import SessionLocal
from models import Pessoa, MovimentoContas, Parcela, Classificacao, MovimentoHasClassificacao
from servico_persistencia import (
    salvar_nota_fiscal, parse_data, calcular_vencimento_parcela, identificacao_parcela,
    normalizar_documento, normalizar_tipo_classificacao, buscar_pessoa, buscar_classificacao,
    buscar_movimento_duplicado, mensagem_duplicidade, validar_documento, filtro_multitermos
)

CATEGORIA_PADRAO = "INSUMOS AGRÍCOLAS"


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

    @staticmethod
    def _status_banco(entidade_id: Optional[int], status: Optional[str]) -> str:
        """Texto exibido na tela: 'EXISTE – ID: 19', 'EXISTE – ID: 19 (INATIVO)' ou 'NÃO EXISTE'."""
        if entidade_id is None:
            return "NÃO EXISTE"
        sufixo = " (INATIVO)" if status == "inativo" else ""
        return f"EXISTE – ID: {entidade_id}{sufixo}"

    def verificar_pessoa_banco(
        self,
        razao_social: str,
        documento: Optional[str] = None,
        nome_fantasia: Optional[str] = None,
        tipo: str = "CLIENTE-FORNECEDOR",
        session: Optional[Session] = None,
        criar_se_nao_existir: bool = True
    ) -> Dict[str, Any]:
        """
        Consulta se a Pessoa (Fornecedor ou Faturado) já existe no Banco de Dados (CPF/CNPJ sem máscara).
        Ao gravar (criar_se_nao_existir=True): cria a pessoa se não existir e reativa se estiver inativa.
        """
        s = session or self._get_session()
        should_close = session is None and self.db_session is None

        try:
            doc_limpo = normalizar_documento(documento)
            razao_limpa = (razao_social or "Não Identificado").strip()

            pessoa = buscar_pessoa(s, doc_limpo, razao_limpa)
            ja_existia = pessoa is not None
            inativo = ja_existia and pessoa.status == "inativo"
            status_banco = self._status_banco(pessoa.id_pessoa if pessoa else None, pessoa.status if pessoa else None)
            reativado = False

            if criar_se_nao_existir:
                if not pessoa:
                    pessoa = Pessoa(
                        tipo=tipo,
                        razao_social=razao_limpa,
                        nome_fantasia=nome_fantasia,
                        documento=doc_limpo,
                        status="ativo"
                    )
                    s.add(pessoa)
                    s.flush()
                elif inativo:
                    # Cadastro não pode ser excluído, apenas inativado/reativado
                    pessoa.status = "ativo"
                    reativado = True

            return {
                "pessoa": pessoa,
                "ja_existia": ja_existia,
                "inativo": inativo,
                "reativado": reativado,
                "status_banco": status_banco,
                "razao_social": razao_limpa,
                "documento": documento or ""
            }
        finally:
            if should_close:
                s.close()

    def verificar_classificacao_banco(
        self,
        descricao_cat: str,
        tipo: str = "Despesa",
        session: Optional[Session] = None,
        criar_se_nao_existir: bool = True
    ) -> Dict[str, Any]:
        """
        Consulta se a classificação da Despesa/Receita já existe no Banco de Dados.
        """
        s = session or self._get_session()
        should_close = session is None and self.db_session is None

        try:
            nome_cat = (descricao_cat or CATEGORIA_PADRAO).strip().upper()
            cat = buscar_classificacao(s, nome_cat)
            ja_existia = cat is not None
            inativo = ja_existia and cat.status == "inativo"
            status_banco = self._status_banco(cat.id_classificacao if cat else None, cat.status if cat else None)
            reativado = False

            if criar_se_nao_existir:
                if not cat:
                    cat = Classificacao(tipo=normalizar_tipo_classificacao(tipo), descricao=nome_cat, status="ativo")
                    s.add(cat)
                    s.flush()
                elif inativo:
                    cat.status = "ativo"
                    reativado = True

            return {
                "classificacao": cat,
                "ja_existia": ja_existia,
                "inativo": inativo,
                "reativado": reativado,
                "status_banco": status_banco,
                "descricao": nome_cat
            }
        finally:
            if should_close:
                s.close()

    def _analisar_nota_fiscal(self, dados_json: Dict[str, Any], session: Session, gravar: bool) -> Dict[str, Any]:
        """
        Executa as consultas da 2ª Etapa (FORNECEDOR, FATURADO, DESPESA e duplicidade da NF).
        Com gravar=True também cria/reativa os cadastros necessários.
        """
        forn_data = dados_json.get("fornecedor") or {}
        res_forn = self.verificar_pessoa_banco(
            razao_social=forn_data.get("razaoSocial") or forn_data.get("nome") or "FORNECEDOR",
            documento=forn_data.get("cnpj"),
            nome_fantasia=forn_data.get("fantasia"),
            tipo="CLIENTE-FORNECEDOR",
            session=session,
            criar_se_nao_existir=gravar
        )

        fat_data = dados_json.get("faturado") or {}
        res_fat = self.verificar_pessoa_banco(
            razao_social=fat_data.get("nomeCompleto") or fat_data.get("nome") or "FATURADO",
            documento=fat_data.get("cpf"),
            tipo="FATURADO",
            session=session,
            criar_se_nao_existir=gravar
        )

        # Um registro de contas a pagar pode ter uma ou mais classificações de despesa
        classificacoes_lista = dados_json.get("classificacaoDespesa") or [{"categoria": CATEGORIA_PADRAO}]
        res_despesas = []
        vistos = set()
        for c in classificacoes_lista:
            res = self.verificar_classificacao_banco(
                descricao_cat=c.get("categoria"),
                tipo="Despesa",
                session=session,
                criar_se_nao_existir=gravar
            )
            if res["descricao"] in vistos:
                continue
            vistos.add(res["descricao"])
            res["justificativa"] = c.get("justificativa")
            res_despesas.append(res)

        duplicado = None
        if res_forn["pessoa"] is not None:
            duplicado = buscar_movimento_duplicado(
                session, dados_json.get("numeroNotaFiscal"), "Despesa", res_forn["pessoa"].id_pessoa
            )

        return {"fornecedor": res_forn, "faturado": res_fat, "despesas": res_despesas, "duplicado": duplicado}

    @staticmethod
    def _montar_resposta_consulta(analise: Dict[str, Any], dados_json: Dict[str, Any]) -> Dict[str, Any]:
        """Monta o quadro exibido na tela (formato do exemplo da página 2 do documento)."""
        forn, fat, duplicado = analise["fornecedor"], analise["faturado"], analise["duplicado"]
        despesas = [
            {
                "descricao": d["descricao"],
                "status_banco": d["status_banco"],
                "existe": d["ja_existia"],
                "inativo": d["inativo"]
            }
            for d in analise["despesas"]
        ]
        return {
            "fornecedor": {
                "nome": forn["razao_social"],
                "cnpj": forn["documento"],
                "status_banco": forn["status_banco"],
                "existe": forn["ja_existia"],
                "inativo": forn["inativo"]
            },
            "faturado": {
                "nome": fat["razao_social"],
                "cpf": fat["documento"],
                "status_banco": fat["status_banco"],
                "existe": fat["ja_existia"],
                "inativo": fat["inativo"]
            },
            # 'despesa' mantém compatibilidade com a primeira classificação; 'despesas' traz todas
            "despesa": despesas[0] if despesas else None,
            "despesas": despesas,
            "nota_fiscal": {
                "numero": dados_json.get("numeroNotaFiscal"),
                "duplicada": duplicado is not None,
                "id_movimento_existente": duplicado.id_movimento_contas if duplicado else None
            }
        }

    def consultar_dados_nota_fiscal(self, dados_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Consulta no banco se FORNECEDOR, FATURADO e DESPESA existem ou não,
        SEM gravar nada no banco (apenas verificação prévia para confirmação do usuário).
        """
        session = self._get_session()
        should_close = self.db_session is None
        try:
            analise = self._analisar_nota_fiscal(dados_json, session, gravar=False)
            return {
                "status": "success",
                "resposta_consulta": self._montar_resposta_consulta(analise, dados_json)
            }
        finally:
            if should_close:
                session.close()

    def salvar_nota_fiscal(self, dados_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executa a ATIVIDADE 2ª Etapa conforme o documento oficial da UniRV:
        1. FORNECEDOR: Consulta no Banco e informa se existe ou não.
        2. FATURADO: Consulta no Banco e informa se existe ou não.
        3. DESPESA: Consulta no Banco e informa se a classificação existe ou não.
        4. Cria novo fornecedor/faturado/despesa (se for o caso) e salva o movimento e parcelas.
        Tudo em uma única transação: se algo falhar, nada é gravado.
        """
        session = self._get_session()
        should_close = self.db_session is None
        try:
            analise = self._analisar_nota_fiscal(dados_json, session, gravar=True)
            resposta_consulta = self._montar_resposta_consulta(analise, dados_json)

            if analise["duplicado"] is not None:
                session.rollback()
                return {
                    "status": "error",
                    "message": f"{mensagem_duplicidade(analise['duplicado'])} Nenhum registro foi gravado.",
                    "resposta_consulta": resposta_consulta
                }

            movimento = salvar_nota_fiscal(
                dados_json,
                emitente=analise["fornecedor"]["pessoa"],
                destinatario=analise["faturado"]["pessoa"],
                classificacoes=[(d["classificacao"], d.get("justificativa")) for d in analise["despesas"]],
                db=session
            )
            session.commit()
            session.refresh(movimento)

            reativados = [
                r["razao_social"] for r in (analise["fornecedor"], analise["faturado"]) if r["reativado"]
            ] + [d["descricao"] for d in analise["despesas"] if d["reativado"]]

            return {
                "status": "success",
                "message": "Registro de Movimento e suas Parcelas lançados com SUCESSO!",
                "id_movimento_contas": movimento.id_movimento_contas,
                "reativados": reativados,
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

    @staticmethod
    def _validar_documentos_manuais(dados: Dict[str, Any]) -> Optional[str]:
        """Valida CPF/CNPJ digitados no formulário de lançamento manual."""
        return (
            validar_documento(dados.get("emitente_documento"), "Documento do emitente")
            or validar_documento(dados.get("destinatario_documento"), "Documento do faturado")
        )

    def _resolver_classificacoes_manuais(self, dados: Dict[str, Any], tipo_op: str, session: Session) -> List[Classificacao]:
        """Aceita 'categorias' (lista de descrições) ou 'categoria' (texto único, compatibilidade)."""
        categorias = dados.get("categorias")
        if not categorias:
            categorias = [dados.get("categoria")] if dados.get("categoria") else []
        resultado = []
        for cat in categorias:
            res = self.verificar_classificacao_banco(cat, tipo=tipo_op, session=session)
            if res["classificacao"] not in resultado:
                resultado.append(res["classificacao"])
        return resultado

    def criar_movimento_manual(self, dados: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cria movimento manual de Contas a Pagar (Despesa) ou a Receber (Receita).
        Regra g: No CREATE campo STATUS oculto == ATIVO.
        """
        session = self._get_session()
        should_close = self.db_session is None
        try:
            tipo_op = normalizar_tipo_classificacao(dados.get("tipo"))

            valor_total = float(dados.get("valor_total") or 0.0)
            if valor_total <= 0:
                return {"status": "error", "message": "O valor total deve ser maior que zero."}

            erro_doc = self._validar_documentos_manuais(dados)
            if erro_doc:
                return {"status": "error", "message": erro_doc}

            classificacoes = self._resolver_classificacoes_manuais(dados, tipo_op, session)
            if not classificacoes:
                session.rollback()
                return {"status": "error", "message": f"Informe ao menos um Tipo de {tipo_op}."}

            res_emit = self.verificar_pessoa_banco(
                dados.get("emitente_nome") or "Emitente Geral",
                dados.get("emitente_documento"),
                tipo="CLIENTE-FORNECEDOR" if tipo_op == "Despesa" else "CLIENTE",
                session=session
            )

            res_dest = self.verificar_pessoa_banco(
                dados.get("destinatario_nome") or "Destinatário Geral",
                dados.get("destinatario_documento"),
                tipo="FATURADO",
                session=session
            )

            duplicado = buscar_movimento_duplicado(
                session, dados.get("numero_nota_fiscal"), tipo_op, res_emit["pessoa"].id_pessoa
            )
            if duplicado:
                session.rollback()
                return {"status": "error", "message": mensagem_duplicidade(duplicado)}

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

            # Gera parcelas com vencimento mensal em dia útil; a última absorve a diferença de centavos
            qtd_parcelas = max(int(dados.get("quantidade_parcelas") or 1), 1)
            val_parcela = round(valor_total / qtd_parcelas, 2)
            data_base_venc = parse_data(dados.get("data_vencimento")) or parse_data(dados.get("data_emissao")) or datetime.now().date()

            for i in range(1, qtd_parcelas + 1):
                valor_i = val_parcela if i < qtd_parcelas else round(valor_total - val_parcela * (qtd_parcelas - 1), 2)
                session.add(Parcela(
                    id_movimento_contas=movimento.id_movimento_contas,
                    identificacao=identificacao_parcela(i, qtd_parcelas),
                    data_vencimento=calcular_vencimento_parcela(data_base_venc, i),
                    valor_parcela=valor_i,
                    valor_pago=0.0,
                    valor_saldo=valor_i,
                    status="aberta"
                ))

            for cat in classificacoes:
                session.add(MovimentoHasClassificacao(
                    id_movimento_contas=movimento.id_movimento_contas,
                    id_classificacao=cat.id_classificacao,
                    justificativa=dados.get("justificativa", "Lançamento manual")
                ))

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

            erro_doc = self._validar_documentos_manuais(dados)
            if erro_doc:
                return {"status": "error", "message": erro_doc}

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

            if dados.get("emitente_nome"):
                res_emit = self.verificar_pessoa_banco(
                    dados["emitente_nome"], dados.get("emitente_documento"),
                    tipo="CLIENTE-FORNECEDOR" if movimento.tipo == "Despesa" else "CLIENTE",
                    session=session
                )
                movimento.id_pessoa_emitente = res_emit["pessoa"].id_pessoa
            if dados.get("destinatario_nome"):
                res_dest = self.verificar_pessoa_banco(
                    dados["destinatario_nome"], dados.get("destinatario_documento"),
                    tipo="FATURADO", session=session
                )
                movimento.id_pessoa_destinatario = res_dest["pessoa"].id_pessoa

            duplicado = buscar_movimento_duplicado(
                session, movimento.numero_nota_fiscal, movimento.tipo, movimento.id_pessoa_emitente,
                ignorar_id=movimento.id_movimento_contas
            )
            if duplicado:
                session.rollback()
                return {"status": "error", "message": mensagem_duplicidade(duplicado)}

            if "categorias" in dados or "categoria" in dados:
                classificacoes = self._resolver_classificacoes_manuais(dados, movimento.tipo, session)
                if not classificacoes:
                    session.rollback()
                    return {"status": "error", "message": f"Informe ao menos um Tipo de {movimento.tipo}."}
                ids_novos = {c.id_classificacao for c in classificacoes}
                for assoc in list(movimento.classificacoes_associadas):
                    if assoc.id_classificacao not in ids_novos:
                        movimento.classificacoes_associadas.remove(assoc)
                ids_atuais = {a.id_classificacao for a in movimento.classificacoes_associadas}
                for cat in classificacoes:
                    if cat.id_classificacao not in ids_atuais:
                        movimento.classificacoes_associadas.append(MovimentoHasClassificacao(
                            id_classificacao=cat.id_classificacao, justificativa="Lançamento manual"
                        ))

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
        Também permite REATIVAR (status == ATIVO) um registro inativo.
        """
        if novo_status not in ("ativo", "inativo"):
            return {"status": "error", "message": "Status deve ser 'ativo' ou 'inativo'."}

        session = self._get_session()
        should_close = self.db_session is None
        try:
            movimento = session.query(MovimentoContas).filter_by(id_movimento_contas=id_movimento_contas).first()
            if not movimento:
                return {"status": "error", "message": "Registro não encontrado."}

            if novo_status == "ativo":
                duplicado = buscar_movimento_duplicado(
                    session, movimento.numero_nota_fiscal, movimento.tipo, movimento.id_pessoa_emitente,
                    ignorar_id=movimento.id_movimento_contas
                )
                if duplicado:
                    return {"status": "error", "message": f"Não é possível reativar. {mensagem_duplicidade(duplicado)}"}

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

    def obter_movimento(self, id_movimento_contas: int) -> Optional[Dict[str, Any]]:
        """
        Recupera os detalhes completos de um movimento específico pelo ID,
        incluindo suas parcelas, emitente, destinatário e classificações.
        """
        session = self._get_session()
        should_close = self.db_session is None
        try:
            movimento = session.query(MovimentoContas).filter_by(id_movimento_contas=id_movimento_contas).first()
            return movimento.to_dict() if movimento else None
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
        e. Busca por mais de um elemento (cada palavra deve casar com algum campo)
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

            emit = aliased(Pessoa)
            dest = aliased(Pessoa)
            filtro = filtro_multitermos(termo, [
                MovimentoContas.numero_nota_fiscal,
                MovimentoContas.descricao_produtos,
                emit.razao_social, emit.nome_fantasia, emit.documento,
                dest.razao_social, dest.nome_fantasia, dest.documento,
            ])
            if filtro is not None:
                query = (
                    query.join(emit, MovimentoContas.id_pessoa_emitente == emit.id_pessoa)
                    .join(dest, MovimentoContas.id_pessoa_destinatario == dest.id_pessoa)
                    .filter(filtro)
                )

            movimentos = query.order_by(MovimentoContas.id_movimento_contas.desc()).all()
            return [m.to_dict() for m in movimentos]
        finally:
            if should_close:
                session.close()

    def obter_resumo_financeiro(self) -> Dict[str, Any]:
        """Retorna totais estatísticos (apenas movimentos ativos)."""
        session = self._get_session()
        should_close = self.db_session is None
        try:
            movs = session.query(MovimentoContas).filter_by(status="ativo").all()
            total_despesas = sum(float(m.valor_total or 0) for m in movs if m.tipo == "Despesa")
            total_receitas = sum(float(m.valor_total or 0) for m in movs if m.tipo == "Receita")
            parcelas_abertas = (
                session.query(Parcela)
                .join(MovimentoContas, Parcela.id_movimento_contas == MovimentoContas.id_movimento_contas)
                .filter(Parcela.status == "aberta", MovimentoContas.status == "ativo")
                .all()
            )
            saldo_pendente = sum(float(p.valor_saldo or 0) for p in parcelas_abertas)

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
                "message": f"Pagamento de R$ {val_a_pagar:.2f} registrado com sucesso para a parcela {parcela.identificacao}!",
                "parcela": parcela.to_dict()
            }
        except Exception as e:
            session.rollback()
            return {"status": "error", "message": f"Erro ao registrar pagamento: {str(e)}"}
        finally:
            if should_close:
                session.close()
