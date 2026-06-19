# STATE ET NOEUDS
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
import operator
import json
from rapidfuzz import fuzz, process
from pydantic import BaseModel
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from dotenv import load_dotenv
import os
import sys
sys.path.append("../ingestion/python/src")     
from database import Database
from APIendpoint import GeoAPI  
import reverse_geocoder
from ddgs import DDGS

# =========================== LLM Defintion ===========================
# LLM 
class LLM:
    def __init__(self, groq_key: str=None):
        self._groq_key = groq_key or os.getenv("GROQ_APP_KEY")
        self.llama3_smart = ChatGroq(model="llama-3.3-70b-versatile", api_key=self._groq_key, temperature=0)
        self.llama4_smart = ChatGroq(model="meta-llama/llama-4-scout-17b-16e-instruct", api_key=self._groq_key, temperature=0)

        # Problem of formatting with this model use an another one
        # self.llm_fast  = ChatGroq(model="llama-3.1-8b-instant", api_key=self._groq_key, temperature=0)

        
# =========================== STATE ===========================
# Public State
class JobOfferState(TypedDict):
    # ── keys ──
    id_job: str
    id_company: int | None    
    id_location: int | None   

    # ── analytics.job_offer ──
    api_source: str
    job_title: str
    offer_description: str
    contract_type: str | None   
    is_remote: bool | None   
    job_publisher: str | None   
    location_raw: str | None   
    company_raw: str | None   
    offer_url: str | None   
    source_platform: str | None   
    offer_language: str | None   
    published_at: str | None   
    collected_at: str

    # ── analytics.job_requirement ──
    seniority: str | None   
    skills_languages: list[str] | None
    skills_framework: list[str] | None
    skills_aptitudes: list[str] | None
    skills_soft: list[str] | None

    # ── analytics.job_relevancy ──
    score_relevancy: float | None   
    score_details: dict | None   
    explanation: str | None  
    prompt_relevancy: str | None 

    # ── analytics.company ──
    company_name: str | None   
    company_website: str | None   
    company_primary_type: str | None   

    # ── analytics.company_location ──
    address: str | None   
    city: str | None   
    country: str | None   
    lat: float | None   
    lon: float | None   
    phone: str | None   
    business_status: str | None   


    # ── analytics.company_contact ──
    contacts: list[dict]
    


# =========================== LLM Call ===========================
class Extract:
    """ Generic Node LangGraph : extract data structured via LLM """
    def __init__(self, task: str, output_key:str, schema: type[BaseModel], fields: list[str], llm):
        self._task = task               # LLM mission
        self._output_key = output_key   # field output
        self._schema = schema           # Structure of the response
        self._fields = fields           # field input
        self._llm_structured = llm.with_structured_output(schema)


    def __call__(self, state: JobOfferState) -> dict:
        # Define fields accesible in the state
        context = "\n".join(
            f"{field}: {state.get(field)}" for field in self._fields
        )

        # Structure the mission of the LLM with precision
        system = SystemMessage(content=f"""
                            I did an ingestion pipeline gathering job offer via APIs, I did it to find an internship/job automatically.
                            I want you to be the more precise possible, this is important for me to have valuable and correct information.
                            Task : {self._task}
                            If no information is available, do not invent one and return null for this field
                        """)
        user = HumanMessage(content=context)

        try:
            response = self._llm_structured.invoke([system, user])
            data = response.model_dump()
            if len(data) == 1:
                # Schema with unique field
                return {self._output_key: next(iter(data.values()))}
            # Schema with many fields
            return data
        except Exception as e:
            print(f"Erreur extraction {self._output_key} pour id_job={state.get('id_job')}: {e}")
            # If multiple field schema return None in each field
            if hasattr(self._schema, 'model_fields') and len(self._schema.model_fields) > 1:
                return {field: None for field in self._schema.model_fields}
            return {self._output_key: None}



# =========================== Direction Management ===========================
def is_included(value: str, reference: list[str]):
    score = fuzz.partial_ratio(value, reference)
    return score > 75

def make_verify_included_node(primary_key: str, fields: list[str], fallback_value: str=None):
    """
    Return a node generic verification to ensure the LLM is not hallucinating.

    primary_key : key found by the LLM
    fields : keys where the LLM found the data
    fallback_value : value to use if primary value not in input values
    """
    def verify_included(state: JobOfferState):
        value = state.get(primary_key)
        for key in fields:
            if is_included(value, state.get(key)):
                return {primary_key: value}
        return {primary_key: fallback_value}
    
    verify_included.__name__ = f"verify{primary_key}"
    return verify_included
    

