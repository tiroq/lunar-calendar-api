-- Exactly one content snapshot can be active at any time.
-- This is safe to re-run and detects inconsistent pre-existing databases.
CREATE UNIQUE INDEX IF NOT EXISTS lunar_content_only_one_active
    ON lunar_content_packages ((true))
    WHERE activated_at IS NOT NULL;
