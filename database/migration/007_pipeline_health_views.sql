-- ============================================================================
-- InternshipLatam — GOLD / SERVING layer: pipeline observability views
-- ----------------------------------------------------------------------------
-- Every view is preceded by DROP VIEW IF EXISTS so the whole file stays
-- re-runnable even when a view's column list changes (CREATE OR REPLACE alone
-- refuses any rename / reorder — SQLSTATE 42P16).
-- "Refreshing the views" = re-running this file.
--
-- The views are NOT materialized (recomputed on every SELECT).
-- Rationale: ~2k offers today, aggregation is instantaneous.
-- See the MATERIALIZATION section at the bottom if volume grows.
--
-- Sources: raw.job_offer, staging.enriched_offers,
--          analytics.{company, company_location, job_offer, job_requirement,
--                     job_relevancy},
--          ingestion tracking table (schema auto-detected: raw or landing)
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS serving;


-- ============================================================================
-- 1. PIPELINE FUNNEL — volume per stage, backlog vs permanently unusable
--    Single row, rendered as KPI cards at the top of the page.
-- ============================================================================
DROP VIEW IF EXISTS serving.pipeline_funnel;
CREATE VIEW serving.pipeline_funnel AS
WITH staging_state AS (
    SELECT
        s.id_offer,
        (o.id_offer IS NULL)                                   AS not_in_silver,
        (s.raw_result->>'company_name' IS NULL
         OR s.raw_result->>'company_name'
            IN ('', 'null', 'Empresa confidencial'))           AS no_company
    FROM staging.enriched_offers s
    LEFT JOIN analytics.job_offer o ON o.id_offer = s.id_offer
)
SELECT
    (SELECT COUNT(*) FROM raw.job_offer)                        AS bronze_total,
    (SELECT COUNT(*) FROM staging.enriched_offers)              AS staging_total,
    (SELECT COUNT(*) FROM analytics.job_offer)                  AS silver_total,
    (SELECT COUNT(*) FROM analytics.company)                    AS companies_total,

    -- Real backlog: bronze rows not enriched yet (DAG needs to run)
    (SELECT COUNT(*)
       FROM raw.job_offer b
       LEFT JOIN staging.enriched_offers s ON s.id_offer = b.id_job
      WHERE s.id_offer IS NULL)                                 AS pending_enrichment,

    -- Real backlog: enriched AND usable, but not transferred to Silver yet
    (SELECT COUNT(*) FROM staging_state
      WHERE not_in_silver AND NOT no_company)                   AS pending_silver,

    -- Permanently unusable: no employer identified, will NEVER reach Silver
    (SELECT COUNT(*) FROM staging_state
      WHERE not_in_silver AND no_company)                       AS unusable_no_company,

    -- Theoretical usable base (bronze minus known unusable rows)
    (SELECT COUNT(*) FROM raw.job_offer)
      - (SELECT COUNT(*) FROM staging_state WHERE no_company)   AS usable_base,

    -- Raw conversion rate: Silver / Bronze
    ROUND(100.0 * (SELECT COUNT(*) FROM analytics.job_offer)
                / NULLIF((SELECT COUNT(*) FROM raw.job_offer), 0), 1)
                                                                AS conversion_pct,

    -- Adjusted rate: Silver / (Bronze - unusable) => true transfer health
    ROUND(100.0 * (SELECT COUNT(*) FROM analytics.job_offer)
                / NULLIF((SELECT COUNT(*) FROM raw.job_offer)
                         - (SELECT COUNT(*) FROM staging_state WHERE no_company), 0), 1)
                                                                AS transfer_health_pct;


