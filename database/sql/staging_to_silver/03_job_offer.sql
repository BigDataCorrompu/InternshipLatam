INSERT INTO analytics.job_offer
    (id_offer, id_company, id_location, api_source, job_title, offer_description,
     contract_type, is_remote, job_publisher, location_raw, offer_url,
     source_platform, published_at, collected_at)
SELECT DISTINCT ON (LEFT(s.raw_result->>'offer_url', 500))
    s.id_offer,
    c.id_company,
    cl.id_location,
    LEFT(s.raw_result->>'api_source', 15),
    LEFT(s.raw_result->>'job_title', 150),
    s.raw_result->>'offer_description',
    LEFT(s.raw_result->>'contract_type', 20),
    (s.raw_result->>'is_remote')::boolean,
    LEFT(s.raw_result->>'job_publisher', 100),
    LEFT(s.raw_result->>'location_raw', 100),
    LEFT(s.raw_result->>'offer_url', 500),
    LEFT(s.raw_result->>'source_platform', 100),
    (s.raw_result->>'published_at')::timestamptz,
    (s.raw_result->>'collected_at')::timestamptz
FROM staging.enriched_offers s
JOIN analytics.company c ON c.company_name = s.raw_result->>'company_name'
LEFT JOIN analytics.company_location cl ON cl.id_company = c.id_company 
    AND cl.city = s.raw_result->>'city' AND cl.country = s.raw_result->>'country'
WHERE s.raw_result->>'company_name' NOT IN ('null', '', 'Empresa confidencial')
ORDER BY LEFT(s.raw_result->>'offer_url', 500), s.collected_at DESC
ON CONFLICT (id_offer) DO NOTHING;