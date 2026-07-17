INSERT INTO analytics.company_contact
    (id_company, id_location, email, confidence, explanation, source)
SELECT DISTINCT ON (ct->>'email')
    c.id_company,
    cl.id_location,
    ct->>'email',
    (ct->>'score')::float,
    ct->>'reason',
    'ddg_llm'
FROM staging.enriched_offers s
JOIN analytics.company c ON c.company_name = s.raw_result->>'company_name'
LEFT JOIN analytics.company_location cl ON cl.id_company = c.id_company 
    AND cl.city = s.raw_result->>'city' AND cl.country = s.raw_result->>'country'
CROSS JOIN LATERAL jsonb_array_elements(s.raw_result->'contacts') AS ct
WHERE ct->>'email' IS NOT NULL
ON CONFLICT (email) DO UPDATE SET
    (confidence, explanation) = (EXCLUDED.confidence, EXCLUDED.explanation);