-- ============================================================================
-- 2. QUERY PERFORMANCE — yield per API call configuration
--    One row per distinct query_parameters JSON, so each row maps exactly to
--    one real API call config. This is THE view used to tune search configs.
-- ============================================================================
DROP VIEW IF EXISTS serving.query_optimization;   -- previous name, cleanup
DROP VIEW IF EXISTS serving.query_performance;
CREATE VIEW serving.query_performance AS
WITH base AS (
    SELECT
        b.api_source,
        b.query_parameters                                   AS params_json,
        COALESCE(b.query_parameters->>'keywords',
                 b.query_parameters->>'query')               AS keywords,
        COALESCE(b.query_parameters->>'location',
                 b.query_parameters->>'country')             AS location,
        o.id_offer,
        jreq.seniority,
        jreq.offer_languages,
        jr.score_relevancy
    FROM raw.job_offer b
    JOIN analytics.job_offer o               ON o.id_offer    = b.id_job
    LEFT JOIN analytics.job_requirement jreq ON jreq.id_offer = o.id_offer
    LEFT JOIN analytics.job_relevancy  jr    ON jr.id_offer   = o.id_offer
    WHERE b.query_parameters IS NOT NULL
),
lang_counts AS (
    SELECT
        params_json,
        COUNT(*) FILTER (WHERE lang = 'es')  AS n_es,
        COUNT(*) FILTER (WHERE lang = 'en')  AS n_en,
        COUNT(*) FILTER (WHERE lang = 'pt')  AS n_pt,
        COUNT(*)                             AS n_lang_total
    FROM base
    CROSS JOIN LATERAL unnest(COALESCE(offer_languages, ARRAY[]::text[])) AS lang
    GROUP BY params_json
),
offer_stats AS (
    SELECT
        params_json,
        MIN(api_source)                                                 AS api_source,
        MIN(keywords)                                                   AS keywords,
        MIN(location)                                                   AS location,
        COUNT(DISTINCT id_offer)                                        AS nb_offers,
        ROUND(AVG(score_relevancy)::numeric, 2)                         AS avg_score,
        ROUND(MAX(score_relevancy)::numeric, 2)                         AS max_score,
        COUNT(DISTINCT id_offer) FILTER (WHERE score_relevancy >= 6)    AS nb_relevant,
        COUNT(DISTINCT id_offer) FILTER (WHERE seniority = 'junior')    AS n_junior,
        COUNT(DISTINCT id_offer) FILTER (WHERE seniority = 'mid')       AS n_mid,
        COUNT(DISTINCT id_offer) FILTER (WHERE seniority = 'senior')    AS n_senior,
        COUNT(DISTINCT id_offer) FILTER (WHERE seniority = 'unknown'
                                            OR seniority IS NULL)       AS n_seniority_unknown
    FROM base
    GROUP BY params_json
)
SELECT
    os.params_json,
    os.params_json::text                                        AS params_text,
    os.api_source,
    os.keywords,
    os.location,
    os.nb_offers,
    os.nb_relevant,
    ROUND(100.0 * os.nb_relevant / NULLIF(os.nb_offers, 0), 1)  AS pct_relevant,
    os.avg_score,
    os.max_score,

    ROUND(100.0 * lc.n_es / NULLIF(lc.n_lang_total, 0), 1)      AS pct_spanish,
    ROUND(100.0 * lc.n_en / NULLIF(lc.n_lang_total, 0), 1)      AS pct_english,
    ROUND(100.0 * lc.n_pt / NULLIF(lc.n_lang_total, 0), 1)      AS pct_portuguese,

    os.n_junior, os.n_mid, os.n_senior, os.n_seniority_unknown,
    ROUND(100.0 * os.n_junior            / NULLIF(os.nb_offers, 0), 1) AS pct_junior,
    ROUND(100.0 * os.n_mid               / NULLIF(os.nb_offers, 0), 1) AS pct_mid,
    ROUND(100.0 * os.n_senior            / NULLIF(os.nb_offers, 0), 1) AS pct_senior,
    ROUND(100.0 * os.n_seniority_unknown / NULLIF(os.nb_offers, 0), 1) AS pct_seniority_unknown
FROM offer_stats os
LEFT JOIN lang_counts lc ON lc.params_json = os.params_json
ORDER BY pct_relevant DESC NULLS LAST, os.nb_offers DESC;


