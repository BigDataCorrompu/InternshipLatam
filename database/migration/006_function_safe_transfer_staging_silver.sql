CREATE SCHEMA IF NOT EXISTS public;

CREATE OR REPLACE FUNCTION public.ensure_jsonb_array(val jsonb)
RETURNS jsonb AS $$
BEGIN
  -- Si c'est null, renvoie un tableau vide
  IF val IS NULL THEN RETURN '[]'::jsonb; END IF;
  -- Si c'est déjà un tableau, le renvoie tel quel
  IF jsonb_typeof(val) = 'array' THEN RETURN val; END IF;
  -- Si c'est une string ou autre, le met dans un tableau
  RETURN jsonb_build_array(val);
END;
$$ LANGUAGE plpgsql IMMUTABLE;