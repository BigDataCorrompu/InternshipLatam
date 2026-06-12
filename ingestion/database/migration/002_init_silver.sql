-- _______ Create Schema _______
CREATE SCHEMA IF NOT EXISTS analytics;

-- _______ Clean up existing tables to ensure a fresh state _______ 
DROP TABLE IF EXISTS analytics.job_offer;

-- _______ Create structural tables _______
-- On copie la structure de la table raw
CREATE TABLE analytics.job_offer (LIKE raw.job_offer INCLUDING ALL);

-- _______ Add constraint _______
-- 1. On s'assure que id_job ne peut pas être null pour devenir une clé primaire
ALTER TABLE analytics.job_offer ALTER COLUMN id_job SET NOT NULL;

-- 2. On ajoute la clé primaire sur id_job pour garantir l'unicité en Silver
ALTER TABLE analytics.job_offer ADD CONSTRAINT job_offer_silver_pkey PRIMARY KEY (id_job);