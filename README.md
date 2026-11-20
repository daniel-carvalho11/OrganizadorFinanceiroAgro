# Organizador Financeiro Agro (UniRV – Prática de Engenharia, N2)

Sistema administrativo-financeiro: extração de Notas Fiscais em PDF com Gemini (Agent1),
consulta/gravação no banco relacional (Agent2), cadastros com exclusão lógica,
Contas a Pagar / a Receber, relatórios e Busca Inteligente com RAG (Agent3).

## Ambientes de banco de dados

| Ambiente | Banco | Onde é configurado |
|---|---|---|
| Desenvolvimento (cada máquina) | PostgreSQL local | `DATABASE_URL` no arquivo `.env` (não vai para o git) |
| Produção (Render) | PostgreSQL do Render | Variável `DATABASE_URL` no painel do Render |
| Testes automatizados | SQLite temporário | Criado e apagado pelo `pytest` |
| Fallback (sem `DATABASE_URL`) | SQLite `financeiro.db` | Arquivo local, ignorado pelo git |

O deploy leva apenas código: o banco local de cada desenvolvedor nunca é afetado.

## Configuração local

### 1. Dependências
```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. PostgreSQL local
Com Podman (ou troque `podman` por `docker`):
```bash
podman run -d --name agro-postgres \
  -e POSTGRES_USER=agro -e POSTGRES_PASSWORD=agro -e POSTGRES_DB=agro_financeiro \
  -p 127.0.0.1:5432:5432 -v agro-pgdata:/var/lib/postgresql/data \
  docker.io/library/postgres:16
```
Após reiniciar o computador: `podman start agro-postgres`.
No Windows também é possível usar o instalador oficial do PostgreSQL e criar o usuário/banco equivalentes.

**DBeaver:** Nova conexão → PostgreSQL → host `localhost`, porta `5432`,
banco `agro_financeiro`, usuário `agro`, senha `agro`.

### 3. Arquivo `.env`
```bash
cp .env.example .env
```
Preencha a `GEMINI_API_KEY` e confira a `DATABASE_URL`.

### 4. Dados de exemplo e execução
```bash
python seed_demo.py   # opcional: popula o banco local com dados de demonstração
python main.py        # http://127.0.0.1:8000
```
As tabelas são criadas automaticamente na primeira execução.
O rodapé do sistema mostra qual banco está em uso.

## Busca Inteligente (RAG) – Agent3

Na tela principal, card **Buscar Lançamentos**, escolha a **Categoria de pesquisa** "Pergunta com IA" (RAG Simples ou RAG Embeddings): o usuário digita uma pergunta sobre os lançamentos e o Gemini
elabora a resposta usando apenas os dados do banco. Fluxo:
`rag_query.html` → `POST /api/rag/consulta` → `Agent3.run_query()` → recupera os dados → Gemini gera a resposta.

| Arquivo | Função |
|---|---|
| `agents/agent3/agent_RAG.py` | Classe `Agent3`: `_retrieve_data` (Retrieval), `_montar_contexto` (Augmentation), `_generate_response` (Generation) |
| `main.py` (`rag_query`) | Rota `/api/rag/consulta`: recebe a pergunta e devolve resposta + fontes |
| `templates/rag_query.html` | Painel de resposta e lógica da pesquisa com IA (incluído na tela principal do `index.html`) |

Modos de busca:
- **RAG Simples**: envia ao modelo os 20 lançamentos ativos mais recentes.
- **RAG com Embeddings**: cada lançamento é vetorizado com `gemini-embedding-001` e guardado na tabela
  `rag_embeddings` (índice vetorial). A pergunta também é vetorizada e os 10 lançamentos mais próximos
  (similaridade de cosseno) formam o contexto. O índice é atualizado sozinho a cada consulta: só os
  lançamentos novos ou alterados são vetorizados de novo, e os excluídos saem do índice.

A chave do Gemini vem da tela (a mesma salva na aba de extração) ou da `GEMINI_API_KEY` do `.env`.

## Testes
```bash
pytest -q
```
Usam um SQLite temporário e não tocam no banco local. Para validar contra PostgreSQL,
aponte `TEST_DATABASE_URL` para um banco **descartável** (as tabelas são apagadas a cada teste).

## Atenção ao atualizar a partir de versões antigas
O `financeiro.db` deixou de ser versionado. Se o seu clone ainda tem esse arquivo e você quer
manter os dados dele, faça uma cópia **antes** do `git pull`:
```bash
cp financeiro.db financeiro_backup.db
git checkout -- financeiro.db
git pull
mv financeiro_backup.db financeiro.db
```
