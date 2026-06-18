# STATE ET NOEUDS
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
import operator
import json
from pydantic import BaseModel
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_groq import ChatGroq
from dotenv import load_dotenv
import os
import sys
sys.path.append("../ingestion/python/src")        

# LLM 
class LLM:
    def __init__(self, groq_key: str=None):
        self._groq_key = groq_key or os.getenv("GROQ_APP_KEY")

        # Problem of formatting with this model use an another one
        # self.llm_fast  = ChatGroq(model="llama-3.1-8b-instant", api_key=self._groq_key, temperature=0)
        self.llama3_smart = ChatGroq(model="llama-3.3-70b-versatile", api_key=self._groq_key, temperature=0)
        self.llama4_smart = ChatGroq(model="meta-llama/llama-4-scout-17b-16e-instruct", api_key=self._groq_key, temperature=0)
        

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
    skills: dict | None   

    # ── analytics.job_relevancy ──
    score_relevancy: float | None   
    score_details: dict | None   
    explanation: str | None   

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
    

# Private State
class CompanyOutput(BaseModel):
    company_name: str | None = Field(description="Nom de l'entreprise qui recrute, ou null si introuvable")


class Extract:
    """ Generic Node LangGraph : extract data structured via LLM """
    def __init__(self, task: str, output_key:str, schema: type[BaseModel], fields: list[str], llm):
        self._task = task               # LLM mission
        self._output_key = output_key   # field output
        self._schema = schema           # Structure of the response
        self._fields = fields            # field input
        self._llm_structured = llm.with_structured_output(schema)


    def __call__(self, state: JobOfferState) -> dict:
        # Define fields accesible in the state
        context = "\n".join(
            f"{field}: {state.get(field)}" for field in self._fields
        )

        # Structure the mission of the LLM with precision
        system = SystemMessage(content=f"""
                            I did an ingestion pipeline gathering job offer via APIs, I did it to find an internship/job automatically.
                            Task : {self._task}
                            If no information in available, return null for this field
                        """)
        user = HumanMessage(content=context)

        try:
            response = self._llm_structured.invoke([system, user])
            data = response.model_dump()
            if len(data) == 1:
                return {self._output_key: next(iter(data.values()))}
            return {self._output_key: data}
        except Exception as e:
            print(f"Erreur extraction {self._output_key} pour id_job={state.get('id_job')}: {e}")
            return {self._output_key: None}
    

    # def get_raw_data(state: JobOfferState, db: Database) -> JobOfferState:
    #     query = """
    #         SELECT         
    #             rjo.id_job, 
    #             rjo.api_source, 
    #             rjo.job_title, 
    #             rjo.contract_type, 
    #             rjo.job_publisher, 
    #             rjo.company, 
    #             rjo.company_website, 
    #             rjo.location_raw,
    #             rjo.city,
    #             rjo.country,
    #             rjo.latitude,
    #             rjo.longitude,
    #             rjo.is_remote,
    #             rjo.offer_description,
    #             rjo.offer_url,
    #             rjo.source_platform,
    #             rjo.published_at,
    #             rjo.collected_at
    #         FROM raw.job_offer rjo
    #         LEFT JOIN analytics.job_offer ajo
    #         ON rjo.id_job = ajo.id_job
    #         WHERE ajo.id_job IS NULL
    #         ORDER BY DESC rjo.collected_at
    #         LIMIT 10;
    #     """
    #     result = db.execture(query)

# llm = LLM()
# extract_company = Extract(
#     llm=llm.llm_fast,
#     task='Find the name of the company who recruit for this job offer based on the title and the description of the job.',
#     output_key='company_name',
#     schema=CompanyOutput,
#     fields=['job_title', 'offer_description']
# )


# test_state = {
#     "job_title": "Bi Engineer Cencosud Media (Santiago Metropolitan Area)",
#     "offer_description": "Descripción del cargoEstamos buscando un/a BI Engineer Pleno para sumarse al equipo de Ecosistema Retail.",
# }

# result = extract_company(test_state)
# print(result)