-- ============================================================================
-- 3. VOLUME OVER TIME — collected vs enriched vs transferred, per day
--    Reveals ingestion gaps and enrichment catch-up.
--    Explicit ::bigint casts keep column types homogeneous for the HTTP driver.
-- ============================================================================
DROP VIEW IF EXISTS serving.volume_over_time;
CREATE VIEW serving.volume_over_time AS
WITH days AS (
    SELECT DISTINCT DATE(collected_at) AS day FROM raw.job_offer
    UNION
    SELECT DISTINCT DATE(collected_at) AS day FROM staging.enriched_offers
    UNION
    SELECT DISTINCT DATE(collected_at) AS day FROM analytics.job_offer
),
collected AS (
    SELECT DATE(collected_at) AS day, api_source, COUNT(*) AS n
    FROM raw.job_offer GROUP BY 1, 2
),
enriched AS (
    SELECT DATE(collected_at) AS day, COUNT(*) AS n
    FROM staging.enriched_offers GROUP BY 1
),
loaded_silver AS (
    SELECT DATE(collected_at) AS day, COUNT(*) AS n
    FROM analytics.job_offer GROUP BY 1
)
SELECT
    d.day,
    COALESCE(SUM(c.n), 0)::bigint                                          AS offers_collected,
    COALESCE(SUM(c.n) FILTER (WHERE c.api_source = 'careerjet'), 0)::bigint AS collected_careerjet,
    COALESCE(SUM(c.n) FILTER (WHERE c.api_source = 'jsearch'), 0)::bigint   AS collected_jsearch,
    COALESCE(MAX(e.n), 0)::bigint                                          AS offers_enriched,
    COALESCE(MAX(ls.n), 0)::bigint                                         AS offers_in_silver
FROM days d
LEFT JOIN collected     c  ON c.day  = d.day
LEFT JOIN enriched      e  ON e.day  = d.day
LEFT JOIN loaded_silver ls ON ls.day = d.day
GROUP BY d.day
ORDER BY d.day;


-- ============================================================================
-- 4. COMPANY RECOVERY — real contribution of the extract_company LLM node
--    How many offers arrive without an employer, and how many the LLM
--    recovered from the job description itself.
-- ============================================================================
DROP VIEW IF EXISTS serving.company_recovery;
CREATE VIEW serving.company_recovery AS
SELECT
    COUNT(*)                                                         AS enriched_total,
    COUNT(*) FILTER (WHERE b.company IS NULL OR b.company = '')      AS bronze_company_null,
    COUNT(*) FILTER (
        WHERE (b.company IS NULL OR b.company = '')
          AND s.raw_result->>'company_name' IS NOT NULL
          AND s.raw_result->>'company_name' NOT IN ('', 'null', 'Empresa confidencial')
    )                                                                AS recovered_by_llm,
    COUNT(*) FILTER (
        WHERE (b.company IS NULL OR b.company = '')
          AND (s.raw_result->>'company_name' IS NULL
               OR s.raw_result->>'company_name' IN ('', 'null', 'Empresa confidencial'))
    )                                                                AS still_unresolved,
    ROUND(100.0 * COUNT(*) FILTER (
        WHERE (b.company IS NULL OR b.company = '')
          AND s.raw_result->>'company_name' IS NOT NULL
          AND s.raw_result->>'company_name' NOT IN ('', 'null', 'Empresa confidencial')
    ) / NULLIF(COUNT(*) FILTER (WHERE b.company IS NULL OR b.company = ''), 0), 1)
                                                                     AS recovery_rate_pct
FROM raw.job_offer b
JOIN staging.enriched_offers s ON s.id_offer = b.id_job;


-- ============================================================================
-- 4b. COMPANY RECOVERY DETAIL — the actual names the LLM recovered
-- ============================================================================
DROP VIEW IF EXISTS serving.company_recovery_detail;
CREATE VIEW serving.company_recovery_detail AS
SELECT
    s.raw_result->>'company_name'  AS company_name,
    COUNT(*)                       AS nb_offers,
    MIN(b.api_source)              AS api_source
FROM raw.job_offer b
JOIN staging.enriched_offers s ON s.id_offer = b.id_job
WHERE (b.company IS NULL OR b.company = '')
  AND s.raw_result->>'company_name' IS NOT NULL
  AND s.raw_result->>'company_name' NOT IN ('', 'null', 'Empresa confidencial')
GROUP BY 1
ORDER BY nb_offers DESC, company_name;


-- ============================================================================
-- 5. SKILLS EXTRACTION — keyword volume produced by the LLM
-- ============================================================================
DROP VIEW IF EXISTS serving.skills_extraction_volume;
CREATE VIEW serving.skills_extraction_volume AS
SELECT 'programming languages'::text AS skill_type,
       COUNT(DISTINCT skill)::bigint AS distinct_skills,
       COUNT(*)::bigint              AS total_mentions
