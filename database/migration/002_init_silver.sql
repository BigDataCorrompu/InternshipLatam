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
    company_name    VARCHAR(150)    NOT NULL,
    website         VARCHAR(200),
    primary_type    VARCHAR(100),
    collected_at    TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE (company_name)              -- ajouté : nécessaire pour ON CONFLICT (company_name)
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
    business_status VARCHAR(50),
    source          VARCHAR(50),
    collected_at    TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE (id_company, city, country)
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
    confidence      FLOAT,
    explanation     TEXT,
    source          VARCHAR(50),
    collected_at    TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE (email)                      -- ajouté : nécessaire pour ON CONFLICT (email)
);

-- ============================================================
-- 4. job_offer — fait central, transformé depuis raw.job_offer
-- ============================================================
DROP TABLE IF EXISTS analytics.job_offer CASCADE;

CREATE TABLE analytics.job_offer (
    id_offer            VARCHAR(50)     PRIMARY KEY,   -- PK = déjà UNIQUE nativement
    id_company          INT             REFERENCES analytics.company(id_company),
    id_location         INT             REFERENCES analytics.company_location(id_location),
    api_source          VARCHAR(15)     NOT NULL,
    job_title           VARCHAR(150),
    offer_description   TEXT,
    contract_type       VARCHAR(20),
    is_remote           BOOLEAN,
    job_publisher       VARCHAR(100),
    location_raw        VARCHAR(100),
    offer_url           VARCHAR(500)    NOT NULL,
    source_platform     VARCHAR(100),
    published_at        TIMESTAMPTZ,
    collected_at         TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE (offer_url)
);

-- ============================================================
-- 5. job_requirement — append only, enrichissement LLM
-- ============================================================
DROP TABLE IF EXISTS analytics.job_requirement CASCADE;

CREATE TABLE analytics.job_requirement (
    id              SERIAL          PRIMARY KEY,
    id_offer        VARCHAR(50)     NOT NULL REFERENCES analytics.job_offer(id_offer),
    alternative_job_titles  TEXT[],
    offer_languages         TEXT[],
    seniority               VARCHAR(20),
    skills_languages        TEXT[],
    skills_frameworks       TEXT[],
    skills_aptitudes        TEXT[],
    skills_soft             TEXT[],
    prompt_version          VARCHAR(50),
    collected_at             TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE (id_offer)                   -- ajouté : nécessaire pour ON CONFLICT (id_offer)
);

-- ============================================================
-- 6. prompt_relevancy — versionnement des prompts de scoring
-- ============================================================
DROP TABLE IF EXISTS analytics.prompt_relevancy CASCADE;

CREATE TABLE analytics.prompt_relevancy (
    id_prompt       SERIAL          PRIMARY KEY,
    id_user         VARCHAR         NOT NULL DEFAULT 'default',
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
    score_relevancy FLOAT,
    score_job       FLOAT,
    score_skills    FLOAT,
    score_location  FLOAT,
    score_language  FLOAT,
    score_seniority FLOAT,
    score_work_mode FLOAT,
    score_company   FLOAT,
    explanation     TEXT,
    collected_at    TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE (id_offer)                   -- ajouté : nécessaire pour ON CONFLICT (id_offer)
);

-- ============================================================
-- Index : To lookup fast into database to match an offer with an already registered company
-- ============================================================
CREATE INDEX idx_company_location_lookup
    ON analytics.company_location(id_company, city, country);

CREATE INDEX idx_company_name 
    ON analytics.company(company_name);