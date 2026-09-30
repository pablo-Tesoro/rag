# Progreso

Estado del proyecto para poder retomarlo en otra sesión. Se actualiza al cerrar cada fase.

## Fases

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Esqueleto y datos | ✅ Terminada (dataset revisado y aprobado) |
| 2 | Ingesta y recuperación | ✅ Terminada y verificada con el modelo real |
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

## Fase 2: verificación con el modelo real

- `sentence-transformers` con torch solo CPU en Linux (índice `pytorch-cpu` en
  `pyproject.toml`; torch se declara como dependencia directa porque `[tool.uv.sources]` solo
  se aplica a dependencias directas). Torch CPU ocupa 187 MB frente a varios GB con CUDA.
- `make ingest`: 13 documentos y 67 chunks (máximo 369 tokens con el tokenizador de
  e5-small, medio 136) en unos 35 s con la descarga del modelo; una segunda ejecución no
  reprocesa nada.
- `make eval-retrieval` sobre dev (13 casos con evidencia etiquetada), commit `591c4a1`,
  resultado en `evals/results/20260930T175343Z_retrieval_dev.*`:

  | Modo | Recall@5 | MRR@10 |
  |---|---|---|
  | dense | 0.872 | 0.904 |
  | bm25 | 0.923 | 0.938 |
  | hybrid | 0.962 | 0.910 |

  La búsqueda densa falla en códigos exactos y en preguntas de varios saltos; BM25 falla
  cuando la pregunta no comparte palabras con la respuesta (FAC-02). Solo hybrid encuentra
  las dos piezas de MUL-01. Con 13 casos, un caso equivale a unos 0,08 de recall: son
  diferencias orientativas.
- El split de test no se ha ejecutado a propósito: se reserva para el informe final.

## Siguiente paso

Fase 3: agente LangGraph (estado tipado, tres herramientas, interrupt para la aprobación,
límites) y API FastAPI (`/chat`, `/healthz`, `/readyz`). Necesita `GOOGLE_API_KEY`, que se
configuró en el entorno pero solo la ven las sesiones nuevas.

## Incidente de seguridad (30/09/2026)

- Se subió a la rama, desde GitHub, un commit (`e8a6d63`) que escribía una clave real de
  `GOOGLE_API_KEY` en `.env.example`, en un repositorio público.
- Respuesta: el commit se eliminó de la rama con un force-push aprobado por el propietario y
  se añadió `tests/unit/test_env_example.py`, que falla si alguna credencial de
  `.env.example` tiene valor.
- La clave debe revocarse en Google AI Studio y sustituirse por una nueva, guardada solo en la
  configuración del entorno o en el `.env` local. Borrarla de la historia no basta: estuvo
  publicada.

## Acciones del propietario

- ✅ Acceso de push a GitHub concedido.
- ✅ Red abierta (Hugging Face, PyTorch, LangSmith).
- ⚠️ Revocar la clave expuesta y crear una nueva en Google AI Studio; guardarla como
  `GOOGLE_API_KEY` en la configuración del entorno (la leen las sesiones nuevas).
- Opcional: `LANGSMITH_API_KEY` para las trazas de la fase 5.

## Notas del entorno en la nube

- El daemon de Docker no arranca solo: `sudo dockerd > /tmp/dockerd.log 2>&1 &` antes de
  `make up`.
- El aviso `UV_NATIVE_TLS is deprecated` lo provoca la configuración del proxy; es inofensivo.
- `docs.langchain.com` está bloqueado: la doc oficial se lee en `github.com/langchain-ai/docs`.
