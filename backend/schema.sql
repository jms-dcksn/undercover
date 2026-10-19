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
