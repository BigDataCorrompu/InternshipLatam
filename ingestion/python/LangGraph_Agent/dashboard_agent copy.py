from langchain_core.messages import HumanMessage, ToolMessage*
from langchain_core.tools import tool
from pydantic import BaseModel, field_validator, Field




class FilterUpdate(BaseModel):
    search: str | None = None
    countries: list[str] = []
    cities: list[str] = []
    seniorities: list[str] = []
    remote: bool | None = None
    min_score = int | None = None

class AgentIntent(BaseModel):
    """
    Extract the purpose of the question in one LLM call. 
    It makes the LLM having a strict comportment based 
    on the decision of a previous LLM who extracted the intent of the user
    """
    wants_filter: bool = Field(description="User wants to search/filter offers")
    wants_match: bool = Field(description="User wants to match the offers based on his personnal profile, and gave a description of his skills and what job he want")
    wants_info: bool = Field(description="User is not interested by job offers. He asks a general question about the project/dataset, how to use the page or information about the documentation")

class AgentResponse(BaseModel):
    message: str
    offer_ids: list[str] = []
    filters_changed: bool = False



