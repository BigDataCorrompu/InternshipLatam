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
from dotenv import load_dotenv
import operator
from typing import Annotated
import os
import sys
sys.path.append("../ingestion/python/src")     
from database import Database
from LLMprovider import LLM
from APIendpoint import GeoAPI  
import reverse_geocoder
from ddgs import DDGS
import re
import time
from silver_enrichment import Extract, call_with_retry
from langchain_google_genai import ChatGoogleGenerativeAI



# ___ Scrapping queries __________________________________________
class SearchQueryOutput(BaseModel):
    search_queries_mails: list[str] = Field(
        description=(
            "List of up to 3 short, focused search queries to find contact emails at this company. "
            "Target different departments: HR/recruitment, IT/Data Engineering team, and general manager/direction. "
            "Each query must be a single line, max 8 words."
        )
    )

# ___ Mails __________________________________________
class EmailItem(BaseModel):
    email: str
    score: float
    reason: str

class EmailResults(BaseModel):
    emails: list[EmailItem] = Field(
        description="List of relevant contact emails found. Return an empty list [] for the emails field if none are found, do not return an empty array as the entire response."
    )

# ___ Company data __________________________________________
class CompanyState(TypedDict):
    id_company: int
    company_name: str
    website: str
    primary_type: str

    id_location: int
    city: str
    country: str


    highest_grade: float
    average_grades: float
    emails: EmailResults


class MailScrapping:
    def __init__(self, llm):
        self._generate_query = Extract(
            llm=llm.smart, 
            task=(
                "Generate UP TO 3 short search queries to find contact emails at this company, "
                "each targeting a DIFFERENT department:\n"
                "1. IT / Data Engineering team contact (e.g. 'equipo data', 'IT department', 'data engineer team')\n"
                "2. HR / recruitment contact (e.g. 'RRHH', 'recursos humanos', 'talent acquisition')\n"
                "3. General manager / direction contact (e.g. 'gerente general', 'direccion')\n"
                "If you know the company website, use 'site:domain.com' plus ONE relevant keyword per query. "
                "Otherwise, use the company name plus a department keyword. "
                "Each query must be a SINGLE LINE, max 8 words, no line breaks. "
                "Use the location to determine the language queries for exemple Spanish for Latin America "
                "Return fewer than 3 queries only if a department is clearly irrelevant for this company."
            ),
            output_key="search_queries_mails",
            schema=SearchQueryOutput,
            fields=["company_name", "website", "city", "country", "primary_type"]
        )
        self._llm_structured = llm.mailfinder.with_structured_output(EmailResults)
    
    def __call__(self, state: CompanyState) -> dict:
        company = state.get("company_name")
        
        if not company or company == 'null':
            print(f"⚠️  find_mails: pas de company_name, recherche annulée — search_query_mail=None")
            return {'contacts': [], 'search_queries_mail': None}
        
        query_result = self._generate_query(state)
        search_queries_mails = query_result["search_queries_mails"]
        print(f"🔍 find_mails: {company} — search_queries_mails='{query_result}'")

        # Nettoyage + fallback si le LLM n'a produit aucune query exploitable
        cleaned_queries = []
        for q in (search_queries_mails or []):
            q = q.replace("\n", " ").strip()
            if q and q.lower() != "null":
                cleaned_queries.append(q)

        if not cleaned_queries:
            country = state.get("country", "")
            cleaned_queries = [f"{company} RRHH contacto email {country}".strip()]
            print(f"⚠️  find_mails: aucune query LLM valide pour {company}, fallback basique → '{cleaned_queries[0]}'")

        # cleaned_queries = cleaned_queries[:3]  # garde-fou, même si le LLM a déjà pour consigne max 3

        # Concaténation de tous les résultats DDG en un seul bloc (économique : 1 seul appel LLM d'extraction)
        combined_results = []
        for q in cleaned_queries:
            result = self._search_ddg(q)
            if result:
                combined_results.append(f"[Query: {q}]\n{result}")
            else:
                print(f"⚠️  find_mails: aucun résultat DDG pour {company} — query='{q}'")

        if not combined_results:
            print(f"⚠️  find_mails: aucun résultat DDG sur toutes les queries pour {company}")
            return {"contacts": [], "search_queries_mail": cleaned_queries}

        results_text = "\n\n".join(combined_results)
        print(f"📄 find_mails: {len(results_text)} caractères reçus pour {company} — {len(cleaned_queries)} query(ies)")

                
        system = SystemMessage(content="""
            You are an assistant that extracts company contact emails.
            I am looking to apply for a job/internship at this company.
            From the search results provided, identify the most relevant emails.
            1. Technical/data/IT team emails (score 0.8-1.0)
            2. HR/recruitment emails (score 0.8-1.0)
            3. CEO/executive (score 0.6-0.8)
            4. Generic emails info@/contact@ (score 0.3-0.5)
            ONLY use emails present in the provided search results.
            NEVER generate an email from your general knowledge.
            You MUST respond ONLY using the structured format provided.
            Never write conversational text. Always use the function call format.
            If no email is found, do not write any explanatory text.
            """)

        user = HumanMessage(content=f"Company: {company}\nResults:\n{results_text}")


        try:
            response = call_with_retry(lambda: self._llm_structured.invoke([system, user]))
            contacts = [item.model_dump() for item in response.emails]
            if not contacts:
                print(f"⚠️  find_mails: LLM n'a trouvé aucun email pour {company}")
            else:
                print(f"✅ find_mails: {len(contacts)} contact(s) pour {company}")
            return {"contacts": contacts, "search_queries_mail": cleaned_queries}
        except Exception as e:
            if "'[]'" in str(e) or "failed_generation': '[]'" in str(e):
                print(f"⚠️  find_mails: réponse vide interceptée pour {company}")
                return {"contacts": [], "search_queries_mail": cleaned_queries}
            print(f"❌ find_mails: erreur pour {company}: {e}")
            return {"contacts": [], "search_queries_mail": cleaned_queries}

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
        



