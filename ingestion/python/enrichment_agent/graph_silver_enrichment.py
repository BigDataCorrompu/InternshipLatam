from silver_enrichment import *
from typing import Literal
from functools import partial
import os
import sys
sys.path.append("../src")
from APIendpoint import PlacesAPI
from LLMprovider import LLM
from utils import detect_language
llm = LLM()
placesAPI = PlacesAPI(os.getenv('MAPS_APP_KEY'))

# =========================== Company handle ===========================
class CompanyOutput(BaseModel):
    company_name: str | None = Field(
        description=(
            "Name of the FINAL HIRING company — the actual employer, not an intermediary. "
            "EXCLUDE recruitment agencies, staffing firms, job boards, or freelance platforms "
            "acting as intermediaries (e.g. Michael Page, LinkedIn, Jobgether, Mercor, Outlier AI, "
            "WomenTech Network, Talentfinder, generic job aggregators, Linkedin). "
            "If the offer is published BY an agency BUT clearly recruiting FOR a named client company, "
            "return the client's name, not the agency's. "
            "If only the agency/platform name is available and no final employer is mentioned, "
            "return null — do not return the agency name as if it were the employer. "
            "Do not invent or mistake a software/tool name for the company name."
        )
    )
    source_platform: str | None = Field(
        description=(
            "Name of the recruitment agency, staffing firm, job board, or freelance platform "
            "that published this offer, IF it acts as an intermediary (e.g. Michael Page, LinkedIn, "
            "Jobgether, Mercor, Outlier AI, WomenTech Network, Talentfinder). "
            "Return null if the offer was published directly by the final hiring company itself."
        )
    )

extract_company = Extract(
    llm=llm.enrichement,
    task=(
        "Find the name of the FINAL hiring company recruiting for this job offer — not a recruitment "
        "agency, job board, or freelance platform acting as an intermediary. If an agency published "
        "the offer but names a client company, return the client's name in company_name, and the "
        "agency's name in source_platform. "
        "The name must be explicitly mentioned in the text — do not invent it or mistake a software/tool name for it."
    ),
    output_key='company_name',
    schema=CompanyOutput,
    fields=['job_title', 'offer_description']
)

# =========================== Location handle ===========================
class LocationRawOutput(BaseModel):
    city: str | None = Field(
        description=(
            "The city where the company/position is located, if mentioned anywhere in the text "
            "(job_title, offer_description, or the existing location_raw/city field). "
            "Return the city name as written in the text. "
            "Return null if no city is mentioned or inferable."
        )
    )
    country: str | None = Field(
        description=(
            "The country where the company/position is located, if mentioned anywhere in the text. "
            "Return the country name or code as written/implied in the text "
            "(e.g. infer 'Chile' from 'Santiago' if the country isn't explicitly named but the city clearly indicates it). "
            "Return null if truly no country can be determined."
        )
    )

extract_location = Extract(
    llm=llm.enrichement,
    task=(
        "Also explicitly extract the city and country if they are mentioned or can be reasonably inferred "
        "from the text (e.g. a well-known city implies its country)."
    ),
    output_key='location_raw',
    schema=LocationRawOutput,
    fields=['job_title', 'offer_description', 'location_raw', 'city', 'country']
)


def extract_location_node(state: JobOfferState) -> dict:
    original_city = state.get("city")
    original_country = state.get("country")

    result = extract_location(state)

    # Ne jamais écraser une valeur déjà connue par une valeur vide/null du LLM
    if not result.get("city") or result["city"] == "null":
        result["city"] = original_city
    if not result.get("country") or result["country"] == "null":
        result["country"] = original_country

    return result


verify_company = make_verify_included_node(
    primary_key='company_name',
    fields=['job_title', 'offer_description'],
    fallback_value=None
)


find_location = FindLocation(geo_api=placesAPI)


