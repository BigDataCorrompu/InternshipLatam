-- ============================================================
-- 2. blacklist — contacts à ne plus jamais solliciter
--    (ex: demande d'exclusion via le formulaire dans l'email)
-- ============================================================
DROP TABLE IF EXISTS analytics.blacklist CASCADE;

CREATE TABLE analytics.blacklist (
    id_blacklist    SERIAL          PRIMARY KEY,
    id_contact      INT             NOT NULL REFERENCES analytics.company_contact(id_contact),
    data            JSONB           NOT NULL DEFAULT '{}',
    collected_at    TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE (id_contact)
);