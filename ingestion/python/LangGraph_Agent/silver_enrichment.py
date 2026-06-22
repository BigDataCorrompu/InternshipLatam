# STATE ET NOEUDS
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
import operator
import json
from rapidfuzz import fuzz, process
from pydantic import BaseModel, field_validator, Field
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
# from langchain_ollama import ChatOllama
from dotenv import load_dotenv
import operator
from typing import Annotated
import os
import sys
sys.path.append("../ingestion/python/src")     
from database import Database
from APIendpoint import GeoAPI  
import reverse_geocoder
from ddgs import DDGS
import re
import time

def clean_location_raw(location_raw: str) -> str:
    """Retire les artefacts de plateforme du texte de localisation brut."""
    if not location_raw:
        return location_raw
    # Retire tout ce qui suit un séparateur typique de plateforme
    cleaned = re.split(r'•|a través de|via|through', location_raw)[0]
    return cleaned.strip()

# Grok rate limit handle
def call_with_retry(fn, max_retries=20):
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            error_str = str(e)
            if "rate_limit_exceeded" in error_str:
                match = re.search(r"try again in ([\d.]+)s", error_str)
                wait_time = float(match.group(1)) + 1.0 if match else 8  # marge plus large
                print(f"⏳ Rate limit atteint, attente de {wait_time:.1f}s avant retry ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                raise
    raise Exception("Trop de tentatives échouées")


WEIGHTS = {
    "job":       0.20,  # Nouvelle clé pour avantager l'intitulé du poste
    "skills":    0.25,  # Reste le critère principal mais partagé avec le job title
    "language":  0.20,  # Ajusté légèrement pour faire de la place
    "seniority": 0.15,
    "location":  0.15,
    "company":   0.03,  # Réduit car souvent moins discriminant (ou confidentiel)
    "work_mode": 0.02,  # Réduit pour garder une somme totale égale à 1.0
}
# =========================== LLM Defintion ===========================
# LLM 
class LLM:
    def __init__(self, groq_key: str=None):
        self._groq_key = groq_key or os.getenv("GROQ_APP_KEY")
        # Need to pay if groq
        self._enrichement = None

        self.llama3_smart = ChatGroq(model="llama-3.3-70b-versatile", api_key=self._groq_key, temperature=0)
        self.llama4_smart = ChatGroq(model="meta-llama/llama-4-scout-17b-16e-instruct", api_key=self._groq_key, temperature=0)
        # Problem of formatting with this model use an another one
        # self.llm_fast  = ChatGroq(model="llama-3.1-8b-instant", api_key=self._groq_key, temperature=0)
    
    @property
    def enrichement(self):
        """Only import Ollama if the key is requiered"""
        if self._enrichement is None:
            from langchain_ollama import ChatOllama
            self._enrichement = ChatOllama(model="llama3.2", temperature=0)
        return self._enrichement

        
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
    offer_url: str | None   
    source_platform: str | None   
    offer_language: Annotated[list[str], operator.add] | None  
    published_at: str | None   
    collected_at: str

    # ── analytics.job_requirement ──
    seniority: str | None
    alternative_job_titles: Annotated[list[str], operator.add] | None  
    skills_languages: Annotated[list[str], operator.add] | None
    skills_framework: Annotated[list[str], operator.add] | None
    skills_aptitudes: Annotated[list[str], operator.add] | None
    skills_soft: Annotated[list[str], operator.add] | None

    # ── analytics.job_relevancy ──
    score_relevancy: float | None   
    score_details: dict | None   
    explanation: str | None  
    prompt_user_profile: str | None 

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
    contacts: Annotated[list[dict], operator.add]

def map_bronze_to_JobOfferState(row: dict) -> JobOfferState:
    """
    Mapping from database to graph state. (Better for maintenance and debug)
    If a value is absente instantiate None or []
    """
    return {
        # ── keys ──
        "id_job": row["id_job"],
        "id_company": None,
        "id_location": None,

        # ── analytics.job_offer ──
        "api_source": row["api_source"],
        "job_title": row["job_title"],
        "offer_description": row["offer_description"],
        "contract_type": row["contract_type"],
        "is_remote": row["is_remote"],
        "job_publisher": row["job_publisher"],
        "location_raw": row["location_raw"],
        "offer_url": row["offer_url"],
        "source_platform": row["source_platform"],
        "spoken_languages_required": None,
        "published_at": row["published_at"],
        "collected_at": row["collected_at"],

        # ── analytics.job_requirement ──
        "seniority": None,
        "alternative_job_titles": [],
        "skills_languages": [],
        "skills_framework": [],
        "skills_aptitudes": [],
        "skills_soft": [],


        # ── analytics.job_relevancy ──
        "score_relevancy": None,
        "score_details": None,
        "explanation": None,
        "prompt_user_profile": None,

        # ── analytics.company ──
        "company_name": row["company"],          # ⚠️ raw.company → state.company_name
        "company_website": row["company_website"],
        "company_primary_type": None,

        # ── analytics.company_location ──
        "address": None,
        "city": row["city"],
        "country": row["country"],
        "lat": row["latitude"],                   # ⚠️ raw.latitude → state.lat
        "lon": row["longitude"],                   # ⚠️ raw.longitude → state.lon
        "phone": None,
        "business_status": None,

        # ── analytics.company_contact ──
        "contacts": [],
        "search_query_mail": None
    }

    


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
                            ALWAYS REPLY IN ENGLISH even if the task or the text you analyse is in other language.
                            You MUST respond ONLY using the structured format provided, never write a conversational explanation.
                            If no data is found, return null or an empty list. Do not explain why, just do as the explained structure format
                            If no information is available, do not invent one and return null for this field
                        """)
        user = HumanMessage(content=context)

        try:
            response = call_with_retry(lambda: self._llm_structured.invoke([system, user]))
            data = response.model_dump()
            if len(data) == 1:
                return {self._output_key: next(iter(data.values()))}
            return data
        except Exception as e:
            print(f"❌ [{self._output_key}] Erreur pour id_job={state.get('id_job')}: {e}")
            if len(self._schema.model_fields) > 1:
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
    

def make_binary_route_node(primary_key: str, condition: list[str], node_if_true : list[str], node_if_false: list[str]):
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
        location = clean_location_raw(state.get('location_raw'))

        # fallback if location is null or None
        if not location or location == 'null':
            location = state.get('city')
        
        # If no company (shouldn't happen)
        if not company or company == "null":
            return {}

        result = self._geo_api.search_place(company, location)
        if not result:
            print(f"⚠️  find_location: aucun résultat pour {company} @ {location}")
            return {}
        
        result["location_raw"] = location  # overwrite with the cleaned value
        
        if state.get('lat') is not None:
            result['lat'] = state.get('lat')
            result['lon'] = state.get('lon')
            
        # If no coordinate available
        if result.get('lat') is None or result.get('lon') is None:
            return result
        reverse_geocode = reverse_geocoder.search((result['lat'], result['lon']), mode=1)
        geocode = {
            'city': reverse_geocode[0]['admin1'],
            'country': reverse_geocode[0]['cc']
        }
        return result | geocode
    

# Mails
class SearchQueryOutput(BaseModel):
    search_query_mail: str = Field(description="Optimized search query to find HR/recruitment contact email")

class EmailItem(BaseModel):
    email: str
    score: float
    reason: str

class EmailResults(BaseModel):
    emails: list[EmailItem] = Field(
        description="List of relevant contact emails found. Return an empty list [] for the emails field if none are found, do not return an empty array as the entire response."
    )


class FindMails:
    def __init__(self, llm):
        self._generate_query = Extract(
            llm=llm.enrichement, 
            # task=(
            #     "Generate a SHORT and FOCUSED search query (max 4-5 words) to find an HR or recruitment contact email "
            #     "for this company. "
            #     "If the company website is known, use 'site:domain.com' combined with ONE or TWO relevant keywords only "
            #     "(e.g. 'contact' or 'careers', adapted to the local language). "
            #     "Do NOT combine multiple languages or multiple countries in the same query. "
            #     "Pick ONE language based on the offer's country."
            # ),
            task=(
                "Generate ONE single-line search query (no line breaks, no multiple options) "
                "to find an HR or recruitment contact email for this company. "
                "Maximum 8 words. "
                "If you know the company website, use 'site:domain.com' plus ONE keyword like 'contacto' or 'contact'. "
                "Otherwise, just use the company name plus 'contacto email' or 'contact email careers'. "
                "Use Spanish keywords if the company is in Latin America, English otherwise."
            ),
            output_key="search_query_mail",
            schema=SearchQueryOutput,
            fields=["company_name", "city", "country"]
        )
        self._llm_structured = llm.enrichement.with_structured_output(EmailResults)
    
    def __call__(self, state: JobOfferState) -> dict:
        company = state.get("company_name")
        
        if not company or company == 'null':
            print(f"⚠️  find_mails: pas de company_name, recherche annulée — search_query_mail=None")
            return {'contacts': [], 'search_query_mail': None}
        
        query_result = self._generate_query(state)
        search_query_mail = query_result["search_query_mail"]
        print(f"🔍 find_mails: {company} — search_query_mail='{search_query_mail}'")

        # Fallback si le LLM n'a pas pu générer une requête de recherche
        if "\n" in search_query_mail:
            search_query_mail = search_query_mail.replace("\n", " ").strip()
            print(f"⚠️  find_mails: retour à la ligne détecté pour {company}, nettoyé → '{search_query_mail}'")
        if not search_query_mail or search_query_mail.strip().lower() == "null":
            country = state.get("country", "")
            search_query_mail = f"{company} contacto email {country}".strip()
            print(f"⚠️  find_mails: query LLM invalide pour {company}, fallback basique → '{search_query_mail}'")

        results = self._search_ddg(search_query_mail)
        if not results:
            print(f"⚠️  find_mails: aucun résultat DDG pour {company} — search_query_mail='{search_query_mail}'")
            return {"contacts": [], "search_query_mail": search_query_mail}
        print(f"📄 find_mails: {len(results)} caractères reçus pour {company} — search_query_mail='{search_query_mail}'")
                
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
            You MUST respond ONLY using the structured format provided.
            Never write conversational text. Always use the function call format.
            If no email is found, do not write any explanatory text.
            """)

        user = HumanMessage(content=f"Company: {company}\nResult:\n{results}")

        try:
            response = call_with_retry(lambda: self._llm_structured.invoke([system, user]))
            contacts = [item.model_dump() for item in response.emails]
            if not contacts:
                print(f"⚠️  find_mails: LLM n'a trouvé aucun email pour {company} — search_query_mail='{search_query_mail}'")
            else:
                print(f"✅ find_mails: {len(contacts)} contact(s) pour {company} — search_query_mail='{search_query_mail}'")
            return {"contacts": contacts, "search_query_mail": search_query_mail}
        except Exception as e:
            if "'[]'" in str(e) or "failed_generation': '[]'" in str(e):
                print(f"⚠️  find_mails: réponse vide interceptée pour {company} — search_query_mail='{search_query_mail}'")
                # Le LLM a essayé de dire "aucun email" mais dans le mauvais format
                return {"contacts": [], "search_query_mail": search_query_mail}
            print(f"❌ find_mails: erreur pour {company} — search_query_mail='{search_query_mail}': {e}")
            return {"contacts": [], "search_query_mail": search_query_mail}

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
    score_job: float | str | None = Field(
        description=(
            "A score matching on scale from 0 to 10 about the job I search and I could do. "
            "against my profile and the job I search (provided in the system message). "
            "10 = strong overlap with the job I want, 5 = partial/adjacent overlap, 0 = completely unrelated. "
            "If you don't have enough information to score, return null."
        )
    )
    score_skills: float | str | None = Field(
        description=(
            "Skills matching score from 0 to 10, comparing the skills required in this offer "
            "against my profile (provided in the system message). "
            "10 = strong overlap with my skillset, 5 = partial/adjacent overlap, 0 = completely unrelated. "
            "If you don't have enough information to score, return null."
        )
    )
    score_language: float | str | None = Field(
        description=(
            "Language fit score from 0 to 10, comparing the offer's language requirements "
            "against my languages (provided in the system message). "
            "Use this STRICT RUBRIC for professional contexts: "
            "10 = I am Native, C2, or C1 in the required language. "
            "7-8 = I am B2 (working proficiency) and the offer doesn't require native fluency. "
            "2-4 = I am A2 or B1. This is usually INSUFFICIENT for a professional environment unless the offer explicitly accepts beginners. "
            "0 = I do not speak the required language at all. "
            "If the language is not specified or you can't deduce it, return null."
        )
    )
    score_seniority: float | str | None = Field(
        description=(
            "Seniority fit score from 0 to 10, comparing the seniority required by the offer against my "
            "10 = perfect match, 0 = requires a seniority level I don't have. "
            "If seniority is not specified or you can't deduce it, return null."
        )
    )
    score_work_mode: float | str | None = Field(
        description=(
            "Work arrangement fit score from 0 to 10, combining both the work mode (remote/hybrid/on-site) "
            "and the contract type (internship, full-time, part-time, freelance) against my preferences "
            "(provided in the system message). "
            "10 = both work mode and contract type match my preferences, "
            "5 = only one of the two matches, "
            "0 = neither matches. "
            "If you don't have enough information to conclude, return null."
        )
    )
    score_company: float | str | None = Field(
        description=(
            "Company relevance score from 0 to 10 for my career goals (provided in the system message). "
            "If no specific information about the company is available, return null rather than guessing."
        )
    )
    score_location: float | str | None = Field(
        description=(
            "Location fit score from 0 to 10, comparing the offer's location against my target locations "
            "(provided in the system message). "
            "Prioritize city and country if available,  they are the most reliable. "
            "If city and country are both null, fall back on location_raw, which is less precise "
            "but still usable to estimate the score. "
            "If the location is not specified or you can't deduce it, return null."
        )
    )
    explanation: str = Field(
        description=(
            "Short explanation (2-3 sentences) summarizing why this offer is or isn't a good match overall, "
            "based on my profile."
            "Always write it in english"
        )
    )

    @field_validator(
        "score_job", "score_skills", "score_language", "score_seniority",
        "score_work_mode", "score_company", "score_location",
        mode="after"
    )
    @classmethod
    def coerce_and_clamp(cls, v):
        if v is None:
            return None  # Laisse passer le None
        try:
            v_float = float(v)
            return max(0.0, min(10.0, v_float))
        except ValueError:
            return None  # Sécurité supplémentaire si Groq renvoie du texte inexploitable

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
            f"location_raw: {state.get('location_raw')}",
            f"company_name: {state.get('company_name')}",
            f"alternative_job_titles: {state.get('alternative_job_titles')}",
            f"skills_languages: {state.get('skills_languages')}",
            f"skills_framework: {state.get('skills_framework')}",
            f"skills_aptitudes: {state.get('skills_aptitudes')}",
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
            response = call_with_retry(lambda: self._llm_structured.invoke([system, user]))
            data = response.model_dump()
            
            # On extrait l'explication pour la mettre à la racine du State
            explanation = data.pop("explanation", None)
            
            # On met tout le reste (les scores) dans score_details
            return {
                "score_details": data,
                "explanation": explanation,
                "prompt_user_profile": self._profile
            }
        except Exception as e:
            print(f"Error calculate_relevancy for id={state.get('id_job')}: {e}")
            return {
                "score_details": None,
                "explanation": None,
                "prompt_user_profile": self._profile
            }

def calculate_total_score(state: JobOfferState, weights: dict) -> dict:
    """Calculate score based on the result of the LLM."""
    
    # Get dict of differents score attributed by the LLM
    details = state.get("score_details")
    if not details:
        return {"score_relevancy": None}

    # link weight to the scores
    criteria_map = {
        "job":       details.get("score_job"),
        "skills":    details.get("score_skills"),
        "language":  details.get("score_language"),
        "seniority": details.get("score_seniority"),
        "company":   details.get("score_company"),
        "location":  details.get("score_location"),
        "work_mode": details.get("score_work_mode"),
    }

    # Convert in float and remove None values
    valid = {}
    for k, v in criteria_map.items():
        if v is not None:
            try:
                valid[k] = float(v)
            except ValueError:
                pass

    if not valid:
        return {"score_relevancy": None}

    # Calculate score
    total_weight = sum(weights[k] for k in valid if k in weights)
    if total_weight == 0:
        return {"score_relevancy": None}

    weighted_sum = sum(valid[k] * weights[k] for k in valid if k in weights)
    score = round(weighted_sum / total_weight, 2)
    
    # Return the dict to JobOfferState
    return {"score_relevancy": score}