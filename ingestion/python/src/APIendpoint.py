from abc import ABC, abstractmethod
import os
import requests
import base64
from typing import Callable



# ──────────────────────────────────────────
# Parent API
# ──────────────────────────────────────────
class BaseAPI(ABC):
    # Nom du paramètre de pagination envoyé à l'API.
    # Surchargé par chaque sous-classe ("cursor" pour Jsearch, "page" pour CareerJet).
    PAGE_PARAM = "page"

    def __init__(self, api_key):
        self.api_key = api_key

    def _generate_params(self, params: dict, **kwargs):
        for key, val in kwargs.items():
            params[key] = ','.join(str(v) for v in val) if isinstance(val, list) else val
        return params
    
    def normalize(self, raw: dict) -> dict:
        pass
        
    def _call(self, endpoint: str, params: dict):
        url = self.BASE_URL + self.ENDPOINTS[endpoint]
        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code} : {response.text}")
        return response.json()


    def _paginate(self, endpoint_func: Callable, max_pages: int = None, **kwargs):
        """
        Pagination générique pour toutes les APIs.
        Le jeton de page suivante est envoyé sous self.PAGE_PARAM
        (Jsearch -> 'cursor', CareerJet -> 'page').
        La première page est demandée SANS paramètre de pagination.
        max_pages (optionnel) plafonne le nombre de pages pour ménager le quota.
        """
        all_results = []
        page_num = 1
        raw = endpoint_func(**kwargs)                 # page 1 : pas de jeton
        all_results.extend(self._extract_results(raw))

        pages_done = 1
        while self._has_next_page(raw, page_num) and (max_pages is None or pages_done < max_pages):
            token = self._next_page(raw, page_num)
            raw = endpoint_func(**{self.PAGE_PARAM: token}, **kwargs)
            page_num = token if isinstance(token, int) else page_num + 1
            all_results.extend(self._extract_results(raw))
            pages_done += 1

        return all_results
    
    @abstractmethod
    def _extract_results(self, raw:dict):
        """Extract list of result from raw response"""
        pass

    @abstractmethod
    def _has_next_page(self, raw: dict, page):
        """Verify if there's page left"""
        pass

    @abstractmethod
    def _next_page(self, raw: dict, page):
        """return crusor or number of next page"""
        pass


class JobAPI(BaseAPI):
    @abstractmethod
    def search_jobs(self):
        pass



class CompanyAPI(BaseAPI):
    @abstractmethod
    def search_company(self):
        pass



# ──────────────────────────────────────────
# Jsearch/CareerJet/OpenCorporate API
# ──────────────────────────────────────────
class JsearchAPI(JobAPI):
    BASE_URL = "https://jsearch.p.rapidapi.com"
    PAGE_PARAM = "cursor"
    ENDPOINTS = {
        "search": "/search-v2",
        "details": "/job-details",
        "salary": "/estimated-salary",
        "company_salary": "/company-job-salary"
    }


    def __init__(self):
        super().__init__(os.getenv('JSEARCH_APP_KEY'))
        self.headers = {
            "Content-Type": "application/json",
            "x-rapidapi-host": "jsearch.p.rapidapi.com",
            "x-rapidapi-key": self.api_key
        }

    # ___________ PAGINATION ___________
    def _extract_results(self, raw: dict):
        # /search-v2 -> data.jobs ; ancien /search -> data en liste
        data = raw.get("data", {})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("jobs", [])
        return []

    def _has_next_page(self, raw: dict, page):
        data = raw.get("data", {})
        return isinstance(data, dict) and data.get("cursor") is not None

    def _next_page(self, raw: dict, page):
        data = raw.get("data", {})
        return data.get("cursor") if isinstance(data, dict) else None

    # ___________ ENDPOINT ___________
    def search_jobs(self, query: str, paginate: bool=False, max_pages: int=None, **kwargs):
        """ 
        Search offert in a database 
        (Batch flux) 
        from LinkedIn, Indeed, Glassdoor...
        """
        if paginate:
            return self._paginate(self.search_jobs, max_pages=max_pages, query=query, **kwargs)
        params = {'query': query}
        params = self._generate_params(params, **kwargs)
        raw = self._call('search', params)
        return raw

    
    def get_details(self, job_id: str, **kwargs):
        """ 
        Search details for an offer by id
        Support  batching up to 20 IDs per request
        """
        params = {'job_id': job_id}
        params = self._generate_params(params, **kwargs)
        raw = self._call('details', params)
        return raw


    def get_salary(self, location: str, job_title: str, **kwargs):
        """Salarial estimation per 'localisation' and 'job title'"""
        params = {
            'location': location, 
            'job_title': job_title
            }
        params = self._generate_params(params, **kwargs)
        raw = self._call('salary', params)
        return raw
    
    def get_company_salary(self, company: str, job_title: str, **kwargs):
        """Salarial estimation per 'company' and 'job title'"""
        params = {
            'company': company, 
            'job_title': job_title
            }
        params = self._generate_params(params, **kwargs)
        raw = self._call('company_salary', params)
        return raw
   


class CareerJetAPI(JobAPI):
    BASE_URL = "https://search.api.careerjet.net"
    PAGE_PARAM = "page"
    ENDPOINTS = {
        "search": "/v4/query"
    }


    def __init__(self):
        super().__init__(os.getenv('CAREERJET_APP_KEY'))
        credentials = base64.b64encode(f"{self.api_key}:".encode()).decode()
        self.user_ip    = os.getenv('SERVER_IP')
        self.user_agent = os.getenv('CAREERJET_USER_AGENT', 'InternshipLatam/1.0')
        # L'API v4 exige un Referer correspondant au site déclaré dans le compte publisher
        self.referer    = os.getenv('CAREERJET_REFERER')
        self.headers = {
            "Authorization": f"Basic {credentials}"
        }
        if self.referer:
            self.headers["Referer"] = self.referer

    # ___________ PAGINATION ___________
    def _extract_results(self, raw: dict):
        return raw.get("jobs", [])

    def _has_next_page(self, raw: dict, page):
        return page < raw.get("pages", 1)

    def _next_page(self, raw: dict, page):
        return page + 1

    # ___________ ENDPOINT ___________
    def search_jobs(self, paginate: bool=False, max_pages: int=None, **kwargs):
        if paginate:
            return self._paginate(self.search_jobs, max_pages=max_pages, **kwargs)
        params = {
            'user_ip': self.user_ip,
            'user_agent': self.user_agent
        }
        params = self._generate_params(params, **kwargs)
        raw = self._call('search', params)
        return raw