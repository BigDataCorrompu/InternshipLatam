-- ============================================================
-- 2. blacklist — contacts à ne plus jamais solliciter
--    (ex: demande d'exclusion via le formulaire dans l'email)
-- ============================================================
DROP TABLE IF EXISTS analytics.blacklist CASCADE;
 
CREATE TABLE analytics.blacklist (
    id_blacklist    SERIAL          PRIMARY KEY,
    email           VARCHAR(254)    NOT NULL,
    collected_at    TIMESTAMPTZ     DEFAULT NOW(),
 
    UNIQUE (email)
);
 
CREATE INDEX IF NOT EXISTS idx_blacklist_email
    ON analytics.blacklist(email);
 