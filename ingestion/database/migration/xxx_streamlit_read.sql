SELECT
    id_offer,
    api_source,
    job_title,
    contract_type,
    is_remote,
    offer_languages,
    seniority,
    (
        SELECT jsonb_agg(DISTINCT val)
        FROM (
            SELECT jsonb_array_elements_text(
                -- Utilisation de array_to_json() pour uniformiser les types en jsonb
                COALESCE(array_to_json(skills_languages)::jsonb, '[]'::jsonb) || 
                COALESCE(array_to_json(skills_frameworks)::jsonb, '[]'::jsonb) || 
                COALESCE(array_to_json(skills_aptitudes)::jsonb, '[]'::jsonb) || 
                COALESCE(array_to_json(skills_soft)::jsonb, '[]'::jsonb) ||
                COALESCE(array_to_json(alternative_job_titles)::jsonb, '[]'::jsonb)
            ) AS val
        ) sub
    ) AS all_skills,
    score_relevancy,
    explanation,
    company_name,
    website,
    primary_type,
    city,
    country,
    lat,
    lon,
    offer_url,
    published_at,
    collected_at
FROM serving.job_offer;
