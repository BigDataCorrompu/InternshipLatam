INSERT INTO analytics.company_contact (id_company, id_location, email, confidence, explanation, source, collected_at)
SELECT DISTINCT ON (email)
    se.id_company,
    se.id_location,
    (contact->>'email')::TEXT AS email,
    (contact->>'score')::FLOAT,
    contact->>'reason',
    contact->>'source',
    se.collected_at
FROM staging.company_emails se,
     jsonb_array_elements(se.raw_result) AS contact
WHERE contact->>'email' IS NOT NULL
    AND contact->>'email' ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'
ORDER BY email, (contact->>'score')::FLOAT DESC, se.collected_at DESC
ON CONFLICT (email) DO UPDATE
    SET id_company = EXCLUDED.id_company,
        id_location = EXCLUDED.id_location,
        confidence = EXCLUDED.confidence,
        explanation = EXCLUDED.explanation,
        source = EXCLUDED.source,
        collected_at = EXCLUDED.collected_at
    WHERE EXCLUDED.confidence > analytics.company_contact.confidence
RETURNING id_contact, email