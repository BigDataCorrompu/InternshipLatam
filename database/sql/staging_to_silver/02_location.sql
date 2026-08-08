WITH incoming AS (
    SELECT DISTINCT ON (c.id_company, s.raw_result->>'city', s.raw_result->>'country')
        c.id_company,
        s.raw_result->>'address'                    AS address,
        s.raw_result->>'city'                        AS city,
        s.raw_result->>'country'                     AS country,
        (s.raw_result->>'lat')::float                AS lat,
        (s.raw_result->>'lon')::float                AS lon,
        s.raw_result->>'phone'                       AS phone,
        s.raw_result->>'business_status'             AS business_status,
        s.raw_result->>'source'                      AS geo_source
    FROM staging.enriched_offers s
    JOIN analytics.company c
        ON c.company_name = s.raw_result->>'company_name'
        OR s.raw_result->>'company_name' = ANY(c.raw_names)
    WHERE s.raw_result->>'city' IS NOT NULL
      AND s.raw_result->>'company_name' NOT IN ('null', '', 'Empresa confidencial')
    ORDER BY c.id_company, s.raw_result->>'city', s.raw_result->>'country',
             (s.raw_result->>'source' = 'find_place') DESC,
             s.collected_at DESC
)

INSERT INTO analytics.company_location
    (id_company, address, city, country, lat, lon, phone, business_status, source)
SELECT
    i.id_company, i.address, i.city, i.country, i.lat, i.lon, i.phone, i.business_status, i.geo_source
FROM incoming i
ON CONFLICT (id_company, city, country) DO UPDATE SET
    address = CASE
        WHEN (EXCLUDED.source = 'find_place'
              OR analytics.company_location.source IS DISTINCT FROM 'find_place')
             AND EXCLUDED.address IS NOT NULL
        THEN EXCLUDED.address
        ELSE analytics.company_location.address
    END,
    lat = CASE
        WHEN (EXCLUDED.source = 'find_place'
              OR analytics.company_location.source IS DISTINCT FROM 'find_place')
             AND EXCLUDED.lat IS NOT NULL
        THEN EXCLUDED.lat
        ELSE analytics.company_location.lat
    END,
    lon = CASE
        WHEN (EXCLUDED.source = 'find_place'
              OR analytics.company_location.source IS DISTINCT FROM 'find_place')
             AND EXCLUDED.lon IS NOT NULL
        THEN EXCLUDED.lon
        ELSE analytics.company_location.lon
    END,
    phone = CASE
        WHEN (EXCLUDED.source = 'find_place'
              OR analytics.company_location.source IS DISTINCT FROM 'find_place')
             AND EXCLUDED.phone IS NOT NULL
        THEN EXCLUDED.phone
        ELSE analytics.company_location.phone
    END,
    business_status = CASE
        WHEN (EXCLUDED.source = 'find_place'
              OR analytics.company_location.source IS DISTINCT FROM 'find_place')
             AND EXCLUDED.business_status IS NOT NULL
        THEN EXCLUDED.business_status
        ELSE analytics.company_location.business_status
    END,
    source = CASE
        WHEN EXCLUDED.source = 'find_place'
             OR analytics.company_location.source IS DISTINCT FROM 'find_place'
        THEN EXCLUDED.source
        ELSE analytics.company_location.source
    END;