"""
Agent3 - Busca Inteligente com RAG (Retrieval-Augmented Generation).

O usuário faz uma pergunta em linguagem natural sobre os lançamentos do banco e o
agente executa as três etapas do RAG:

    1. Retrieval    -> recupera os lançamentos relevantes no banco de dados
    2. Augmentation -> injeta esses dados no prompt (contexto + pergunta)
    3. Generation   -> o Gemini gera a resposta fundamentada apenas nesses dados

Dois modos de recuperação:
    - "simples":    lançamentos ativos mais recentes (limite de 20 registros), como no protótipo da aula.
    - "embeddings": busca semântica. Cada lançamento vira um vetor (embedding) guardado na
                    tabela rag_embeddings; a pergunta também vira um vetor e os lançamentos
                    mais próximos (similaridade de cosseno) formam o contexto.
"""

import hashlib
import json
import math
import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from google import genai
from google.genai import types
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from database import SessionLocal
from models import MovimentoContas, MovimentoHasClassificacao, Parcela, RagEmbedding

load_dotenv()

MODOS = ("simples", "embeddings")
MODELOS_GERACAO = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]
MODELO_EMBEDDING = "gemini-embedding-001"
DIMENSAO_EMBEDDING = 768
LIMITE_REGISTROS = 20   # RAG simples: limita o contexto para manter o desempenho
TOP_K = 10              # RAG com embeddings: quantidade de lançamentos mais próximos
LOTE_EMBEDDING = 50     # textos enviados por chamada à API de embeddings

SYSTEM_INSTRUCTION = """Você é um assistente de gestão financeira de uma propriedade rural.
Responda em português do Brasil, usando SOMENTE os dados fornecidos no contexto.
Regras:
- Não invente valores, datas, pessoas ou lançamentos que não estejam nos dados.
- Se os dados não forem suficientes para responder, diga isso claramente e explique o que falta.
- Cite os lançamentos usados pelo número (ex.: Lançamento #12, NF 000.084.682).
- Valores em reais (R$ 1.234,56) e datas no formato dd/mm/aaaa.
- Use os subtotais e totais já calculados no contexto em vez de refazer as contas.
- Considere só os lançamentos que respondem à pergunta; se somar apenas parte deles, mostre o cálculo resumido.

Formato da resposta:
1. Comece com uma frase curta respondendo diretamente à pergunta.
2. Se houver compras relevantes, escreva a linha **Compras (Contas a Pagar)** e, abaixo, uma linha "- " por lançamento
   (fornecedor, o que foi comprado, data, valor e situação das parcelas), terminando com "Subtotal de compras: R$ ...".
3. Se houver vendas relevantes, escreva a linha **Vendas (Contas a Receber)** no mesmo formato
   (cliente, o que foi vendido, data, valor e situação), terminando com "Subtotal de vendas: R$ ...".
4. Termine com a linha **Total**: valor total de compras, de vendas e o saldo (vendas - compras), mostrando só o que se aplica.
- Omita a seção que não tiver lançamentos relevantes para a pergunta.
- Não use tabelas nem títulos com "#"."""


def _moeda(valor) -> str:
    texto = f"{float(valor or 0):,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _data(valor) -> str:
    return valor.strftime("%d/%m/%Y") if valor else "não informada"


def _nome_pessoa(pessoa) -> str:
    if not pessoa:
        return "não informado"
    if pessoa.nome_fantasia and pessoa.nome_fantasia != pessoa.razao_social:
        return f"{pessoa.razao_social} ({pessoa.nome_fantasia})"
    return pessoa.razao_social


def _cosseno(a: List[float], b: List[float]) -> float:
    produto = sum(x * y for x, y in zip(a, b))
    norma = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return produto / norma if norma else 0.0