# =========================== Attributes handle ===========================
class OfferAttribute(BaseModel):
    seniority: Literal["junior", "mid", "senior", "unknown"] = Field(
        description=(
            "Seniority level required for the position. "
            "ALWAYS try to infer it, even if not explicitly stated: "
            "look at years of experience required, scope of responsibilities, autonomy expected, "
            "job title nuances (e.g. 'Lead', 'Head of' → senior; no experience required, 'Junior', 'Trainee' → junior), "
            "and the seniority implied by the tasks described. "
            "Map LATAM abbreviations: JR/Jr → junior, SSR/Ssr/Semi-Senior/Pleno → mid, SR/Sr/Senior → senior. "
            "Only use 'unknown' as a last resort, when the offer gives absolutely no clue "
            "about experience level, responsibilities, or seniority-related keywords. "
            "The offer can be in any language."
        )
    )
    is_remote: bool = Field(
        description=(
            "True if the job is fully or partially remote, False if on-site only. "
            "Infer from keywords like 'remoto', 'remote', 'teletrabajo', 'hybrid', 'presencial'. "
            "A raw is_remote value extracted from the source platform is also provided as a hint, "
            "use it only when the text itself is ambiguous or silent, the text always takes priority if it contradicts the hint. "
            "The offer can be in any language. "
            "If genuinely no clue exists, default to False."
        )
    )
    contract_type: Literal["internship", "fulltime", "parttime", "freelance", "unknown"] = Field(
        description=(
            "Type of contract for this position. "
            "Map from keywords: 'pasantía', 'intern', 'stage', 'práctica' → internship. "
            "'tiempo completo', 'full-time', 'CDI' → fulltime. "
            "'medio tiempo', 'part-time' → parttime. "
            "'freelance', 'contractor', 'consultor independiente' → freelance. "
            "If not explicitly stated, INFER from context: most standard job postings without "
            "an internship/part-time/freelance mention are implicitly full-time positions. "
            "Only use 'unknown' if the offer is genuinely too vague to make even that inference "
            "(e.g. a very short fragment description)."
        )
    )
    spoken_languages_required: list[str] | None = Field(
        description=(
            "STEP 1: Read the offer_description text CAREFULLY, word by word — do not skim. "
            "Identify the actual language the text is written in, based STRICTLY on the words present. "
            "Never guess based on the company name, country, or job title alone — if job_title is in English "
            "but offer_description is in Spanish, the answer is Spanish, because the description is the "
            "real signal, not the title. "
            "STEP 2: Only if the text EXPLICITLY states an additional language requirement "
            "(e.g. 'must speak Portuguese', 'bilingüe inglés'), add that language too. "
            "STEP 3: If no additional requirement is stated, return ONLY the language from STEP 1. "
            "EXCLUDE languages mentioned only as tech/documentation keywords. "
            "FORMAT: Return ONLY two-letter ISO 639-1 codes (en, es, fr, pt) — "
            "NEVER three-letter codes (eng, spa, fra, por) and NEVER full language names."
        )
    )
    city: str | None = Field(
        description=(
            "The city where the company/position is located, ONLY if the exact city name is "
            "EXPLICITLY WRITTEN in the text (job_title, offer_description, or location_raw). "
            "Copy it exactly as written. "
            "NEVER guess, infer, or deduce a city that is not literally present in the text. "
            "Return null if no city is explicitly mentioned."
        )
    )
    country: str | None = Field(
        description=(
            "The country where the company/position is located, ONLY if the exact country name "
            "is EXPLICITLY WRITTEN in the text (job_title, offer_description, or location_raw). "
            "Copy it exactly as written. "
            "NEVER guess, infer, or deduce a country from a city name or any other indirect clue — "
            "the country itself must be literally present in the text. "
            "Return null if no country is explicitly mentioned."
        )
    )

    @field_validator("is_remote", mode="before")
    @classmethod
    def normalize_remote(cls, v):
        if v is None:
            return False
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "vrai")
        return v

extract_attributes = Extract(
    llm=llm.enrichement,
    task=(
        'Find the seniority needed for this job offer, or deduce it from context. '
        'Find if the offer is remote, strictly from the text. '
        'Find the contract type, strictly from the text. '
        'Identify the language(s) required for this position, as ISO 639-1 two-letter codes ONLY '
        '(e.g. "en", "es", "pt" — never 3-letter codes like "eng" or "spa"). '
        'Extract city and country ONLY if explicitly written in the text — never guess or infer them.'
    ),
    output_key='attributes',
    schema=OfferAttribute,
    fields=['job_title', 'offer_description', 'is_remote', 'location_raw', 'city', 'country']
)


def extract_attributes_node(state: JobOfferState) -> dict:
    result = extract_attributes(state)

    detected = detect_language(state.get("offer_description", ""))
    langs = result.get("spoken_languages_required") or []
    if detected and detected not in langs:
        langs = langs + [detected]
    result["spoken_languages_required"] = langs

    # Ne jamais écraser une valeur déjà connue par une valeur vide/null du LLM
    if not result.get("city") or result["city"] == "null":
        result["city"] = state.get("city")
    if not result.get("country") or result["country"] == "null":
        result["country"] = state.get("country")

    return result


