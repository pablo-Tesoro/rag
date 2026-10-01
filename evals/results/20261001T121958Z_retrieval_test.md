# Retrieval evaluation (test)

- Commit: `ca622ab` · dataset `203da56f65cc`
- Embedding model: `intfloat/multilingual-e5-small`
- Chunking: max 380 tokens, overlap 60

| Mode | Cases | Recall@5 | MRR@10 |
|---|---|---|---|
| dense | 7 | 0.857 | 0.786 |
| bm25 | 7 | 0.857 | 0.857 |
| hybrid | 7 | 0.857 | 0.786 |

Recall@5 by category:

| Category | dense | bm25 | hybrid |
|---|---|---|---|
| current_vs_obsolete | 1.000 | 1.000 | 1.000 |
| exact_code | 1.000 | 1.000 | 1.000 |
| factual | 1.000 | 1.000 | 1.000 |
| injection | 1.000 | 1.000 | 1.000 |
| multi_hop | 1.000 | 1.000 | 1.000 |
| operation | 0.000 | 0.000 | 0.000 |
