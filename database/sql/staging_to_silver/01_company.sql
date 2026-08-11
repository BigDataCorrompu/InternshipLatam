-- Table temporaire : le CTE "matched" doit etre calcule une seule fois
-- et reste visible pour l'INSERT ET l'UPDATE qui suivent (contrairement
-- a un WITH classique, qui n'est visible que pour la requete immediate).
DROP TABLE IF EXISTS tmp_matched_company;

CREATE TEMP TABLE tmp_matched_company AS
WITH incoming AS (
    SELECT DISTINCT ON (s.raw_result->>'company_name')
        s.raw_result->>'company_name'                 AS raw_company_name,
        LEFT(s.raw_result->>'company_website', 500)    AS website,
        s.raw_result->>'company_primary_type'          AS primary_type,
        s.raw_result->>'source'                        AS geo_source
    FROM staging.enriched_offers s
    LEFT JOIN analytics.job_offer o ON o.id_offer = s.id_offer
    WHERE s.raw_result->>'company_name' IS NOT NULL
      AND s.raw_result->>'company_name' NOT IN ('null', '', 'Empresa confidencial')
    ORDER BY s.raw_result->>'company_name',
             (s.raw_result->>'source' = 'find_place') DESC,
             s.collected_at DESC
)
SELECT
    i.raw_company_name,
    i.website,
    i.primary_type,
    i.geo_source,
    c.id_company AS existing_id_company
FROM incoming i
LEFT JOIN analytics.company c
    ON c.company_name = i.raw_company_name
    OR i.raw_company_name = ANY(c.raw_names);


-- 1. Nouvelle entreprise : aucun match trouve.
--    Le nom brut de l'offre devient le company_name initial ET la
--    premiere entree de raw_names (sera remplace par find_place plus
--    tard si une offre suffisamment pertinente le confirme).
INSERT INTO analytics.company (company_name, raw_names, website, primary_type)
SELECT
    m.raw_company_name,
    ARRAY[m.raw_company_name],
    m.website,
    m.primary_type
FROM tmp_matched_company m
WHERE m.existing_id_company IS NULL
ON CONFLICT (company_name) DO NOTHING;


-- 2. Entreprise deja connue :
--    - raw_names s'enrichit toujours du nom brut de cette offre (jamais retire)
--    - company_name / primary_type / website ecrases UNIQUEMENT si
--      cette offre vient de find_place, et JAMAIS par une valeur NULL,
--      et jamais vers un nom deja pris par une AUTRE entreprise.
UPDATE analytics.company c
SET
    raw_names = CASE
        WHEN m.raw_company_name = ANY(c.raw_names) THEN c.raw_names
        ELSE array_append(c.raw_names, m.raw_company_name)
    END,
    company_name = CASE
        WHEN m.geo_source = 'find_place'
             AND m.raw_company_name IS NOT NULL
             AND NOT EXISTS (
                 SELECT 1 FROM analytics.company c2
                 WHERE c2.company_name = m.raw_company_name
                   AND c2.id_company != c.id_company
             )
        THEN m.raw_company_name
        ELSE c.company_name
    END,
    website = CASE
        WHEN m.geo_source = 'find_place' AND m.website IS NOT NULL
        THEN m.website
        ELSE c.website
    END,
    primary_type = CASE
        WHEN m.geo_source = 'find_place' AND m.primary_type IS NOT NULL
        THEN m.primary_type
        ELSE c.primary_type
    END
FROM tmp_matched_company m
WHERE m.existing_id_company = c.id_company;

DROP TABLE tmp_matched_company;