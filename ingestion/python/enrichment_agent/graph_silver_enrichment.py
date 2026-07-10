from silver_enrichment import *
from typing import Literal
from functools import partial
import os
import sys
sys.path.append("../src")
from APIendpoint import PlacesAPI
llm = LLM()
placesAPI = PlacesAPI(os.getenv('MAPS_APP_KEY'))

# =========================== Company handle ===========================
class CompanyOutput(BaseModel):
    company_name: str | None = Field(
        description="Name of the company recruiting for this offer, mentioned in the text. Do not invent or mistake a software/tool name for the company name. Return null if not found."
    )
extract_company = Extract(
    llm=llm.enrichement,
    task=(
        "Find the name of the company recruiting for this job offer, based on the title and description. "
        "The name must be explicitly mentioned in the text — do not invent it or mistake a software/tool name for it."
    ),
    output_key='company_name',
    schema=CompanyOutput,
    fields=['job_title', 'offer_description']
)

# =========================== Location handle ===========================
class LocationRawOutput(BaseModel):
    location_raw: str | None = Field(
        description= ("A location hint suitable for a Google Maps query. "
        "If you can enrich the existing location_raw with city/country/offer_description, do so. "
        "If you find nothing additional, just return the existing location_raw unchanged.")
    )

extract_location = Extract(
    llm=llm.enrichement,
    task=(
        "I need a location hint to start a Google Maps API query. I don't need a precise location, "
        "just something that indicates where the company is located. "
        "Combine information from location_raw, city, country, and offer_description."
    ),
    output_key='location_raw',
    schema=LocationRawOutput,
    fields=['job_title', 'offer_description', 'location_raw', 'city', 'country']
)

def extract_location_node(state: JobOfferState) -> dict:
    original_location = state.get("location_raw")
    result = extract_location(state)
    result["_location_retry_attempted"] = True
    if not result.get("location_raw") or result["location_raw"] == "null":
        result["location_raw"] = original_location

    return result



verify_company = make_verify_included_node(
    primary_key='company_name',
    fields=['job_title', 'offer_description'],
    fallback_value=None
)


find_location = FindLocation(geo_api=placesAPI)

find_mails = FindMails(llm=llm)



# =========================== Attributes handle ===========================
class OfferAttribute(BaseModel):
    seniority: Literal["junior", "mid", "senior", "unknown"] = Field(
        description=(
            "Seniority level required for the position. Use 'unknown' if not clearly stated."
            "Map LATAM abbreviations: JR/Jr → junior, SSR/Ssr/Semi-Senior/Pleno → mid, SR/Sr/Senior → senior."
            "You can deduct it but if you don't find just use 'unknown'"
            "The offer can be in any language."
        )
    )
    is_remote: bool | str = Field(
        description=(
            "True if the job is fully or partially remote, False if on-site only. "
            "Infer from keywords like 'remoto', 'remote', 'teletrabajo', 'hybrid', 'presencial'."
            "A raw is_remote value extracted from the source platform is also provided as a hint, "
            "use it only when the text itself is ambiguous or silent, the text always takes priority if it contradicts the hint. "
            "The offer can be in any language."
            "If you can't determine if it's remote just return False"
        )
    )
    contract_type: Literal["internship", "fulltime", "parttime", "freelance", "unknown"] = Field(
        description=(
            "Type of contract for this position. "
            "Map from keywords: 'pasantía', 'intern', 'stage', 'práctica' → internship. "
            "'tiempo completo', 'full-time', 'CDI' → fulltime. "
            "'medio tiempo', 'part-time' → parttime. "
            "'freelance', 'contractor', 'consultor independiente' → freelance. "
            "Find it strictly from the text or use 'unknown' if not clearly stated."
        )
    )
    spoken_languages_required: list[str] | None = Field(
        description=(
            "Detect the speaking language required for this job offer."
            "Strictly identify the human language required to speak/work in the position."
            "CRITICAL: If no specific language requirement is explicitly mentioned in the text, "
            "DEFAULT to the language in which the job offer is written (e.g., ['en'] if the text is in English)."
            "EXCLUDE languages that are only used as 'tech keywords' (e.g., if a job is in Spanish but mentions 'English documentation', do NOT add 'en')."
            "If the job description is written in one language and no other is required, return only the language of the description."
            "CRITICAL: Return ONLY the ISO 639-1 codes (e.g., ['es'], ['fr'], ['pt']). Do NOT return the full language names."
        )
    )
    @field_validator("is_remote", mode="before")
    @classmethod
    def normalize_remote(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "vrai")
        return v