class Agent3:
    """Motor do RAG: recupera dados do banco, aumenta o prompt e gera a resposta com o Gemini."""

    def __init__(self, api_key: Optional[str] = None, db_session: Optional[Session] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        self.db_session = db_session

    def _get_session(self) -> Session:
        return self.db_session or SessionLocal()

    # ------------------------------------------------------------------
    # Fluxo principal
    # ------------------------------------------------------------------
    def run_query(self, query: str, modo: str = "simples") -> Dict[str, Any]:
        """Executa o ciclo completo do RAG e devolve a resposta com as fontes consultadas."""
        query = (query or "").strip()
        if not query:
            raise ValueError("Digite uma pergunta sobre os lançamentos.")
        if modo not in MODOS:
            raise ValueError(f"Modo de busca inválido: {modo}. Use 'simples' ou 'embeddings'.")
        if not self.client:
            raise ValueError("Chave GEMINI_API_KEY não configurada no ambiente ou na tela.")

        session = self._get_session()
        try:
            info_indice = None
            # 1. Retrieval
            if modo == "embeddings":
                registros, info_indice = self._retrieve_data_embeddings(query, session)
            else:
                registros = self._retrieve_data(query, session)

            if not registros:
                return self._resultado(query, modo, "Não há lançamentos ativos no banco de dados para responder a essa pergunta.",
                                       None, [], info_indice)

            # 2. Augmentation
            contexto = self._montar_contexto(registros, modo, session)
            # 3. Generation
            resposta, modelo = self._generate_response(query, contexto)
            return self._resultado(query, modo, resposta, modelo, registros, info_indice)
        finally:
            if not self.db_session:
                session.close()

    @staticmethod
    def _resultado(query, modo, resposta, modelo, registros, info_indice) -> Dict[str, Any]:
        fontes = []
        for r in registros:
            m = r["movimento"]
            fonte = {
                "id_movimento_contas": m.id_movimento_contas,
                "tipo": m.tipo,
                "numero_nota_fiscal": m.numero_nota_fiscal,
                "data_emissao": str(m.data_emissao) if m.data_emissao else None,
                "valor_total": float(m.valor_total or 0),
                "emitente": _nome_pessoa(m.emitente),
            }
            if "similaridade" in r:
                fonte["similaridade"] = round(r["similaridade"], 4)
            fontes.append(fonte)
        resultado = {"pergunta": query, "modo": modo, "resposta": resposta, "modelo": modelo, "fontes": fontes}
        if info_indice is not None:
            resultado["indice"] = info_indice
        return resultado

    # ------------------------------------------------------------------
    # 1. Retrieval
    # ------------------------------------------------------------------
    @staticmethod
    def _consulta_ativos(session: Session):
        return (
            session.query(MovimentoContas)
            .options(
                selectinload(MovimentoContas.emitente),
                selectinload(MovimentoContas.destinatario),
                selectinload(MovimentoContas.parcelas),
                selectinload(MovimentoContas.classificacoes_associadas).selectinload(MovimentoHasClassificacao.classificacao),
            )
            .filter(MovimentoContas.status == "ativo")
        )

    def _retrieve_data(self, query: str, session: Session) -> List[Dict[str, Any]]:
        """RAG simples: lançamentos ativos mais recentes, limitados a 20 registros."""
        movimentos = (
            self._consulta_ativos(session)
            .order_by(MovimentoContas.data_emissao.desc(), MovimentoContas.id_movimento_contas.desc())
            .limit(LIMITE_REGISTROS)
            .all()
        )
        return [{"movimento": m, "texto": self._texto_movimento(m)} for m in movimentos]

    def _retrieve_data_embeddings(self, query: str, session: Session) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        """RAG com embeddings: compara o vetor da pergunta com o índice vetorial dos lançamentos."""
        indice, info = self._sincronizar_indice(session)
        if not indice:
            return [], info

        vetor_pergunta = self._embed([query], "RETRIEVAL_QUERY")[0]
        ranking = sorted(
            ({"movimento": m, "texto": texto, "similaridade": _cosseno(vetor_pergunta, vetor)}
             for m, texto, vetor in indice),
            key=lambda r: r["similaridade"],
            reverse=True,
        )
        return ranking[:TOP_K], info

    def _sincronizar_indice(self, session: Session) -> Tuple[List[Tuple[MovimentoContas, str, List[float]]], Dict[str, int]]:
        """Mantém a tabela rag_embeddings igual aos lançamentos ativos.

        Gera embeddings só para lançamentos novos ou alterados (hash do texto diferente)
        e remove do índice os lançamentos excluídos (inativos).
        """
        movimentos = self._consulta_ativos(session).all()
        existentes = {e.id_movimento_contas: e for e in session.query(RagEmbedding).all()}

        textos = {m.id_movimento_contas: self._texto_movimento(m) for m in movimentos}
        hashes = {mid: hashlib.sha256(t.encode("utf-8")).hexdigest() for mid, t in textos.items()}
        pendentes = [
            m for m in movimentos
            if m.id_movimento_contas not in existentes
            or existentes[m.id_movimento_contas].hash_texto != hashes[m.id_movimento_contas]
            or existentes[m.id_movimento_contas].modelo != MODELO_EMBEDDING
        ]

        ids_pendentes = {m.id_movimento_contas for m in pendentes}
        vetores_por_id = {
            mid: json.loads(emb.vetor) for mid, emb in existentes.items()
            if mid in textos and mid not in ids_pendentes
        }

        removidos = 0
        for mid, emb in existentes.items():
            if mid not in textos:
                session.delete(emb)
                removidos += 1

        if pendentes:
            vetores = self._embed([textos[m.id_movimento_contas] for m in pendentes], "RETRIEVAL_DOCUMENT")
            for m, vetor in zip(pendentes, vetores):
                mid = m.id_movimento_contas
                emb = existentes.get(mid) or RagEmbedding(id_movimento_contas=mid)
                emb.texto = textos[mid]
                emb.hash_texto = hashes[mid]
                emb.modelo = MODELO_EMBEDDING
                emb.vetor = json.dumps(vetor)
                vetores_por_id[mid] = vetor
                session.add(emb)

        if pendentes or removidos:
            try:
                session.commit()
            except Exception:
                # Outra requisição pode ter gravado o mesmo índice ao mesmo tempo; os vetores
                # calculados continuam válidos para esta consulta e serão regravados na próxima.
                session.rollback()

        indice = [(m, textos[m.id_movimento_contas], vetores_por_id[m.id_movimento_contas]) for m in movimentos]
        info = {"total_indexados": len(indice), "atualizados_agora": len(pendentes), "removidos_agora": removidos}
        return indice, info

    def _embed(self, textos: List[str], task_type: str) -> List[List[float]]:
        """Converte textos em vetores (embeddings) com o modelo de embeddings do Gemini."""
        vetores: List[List[float]] = []
        for inicio in range(0, len(textos), LOTE_EMBEDDING):
            resposta = self.client.models.embed_content(
                model=MODELO_EMBEDDING,
                contents=textos[inicio:inicio + LOTE_EMBEDDING],
                config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=DIMENSAO_EMBEDDING),
            )
            vetores.extend(list(e.values) for e in resposta.embeddings)
        return vetores

    # ------------------------------------------------------------------
    # 2. Augmentation
    # ------------------------------------------------------------------
    @staticmethod
    def _texto_movimento(m: MovimentoContas) -> str:
        """Converte um lançamento em texto estruturado (usado no prompt e no embedding)."""
        hoje = date.today()
        natureza = "Contas a Pagar" if m.tipo == "Despesa" else "Contas a Receber"
        classificacoes = "; ".join(
            c.classificacao.descricao for c in m.classificacoes_associadas if c.classificacao
        ) or "sem classificação"

        parcelas = []
        for p in sorted(m.parcelas, key=lambda p: (p.data_vencimento or date.max, p.id_parcela or 0)):
            situacao = p.status
            if p.status == "aberta" and p.data_vencimento and p.data_vencimento < hoje:
                situacao = "vencida"
            parcelas.append(
                f"{p.identificacao}: vencimento {_data(p.data_vencimento)}, valor {_moeda(p.valor_parcela)}, "
                f"pago {_moeda(p.valor_pago)}, saldo {_moeda(p.valor_saldo)} ({situacao})"
            )

        return "\n".join([
            f"Lançamento #{m.id_movimento_contas} | {m.tipo} ({natureza}) | NF {m.numero_nota_fiscal or 'sem número'} "
            f"| Emissão {_data(m.data_emissao)} | Valor total {_moeda(m.valor_total)}",
            f"Emitente: {_nome_pessoa(m.emitente)} | Destinatário: {_nome_pessoa(m.destinatario)}",
            f"Classificação: {classificacoes}",
            f"Produtos/serviços: {m.descricao_produtos or 'não informado'}",
            "Parcelas: " + (" | ".join(parcelas) if parcelas else "nenhuma"),
        ])

    @staticmethod
    def _resumo_geral(session: Session) -> str:
        """Totais gerais dos lançamentos ativos, para perguntas sobre o conjunto dos dados."""
        linhas = []
        for tipo in ("Despesa", "Receita"):
            qtd, total = (
                session.query(func.count(MovimentoContas.id_movimento_contas), func.coalesce(func.sum(MovimentoContas.valor_total), 0))
                .filter(MovimentoContas.status == "ativo", MovimentoContas.tipo == tipo)
                .one()
            )
            saldo = (
                session.query(func.coalesce(func.sum(Parcela.valor_saldo), 0))
                .join(MovimentoContas)
                .filter(MovimentoContas.status == "ativo", MovimentoContas.tipo == tipo, Parcela.status == "aberta")
                .scalar()
            )
            rotulo = "Despesas (Contas a Pagar)" if tipo == "Despesa" else "Receitas (Contas a Receber)"
            linhas.append(f"{rotulo}: {qtd} lançamentos ativos, total {_moeda(total)}, saldo em aberto {_moeda(saldo)}")
        return "\n".join(linhas)

    def _montar_contexto(self, registros: List[Dict[str, Any]], modo: str, session: Session) -> str:
        if modo == "embeddings":
            cabecalho = f"Lançamentos mais relacionados à pergunta (busca semântica, top {len(registros)})"
        else:
            cabecalho = f"Lançamentos ativos mais recentes ({len(registros)} de no máximo {LIMITE_REGISTROS})"

        # Compras e vendas em grupos separados, cada um com o subtotal já calculado
        secoes = []
        subtotais = {}
        for tipo, titulo in (("Despesa", "COMPRAS (Despesas / Contas a Pagar)"), ("Receita", "VENDAS (Receitas / Contas a Receber)")):
            grupo = [r for r in registros if r["movimento"].tipo == tipo]
            if not grupo:
                continue
            subtotais[tipo] = sum(float(r["movimento"].valor_total or 0) for r in grupo)
            blocos = [
                (f"[similaridade {r['similaridade']:.3f}]\n" if "similaridade" in r else "") + r["texto"]
                for r in grupo
            ]
            secoes.append(
                f"=== {titulo}: {len(grupo)} lançamento(s), subtotal {_moeda(subtotais[tipo])} ===\n\n" + "\n\n".join(blocos)
            )

        compras, vendas = subtotais.get("Despesa", 0.0), subtotais.get("Receita", 0.0)
        totais = (
            f"Totais dos lançamentos acima: compras {_moeda(compras)} | vendas {_moeda(vendas)} | "
            f"saldo (vendas - compras) {_moeda(vendas - compras)}"
        )
        return (
            f"Data de hoje: {_data(date.today())}\n\n"
            f"Resumo geral do banco:\n{self._resumo_geral(session)}\n\n"
            f"{cabecalho}:\n\n" + "\n\n".join(secoes) + f"\n\n{totais}"
        )

    # ------------------------------------------------------------------
    # 3. Generation
    # ------------------------------------------------------------------
    def _generate_response(self, user_query: str, retrieved_data: str) -> Tuple[str, str]:
        """Gera a resposta com o Gemini a partir do prompt enriquecido (dados reais + pergunta)."""
        prompt = f"""Você é um assistente de gestão financeira. Responda à pergunta usando apenas os dados abaixo.

Dados:
{retrieved_data}

Pergunta: {user_query}
"""
        ultimo_erro = None
        for modelo in MODELOS_GERACAO:
            try:
                response = self.client.models.generate_content(
                    model=modelo,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.2,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    ),
                )
                texto = (response.text or "").strip()
                if texto:
                    return texto, modelo
                ultimo_erro = RuntimeError(f"O modelo {modelo} não retornou texto.")
            except Exception as e:
                ultimo_erro = e
        raise ultimo_erro
