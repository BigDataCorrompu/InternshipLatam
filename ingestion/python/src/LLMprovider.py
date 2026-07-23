import os
from langchain_ollama import ChatOllama
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mistralai import ChatMistralAI


class LLM:
    def __init__(self, groq_key: str = None, gemini_key: str = None, mistral_key: str = None):
        self._groq_key = groq_key or os.getenv("GROQ_API_KEY")
        self._gemini_key = gemini_key or os.getenv("GEMINI_DASHBOARD_API_KEY")
        self._mistral_key = mistral_key or os.getenv("MISTRAL_API_KEY")

        self._enrichement = None
        self._smart = None
        self._fast = None
        self._mailfinder = None

    @property
    def enrichement(self):
        """Modèle utilisé pour tout le pipeline LangGraph d'enrichissement.
        Un seul endroit à changer pour switcher de provider partout dans le pipeline."""
        if self._enrichement is None:
            self._enrichement = ChatMistralAI(
                model="ministral-8b-2512", 
                mistral_api_key=self._mistral_key,
                temperature=0
            )
        return self._enrichement

    @property
    def fast(self):
        """Light model usefull in graph redirection and dynamic scrapping query"""
        if self._fast is None:
            self._fast = ChatMistralAI(
                model="ministral-8b-2512", 
                mistral_api_key=self._mistral_key,
                temperature=0
            )
        return self._fast
    

    @property
    def smart(self):
        """Light model usefull in graph redirection and dynamic scrapping query"""
        if self._smart is None:
            self._smart = ChatMistralAI(
                model="mistral-small-2603", 
                mistral_api_key=self._mistral_key,
                temperature=0
            )
        return self._smart



    @property
    def mailfinder(self):
        """Intelligent model usefull for """
        if self._mailfinder is None:
            self._mailfinder = ChatGoogleGenerativeAI(
                model="gemini-3.1-flash-lite",
                google_api_key=self._gemini_key,
                temperature=0
            )
        return self._mailfinder
    

   