class MailGrounder:
    def __init__(self, llm):
        # Modèle avec grounding Google Search natif activé
        self._grounded_llm = llm.grounder,
        self._llm_structured = llm.mailfinder.with_structured_output(EmailResults)

    def __call__(self, state: CompanyState) -> dict:
        company = state.get("company_name")

        if not company or company == 'null':
            print(f"⚠️  find_mails (grounder): pas de company_name, recherche annulée")
            return {'contacts': [], 'grounding_used': False}

        website = state.get("website", "")
        country = state.get("country", "")
        city = state.get("city", "")

        prompt = (
            f"Find contact emails for {company}"
            f"{f' (website: {website})' if website else ''}, located in {city}, {country}. "
            "I am looking to apply for a job/internship. "
            "Search for HR/recruitment contacts, IT/Data Engineering team contacts, "
            "general manager/direction contacts, or generic contact emails. "
            "Report every email address you find, along with where you found it."
        )

        try:
            response = call_with_retry(lambda: self._grounded_llm.invoke(prompt))
            grounded_text = response.content
            print(f"🌐 find_mails (grounder): {len(grounded_text)} caractères groundés pour {company}")
        except Exception as e:
            print(f"❌ find_mails (grounder): erreur grounding pour {company}: {e}")
            return {"contacts": [], "grounding_used": False}

        if not grounded_text or not grounded_text.strip():
            print(f"⚠️  find_mails (grounder): réponse groundée vide pour {company}")
            return {"contacts": [], "grounding_used": True}

        system = SystemMessage(content="""
            You are an assistant that extracts company contact emails.
            I am looking to apply for a job/internship at this company.
            From the search results provided, identify the most relevant emails.
            1. Technical/data/IT team emails (score 0.8-1.0)
            2. HR/recruitment emails (score 0.8-1.0)
            3. CEO/executive (score 0.6-0.8)
            4. Generic emails info@/contact@ (score 0.3-0.5)
            ONLY use emails present in the provided search results.
            NEVER generate an email from your general knowledge.
            You MUST respond ONLY using the structured format provided.
            Never write conversational text. Always use the function call format.
            If no email is found, do not write any explanatory text.
            """)

        user = HumanMessage(content=f"Company: {company}\nResults:\n{grounded_text}")

        try:
            structured_response = call_with_retry(lambda: self._llm_structured.invoke([system, user]))
            contacts = [item.model_dump() for item in structured_response.emails]
            if not contacts:
                print(f"⚠️  find_mails (grounder): aucun email extrait pour {company}")
            else:
                print(f"✅ find_mails (grounder): {len(contacts)} contact(s) pour {company}")
            return {"contacts": contacts, "grounding_used": True}
        except Exception as e:
            if "'[]'" in str(e) or "failed_generation': '[]'" in str(e):
                print(f"⚠️  find_mails (grounder): réponse vide interceptée pour {company}")
                return {"contacts": [], "grounding_used": True}
            print(f"❌ find_mails (grounder): erreur extraction pour {company}: {e}")
            return {"contacts": [], "grounding_used": True}