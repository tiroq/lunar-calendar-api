-- Public schema only. No content records are stored in the repository.
CREATE TABLE IF NOT EXISTS lunar_content_packages (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    content_version TEXT NOT NULL UNIQUE,
    sha256 CHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at TIMESTAMPTZ,
    CONSTRAINT lunar_content_schema CHECK (
        jsonb_typeof(payload) = 'object' AND
        payload ->> 'schema_version' = '1' AND
        jsonb_typeof(payload -> 'days') = 'object'
    )
);
CREATE INDEX IF NOT EXISTS lunar_content_active_idx
    ON lunar_content_packages(activated_at DESC NULLS LAST, id DESC);
