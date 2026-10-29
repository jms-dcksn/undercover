CREATE SCHEMA IF NOT EXISTS undercover;
REVOKE ALL ON SCHEMA undercover FROM PUBLIC;

CREATE TABLE IF NOT EXISTS undercover.settings (
    key TEXT PRIMARY KEY,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS undercover.customers (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS undercover.plans (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS undercover.policies (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES undercover.customers,
    plan TEXT NOT NULL REFERENCES undercover.plans,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS undercover.handlers (
    id TEXT PRIMARY KEY,
    can_sign_off BOOLEAN NOT NULL,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS undercover.claims (
    id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES undercover.policies,
    customer_id TEXT NOT NULL REFERENCES undercover.customers,
    state TEXT NOT NULL DEFAULT 'waiting'
        CHECK (state IN ('waiting', 'in_progress', 'waiting_for_sign_off', 'decided')),
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS undercover.runs (
    id UUID PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES undercover.claims,
    thread_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('running', 'completed', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deadline TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_run
    ON undercover.runs (claim_id) WHERE state = 'running';
CREATE TABLE IF NOT EXISTS undercover.decisions (
    claim_id TEXT PRIMARY KEY REFERENCES undercover.claims,
    run_id UUID NOT NULL REFERENCES undercover.runs,
    outcome TEXT NOT NULL CHECK (outcome IN ('approve', 'decline', 'refer')),
    payout NUMERIC(12, 2) NOT NULL CHECK (payout >= 0 AND payout < 'Infinity'),
    explanation TEXT NOT NULL,
    policy_section INTEGER NOT NULL CHECK (policy_section BETWEEN 1 AND 12),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (outcome = 'approve' OR payout = 0)
);
CREATE TABLE IF NOT EXISTS undercover.sign_offs (
    claim_id TEXT PRIMARY KEY REFERENCES undercover.decisions,
    handler_id TEXT NOT NULL REFERENCES undercover.handlers,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS undercover.payments (
    claim_id TEXT PRIMARY KEY REFERENCES undercover.decisions,
    amount NUMERIC(12, 2) NOT NULL CHECK (amount > 0 AND amount < 'Infinity'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS undercover.activity (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES undercover.claims,
    run_id UUID REFERENCES undercover.runs,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS claim_activity ON undercover.activity (claim_id, id);
CREATE INDEX IF NOT EXISTS claim_runs ON undercover.runs (claim_id, created_at);
CREATE INDEX IF NOT EXISTS claim_policy ON undercover.claims (policy_id);
CREATE INDEX IF NOT EXISTS claim_customer ON undercover.claims (customer_id);
CREATE INDEX IF NOT EXISTS policy_customer ON undercover.policies (customer_id);

DO $$
DECLARE
    app_table RECORD;
BEGIN
    FOR app_table IN SELECT tablename FROM pg_tables WHERE schemaname = 'undercover' LOOP
        EXECUTE format('ALTER TABLE undercover.%I ENABLE ROW LEVEL SECURITY', app_table.tablename);
    END LOOP;
END $$;

-- Additive, repeatable upgrade from the pilot schema.
ALTER TABLE undercover.claims DROP CONSTRAINT IF EXISTS claims_state_check;
ALTER TABLE undercover.claims ADD CONSTRAINT claims_state_check CHECK
    (state IN ('waiting', 'in_progress', 'waiting_for_sign_off', 'decided', 'needs_handler'));
ALTER TABLE undercover.claims ADD COLUMN IF NOT EXISTS failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE undercover.claims ADD COLUMN IF NOT EXISTS last_error TEXT;
CREATE TABLE IF NOT EXISTS undercover.queue_runs (
    id UUID PRIMARY KEY,
    thread_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('queue', 'named')),
    claim_id TEXT REFERENCES undercover.claims,
    claim_limit INTEGER CHECK (claim_limit > 0),
    snapshot JSONB NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('running', 'completed', 'failed')),
    legacy BOOLEAN NOT NULL DEFAULT false,
    summary TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deadline TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_queue_run
    ON undercover.queue_runs ((true)) WHERE state = 'running';
ALTER TABLE undercover.runs ADD COLUMN IF NOT EXISTS parent_id UUID
    REFERENCES undercover.queue_runs;
ALTER TABLE undercover.runs ADD COLUMN IF NOT EXISTS error TEXT;
CREATE TABLE IF NOT EXISTS undercover.tasks (
    parent_id UUID NOT NULL REFERENCES undercover.queue_runs,
    claim_id TEXT NOT NULL REFERENCES undercover.claims,
    position INTEGER NOT NULL,
    description TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('todo', 'in_progress', 'done', 'left_for_handler')),
    admitted BOOLEAN NOT NULL DEFAULT false,
    result TEXT,
    PRIMARY KEY (parent_id, claim_id)
);
ALTER TABLE undercover.queue_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE undercover.tasks ENABLE ROW LEVEL SECURITY;
