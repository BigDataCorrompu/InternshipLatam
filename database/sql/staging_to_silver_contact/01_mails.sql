INSERT INTO silver.company_contacts (id_company, id_location, email, score, reason, source, found_at)
SELECT DISTINCT ON (id_company, email)
    se.id_company,
    se.id_location,
    (contact->>'email')::TEXT,
    (contact->>'score')::NUMERIC(3,2),
    contact->>'reason',
    contact->>'source',
    se.collected_at
FROM staging.company_emails se,
        jsonb_array_elements(se.raw_result) AS contact
ORDER BY id_company, email, (contact->>'score')::NUMERIC(3,2) DESC, se.collected_at DESC
ON CONFLICT (id_company, email) DO UPDATE
    SET score = EXCLUDED.score,
        reason = EXCLUDED.reason,
        source = EXCLUDED.source,
        found_at = EXCLUDED.found_at
    WHERE EXCLUDED.score > silver.company_contacts.score