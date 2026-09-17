-- ============================================================
-- Migration : suivi des candidatures automatisées + blacklist
-- Schéma analytics — InternshipLatam
-- ============================================================

-- ============================================================
-- 1. tracking_application — une ligne par candidature envoyée
-- ============================================================
DROP TABLE IF EXISTS analytics.tracking_application CASCADE;

CREATE TABLE analytics.tracking_application (
    id_tracking     SERIAL          PRIMARY KEY,
    id_offer        TEXT            NOT NULL REFERENCES analytics.job_offer(id_offer),
    id_location     INT             REFERENCES analytics.company_location(id_location),
    id_company      INT             NOT NULL REFERENCES analytics.company(id_company),
    id_contact      INT             NOT NULL REFERENCES analytics.company_contact(id_contact),
    date            TIMESTAMPTZ     DEFAULT NOW(),

    -- Un seul envoi par (offre, contact) : empêche de renvoyer au même
    -- contact pour la même offre si le DAG est rejoué ou retry.
    UNIQUE (id_offer, id_contact)
);

CREATE INDEX IF NOT EXISTS idx_tracking_application_offer
    ON analytics.tracking_application(id_offer);

-- ============================================================
-- Migration : tracking_application sans contrainte UNIQUE,
-- + colonne b2_key pour retrouver le JSON archivé en bucket.
--
-- Retrait de UNIQUE(id_offer, id_contact) : un même contact peut
-- recevoir plusieurs emails pour la même offre (relances successives),
-- chaque envoi doit être tracké comme une ligne distincte.
--
-- ⚠️ Conséquence à connaître : la logique de relance
-- (fetch_next_candidates / QUERY_FETCH_REMINDER) compte times_sent
-- via COUNT(*) GROUP BY id_offer pour décider du prochain contact
-- (contact_rank = times_sent + 1). Sans UNIQUE, un retry Airflow qui
-- réinsère une ligne pour le même (id_offer, id_contact) ferait
-- gonfler times_sent et pourrait sauter un contact dans l'ordre. Le
-- bulk_insert reste idempotent côté fichiers (généré une fois par
-- offer_id_id_contact.json), mais la DB elle-même n'empêche plus le
-- doublon exact — à surveiller si des retries de la tâche archive
-- deviennent fréquents.
-- ============================================================

DROP TABLE IF EXISTS analytics.tracking_application CASCADE;

CREATE TABLE analytics.tracking_application (
    id_tracking     SERIAL          PRIMARY KEY,
    id_offer        TEXT            NOT NULL REFERENCES analytics.job_offer(id_offer),
    id_location     INT             REFERENCES analytics.company_location(id_location),
    id_company      INT             NOT NULL REFERENCES analytics.company(id_company),
    id_contact      INT             NOT NULL REFERENCES analytics.company_contact(id_contact),
    b2_key          TEXT,
    date            TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tracking_application_offer
    ON analytics.tracking_application(id_offer);

CREATE INDEX IF NOT EXISTS idx_tracking_application_contact
    ON analytics.tracking_application(id_contact);