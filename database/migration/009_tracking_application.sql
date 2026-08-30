-- ============================================================
-- Migration : suivi des candidatures automatisées + blacklist
-- Schéma analytics — InternshipLatam
-- ============================================================

-- ============================================================
-- 1. tracking_application — une ligne par candidature envoyée
-- ============================================================
DROP TABLE IF EXISTS analytics.tracking_application CASCADE;

CREATE TABLE analytics.tracking_application (
    id_tracking     SERIAL          PRIMARY KEY,
    id_offer        TEXT            NOT NULL REFERENCES analytics.job_offer(id_offer),
    id_location     INT             REFERENCES analytics.company_location(id_location),
    id_company      INT             NOT NULL REFERENCES analytics.company(id_company),
    id_contact      INT             NOT NULL REFERENCES analytics.company_contact(id_contact),
    date            TIMESTAMPTZ     DEFAULT NOW(),

    -- Un seul envoi par (offre, contact) : empêche de renvoyer au même
    -- contact pour la même offre si le DAG est rejoué ou retry.
    UNIQUE (id_offer, id_contact)
);

CREATE INDEX IF NOT EXISTS idx_tracking_application_offer
    ON analytics.tracking_application(id_offer);

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