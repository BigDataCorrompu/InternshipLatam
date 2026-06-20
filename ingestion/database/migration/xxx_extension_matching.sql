-- 1. Activez l'extension (à faire une seule fois)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. La requête pour trouver l'ID le plus probable
-- SELECT id, nom_entreprise, similarity(nom_entreprise, 'TOTAL ENERGIES SA') AS score
-- FROM entreprises
-- WHERE similarity(nom_entreprise, 'TOTAL ENERGIES SA') > 0.3 -- Seuil minimal de tolérance
-- ORDER BY score DESC
-- LIMIT 1; -- Retourne uniquement le meilleur match
