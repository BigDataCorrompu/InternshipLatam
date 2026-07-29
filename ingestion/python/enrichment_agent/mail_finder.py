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


class MailScrapping:
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
        


