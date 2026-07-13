CREATE SCHEMA IF NOT EXISTS staging;

DROP TABLE IF EXISTS staging.enriched_offers;
DROP TABLE IF EXISTS staging.transfer_history;


CREATE TABLE staging.enriched_offers (
    id_offer VARCHAR PRIMARY KEY,
    raw_result JSONB,
    collected_at TIMESTAMPTZ DEFAULT now()
);


CREATE TABLE staging.enriched_offers (
    id_offer      VARCHAR      PRIMARY KEY,
    raw_result    JSONB,
    llm_model     VARCHAR(50),                    -- 'ministral-8b-2512'
    collected_at  TIMESTAMPTZ  DEFAULT now()
);