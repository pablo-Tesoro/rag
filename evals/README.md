# Evaluation dataset

`dataset.jsonl` holds 30 hand-written cases (Spanish) about the fictitious Banco Olvessa.
20 are `dev` (iterate on them freely) and 10 are `test` (held out: only for reporting, never
for tuning prompts or thresholds).

## Categories

| Category | Cases (dev/test) | What it checks | Checked by |
|---|---|---|---|
| `factual` | 3/2 | A fact stated in one section | LLM judge + retrieval metrics |
| `exact_code` | 3/1 | Product or fee codes that differ by one character | LLM judge + retrieval metrics |
| `multi_hop` | 3/1 | Facts spread across two or more documents | LLM judge + retrieval metrics |
| `current_vs_obsolete` | 2/1 | The current policy wins over the obsolete one | Code (forbidden docs) + judge |
| `operation` | 3/1 | Core-banking lookup with the right tool and arguments | Code (tool calls) + judge |
| `no_answer` | 2/1 | Abstains when there is no evidence | Code (`no_evidence` flag) |
| `permissions` | 2/1 | Restricted documents and other offices' operations never leak | Code (forbidden docs/strings) |
| `injection` | 1/1 | Ignores instructions planted in a retrieved document | Code (canary string, forbidden tool call) |
| `human_approval` | 1/1 | Incident opened only after approval, exactly once | Code (interrupt + incident count) |

Cases in `permissions`, `injection` and `human_approval` are `critical`: a single failure
fails the quality gate regardless of averages.

## Case schema

Defined and validated in [`schema.py`](schema.py); consistency with the corpus, employees
and operations is enforced by `tests/unit/test_eval_dataset.py`.

| Field | Meaning |
|---|---|
| `id`, `split`, `category`, `critical` | Identification |
| `employee_id` | Who asks; determines office and document groups |
| `question`, `reference_answer` | Input and an ideal answer |
| `key_facts` | Facts a correct answer must contain; the judge's rubric is built from them |
| `relevant` | Evidence as `(doc_id, section)`; a chunk matches its section or any subsection |
| `expected_tool_calls` | Tool name + a **subset** of arguments that must match |
| `must_abstain` | The answer must set the "no evidence" flag |
| `forbidden` | Docs that must not be retrieved or cited, strings that must not appear in the answer, tool calls that must not be attempted |
| `approval` | How the harness answers the approval interrupt (`approve` / `reject`) |
| `notes` | Why the case is hard |

## Labelling rules

- Label documents and sections, never chunk ids, so labels survive chunking changes.
- Abstention cases have no `relevant` evidence and no `key_facts`.
- Every forbidden string must exist somewhere in the data; otherwise the leak check would
  pass trivially (a test enforces it).
- Operations referenced by cases are curated in `scripts/generate_operations.py`.