def make_binary_route_node(primary_key: str, condition: list[str], node_if_true : str, node_if_false: str):
    """
    Route towards a node depending of a condition

    primary_key : key to test in the sate
    condition : if true go to fallback_node1 else fallback_node2
    node_if_true : node to visit if value is in condition
    node_if_false: node to visit otherwise
    """
    def binary_route(state: JobOfferState):
        if state.get(primary_key) in condition:
            return node_if_true
        return node_if_false
    
    binary_route.__name__ = f"route_{primary_key}"
    return binary_route


# =========================== APIs Call ===========================
# Location
class FindLocation:
    """    
    Receive company and raw_location
    Return :
        normalised city name and country code
        company_website
        location (lat, lon)
        phone number of the office 
        adress of the company
    """
    def __init__(self, geo_api: GeoAPI):
        self._geo_api = geo_api

    def __call__(self, state: JobOfferState) -> dict:
        company = state.get('company_name')
        location = state.get('location_raw')

        # fallback if location is null or None
        if not location or location == 'null':
            location = state.get('city')
        
        # If no company (shouldn't happen)
        if not company or company == "null":
            return {}

        result = self._geo_api.search_place(company, location)
        if not result:
            return {}
        
        # If no coordinate available
        if result.get('lat') is None or result.get('lon') is None:
            return result
        reverse_geocode = reverse_geocoder.search((result['lat'], result['lon']))
        geocode = {
            'city': reverse_geocode[0]['admin1'],
            'country': reverse_geocode[0]['cc']
        }
        return result | geocode
    

# Mails
class SearchQueryOutput(BaseModel):
    query: str = Field(description="Optimized search query to find HR/recruitment contact email")

class EmailItem(BaseModel):
    email: str
    score: float
    reason: str

class EmailResults(BaseModel):
    emails: list[EmailItem]


class FindMails:
    def __init__(self, llm):
        self._generate_query = Extract(
            llm=llm.llama3_smart, 
            task="Generate an optimised search query to find HR contact email on web." \
            "Adapt the language of your request with the local language of the country" \
            "for example spanish in Chile, Argentina or Urugay",
            output_key="search_query",
            schema=SearchQueryOutput,
            fields=["company_name", "city", "country"]
        )
        self._llm_structured = llm.llama4_smart.with_structured_output(EmailResults)
    
    def __call__(self, state: JobOfferState) -> dict:
        company = state.get("company_name")
        if not company or company == 'null':
            return {'contacts': []}
        
        query_result = self._generate_query(state)
        query = query_result["search_query"]

        results = self._search_ddg(query)
        if not results:
            return {"contacts": []}
                
        system = SystemMessage(content="""
            You are an assistant that extracts company contact emails.
            I am looking to apply for a job/internship at this company.
            From the search results provided, identify the most relevant emails.
            1. HR/recruitment emails (score 0.8-1.0)
            2. Technical/data/IT team emails (score 0.6-0.8)
            3. Generic emails info@/contact@ (score 0.3-0.5)
            Exclude CEO/executive emails unless no other option is available.
            ONLY use emails present in the provided search results.
            NEVER generate an email from your general knowledge.
            If you find an official application portal (career page, trabajando.cl, etc.)
            instead of a direct email, indicate the URL in career_portal_url.
            If no email is found, state it clearly.
            """)

        user = HumanMessage(content=f"Company: {company}\nResult:\n{results}")

        try:
            response = self._llm_structured.invoke([system, user])
            contacts = [item.model_dump() for item in response.emails]
            return {"contacts": contacts}
        except Exception as e:
            print(f"Erreur find_mails pour {company}: {e}")
            return {"contacts": []}

    def _search_ddg(self, query: str, max_results: int = 10) -> str:
        try:
            with DDGS() as ddgs:
                results = ddgs.text(query, max_results=max_results)
                if not results:
                    return ""
                return "\n".join([r["body"] for r in results])
        except Exception as e:
            print(f"Erreur DDG: {e}")
            return ""
        




# =========================== Relevancy Calcule ===========================

