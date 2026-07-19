import json
import logging
from datetime import datetime 
from pathlib import Path
from database import Database
from bucket import Bucket
import langdetect
logger = logging.getLogger(__name__)


def write_json(filepath: str, filename: str, data: dict) -> None:
    """Write a dictionary to a JSON file.
    
    Args:
        filepath: Directory path where the file will be written.
        filename: Name of the JSON file.
        data: Dictionary to serialize.
    """
    path = (Path(filepath) / filename).with_suffix('.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f"[WRITE] file={filename} status=success")

def load_json(filepath: str, filename: str) -> dict:
    """Return a dictionary from a JSON file.
    
    Args:
        filepath: Directory path where the file is located.
        filename: Name of the JSON file.
        
    Returns:
        Dictionary parsed from the JSON file.
    """
    path = (Path(filepath) / filename).with_suffix('.json')
    if not path.exists():
        logger.warning(f"[READ] file={filename} status=not_found path={path}")
        return None
    json_text = path.read_text(encoding='utf-8')
    logger.info(f"[READ] file={filename} status=success")
    return json.loads(json_text)



# The function who saves the jsonfile to the datalake
def save_to_landing(
    source: str,
    directory: str,
    filename: str,
    db_config: dict,
):
    
    offers = load_json(directory, filename)
    
    if not offers:
        logger.warning(f"[LOAD] source={source} status=no_data")
        return 0
    

    rows = [
        (source, json.dumps(o.get("params", {})), json.dumps(o.get("data", [])))
        for o in offers
    ]

    db = Database(**db_config)
    db.bulk_insert(
        table="landing.raw_job_offers",
        columns=["source", "params", "data"],
        data=rows,
        batch_size=5000,
    )

    # Supprime le fichier JSON après insertion réussie
    json_path = Path(directory) / f"{filename}.json"
    if json_path.exists():
        json_path.unlink()
        logger.info(f"[CLEAN] file={json_path.name} status=deleted")
    
    logger.info(f"[LOAD] source={source} records={len(rows)} status=success")
    return len(rows)



def run_fetch(api_client, queries, params, source, extract_query: bool):
    all_responses = []
    for q in queries:
        if extract_query:
            q_copy = q.copy()
            query = q_copy.pop('query')
            config = params | q_copy
            jobs = api_client.search_jobs(query=query, paginate=True, **config)
            response_params = {'query': query} | config
        else:
            config = params | q
            jobs = api_client.search_jobs(paginate=True, **config)
            response_params = config
        all_responses.append({"params": response_params, "data": jobs})
        if api_client.quota_exceeded:
            logger.warning(f"[Extract] source={source} exhausted")
            break
    logger.info(f"[EXTRACT] source={source} records={len(jobs)}")
    return all_responses

def save_to_landing_bucket(
        bucket: Bucket,
        api_source: str, 
        local_file: str,
        data_type: str, # job_offer, company_info ...
        ds: str,
        ts_nodash: str,
    ) -> str:
    """
    Upload raw json file to b2 bucket using norm 'year/month/source/' + file_name
    Airflow ds (YYYY-MM-DD) is time base.
    Return bucket path (b2_key).
    """
    # Verification
    local_path_obj = Path(local_file)
    if not local_path_obj.exists():
        logger.warning(f"[LANDING] ⚠️ No local file to upload for {api_source} on {ds}. Skipping.")
        return None

    # ds = "2026-06-08" → year=2026, month=06
    dt = datetime.strptime(ds, '%Y-%m-%d')
    year = dt.year
    month = f"{dt.month:02d}"

    # Bucket path : data_type/year/month/api_source
    bucket_dir = f"{data_type}/{year}/{month}/{api_source}"

    # File name : {date}_{api_source}
    file_name = f"{ts_nodash}_{api_source}"

    # Paths
    path_bucket = str((Path(bucket_dir) / file_name).with_suffix('.json'))

    # Load in bucket
    bucket.upload_file(bucket_path=path_bucket, local_path=local_file)
    logger.info(f"[LANDING] file={file_name} status=uploaded bucket_path={path_bucket}")

    # Delete local file once it's in the bucket
    Path(local_file).unlink(missing_ok=True)
    logger.info(f"[CLEAN] file={local_file} status=deleted")

    return path_bucket


def normalise_list_language(liste_brute):
    """
    Normalise spanish, espanol in es
    And ignore what is not a language like C++
    """
    # Liste officielle de TOUS les codes ISO 639-1 valides sur Terre (2 lettres)
    # Permet de bloquer instantanément les faux positifs informatiques (ex: SQL -> sq)
    ISO_639_1_OFFICIEL = {
        "aa", "ab", "ae", "af", "ak", "am", "an", "ar", "as", "av", "ay", "az",
        "ba", "be", "bg", "bi", "bm", "bn", "bo", "br", "bs", "ca", "ce", "ch",
        "co", "cr", "cs", "cu", "cv", "cy", "da", "de", "dv", "dz", "ee", "el",
        "en", "eo", "es", "et", "eu", "fa", "ff", "fi", "fj", "fo", "fr", "fy",
        "ga", "gd", "gl", "gn", "gu", "gv", "ha", "he", "hi", "ho", "hr", "ht",
        "hu", "hy", "hz", "ia", "id", "ie", "ig", "ii", "ik", "io", "is", "it",
        "iu", "ja", "jv", "ka", "kg", "ki", "kj", "kk", "kl", "km", "kn", "ko",
        "kr", "ks", "kv", "kw", "ky", "la", "lb", "lg", "li", "ln", "lo", "lt",
        "lu", "lv", "mg", "mh", "mi", "mk", "ml", "mn", "mr", "ms", "mt", "my",
        "na", "nb", "nd", "ne", "ng", "nl", "nn", "no", "nr", "nv", "ny", "oc",
        "oj", "om", "or", "os", "pa", "pi", "pl", "ps", "pt", "qu", "rm", "rn",
        "ro", "ru", "rw", "sa", "sc", "sd", "se", "sg", "si", "sk", "sl", "sm",
        "sn", "so", "sq", "sr", "ss", "st", "su", "sv", "sw", "ta", "te", "tg",
        "th", "ti", "tk", "tl", "tn", "to", "tr", "ts", "tt", "tw", "ty", "ug",
        "uk", "ur", "uz", "ve", "vi", "vo", "wa", "wo", "xh", "yi", "yo", "za",
        "zh", "zu"
    }

    def normalise_word(texte):
        # 1. Nettoyage strict
        txt = str(texte).strip().lower()
        
        # 2. Élimination des valeurs inconnues ou trop courtes (C, C++, etc.)
        if txt in ["unknown", "none", "null", ""] or len(txt) < 2:
            return None
            
        # Exception manuelle pour bloquer les rares technos qui imitent des codes valides
        # ex: Python -> py (langue officielle féroïen), .NET -> ne (langue officielle népalais)
        if txt in ["python", ".net", "dotnet", "java", "sql"]:
            return None

        # 3. Si c'est déjà un code ISO valide à 2 lettres (ex: "es", "en")
        if len(txt) == 2 and txt in ISO_639_1_OFFICIEL:
            return txt
            
        # 4. Extraction des 2 premières lettres pour les mots longs
        code_graine = txt[:2]
        
        # Correction automatique pour les racines spécifiques
        if code_graine == "sp": 
            return "es"
        if code_graine == "po": 
            return "pt"
        if code_graine == "ge":
            return "de"
            
        # Sécurité : On valide que la racine extraite est une VRAIE langue humaine
        # Bloque définitivement SQL (sq), .NET (ne), HTML (ht), etc.
        if code_graine in ISO_639_1_OFFICIEL:
            return code_graine

        return None

    # Si l'entrée est du texte au lieu d'une liste (ex: "espanol, sql")
    if isinstance(liste_brute, str):
        liste_brute = [lang.strip() for lang in liste_brute.replace(",", " ").split()]
    elif not isinstance(liste_brute, list):
        return []

    # Application de la logique sur chaque élément de la liste
    resultat_clean = [normalise_word(item) for item in liste_brute]
    
    # Suppression des valeurs None et des doublons, puis conversion en liste
    return list(set(code for code in resultat_clean if code is not None))



def detect_language(text: str) -> str | None:
    """Détecte la langue sur l'ensemble des langues supportées, retourne un code ISO 639-1."""
    if not text or len(text.strip()) < 20:
        return None
    try:
        return langdetect.detect(text)
    except langdetect.LangDetectException:
        return None