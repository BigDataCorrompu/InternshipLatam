from abc import ABC, abstractmethod
import os
import requests
import base64
from typing import Callable
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# Gestion quota api
import logging
logger = logging.getLogger(__name__)

# Gestion quota api
class QuotaExceededError(Exception):
    """Levée quand l'API signale un quota/crédit épuisé (HTTP 429)."""
    pass

# ──────────────────────────────────────────
# Parent API
# ──────────────────────────────────────────
class API(ABC):
    # Nom du paramètre de pagination envoyé à l'API.
    # Surchargé par chaque sous-classe ("cursor" pour Jsearch, "page" pour CareerJet).
    PAGE_PARAM = "page"


    def __init__(self, api_key):
        self.api_key = api_key
        self.quota_exceeded = False

    def _generate_params(self, params: dict, **kwargs):
        for key, val in kwargs.items():
            params[key] = ','.join(str(v) for v in val) if isinstance(val, list) else val
        return params
    
        
    def _call(self, endpoint: str, params: dict):
        url = self.BASE_URL + self.ENDPOINTS[endpoint]
        response = requests.get(url, headers=self.headers, params=params)
        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code} : {response.text}")
        
        # Gestion quota api
        if response.status_code == 429:                      
            raise QuotaExceededError(response.text[:200])
        
        return response.json()


    def _paginate(self, endpoint_func: Callable, max_pages: int = None, **kwargs):
        """
        Pagination générique pour toutes les APIs.
        Le jeton de page suivante est envoyé sous self.PAGE_PARAM
        (Jsearch -> 'cursor', CareerJet -> 'page').
        La première page est demandée SANS paramètre de pagination.
        max_pages (optionnel) plafonne le nombre de pages pour ménager le quota.
        """
        try:
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
        # Gestion quota api
        except QuotaExceededError:
            self.quota_exceeded = True
            logger.warning(f"Quota exhausted — pagination stopped, {len(all_results)} results retained")
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


class JobAPI(API):
    @abstractmethod
    def search_jobs(self):
        pass

class GeoAPI(API):
    @abstractmethod
    def search_place(self) -> dict | None:
        pass

    def _extract_results(self, response: dict) -> list:
        return response.get("places", [])

    def _has_next_page(self, response: dict) -> bool:
        return False  # Places Text Search (New) n'a pas de pagination par défaut

    def _next_page(self, response: dict) -> dict:
        raise NotImplementedError("Pas de pagination pour cette API")


# ──────────────────────────────────────────
# Google Maps
# ──────────────────────────────────────────
class PlacesAPI(GeoAPI):
    BASE_URL = 'https://places.googleapis.com'
    ENDPOINTS = {
        "search_text": 'v1/places:searchText'
    }
    def __init__(self, api_key: str = None):
        super().__init__(api_key or os.getenv('MAPS_APP_KEY'))
        self.headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": (
                "places.displayName,"
                "places.formattedAddress,"
                "places.location,"
                "places.internationalPhoneNumber,"
                "places.websiteUri,"
                "places.rating,"
                "places.userRatingCount,"
                "places.businessStatus,"
                "places.primaryType,"
            )
        }

    def search_place(self, company: str, location: str, **kwargs):
        params = {"textQuery": f"{company}, {location}"}
        params = self._generate_params(params, **kwargs)
        result = self._call("search_text", params)
        if not result:
            return
        return self._map_result_PlacesAPI(result.get("places")[0])

    def _call(self, endpoint: str, params: dict):
        url = self.BASE_URL + "/" + self.ENDPOINTS[endpoint]
        response = requests.post(url, headers=self.headers, json=params)  # POST + json
        if response.status_code == 429:
            raise QuotaExceededError(response.text[:200])

        if response.status_code != 200:
            raise Exception(f"HTTP {response.status_code} : {response.text}")
        return response.json()

    def _map_result_PlacesAPI(self, result: dict) -> dict:
        """Maps raw Google Places result to JobOfferState keys."""
        return {
            # company 
            "company_name":         result.get("displayName", {}).get("text"),
            "company_primary_type": result.get("primaryType"),
            "company_website":      result.get("websiteUri"),

            # company_location 
            "address":              result.get("formattedAddress"),
            "lat":                  result.get("location", {}).get("latitude"),
            "lon":                  result.get("location", {}).get("longitude"),
            "phone":                result.get("internationalPhoneNumber"),
            "business_status":      result.get("businessStatus"),
            "rating":               result.get("rating"),
            "rating_count":         result.get("userRatingCount"),
        }



# ──────────────────────────────────────────
# Jsearch/CareerJet
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


    def __init__(self, api_key: str = None):
        super().__init__(api_key or os.getenv('JSEARCH_APP_KEY'))
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


    def __init__(
        self, 
        api_key: str = None,
        user_ip: str = None,        # Mandatory careerjet call API
        user_agent: str = None,     # Mandatory careerjet call API
        days_max_offer: int = 3,
    ):
        super().__init__(api_key or os.getenv('CAREERJET_APP_KEY'))
        credentials = base64.b64encode(f"{self.api_key}:".encode()).decode()
        self.user_ip    = user_ip or os.getenv('SERVER_IP')
        self.user_agent = user_agent or os.getenv('CAREERJET_USER_AGENT', 'InternshipLatam/1.0')
        # L'API v4 exige un Referer correspondant au site déclaré dans le compte publisher
        self.referer    = os.getenv('CAREERJET_REFERER')
        self.headers = {
            "Authorization": f"Basic {credentials}"
        }
        if self.referer:
            self.headers["Referer"] = self.referer


        self.days_max_offer = days_max_offer
        

    # ___________ PAGINATION ___________
    def _extract_results(self, raw: dict) -> str:
        return raw.get("jobs", [])

    def _has_next_page(self, raw: dict, page) -> bool:
        if page >= raw.get("pages", 1):
            return False
        jobs = raw.get("jobs")
        if not jobs:  # Prevent index error
            return False
        last_date = parsedate_to_datetime(jobs[-1]['date'])   
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_max_offer)
        return last_date >= cutoff         # return if we are still in the desired plage

    def _next_page(self, raw: dict, page) -> int:
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