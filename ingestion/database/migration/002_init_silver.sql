-- _______ Create Schema _______
CREATE SCHEMA IF NOT EXISTS analytics;

-- _______ Clean up existing tables to ensure a fresh state _______ 
DROP TABLE IF EXISTS analytics.job_offer;

-- _______ Create structural tables _______
CREATE TABLE analytics.job_offer (LIKE raw.job_offer INCLUDING ALL);

-- _______ Add constraint _______
ALTER TABLE IF EXISTS analytics.job_offer;