extract_attributes = Extract(
    llm=llm.enrichement,
    task=(
        'Find the seniority needed for this job offer or deduct it. '
        'Find if the offer is in remote strictly from the text. '
        'Find the contract type strictly from the text. '
        'Identify the spoken languages required for the position (as ISO 639-1 codes).'
    ),
    output_key='attributes',
    schema=OfferAttribute,
    fields=['job_title', 'offer_description', 'is_remote']
)




# =========================== Skills handle ===========================
class OfferSkills(BaseModel):
    skills_languages: list[str] = Field(description="Programming language mentionned in the offer, e.g python, sql, terraform")
    skills_framework: list[str] = Field(description="Framework mentionned in the offer, e.g airflow, AWS")
    skills_aptitudes: list[str] = Field(
        description=(
            "Technical competencies or domain knowledge needed for this job, e.g "
            "cloud architecture, database management, data warehousing, ETL design. "
            "Do NOT include job titles or role names (e.g. 'Data Engineer', 'Analytics Engineer', "
            "'BI Developer') — those belong to alternative_job_titles, not here."
        )
    )
    skills_soft: list[str] = Field(description="Soft skills needed for this job, for example communication")
    alternative_job_titles: list[str] = Field(
        description=(
            "Other job titles or role names mentioned in the offer as equivalent or acceptable "
            "for this position, besides the main job_title already known "
            "(e.g. if the offer says 'Data Engineer, Analytics Engineer or BI Developer', "
            "list all of them here, including the one matching job_title if repeated)."
        )
    )


extract_skills = Extract(
    llm=llm.enrichement,
    task=(
        "Extract the required skills needed for this offer. "
        "You can deduce it if it is implied but do not invent anything. "
        "Job titles or role names mentioned in the text (e.g. 'Data Engineer', 'BI Developer') "
        "are NOT skills,  list them separately in alternative_job_titles instead."
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
    node_if_false=['find_location']
)

# Can we keep dealing with this offer 
route_company_to_end = make_binary_route_node(
    primary_key="company_name",
    condition=[None, 'null', '', "Empresa confidencial"],
    node_if_true=[END],
    node_if_false=["find_location"]
)



def route_after_find_location(state: JobOfferState):    
    # if find_location failed but we haven't tried extract_location yet
    if state.get("_location_failed") and not state.get("_location_retry_attempted"):
        return "extract_location"
    
    # Continue the graph
    return "extract_attributes"




# =========================== Graph intialisation ===========================
builder = StateGraph(JobOfferState)

# Initial route ________________________________________________________________________
builder.add_conditional_edges(
    START,
    route_to_extract_company,
    ['find_location', 'extract_company']
)

# Company ______________________________________________________________________________
builder.add_sequence([
    ("extract_company", extract_company),
    ("verify_company", verify_company),
])

builder.add_conditional_edges(
    "verify_company",
    route_company_to_end,
    ["find_location", END]
)

# Location (La boucle d'essai) _________________________________________________________
# Ajout explicite des nœuds
builder.add_node("find_location", find_location)
builder.add_node("extract_location", extract_location_node)

# La condition après find_location
builder.add_conditional_edges(
    "find_location",
    route_after_find_location,
    {
        "extract_location": "extract_location",
        "extract_attributes": "extract_attributes"
    }
)

# Si on passe par l'enrichissement, on retourne tester
builder.add_edge("extract_location", "find_location")

# Attributes & Skills __________________________________________________________________
builder.add_sequence([
    ("extract_attributes", extract_attributes),
    ("extract_skills", extract_skills),
])

# De skills, on passe directement au scoring
builder.add_edge("extract_skills", "determine_relevancy")

# Scoring ______________________________________________________________________________
builder.add_sequence([
    ("determine_relevancy", determine_relevancy),
    ("calculate_relevancy", calculate_relevancy)
])
builder.add_edge("calculate_relevancy", END)