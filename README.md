# Organizador Financeiro Agro (UniRV – Prática de Engenharia, N2)

Sistema administrativo-financeiro: extração de Notas Fiscais em PDF com Gemini (Agent1),
consulta/gravação no banco relacional (Agent2), cadastros com exclusão lógica,
Contas a Pagar / a Receber e relatórios.

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
