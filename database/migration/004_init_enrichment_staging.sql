CREATE SCHEMA IF NOT EXISTS staging;

DROP TABLE IF EXISTS staging.enriched_offers;
DROP TABLE IF EXISTS staging.transfer_history;


CREATE TABLE staging.enriched_offers (
    id_offer VARCHAR PRIMARY KEY,
    raw_result JSONB,
    collected_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS staging.transfer_history (
    id              SERIAL PRIMARY KEY,
    staging_id      INT NOT NULL REFERENCES staging.enriched_offers(id_offer),
    transferred_at  TIMESTAMPTZ DEFAULT NOW(),
    status          TEXT NOT NULL,          -- 'success' | 'failed' | 'skipped'
    error_message   TEXT
);