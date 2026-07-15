CREATE SCHEMA IF NOT EXISTS landing;

DROP TABLE IF EXISTS landing.ingestion_tracking;



CREATE TABLE landing.ingestion_tracking (
    id              SERIAL          PRIMARY KEY,
    b2_file_id      TEXT            NOT NULL,   -- ← identité réelle (change si réécrit)
    b2_key          TEXT            NOT NULL,   -- ex: "job_offer/2026/06/jsearch/2026-06-08_jsearch.json"
    source          TEXT            NOT NULL,           -- "jsearch" | "careerjet"
    data_type       TEXT            NOT NULL,           -- "job_offer" | futur: "company_info"
    loaded_at       TIMESTAMPTZ     DEFAULT NOW(),
    record_count    INT,                                -- nombre d'offres normalisées et insérées
    status          TEXT            NOT NULL,           -- "success" | "failed"
    error_message   TEXT
);

CREATE INDEX idx_ingestion_tracking_success_file_id 
ON landing.ingestion_tracking (b2_file_id) 
WHERE status = 'success';