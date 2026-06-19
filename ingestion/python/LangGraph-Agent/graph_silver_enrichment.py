from silver_enrichment import *
from typing import Literal
from functools import partial
import os
import sys
sys.path.append("../src")

llm = LLM()
placesAPI = PlacesAPI(os.getenv('MAPS_APP_KEY'))

# =========================== Company handle ===========================
class CompanyOutput(BaseModel):
    company_name: str | None = Field(description="Name of the company, or null if no company is found")

extract_company = Extract(
    llm=llm.llama4_smart,
    task=(
        'Find the name of the company who recruit for this job offer based on the title and the description of the job. '
        'The name has to be mentioned in the text, do not invent or mistake a software name for the company name, for example Microsoft.'
    ),
    output_key='company_name',
    schema=CompanyOutput,
    fields=['job_title', 'offer_description']
)
verify_company = make_verify_included_node(
    primary_key='company_name',
    fields=['job_title', 'offer_description'],
    fallback_value=None
)

# Does we need to extract company or we can keep going
route_to_extract_company = make_binary_route_node(
    primary_key="company_name",
    condition=[None, 'null', "Empresa confidencial"],
    node_if_true=, # Skip extract company
    node_if_false='extract_company'
)

# Can we keep dealing with this offer 
route_company_to_end = make_binary_route_node(
    primary_key="company_name"
    condition=[None, 'null', "Empresa confidencial"],
    node_if_true=END, # End the graph, impossible to deal with the offer if no company
    node_if_false= # Go to find_location or whatever
)

# =========================== meta data handle ===========================
class OfferMetaOutput(BaseModel):
    seniority: Literal["junior", "mid", "senior", "unknown"] = Field(
        description=(
            "Seniority level required for the position. Use 'unknown' if not clearly stated."
            "Map LATAM abbreviations: JR/Jr → junior, SSR/Ssr/Semi-Senior/Pleno → mid, SR/Sr/Senior → senior."
            "You can deduct it but if you don't find just use 'unknown'"
            "The offer can be in any language."
        )
    )
    is_remote: bool = Field(
        description=(
            "True if the job is fully or partially remote, False if on-site only. "
            "Infer from keywords like 'remoto', 'remote', 'teletrabajo', 'hybrid', 'presencial'. "
            "The offer can be in any language."
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
    offer_language: str = Field(
        description=(
            "Detect the language in which this job offer is written."
            "Infer from the description content, not from English tech keywords in the title. "
            "Return it STRICTLY with the Norme ISO 639-1 (ex: es, en, fr, pt)"
        )
    )

extract_meta_offer = Extract(
    llm=llm.llama4_smart,
    task=(
        'Find the seniority needed for this job offer or deduct it. '
        'Find if the offer is in remote strictly from the text. '
        'Find the contract type strictly from the text. '
        'Find the language of the offer.'
    ),
    output_key='meta',
    schema=OfferMetaOutput,
    fields=['job_title', 'offer_description']
)



# =========================== Location handle ===========================
find_location = FindLocation(geo_api=placesAPI)

find_mails = FindMails(llm=llm)

# =========================== Skills handle ===========================
class OfferSkills(BaseModel):
    skills_languages: list[str] = Field(description="Programming language mentionned in the offer, for example python, sql, terraform")
    skills_framework: list[str] = Field(description="Framework mentionned in the offer, for exemple airflow, AWS")
    skills_aptitudes: list[str] = Field(description="Aptitude needed for this job, for exemple cloud architecture, database management")
    skills_soft:      list[str] = Field(description="Soft skills needed for this job, for example communication")


extract_skills = Extract(
    llm=llm.llama4_smart,
    task="Extract the requiered skills needed for this offer." 
    "You can deduce it if it is implied but do not invent anything",
    output_key='skills',
    schema=OfferSkills,
    fields=['job_title', 'offer_description']
)

# =========================== Relevancy handle ===========================
profile = "TODO"
calculate_relevancy = DetermineRelevancy(llm=llm.llama4_smart, profile=profile)

WEIGHTS = {
    "skills": 0.30,
    "language": 0.25,
    "seniority": 0.15,
    "location": 0.15,
    "company": 0.10,
    "work_mode": 0.05,
}
calculate_total_score_relevancy = partial(calculate_total_score, weights=WEIGHTS)
