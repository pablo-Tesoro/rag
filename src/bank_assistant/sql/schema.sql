-- Idempotent schema: safe to run on every start.
--
-- Retrieval index (documents, chunks, chunk_terms): derived data that can always be rebuilt
-- from data/corpus with `make ingest`, so its schema changes are handled by re-ingesting.
-- Incidents (end of file) are real data and would need proper migrations if they changed.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    doc_id        text PRIMARY KEY,
    title         text NOT NULL,
    version       text NOT NULL,
    doc_date      date NOT NULL,
    status        text NOT NULL CHECK (status IN ('vigente', 'obsoleto')),
    groups        text[] NOT NULL CHECK (cardinality(groups) > 0),
    source_path   text NOT NULL,
    content_hash  text NOT NULL,   -- file bytes + index fingerprint; drives incremental ingestion
    ingested_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS documents_groups_idx ON documents USING gin (groups);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id       text PRIMARY KEY,
    doc_id         text NOT NULL REFERENCES documents (doc_id) ON DELETE CASCADE,
    ordinal        integer NOT NULL,
    section        text NOT NULL,
    section_title  text NOT NULL,
    heading_path   text NOT NULL,
    content        text NOT NULL,   -- body shown to the model
    search_text    text NOT NULL,   -- contextual header + body, embedded and indexed
    token_count    integer NOT NULL,
    term_count     integer NOT NULL, -- document length for BM25
    -- No fixed dimension: the model is configurable. Exact search needs no ANN index at
    -- this corpus size; the index fingerprint forces a full re-embed when the model changes.
    embedding      vector NOT NULL,
    UNIQUE (doc_id, ordinal)
);

-- Inverted index for BM25: one row per (term, chunk) with the term frequency.
CREATE TABLE IF NOT EXISTS chunk_terms (
    term      text NOT NULL,
    chunk_id  text NOT NULL REFERENCES chunks (chunk_id) ON DELETE CASCADE,
    tf        integer NOT NULL CHECK (tf > 0),
    PRIMARY KEY (term, chunk_id)
);

CREATE INDEX IF NOT EXISTS chunk_terms_chunk_idx ON chunk_terms (chunk_id);

-- ---------------------------------------------------------------------------------------
-- Simulated core banking (fictitious operations, loaded from data/core_banking).
-- In production this would be an external system reached with the employee's delegated
-- token; here the office filter lives in the SQL query for the same reason.

CREATE TABLE IF NOT EXISTS core_operations (
    operation_id  text PRIMARY KEY CHECK (operation_id ~ '^OP-[0-9]{6}$'),
    type          text NOT NULL,
    status        text NOT NULL,
    amount        numeric(14, 2) NOT NULL CHECK (amount > 0),
    currency      char(3) NOT NULL,
    office_id     text NOT NULL,
    concept       text NOT NULL,
    created_at    timestamptz NOT NULL,
    updated_at    timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS core_operations_office_idx ON core_operations (office_id);

-- ---------------------------------------------------------------------------------------
-- Incidents opened by the assistant after human approval. Not derived data: never dropped
-- by re-ingestion. The idempotency key makes a retried or replayed write a no-op.

CREATE TABLE IF NOT EXISTS incidents (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    incident_number  text GENERATED ALWAYS AS ('INC-' || lpad(id::text, 6, '0')) STORED,
    idempotency_key  text NOT NULL UNIQUE,
    employee_id      text NOT NULL,
    office_id        text NOT NULL,
    operation_id     text NOT NULL,
    category         text NOT NULL,
    description      text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);
