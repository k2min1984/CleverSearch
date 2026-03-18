# Database Migration Guide

## 1) Install dependencies

```bash
pip install -r requirements.txt
```

## 2) Configure database URL

Set `DATABASE_URL` in `.env`.

Examples:

```bash
DATABASE_URL=sqlite:///./cleversearch_app.db
# or
DATABASE_URL=postgresql+psycopg2://cleversearch:cleversearch123@localhost:5432/cleversearch
```

## 3) Run migration

```bash
alembic upgrade head
```

## 4) Create new revision after schema changes

```bash
alembic revision -m "add new field"
```

Then edit generated migration file under `alembic/versions` and run:

```bash
alembic upgrade head
```