# =========================== Skills handle ===========================
class OfferSkills(BaseModel):
    skills_languages: list[str] = Field(
        description="Programming languages mentioned in the offer, e.g. Python, SQL, Terraform"
    )
    skills_framework: list[str] = Field(
        description="Frameworks and tools mentioned in the offer, e.g. Airflow, AWS, BigQuery"
    )
    skills_aptitudes: list[str] = Field(
        description=(
            "Technical competencies or domain knowledge needed for this job, e.g. "
            "cloud architecture, database management, data warehousing, ETL design. "
            "MUST be written in English, even if the offer is in Spanish or Portuguese. "
            "Do NOT include job titles or role names (e.g. 'Data Engineer', 'Analytics Engineer', "
            "'BI Developer') — those belong to related_job_titles, not here."
        )
    )
    skills_soft: list[str] = Field(
        description=(
            "Soft skills needed for this job, e.g. communication, teamwork, problem-solving. "
            "MUST be written in English, even if the offer is in Spanish or Portuguese."
        )
    )
    related_job_titles: list[str] = Field(
        description=(
            "MANDATORY, NEVER LEAVE EMPTY: this list MUST contain at least the offer's own "
            "main job title (given to you in the job_title field), copied exactly as provided. "
            "Additionally include any other equivalent job titles explicitly written in the offer text "
            "(e.g. 'Data Engineer, Analytics Engineer or BI Developer' → list all three). "
            "Do NOT invent titles that aren't in the text, but DO always copy the main job_title in."
        )
    )


extract_skills = Extract(
    llm=llm.enrichement,
    task=(
        "Extract the required skills needed for this offer. "
        "You can deduce it if it is implied but do not invent anything. "
        "In related_job_titles, include the offer's own job title AND any equivalent/related "
        "role names mentioned in the text — this field should contain every relevant job title, "
        "not just alternatives to it. "
        "Job titles or role names mentioned in the text are NOT skills, they belong in related_job_titles. "
        "IMPORTANT: All extracted values MUST be written in English, even when the offer is written "
        "in Spanish or French. Translate every skill, aptitude, soft skill and job title into English. "
        "Keep proper nouns and technology names unchanged (Python, BigQuery, Apache Airflow, GCP)."
    ),
    output_key='skills',
    schema=OfferSkills,
    fields=['job_title', 'offer_description']
)
# =========================== Relevancy handle ===========================
# profile = """
# Etudiant ingénieur français
# Languages informatique : python intermédiaire, sql intermédiaire, java intermédiaire, C débutant, C++ base, Terraform base
# Framework : Docker intermédiaire, airflow débutant, PostgreSQL intermédiaire, cloud neon débutant, aws base, LangGraph, débutant 
# Ce que je cherche : Un stage en Amérique latine nottament Argentine, Chilie et Urugay dans les capitales en priorité donc Santiago, Buenos Aires, Montevideo.
# Je veux developper mes connaissance en cloud data engineering nottament AWS et l'ajout d'intégration LLM dans le processus de production avec LangGraph. 
# Je parle français C2, anglais B2, espagnol débutant A2.
# Je veux faire un stage a temps plein sur le lieux de l'ebtreprise, le remote hybride ne me derange pas
# """
determine_relevancy = DetermineRelevancy(llm=llm.enrichement)

calculate_relevancy = partial(calculate_total_score, weights=WEIGHTS)




# =========================== Route ===========================
# Does we need to extract company or we can keep going
route_to_extract_company = make_binary_route_node(
    primary_key="company_name",
    condition=[None, 'null', '', "Empresa confidencial"],
    node_if_true=['extract_company'],
    node_if_false=['extract_attributes_node']
)

# Can we keep dealing with this offer 
# route_company_to_end = make_binary_route_node(
#     primary_key="company_name",
#     condition=[None, 'null', '', "Empresa confidencial"],
#     node_if_true=[END],
#     node_if_false=["find_location"]
# )



def route_after_find_location(state: JobOfferState):    
    # if find_location failed but we haven't tried extract_location yet
    if state.get("_location_failed") and not state.get("_location_retry_attempted"):
        return "extract_location"
    
    # Continue the graph
    return "extract_attributes_node"



# =========================== Graph intialisation ===========================
builder = StateGraph(JobOfferState)

# Initial route ________________________________________________________________________
builder.add_conditional_edges(
    START,
    route_to_extract_company,
    ['extract_company', 'extract_attributes_node']
)

# Company ______________________________________________________________________________
builder.add_sequence([
    ("extract_company", extract_company),
    ("verify_company", verify_company),
])

# Peu importe si company est valide ou pas, on continue toujours vers l'enrichissement
builder.add_edge("verify_company", "extract_attributes_node")

# Attributes & Skills __________________________________________________________________
builder.add_sequence([
    ("extract_attributes_node", extract_attributes_node),
    ("extract_skills", extract_skills),
])

builder.add_edge("extract_skills", "determine_relevancy")

# Scoring ______________________________________________________________________________
builder.add_sequence([
    ("determine_relevancy", determine_relevancy),
    ("calculate_relevancy", calculate_relevancy)
])
builder.add_edge("calculate_relevancy", END)

graph = builder.compile()