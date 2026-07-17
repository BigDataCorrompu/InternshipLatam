INSERT INTO analytics.company_location
    (id_company, address, city, country, lat, lon, phone, business_status)
SELECT DISTINCT ON (c.id_company, s.raw_result->>'city', s.raw_result->>'country')
    c.id_company,
    s.raw_result->>'address',
    s.raw_result->>'city',
    s.raw_result->>'country',
    (s.raw_result->>'lat')::float,
    (s.raw_result->>'lon')::float,
    s.raw_result->>'phone',
    s.raw_result->>'business_status'
FROM staging.enriched_offers s
JOIN analytics.company c ON c.company_name = s.raw_result->>'company_name'
WHERE s.raw_result->>'city' IS NOT NULL
  AND s.raw_result->>'company_name' NOT IN ('null', '', 'Empresa confidencial')
ON CONFLICT (id_company, city, country) DO UPDATE SET
    (address, lat, lon, phone, business_status) = 
    (EXCLUDED.address, EXCLUDED.lat, EXCLUDED.lon, EXCLUDED.phone, EXCLUDED.business_status);
