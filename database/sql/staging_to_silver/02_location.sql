INSERT INTO analytics.company_location
    (id_company, address, city, country, lat, lon, phone, business_status, source)
SELECT DISTINCT ON (c.id_company, s.raw_result->>'city', s.raw_result->>'country')
    c.id_company,
    s.raw_result->>'address',
    s.raw_result->>'city',
    s.raw_result->>'country',
    (s.raw_result->>'lat')::float,
    (s.raw_result->>'lon')::float,
    s.raw_result->>'phone',
    s.raw_result->>'business_status',
    s.raw_result->>'source'
FROM staging.enriched_offers s
JOIN analytics.company c ON c.company_name = s.raw_result->>'company_name'
WHERE s.raw_result->>'city' IS NOT NULL
  AND s.raw_result->>'company_name' NOT IN ('null', '', 'Empresa confidencial')
ON CONFLICT (id_company, city, country) DO UPDATE SET
    address         = EXCLUDED.address,
    lat             = EXCLUDED.lat,
    lon             = EXCLUDED.lon,
    phone           = EXCLUDED.phone,
    business_status = EXCLUDED.business_status,
    source          = EXCLUDED.source;