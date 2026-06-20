
-- IMPORTANT Call this in streamlit
-- SELECT serving.refresh_job_offer_if_stale();


CREATE SCHEMA IF NOT EXISTS serving;

DROP MATERIALIZED VIEW IF EXISTS serving.job_offer;

CREATE MATERIALIZED VIEW serving.job_offer AS
SELECT
    jo.id_offer,
    jo.api_source,
    jo.job_title,
    jo.offer_description,
    jo.contract_type,
    jo.is_remote,

    jr.alternative_job_titles,
    jr.offer_languages,
    jr.seniority,
    jr.skills_languages,
    jr.skills_frameworks,
    jr.skills_aptitudes,
    jr.skills_soft,

    jrel.score_job,
    jrel.score_skills,
    jrel.score_language,
    jrel.score_seniority,
    jrel.score_work_mode,
    jrel.score_company,
    jrel.score_location,
    jrel.score_relevancy,
    jrel.explanation,

    c.company_name,
    c.website,
    c.primary_type,
    cl.address,
    cl.city,
    cl.country,
    cl.lat,
    cl.lon,
    cl.phone,
    cl.business_status,

    cc.company_mails,

    jo.job_publisher,
    jo.offer_url,
    jo.source_platform,
    jo.published_at,
    jo.collected_at

FROM analytics.job_offer jo

LEFT JOIN analytics.company c
    ON jo.id_company = c.id_company

LEFT JOIN analytics.company_location cl
    ON jo.id_location = cl.id_location

LEFT JOIN LATERAL (
    SELECT *
    FROM analytics.job_requirement
    WHERE id_offer = jo.id_offer
    ORDER BY collected_at DESC
    LIMIT 1
) jr ON TRUE

LEFT JOIN LATERAL (
    SELECT *
    FROM analytics.job_relevancy
    WHERE id_offer = jo.id_offer
    ORDER BY collected_at DESC
    LIMIT 1
) jrel ON TRUE

LEFT JOIN LATERAL (
    SELECT
        jsonb_agg(
            jsonb_build_object(
                'email', email,
                'confidence', confidence,
                'explanation', explanation
            )
            ORDER BY confidence DESC
        ) AS company_mails
    FROM analytics.company_contact
    WHERE id_location = jo.id_location
) cc ON TRUE;

CREATE UNIQUE INDEX idx_serving_job_offer_id ON serving.job_offer(id_offer);



-- Automaticaly update table
CREATE OR REPLACE FUNCTION serving.refresh_job_offer_if_stale()
RETURNS VOID AS $$
DECLARE
    last_collected TIMESTAMPTZ;
BEGIN
    SELECT MAX(collected_at) INTO last_collected
    FROM serving.job_offer;

    IF last_collected IS NULL OR (NOW() - last_collected) > INTERVAL '5 hours' THEN
        REFRESH MATERIALIZED VIEW CONCURRENTLY serving.job_offer;
    END IF;
END;
$$ LANGUAGE plpgsql;