class OfferRelevancy(BaseModel):
    score_skills: float = Field(
        ge=0, le=10,
        description=(
            "Skills matching score from 0 to 10, comparing the skills required in this offer "
            "against my profile (provided in the system message). "
            "10 = strong overlap with my skillset, 5 = partial/adjacent overlap, 0 = completely unrelated."
        )
    )
    score_language: float = Field(
        ge=0, le=10,
        description=(
            "Language fit score from 0 to 10, based on the offer's language compared to the languages I speak "
            "(provided in the system message). "
            "10 = offer language matches my fluent languages, 0 = offer requires a language I don't speak."
        )
    )
    score_seniority: float = Field(
        ge=0, le=10,
        description=(
            "Seniority fit score from 0 to 10, comparing the seniority required by the offer against my "
            "10 = perfect match, 0 = requires a seniority level I don't have."
        )
    )
    score_work_mode: float = Field(
        ge=0, le=10,
        description=(
            "Work arrangement fit score from 0 to 10, combining both the work mode (remote/hybrid/on-site) "
            "and the contract type (internship, full-time, part-time, freelance) against my preferences "
            "(provided in the system message). "
            "10 = both work mode and contract type match my preferences, "
            "5 = only one of the two matches, "
            "0 = neither matches."
            "If you can't conclude attribute 5."
        )
    )
    score_company: float = Field(
        ge=0, le=10,
        description=(
            "Company relevance score from 0 to 10 for my career goals (provided in the system message). "
            "If no specific information about the company is available, return a neutral score of 5.0 "
            "rather than guessing."
        )
    )
    score_location: float = Field(
        ge=0, le=10,
        description=(
            "Location fit score from 0 to 10, comparing the offer's location against my target locations "
            "(provided in the system message)."
        )
    )
    explanation: str = Field(
        description=(
            "Short explanation (2-3 sentences) summarizing why this offer is or isn't a good match overall, "
            "based on my profile."
            "Always write it in english"
        )
    )

class DetermineRelevancy:
    def __init__(self, llm, profile: str):
        """
        llm : instance of the llm used to answer
        profile : text describing the user profile (languages, experience, target locations, skills ...)
        """
        self._profile = profile
        self._llm_structured = llm.with_structured_output(OfferRelevancy)

    def __call__(self, state: JobOfferState) -> dict:
        context = "\n".join([
            f"job_title: {state.get('job_title')}",
            f"offer_language: {state.get('offer_language')}",
            f"seniority: {state.get('seniority')}",
            f"is_remote: {state.get('is_remote')}",
            f"contract_type: {state.get('contract_type')}",
            f"city: {state.get('city')}",
            f"country: {state.get('country')}",
            f"company_name: {state.get('company_name')}",
            f"skills_languages: {state.get('skills_languages')}",
            f"skills_framework: {state.get('skills_framework')}",
            f"skills_aptitude: {state.get('skills_aptitude')}",
            f"skills_soft: {state.get('skills_soft')}",
        ])

        
        system = SystemMessage(content=f"""
            I built an ingestion pipeline gathering job offers to automatically find an internship/job.
            Calculate the relevancy of this job offer based on my profile below.
            Attribute a grade from 0 to 10 for each criterion.
        
            My profile:
            {self._profile} 
        """)

        user = HumanMessage(content=context)

        try:
            response = self._llm_structured.invoke([system, user])
            return {**response.model_dump(), "prompt_relevancy": self._profile}
        except Exception as e:
            print(f"Error calculate_relevancy for id={state.get('id_job')}: {e}")
            return {
                "score_skills": None,
                "score_language": None,
                "score_seniority": None,
                "score_company": None,
                "score_location": None,
                "score_work_mode": None,
                "explanation": None,
                "prompt_relevancy": self._profile
            }
        


def calculate_total_score(state: JobOfferState, weights: dict) -> dict:
    """Calcule le score de pertinence final pondéré à partir des sous-scores du LLM."""
    criteria_map = {
        "skills":    state.get("score_skills"),
        "language":  state.get("score_language"),
        "seniority": state.get("score_seniority"),
        "company":   state.get("score_company"),
        "location":  state.get("score_location"),
        "work_mode": state.get("score_work_mode"),
    }

    valid = {k: v for k, v in criteria_map.items() if v is not None}
    if not valid:
        return {"relevancy_score": None}

    total_weight = sum(weights[k] for k in valid)
    weighted_sum = sum(valid[k] * weights[k] for k in valid)

    score = round(weighted_sum / total_weight, 2) if total_weight > 0 else None
    return {"relevancy_score": score}