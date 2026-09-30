# Progreso

Estado del proyecto para poder retomarlo en otra sesión. Se actualiza al cerrar cada fase.

## Fases

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Esqueleto y datos | ✅ Terminada (dataset revisado y aprobado) |
| 2 | Ingesta y recuperación | 🟡 Código y tests terminados; falta la verificación con el modelo real |
| 3 | Agente y API (grafo LangGraph, herramientas, interrupt, FastAPI) | ⏳ Pendiente |
| 4 | Evaluación (harness, métricas, puerta de calidad) | ⏳ Pendiente |
| 5 | Trazas, Docker y CI | ⏳ Pendiente |
| 6 | Ablación y README | ⏳ Pendiente |

## Fase 1: qué hay

- Tooling: uv, ruff, mypy estricto, pytest y Makefile. Compose con Postgres + pgvector.
- Configuración con pydantic-settings y logs JSON sin datos personales.
- Corpus de 13 documentos (11 en Markdown y 2 PDFs deterministas), 50 operaciones, 4
  oficinas y 3 empleados. El mapa de casos difíciles está en `data/README.md`.
- Dataset de 30 casos (20 de dev y 10 de test) con esquema y tests de coherencia.

## Fase 2: qué hay

- `ingestion/loaders.py`: Markdown y PDF convertidos a secciones numeradas con bloques de
  texto y tablas. En los PDFs se descartan las franjas de cabecera y pie, los títulos se
  detectan por numeración y tamaño de letra, y las tablas partidas entre páginas se unen.
- `ingestion/chunking.py`: chunks por sección, hasta 380 tokens, tablas enteras, 60 tokens
  de solapamiento en la prosa y cabecera contextual.
- `retrieval/lexical.py`: analizador en español que conserva los códigos.
- `sql/schema.sql`: tablas `documents`, `chunks` (vector) y `chunk_terms` (índice invertido).
- `ingestion/pipeline.py`: ingesta incremental por hash con huella del índice, borrados en
  cascada, una transacción por documento y advisory lock.
- `retrieval/retriever.py`: modos `dense`, `bm25` (SQL) e `hybrid` (RRF). Los filtros de
  grupos y de vigencia van en todas las consultas.
- `embeddings.py`: protocolo `Embedder` e implementación con sentence-transformers (carga
  perezosa).
- `cli.py`: `ingest` y `search`. `evals/retrieval_eval.py`: recall@5 y MRR@10 por modo, sin
  LLM.
- Tests: 80 en verde, unitarios y de integración contra Postgres real con un embedder
  falso determinista. Incluyen la comparación del BM25 en SQL con una referencia en Python
  y pruebas de mutación manuales de los filtros de permisos.

## Pendiente para cerrar la fase 2 (necesita la red nueva, en una sesión nueva)

La sesión en la que se escribió la fase 2 no tenía acceso a `huggingface.co` ni a
`download.pytorch.org`: los cambios de red del entorno solo se aplican a sesiones nuevas.

1. Añadir la pila de embeddings locales con torch solo CPU en Linux. En `pyproject.toml`:
   ```toml
   dependencies = [..., "sentence-transformers>=6.1,<7"]

   [tool.uv.sources]
   torch = [{ index = "pytorch-cpu", marker = "sys_platform == 'linux'" }]

   [[tool.uv.index]]
   name = "pytorch-cpu"
   url = "https://download.pytorch.org/whl/cpu"
   explicit = true
   ```
   Después, `uv lock` y quitar `sentence_transformers` de las excepciones de mypy si trae
   tipos.
2. `make up && make ingest`: comprobar que descarga e5-small, ingesta 13 documentos y que una
   segunda ejecución no reprocesa nada.
3. Revisar con `uv run python -m bank_assistant.cli search "..." --employee EMP-001` que los
   resultados tienen sentido.
4. `make eval-retrieval`: primera tabla real de recall@5 y MRR por modo, guardada en
   `evals/results/`. Estas son las primeras cifras que pueden citarse.
5. Commit y resumen de la fase 2 al propietario.

## Acciones del propietario

- ✅ Acceso de push a GitHub concedido.
- Clave gratuita de Google AI Studio como `GOOGLE_API_KEY` en la configuración del entorno
  (no en el chat). Necesaria en la fase 3.
- Red: `huggingface.co` con sus CDN (`*.hf.co`, `cdn-lfs.huggingface.co`) y
  `download.pytorch.org`. Opcional: `api.smith.langchain.com` y `LANGSMITH_API_KEY`.

## Notas del entorno en la nube

- El daemon de Docker no arranca solo: `sudo dockerd > /tmp/dockerd.log 2>&1 &` antes de
  `make up`.
- El aviso `UV_NATIVE_TLS is deprecated` lo provoca la configuración del proxy; es inofensivo.
- `docs.langchain.com` está bloqueado: la doc oficial se lee en `github.com/langchain-ai/docs`.