FROM analytics.job_requirement,
     unnest(COALESCE(skills_languages, ARRAY[]::text[])) AS skill
UNION ALL
SELECT 'frameworks', COUNT(DISTINCT skill)::bigint, COUNT(*)::bigint
FROM analytics.job_requirement,
     unnest(COALESCE(skills_frameworks, ARRAY[]::text[])) AS skill
UNION ALL
SELECT 'aptitudes', COUNT(DISTINCT skill)::bigint, COUNT(*)::bigint
FROM analytics.job_requirement,
     unnest(COALESCE(skills_aptitudes, ARRAY[]::text[])) AS skill
UNION ALL
SELECT 'soft skills', COUNT(DISTINCT skill)::bigint, COUNT(*)::bigint
FROM analytics.job_requirement,
     unnest(COALESCE(skills_soft, ARRAY[]::text[])) AS skill
UNION ALL
SELECT 'related job titles', COUNT(DISTINCT skill)::bigint, COUNT(*)::bigint
FROM analytics.job_requirement,
     unnest(COALESCE(alternative_job_titles, ARRAY[]::text[])) AS skill;


-- ============================================================================
-- 5b. TOP SKILLS — most frequent technical keywords
-- ============================================================================
DROP VIEW IF EXISTS serving.top_skills;
CREATE VIEW serving.top_skills AS
SELECT skill, skill_type, COUNT(*)::bigint AS nb_mentions
FROM (
    SELECT unnest(COALESCE(skills_languages, ARRAY[]::text[])) AS skill,
           'programming language'::text AS skill_type
    FROM analytics.job_requirement
    UNION ALL
    SELECT unnest(COALESCE(skills_frameworks, ARRAY[]::text[])), 'framework'
    FROM analytics.job_requirement
    UNION ALL
    SELECT unnest(COALESCE(skills_aptitudes, ARRAY[]::text[])), 'aptitude'
    FROM analytics.job_requirement
    UNION ALL
    SELECT unnest(COALESCE(skills_soft, ARRAY[]::text[])), 'soft skill'
    FROM analytics.job_requirement
    UNION ALL
    SELECT unnest(COALESCE(alternative_job_titles, ARRAY[]::text[])), 'related job title'
    FROM analytics.job_requirement
) t
WHERE skill IS NOT NULL AND btrim(skill) <> ''
GROUP BY skill, skill_type
ORDER BY nb_mentions DESC;


-- ============================================================================
-- 6. INGESTION FRESHNESS — "a source stopped delivering" alert
--    The tracking table lives in raw.* or landing.* depending on which
--    migration was applied — detected at creation time.
-- ============================================================================
DROP VIEW IF EXISTS serving.ingestion_freshness;

DO $do$
DECLARE
    tracking_table TEXT;
BEGIN
    SELECT format('%I.%I', table_schema, table_name)
      INTO tracking_table
      FROM information_schema.tables
     WHERE table_name = 'ingestion_tracking'
       AND table_schema IN ('raw', 'landing')
     ORDER BY CASE table_schema WHEN 'raw' THEN 1 ELSE 2 END
     LIMIT 1;

    IF tracking_table IS NULL THEN
        RAISE NOTICE 'ingestion_tracking not found in raw/landing — serving.ingestion_freshness skipped';
        RETURN;
    END IF;

    EXECUTE format($view$
        CREATE VIEW serving.ingestion_freshness AS
        SELECT
            source,
            status,
            COUNT(*)::bigint       AS nb_files,
            SUM(record_count)      AS total_records,
            MAX(loaded_at)         AS last_load,
            NOW() - MAX(loaded_at) AS time_since_last_load,
            CASE
                WHEN NOW() - MAX(loaded_at) > INTERVAL '48 hours' THEN 'STALE'
                WHEN NOW() - MAX(loaded_at) > INTERVAL '26 hours' THEN 'WARN'
                ELSE 'OK'
            END                    AS freshness_status
        FROM %s
        GROUP BY source, status
        ORDER BY source, status
    $view$, tracking_table);

    RAISE NOTICE 'serving.ingestion_freshness created on %', tracking_table;
END
$do$;


