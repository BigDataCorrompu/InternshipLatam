INSERT INTO analytics.company (company_name, raw_names, website, primary_type)
SELECT DISTINCT ON (s.raw_result->>'company_name')
    s.raw_result->>'company_name',
    ARRAY[s.raw_result->>'company_name'],
    LEFT(s.raw_result->>'company_website', 500),
    s.raw_result->>'company_primary_type'
FROM staging.enriched_offers s
WHERE s.raw_result->>'company_name' IS NOT NULL
  AND s.raw_result->>'company_name' NOT IN ('null', '', 'Empresa confidencial')
ORDER BY s.raw_result->>'company_name',
         (s.raw_result->>'source' = 'find_place') DESC,
         s.collected_at DESC
ON CONFLICT (company_name) DO UPDATE SET
    website = CASE
        WHEN EXCLUDED.website IS NOT NULL THEN EXCLUDED.website
        ELSE analytics.company.website
    END,
    primary_type = CASE
        WHEN EXCLUDED.primary_type IS NOT NULL THEN EXCLUDED.primary_type
        ELSE analytics.company.primary_type
    END;