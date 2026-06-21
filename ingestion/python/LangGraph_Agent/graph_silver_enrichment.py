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
# =========================== Location handle ===========================
class CompanyOutput(BaseModel):
    company_name: str | None = Field(
        description="Name of the company recruiting for this offer, mentioned in the text. Do not invent or mistake a software/tool name for the company name. Return null if not found."
    )
extract_company = Extract(
    llm=llm.llama4_smart,
    task=(
        "Find the name of the company recruiting for this job offer, based on the title and description. "
        "The name must be explicitly mentioned in the text — do not invent it or mistake a software/tool name for it."
    ),
    output_key='company_name',
    schema=CompanyOutput,
    fields=['job_title', 'offer_description']
)


class LocationRawOutput(BaseModel):
    location_raw: str | None = Field(
        description= ("A location hint suitable for a Google Maps query. "
        "If you can enrich the existing location_raw with city/country/offer_description, do so. "
        "If you find nothing additional, just return the existing location_raw unchanged.")
    )
extract_location = Extract(
    llm=llm.llama4_smart,
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
    offer_language: list[str] = Field(
        description=(
            "Detect the language required for this job offer."
            "If no languages is mentionned detect the language in which this job offer is written."
            "Infer from the description content, not from English tech keywords in the title. "
            "Many languages can be precised like english and spanish"
            "Return it STRICTLY with the Norme ISO 639-1 (ex: es, en, fr, pt)"
        )
    )
    @field_validator("is_remote", mode="before")
    @classmethod
    def normalize_remote(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "vrai")
        return v

extract_attributes = Extract(
    llm=llm.llama4_smart,
    task=(
        'Find the seniority needed for this job offer or deduct it. '
        'Find if the offer is in remote strictly from the text. '
        'Find the contract type strictly from the text. '
        'Find the language of the offer.'
    ),
    output_key='attributes',
    schema=OfferAttribute,
    fields=['job_title', 'offer_description', 'is_remote']
)




# =========================== Skills handle ===========================
class OfferSkills(BaseModel):
    skills_languages: list[str] = Field(description="Programming language mentionned in the offer, for example python, sql, terraform")
    skills_framework: list[str] = Field(description="Framework mentionned in the offer, for exemple airflow, AWS")
    skills_aptitudes: list[str] = Field(
        description=(
            "Technical competencies or domain knowledge needed for this job, for example "
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
    llm=llm.llama4_smart,
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
profile = """
Etudiant ingénieur français
Languages informatique : python intermédiaire, sql intermédiaire, java intermédiaire, C débutant, C++ base, Terraform base
Framework : Docker intermédiaire, airflow débutant, PostgreSQL intermédiaire, cloud neon débutant, aws base, LangGraph, débutant 
Ce que je cherche : Un stage en Amérique latine nottament Argentine, Chilie et Urugay dans les capitales en priorité donc Santiago, Buenos Aires, Montevideo.
Je veux developper mes connaissance en cloud data engineering nottament AWS et l'ajout d'intégration LLM dans le processus de production avec LangGraph. 
Je parle français C2, anglais B2, espagnol débutant A2.
Je veux faire un stage a temps plein sur le lieux de l'ebtreprise, le remote hybride ne me derange pas
"""
determine_relevancy = DetermineRelevancy(llm=llm.llama4_smart, profile=profile)

calculate_relevancy = partial(calculate_total_score, weights=WEIGHTS)


# # =========================== Route ===========================
# # Does we need to extract company or we can keep going
# route_to_extract_company = make_binary_route_node(
#     primary_key="company_name",
#     condition=[None, 'null', '', "Empresa confidencial"],
#     node_if_true=['extract_company'], # Skip extract company
#     node_if_false=['extract_location', 'extract_attributes', 'extract_skills']
# )

# # Can we keep dealing with this offer 
# route_company_to_end = make_binary_route_node(
#     primary_key="company_name",
#     condition=[None, 'null', '', "Empresa confidencial"],
#     node_if_true=[END], # End the graph, impossible to deal with the offer if no company
#     node_if_false=["extract_location", "extract_attributes", "extract_skills"] # Keep going
# )



# # Graph intialisation __________________________________________________________________
# builder = StateGraph(JobOfferState)

# # Initial route ________________________________________________________________________
# builder.add_conditional_edges(
#     START,              # ← un VRAI nœud, déjà ajouté avec add_node
#     route_to_extract_company,       # ← la fonction qui décide où aller
#     ['extract_location', 'extract_attributes', 'extract_skills', 'extract_company']
# )


# # Company ______________________________________________________________________________
# builder.add_sequence([
#     ("extract_company", extract_company),
#     ("verify_company", verify_company),
# ])

# builder.add_conditional_edges(
#     "verify_company",              # ← un VRAI nœud, déjà ajouté avec add_node
#     route_company_to_end,       # ← la fonction qui décide où aller
#     ["extract_location", "extract_attributes", "extract_skills", END]
# )

# # Location & contacts ___________________________________________________________________
# builder.add_sequence([
#     ("extract_location", extract_location_node),
#     ("find_location", find_location),
#     ("find_mails", find_mails)
# ])
# builder.add_edge("find_mails", END)

# # Scoring ______________________________________________________________________________
# builder.add_sequence([
#     ("determine_relevancy", determine_relevancy),
#     ("calculate_relevancy", calculate_relevancy)
# ])
# builder.add_edge("calculate_relevancy", END)

# # Attributes & skills ___________________________________________________________________
# builder.add_node("extract_attributes", extract_attributes)
# builder.add_node("extract_skills", extract_skills)
# builder.add_edge(["extract_attributes", "extract_skills", "find_location"], "determine_relevancy")





# =========================== Route ===========================
# Does we need to extract company or we can keep going
route_to_extract_company = make_binary_route_node(
    primary_key="company_name",
    condition=[None, 'null', '', "Empresa confidencial"],
    node_if_true=['extract_company'],
    node_if_false=['extract_location']
)

# Can we keep dealing with this offer 
route_company_to_end = make_binary_route_node(
    primary_key="company_name",
    condition=[None, 'null', '', "Empresa confidencial"],
    node_if_true=[END],
    node_if_false=["extract_location"]
)



# Graph intialisation __________________________________________________________________
builder = StateGraph(JobOfferState)

# Initial route ________________________________________________________________________
builder.add_conditional_edges(
    START,
    route_to_extract_company,
    ['extract_location', 'extract_company']
)


# Company ______________________________________________________________________________
builder.add_sequence([
    ("extract_company", extract_company),
    ("verify_company", verify_company),
])

builder.add_conditional_edges(
    "verify_company",
    route_company_to_end,
    ["extract_location", END]
)

# Location → Attributes → Skills → Mails, tout en séquentiel ___________________________
builder.add_sequence([
    ("extract_location", extract_location_node),
    ("find_location", find_location),
    ("extract_attributes", extract_attributes),
    ("extract_skills", extract_skills),
    ("find_mails", find_mails),
])
builder.add_edge("find_mails", END)

# Scoring ______________________________________________________________________________
builder.add_sequence([
    ("determine_relevancy", determine_relevancy),
    ("calculate_relevancy", calculate_relevancy)
])
builder.add_edge("calculate_relevancy", END)

builder.add_edge("extract_skills", "determine_relevancy")