-- ============================================================================
-- 7. ENRICHMENT QUALITY — field-level resolution rate, per LLM model
--    Lets you compare models / prompt versions over time.
--
--    NOTE: jsonb_array_length() raises on a scalar, and SQL does NOT guarantee
--    OR short-circuiting — the type check MUST be a CASE WHEN, which does
--    guarantee evaluation order.
-- ============================================================================
DROP VIEW IF EXISTS serving.enrichment_quality;
CREATE VIEW serving.enrichment_quality AS
SELECT
    COALESCE(llm_model, 'unknown')                                   AS llm_model,
    COUNT(*)::bigint                                                 AS total_enriched,

    COUNT(*) FILTER (WHERE raw_result->>'company_name' IS NOT NULL
                       AND raw_result->>'company_name'
                           NOT IN ('', 'null', 'Empresa confidencial'))::bigint
                                                                     AS company_found,
    COUNT(*) FILTER (WHERE raw_result->>'seniority' = 'unknown'
                        OR raw_result->>'seniority' IS NULL)::bigint AS seniority_unknown,
    COUNT(*) FILTER (WHERE raw_result->>'city' IS NOT NULL)::bigint   AS location_found,

    COUNT(*) FILTER (
        WHERE CASE
                WHEN jsonb_typeof(raw_result->'related_job_titles') = 'array'
                THEN jsonb_array_length(raw_result->'related_job_titles')
                ELSE 0
              END = 0
    )::bigint                                                        AS empty_job_titles,

    COUNT(*) FILTER (
        WHERE CASE
                WHEN jsonb_typeof(raw_result->'spoken_languages_required') = 'array'
                THEN jsonb_array_length(raw_result->'spoken_languages_required')
                ELSE 0
              END = 0
    )::bigint                                                        AS empty_languages,

    COUNT(*) FILTER (WHERE raw_result->>'score_relevancy' IS NULL)::bigint
                                                                     AS score_missing,

    ROUND(AVG(
        CASE WHEN raw_result->>'score_relevancy' ~ '^-?[0-9]+(\.[0-9]+)?$'
             THEN (raw_result->>'score_relevancy')::numeric END), 2) AS avg_score,
    MIN(collected_at)                                                AS first_run,
    MAX(collected_at)                                                AS last_run
FROM staging.enriched_offers
GROUP BY COALESCE(llm_model, 'unknown')
ORDER BY last_run DESC;


-- ============================================================================
-- 8. NOT TRANSFERRED — what stays in staging, and why
--    blocking_type separates a genuine processing backlog from rows that can
--    never be transferred.
-- ============================================================================
DROP VIEW IF EXISTS serving.blocked_offers;
CREATE VIEW serving.blocked_offers AS
SELECT
    CASE
        WHEN s.raw_result->>'company_name' IS NULL  THEN 'company_name is NULL'
        WHEN s.raw_result->>'company_name' = ''     THEN 'company_name is empty'
        WHEN s.raw_result->>'company_name' = 'null' THEN 'company_name = "null"'
        WHEN s.raw_result->>'company_name' = 'Empresa confidencial'
                                                    THEN 'Confidential employer'
        ELSE 'Awaiting transfer'
    END                             AS blocking_reason,
    CASE
        WHEN s.raw_result->>'company_name' IS NULL
          OR s.raw_result->>'company_name'
             IN ('', 'null', 'Empresa confidencial') THEN 'unusable'
        ELSE 'backlog'
    END                             AS blocking_type,
    COUNT(*)::bigint                AS nb_offers,
    MIN(s.collected_at)             AS oldest,
    MAX(s.collected_at)             AS newest
FROM staging.enriched_offers s
LEFT JOIN analytics.job_offer o ON o.id_offer = s.id_offer
WHERE o.id_offer IS NULL
GROUP BY 1, 2
ORDER BY nb_offers DESC;


-- ============================================================================
-- 9. GEOGRAPHIC COVERAGE — where the usable offers are
-- ============================================================================
DROP VIEW IF EXISTS serving.geographic_coverage;
CREATE VIEW serving.geographic_coverage AS
SELECT
    COALESCE(cl.country, 'unknown')                             AS country,
    COALESCE(cl.city, 'unknown')                                AS city,
    COUNT(*)::bigint                                            AS nb_offers,
    COUNT(DISTINCT jo.id_company)::bigint                       AS nb_companies,
    ROUND(AVG(jr.score_relevancy)::numeric, 2)                  AS avg_score,
    COUNT(*) FILTER (WHERE jr.score_relevancy >= 6)::bigint     AS nb_relevant
