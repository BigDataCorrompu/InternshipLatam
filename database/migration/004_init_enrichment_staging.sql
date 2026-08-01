CREATE SCHEMA IF NOT EXISTS staging;

DROP TABLE IF EXISTS staging.enriched_offers;
DROP TABLE IF EXISTS staging.company_emails;


CREATE TABLE staging.enriched_offers (
    id_offer      TEXT      PRIMARY KEY,
    raw_result    JSONB,
    llm_model     VARCHAR(50),                    -- 'ministral-8b-2512'
    collected_at  TIMESTAMPTZ  DEFAULT now()
);


CREATE TABLE staging.company_emails (
    id_company    INTEGER      NOT NULL,
    id_location   INTEGER      NOT NULL,
    raw_result    JSONB,                          -- list of dicts {email, score, reason, source}
    collected_at  TIMESTAMPTZ  DEFAULT now(),
    PRIMARY KEY (id_company, collected_at)        
);