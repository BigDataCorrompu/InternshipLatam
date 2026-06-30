-- Schema
CREATE SCHEMA IF NOT EXISTS landing;

-- Drop tables if exists
DROP TABLE IF EXISTS landing.raw_job_offers CASCADE;
DROP TABLE IF EXISTS landing.push_history CASCADE;

-- Landing zone : offres brutes
CREATE TABLE landing.raw_job_offers (
    id          SERIAL PRIMARY KEY,
    source      TEXT        NOT NULL,  -- "jsearch", "careerjet"
    params      JSONB,                 -- paramètres de la requête API
    data        JSONB       NOT NULL,  -- payload brut
    collected_at TIMESTAMPTZ DEFAULT NOW()
);

-- Historique des pushes vers Bronze (Neon)
CREATE TABLE landing.push_history (
    id              SERIAL PRIMARY KEY,
    raw_offer_id    INT NOT NULL REFERENCES landing.raw_job_offers(id),  -- FK
    pushed_at       TIMESTAMPTZ DEFAULT NOW(),
    status          TEXT NOT NULL,   -- "success", "failed"
    error_message   TEXT             -- NULL si success
);