FROM analytics.job_offer jo
LEFT JOIN analytics.company_location cl ON cl.id_location = jo.id_location
LEFT JOIN analytics.job_relevancy jr    ON jr.id_offer    = jo.id_offer
GROUP BY 1, 2
ORDER BY nb_offers DESC;


-- ============================================================================
-- 10. DATA FINGERPRINT — lightweight signature for Streamlit cache busting
--     Deliberately minimal: this query must stay near-instant.
-- ============================================================================
DROP VIEW IF EXISTS serving.data_fingerprint;
CREATE VIEW serving.data_fingerprint AS
SELECT
    (SELECT COUNT(*)          FROM raw.job_offer)           AS bronze_count,
    (SELECT COUNT(*)          FROM staging.enriched_offers) AS staging_count,
    (SELECT COUNT(*)          FROM analytics.job_offer)     AS silver_count,
    (SELECT MAX(collected_at) FROM raw.job_offer)           AS last_bronze,
    (SELECT MAX(collected_at) FROM staging.enriched_offers) AS last_staging,
    (SELECT MAX(collected_at) FROM analytics.job_offer)     AS last_silver;


-- ============================================================================
-- MAINTENANCE FUNCTIONS
-- ----------------------------------------------------------------------------
-- The views above are NOT materialized: they always reflect current state, so
-- there is nothing to "refresh" in the strict sense. These functions exist to:
--   1) verify every view is queryable (schema health check)
--   2) give the update_views DAG a stable entry point if some views ever
--      become MATERIALIZED
-- ============================================================================

CREATE OR REPLACE FUNCTION serving.check_views()
RETURNS TABLE(view_name TEXT, row_count BIGINT, status TEXT) AS $fn$
DECLARE
    v TEXT;
    n BIGINT;
BEGIN
    FOR v IN
        SELECT table_name FROM information_schema.views
        WHERE table_schema = 'serving' ORDER BY table_name
    LOOP
        BEGIN
            EXECUTE format('SELECT COUNT(*) FROM serving.%I', v) INTO n;
            view_name := v; row_count := n; status := 'OK';
        EXCEPTION WHEN OTHERS THEN
            view_name := v; row_count := NULL; status := 'ERROR: ' || SQLERRM;
        END;
        RETURN NEXT;
    END LOOP;
END;
$fn$ LANGUAGE plpgsql;

-- Usage: SELECT * FROM serving.check_views();


CREATE OR REPLACE FUNCTION serving.refresh_all_materialized()
RETURNS TABLE(view_name TEXT, status TEXT) AS $fn$
DECLARE
    v TEXT;
BEGIN
    FOR v IN
        SELECT matviewname FROM pg_matviews
        WHERE schemaname = 'serving' ORDER BY matviewname
    LOOP
        BEGIN
            EXECUTE format('REFRESH MATERIALIZED VIEW serving.%I', v);
            view_name := v; status := 'REFRESHED';
        EXCEPTION WHEN OTHERS THEN
            view_name := v; status := 'ERROR: ' || SQLERRM;
        END;
        RETURN NEXT;
    END LOOP;
END;
$fn$ LANGUAGE plpgsql;

-- Usage in the update_views DAG: SELECT * FROM serving.refresh_all_materialized();
-- No-op while no view is materialized — safe to call from day one.


-- ============================================================================
-- MATERIALIZATION (only if volume makes the views slow)
-- ----------------------------------------------------------------------------
-- Example for query_performance, the most expensive one (double aggregation
-- plus an unnest):
--
--   DROP VIEW IF EXISTS serving.query_performance;
--   CREATE MATERIALIZED VIEW serving.query_performance AS <same SELECT>;
--   CREATE UNIQUE INDEX ON serving.query_performance (params_json);
--
-- The UNIQUE index enables REFRESH ... CONCURRENTLY (no read lock).
-- serving.refresh_all_materialized() then picks it up automatically.
-- ============================================================================