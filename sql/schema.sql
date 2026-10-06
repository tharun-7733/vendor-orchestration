CREATE TYPE case_status AS ENUM ('queued', 'processing', 'clear', 'review', 'failed', 'rejected');

CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR(320) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE screening_cases (
    id UUID PRIMARY KEY,
    external_reference VARCHAR(128) NOT NULL,
    owner_id UUID REFERENCES users(id) ON DELETE CASCADE,
    subject_name VARCHAR(200) NOT NULL,
    date_of_birth VARCHAR(10),
    country VARCHAR(2),
    status case_status NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_screening_cases_owner_reference UNIQUE (owner_id, external_reference)
);
CREATE INDEX ix_screening_cases_owner_id ON screening_cases (owner_id);

CREATE TABLE vendor_results (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES screening_cases(id) ON DELETE CASCADE,
    vendor VARCHAR(40) NOT NULL,
    outcome VARCHAR(20) NOT NULL,
    matched BOOLEAN NOT NULL DEFAULT false,
    confidence DOUBLE PRECISION,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_vendor_results_case_id ON vendor_results (case_id);
