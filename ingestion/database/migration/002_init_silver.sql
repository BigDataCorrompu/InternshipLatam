-- ============================================================
-- Schéma analytics (silver) — InternshipLatam
-- Ordre de création respectant les dépendances FK
-- ============================================================

CREATE SCHEMA IF NOT EXISTS analytics;

-- ============================================================
-- 1. company — dimension, une ligne par entreprise normalisée
-- ============================================================
DROP TABLE IF EXISTS analytics.company CASCADE;

CREATE TABLE analytics.company (
    id_company      SERIAL          PRIMARY KEY,
    company_name    VARCHAR(150)    NOT NULL,   -- nom normalisé par LLM
    website         VARCHAR(200),
    primary_type    VARCHAR(100),                -- secteur / type d'activité (Google Places)
    collected_at    TIMESTAMPTZ     DEFAULT NOW()
);

-- ============================================================
-- 2. company_location — dimension, une ligne par filiale
-- ============================================================
DROP TABLE IF EXISTS analytics.company_location CASCADE;

CREATE TABLE analytics.company_location (
    id_location     SERIAL          PRIMARY KEY,
    id_company      INT             NOT NULL REFERENCES analytics.company(id_company),
    address         VARCHAR(255),
    city            VARCHAR(100),
    country         VARCHAR(50),
    lat             FLOAT,
    lon             FLOAT,
    phone           VARCHAR(50),
    business_status VARCHAR(50),                -- "OPERATIONAL" | "CLOSED" (Google Places)
    source          VARCHAR(50),                 -- "google_places" | "llm"
    collected_at    TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE (id_company, city, country)           -- une seule filiale par ville/pays
);

-- ============================================================
-- 3. company_contact — append only, plusieurs emails par filiale
-- ============================================================
DROP TABLE IF EXISTS analytics.company_contact CASCADE;

CREATE TABLE analytics.company_contact (
    id_contact      SERIAL          PRIMARY KEY,
    id_company      INT             NOT NULL REFERENCES analytics.company(id_company),
    id_location     INT             REFERENCES analytics.company_location(id_location),
    email           VARCHAR(254)    NOT NULL,
    confidence      FLOAT,                       -- score 0-1
    explanation     TEXT,
    source          VARCHAR(50),                 -- "hunter.io" | "llm" | "ddgs"
    collected_at    TIMESTAMPTZ     DEFAULT NOW()
);

-- ============================================================
-- 4. job_offer — fait central, transformé depuis raw.job_offer
-- ============================================================
DROP TABLE IF EXISTS analytics.job_offer CASCADE;

CREATE TABLE analytics.job_offer (
    id_offer            VARCHAR(50)     PRIMARY KEY,   -- = raw.id_job
    id_company          INT             REFERENCES analytics.company(id_company),
    id_location         INT             REFERENCES analytics.company_location(id_location),
    api_source          VARCHAR(15)     NOT NULL,
    job_title           VARCHAR(150),
    offer_description   TEXT,
    contract_type       VARCHAR(20),
    is_remote           BOOLEAN,
    job_publisher       VARCHAR(100),
    location_raw        VARCHAR(100),               -- valeur brute conservée pour audit
    offer_url           VARCHAR(500)    NOT NULL,
    source_platform     VARCHAR(100),
    offer_language       VARCHAR(10),                 -- langue de rédaction de l'offre
    published_at        TIMESTAMPTZ,
    collected_at         TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE (offer_url)                              -- déduplication cross-collecte
);

-- ============================================================
-- 5. job_requirement — append only, enrichissement LLM
-- ============================================================
DROP TABLE IF EXISTS analytics.job_requirement CASCADE;

CREATE TABLE analytics.job_requirement (
    id              SERIAL          PRIMARY KEY,
    id_offer        VARCHAR(50)     NOT NULL REFERENCES analytics.job_offer(id_offer),
    alternative_job_titles  TEXT[],
    offer_languages         TEXT[],              -- langues humaines requises par le poste
    seniority               VARCHAR(20),         -- "junior" | "mid" | "senior"
    skills_languages        TEXT[],              -- Python, SQL, Java...
    skills_frameworks       TEXT[],              -- Airflow, dbt, AWS...
    skills_aptitudes        TEXT[],              -- Administration BDD, Architecture...
    skills_soft             TEXT[],              -- Autonomie, Travail en équipe...
    prompt_version          VARCHAR(50),
    collected_at             TIMESTAMPTZ     DEFAULT NOW()
);

-- ============================================================
-- 6. prompt_relevancy — versionnement des prompts de scoring
-- ============================================================
DROP TABLE IF EXISTS analytics.prompt_relevancy CASCADE;

CREATE TABLE analytics.prompt_relevancy (
    id_prompt       SERIAL          PRIMARY KEY,
    prompt          TEXT            NOT NULL,
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

-- ============================================================
-- 7. job_relevancy — append only, scores dimensionnels par prompt
-- ============================================================
DROP TABLE IF EXISTS analytics.job_relevancy CASCADE;

CREATE TABLE analytics.job_relevancy (
    id              SERIAL          PRIMARY KEY,
    id_offer        VARCHAR(50)     NOT NULL REFERENCES analytics.job_offer(id_offer),
    id_prompt       INT             REFERENCES analytics.prompt_relevancy(id_prompt),
    score_relevancy FLOAT,                       -- score global (calculé ou fourni par le LLM)
    score_job       FLOAT,
    score_skills    FLOAT,
    score_location  FLOAT,
    score_language  FLOAT,
    score_seniority FLOAT,
    score_work_mode FLOAT,
    score_company   FLOAT,
    explanation     TEXT,
    collected_at    TIMESTAMPTZ     DEFAULT NOW()
);

-- ============================================================
-- Index : To lookup fast into database to match an offer with an already registered company
-- ============================================================
CREATE INDEX idx_company_location_lookup
    ON analytics.company_location(id_company, city, country);

CREATE INDEX idx_company_name 
    ON analytics.company(company_name);
