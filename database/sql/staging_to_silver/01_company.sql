INSERT INTO analytics.company (company_name, website, primary_type)
SELECT DISTINCT ON (s.raw_result->>'company_name')
    s.raw_result->>'company_name',
    s.raw_result->>'company_website',
    s.raw_result->>'company_primary_type'
FROM staging.enriched_offers s
LEFT JOIN analytics.job_offer o ON o.id_offer = s.id_offer
WHERE s.raw_result->>'company_name' IS NOT NULL
  AND s.raw_result->>'company_name' NOT IN ('null', '', 'Empresa confidencial')
ON CONFLICT (company_name) DO UPDATE SET
    (website, primary_type) = (EXCLUDED.website, EXCLUDED.primary_type);
