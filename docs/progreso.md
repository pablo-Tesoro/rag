# Progreso

Estado del proyecto para poder retomarlo en otra sesión. Se actualiza al cerrar cada fase.

## Fases

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Esqueleto y datos | ✅ Terminada, pendiente de revisión del dataset |
| 2 | Ingesta y recuperación (chunking, ingesta incremental, dense/bm25/hybrid, RRF) | ⏳ Pendiente |
| 3 | Agente y API (grafo LangGraph, herramientas, interrupt, FastAPI) | ⏳ Pendiente |
| 4 | Evaluación (harness, métricas, puerta de calidad) | ⏳ Pendiente |
| 5 | Trazas, Docker y CI | ⏳ Pendiente |
| 6 | Ablación y README | ⏳ Pendiente |

## Fase 1: qué hay

- Tooling: uv, ruff, mypy estricto, pytest y Makefile. `make check` en verde.
- `docker-compose.yml` solo con Postgres + pgvector (`pgvector/pgvector:0.8.6-pg17`).
- Configuración con pydantic-settings (`src/bank_assistant/config.py`) y logs JSON sin datos
  personales (`logs.py`).
- Modelos Pydantic para empleados, oficinas, operaciones y metadatos de documentos.
- Corpus de 13 documentos: 11 en Markdown y 2 PDFs generados de forma determinista. El
  mapa de casos difíciles está en `data/README.md`.
- 50 operaciones (script con semilla fija), 4 oficinas y 3 empleados.
- Borrador del dataset en `evals/dataset.jsonl`: 30 casos, 20 de dev y 10 de test, con
  esquema en `evals/schema.py` y tests de coherencia con los datos.

## Siguiente paso

1. El propietario revisa y corrige el dataset.
2. Fase 2: ingesta y recuperación. Propuesta pendiente de OK: BM25 implementado en SQL
   sobre una tabla de índice invertido, para que los filtros de permisos y de vigencia vayan
   en la misma consulta que la búsqueda densa.

## Acciones pendientes del propietario

- Para ejecutar el agente y las evals desde el entorno en la nube: crear una clave gratuita
  en Google AI Studio y añadirla como variable de entorno `GOOGLE_API_KEY` en la
  configuración del entorno. No debe pegarse en el chat.
- Permitir en la red del entorno `huggingface.co` y sus CDN (`*.hf.co`,
  `cdn-lfs.huggingface.co`), necesarios para descargar el modelo de embeddings local, y
  `download.pytorch.org` para torch CPU.
- Opcional: `api.smith.langchain.com` y `LANGSMITH_API_KEY` (plan gratuito) para las trazas.

## Notas del entorno en la nube

- El daemon de Docker no arranca solo: `sudo dockerd &` antes de usar `docker compose`.
- El aviso `UV_NATIVE_TLS is deprecated` lo provoca la configuración del proxy del entorno;
  es inofensivo.
- La doc oficial de LangChain (`docs.langchain.com`) está bloqueada; se consulta en su
  repositorio de GitHub (`langchain-ai/docs`).
