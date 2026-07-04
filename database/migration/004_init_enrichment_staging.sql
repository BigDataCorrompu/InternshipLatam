CREATE SCHEMA IF NOT EXISTS staging;

DROP TABLE IF EXISTS staging.enriched_offers;

CREATE TABLE staging.enriched_offers (
    id_offer VARCHAR,
    raw_result JSONB,
    collected_at TIMESTAMPTZ DEFAULT now()
);