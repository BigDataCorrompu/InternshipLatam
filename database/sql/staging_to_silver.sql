-- ============================================================
-- STAGING → SILVER : transfert in-database (IDEMPOTENT)
-- ============================================================

-- ─── 1. COMPANIES ───────────────────────────────────────────
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


-- ─── 2. LOCATIONS ───────────────────────────────────────────
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


-- ─── 3. JOB OFFERS ──────────────────────────────────────────
INSERT INTO analytics.job_offer
    (id_offer, id_company, id_location, api_source, job_title, offer_description,
     contract_type, is_remote, job_publisher, location_raw, offer_url,
     source_platform, published_at, collected_at)
SELECT
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
ON CONFLICT (id_offer) DO NOTHING;


-- ─── 4. REQUIREMENTS ────────────────────────────────────────
INSERT INTO analytics.job_requirement
    (id_offer, seniority, offer_languages, skills_languages, skills_frameworks,
     skills_aptitudes, skills_soft, alternative_job_titles)
SELECT
    o.id_offer,
    LEFT(s.raw_result->>'seniority', 20),
    ARRAY(SELECT jsonb_array_elements_text(s.raw_result->'spoken_languages_required')),
    ARRAY(SELECT jsonb_array_elements_text(s.raw_result->'skills_languages')),
    ARRAY(SELECT jsonb_array_elements_text(s.raw_result->'skills_framework')),
    ARRAY(SELECT jsonb_array_elements_text(s.raw_result->'skills_aptitudes')),
    ARRAY(SELECT jsonb_array_elements_text(s.raw_result->'skills_soft')),
    ARRAY(SELECT jsonb_array_elements_text(s.raw_result->'related_job_titles')),
FROM staging.enriched_offers s
JOIN analytics.job_offer o ON o.id_offer = s.id_offer
ON CONFLICT (id_offer) DO UPDATE SET
    (seniority, offer_languages, skills_languages, skills_frameworks, skills_aptitudes, skills_soft, alternative_job_titles) = 
    (EXCLUDED.seniority, EXCLUDED.offer_languages, EXCLUDED.skills_languages, EXCLUDED.skills_frameworks, EXCLUDED.skills_aptitudes, EXCLUDED.skills_soft, EXCLUDED.alternative_job_titles);


-- ─── 5. RELEVANCY ───────────────────────────────────────────
INSERT INTO analytics.job_relevancy
    (id_offer, id_prompt, score_relevancy, score_job, score_skills, score_location,
     score_language, score_seniority, score_work_mode, score_company, explanation)
SELECT
    o.id_offer,
    (s.raw_result->>'id_prompt')::int,
    (s.raw_result->>'score_relevancy')::float,
    (s.raw_result->'score_details'->>'score_job')::float,
    (s.raw_result->'score_details'->>'score_skills')::float,
    (s.raw_result->'score_details'->>'score_location')::float,
    (s.raw_result->'score_details'->>'score_language')::float,
    (s.raw_result->'score_details'->>'score_seniority')::float,
    (s.raw_result->'score_details'->>'score_work_mode')::float,
    (s.raw_result->'score_details'->>'score_company')::float,
    s.raw_result->>'explanation'
FROM staging.enriched_offers s
JOIN analytics.job_offer o ON o.id_offer = s.id_offer
ON CONFLICT (id_offer) DO UPDATE SET
    (id_prompt, score_relevancy, score_job, score_skills, score_location, score_language, score_seniority, score_work_mode, score_company, explanation) =
    (EXCLUDED.id_prompt, EXCLUDED.score_relevancy, EXCLUDED.score_job, EXCLUDED.score_skills, EXCLUDED.score_location, EXCLUDED.score_language, EXCLUDED.score_seniority, EXCLUDED.score_work_mode, EXCLUDED.score_company, EXCLUDED.explanation);


-- ─── 6. CONTACTS ────────────────────────────────────────────
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