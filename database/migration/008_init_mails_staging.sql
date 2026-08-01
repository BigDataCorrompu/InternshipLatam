CREATE SCHEMA IF NOT EXISTS staging;

DROP TABLE IF EXISTS staging.company_emails;

CREATE TABLE staging.company_emails (
    id_company    INTEGER      NOT NULL,
    id_location   INTEGER      NOT NULL,
    raw_result    JSONB,
    collected_at  TIMESTAMPTZ  DEFAULT now(),
    PRIMARY KEY (id_company, id_location, collected_at)
);