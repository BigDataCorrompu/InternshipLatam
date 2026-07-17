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
    ARRAY(SELECT jsonb_array_elements_text(s.raw_result->'related_job_titles'))
FROM staging.enriched_offers s
JOIN analytics.job_offer o ON o.id_offer = s.id_offer
ON CONFLICT (id_offer) DO UPDATE SET
    (seniority, offer_languages, skills_languages, skills_frameworks, skills_aptitudes, skills_soft, alternative_job_titles) = 
    (EXCLUDED.seniority, EXCLUDED.offer_languages, EXCLUDED.skills_languages, EXCLUDED.skills_frameworks, EXCLUDED.skills_aptitudes, EXCLUDED.skills_soft, EXCLUDED.alternative_job_titles);
