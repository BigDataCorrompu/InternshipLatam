-- _______ Create Schema _______
CREATE SCHEMA IF NOT EXISTS raw;

-- _______ Clean up existing tables to ensure a fresh state _______ 
DROP TABLE IF EXISTS raw.job_offer;


-- _______ Create structural tables _______


CREATE TABLE raw.job_offer (
    -- Identifiants
    id_job          VARCHAR(50),        -- JSearch ~32 chars, CJ hash
    api_source          VARCHAR(15)     NOT NULL,           -- "jsearch" | "careerjet"

    -- Offre
    job_title       VARCHAR(150),                       -- max ~100 chars en pratique
    contract_type   VARCHAR(20),                        -- "INTERN" | "FULLTIME" | null
    job_publisher   VARCHAR(100),

    -- Entreprise
    company         VARCHAR(100),                       -- CJ max 8 chars, JS plus long
    company_website VARCHAR(200),                       -- null CJ

    -- Localisation
    location_raw    VARCHAR(100),                       -- CJ "Buenos Aires" = 12 chars
    city            VARCHAR(100),
    country         VARCHAR(50),
    latitude        FLOAT,                              -- null CJ
    longitude       FLOAT,                              -- null CJ
    is_remote       BOOLEAN,

    -- Candidature
    offer_url       VARCHAR(500),                       -- CJ url = 263 chars fixes
    is_direct       BOOLEAN,
    source_platform VARCHAR(100),                       -- null CJ (site vide)

    -- Description
    offer_description TEXT,                             -- CJ ~300 chars, JS beaucoup plus long
    job_highlights   TEXT,

    -- Salaire
    salary_raw      VARCHAR(200),                       -- CJ toujours vide
    salary_min      FLOAT,                              -- null CJ
    salary_max      FLOAT,                              -- null CJ
    salary_period   VARCHAR(50),                        -- null CJ

    -- Dates
    published_at    TIMESTAMPTZ,                        -- CJ date string à parser
    collected_at    TIMESTAMPTZ     DEFAULT NOW(),

    -- Query
    query_parameters    JSONB
);

