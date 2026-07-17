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

