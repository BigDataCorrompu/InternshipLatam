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
),

matched AS (
    SELECT
        i.raw_company_name,
        i.website,
        i.primary_type,
        i.geo_source,
        c.id_company AS existing_id_company
    FROM incoming i
    LEFT JOIN analytics.company c
        ON c.company_name = i.raw_company_name
        OR i.raw_company_name = ANY(c.raw_names)
)


INSERT INTO analytics.company (company_name, raw_names, website, primary_type)
SELECT
    m.raw_company_name,
    ARRAY[m.raw_company_name],
    m.website,
    m.primary_type
FROM matched m
WHERE m.existing_id_company IS NULL
ON CONFLICT (company_name) DO NOTHING;


UPDATE analytics.company c
SET
    raw_names = CASE
        WHEN m.raw_company_name = ANY(c.raw_names) THEN c.raw_names
        ELSE array_append(c.raw_names, m.raw_company_name)
    END,
    company_name = CASE
        WHEN m.geo_source = 'find_place' AND m.raw_company_name IS NOT NULL
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
FROM matched m
WHERE m.existing_id_company = c.id_company;