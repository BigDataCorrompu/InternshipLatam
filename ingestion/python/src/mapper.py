from dataclasses import dataclass, asdict, field
from typing import Optional
from abc import ABC, abstractmethod
import hashlib
import json
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, field, fields, astuple
from typing import Optional, Type

@dataclass
class JobOffer:
    # Identifiants
    id_job:           str
    api_source:       str

    # Offre
    job_title:        str | None = None
    contract_type:    str | None = None
    job_publisher:    str | None = None      # "Bumeran", "LinkedIn"...

    # Entreprise
    company:          str | None = None
    company_website:  str | None = None

    # Localisation
    location_raw:     str | None = None
    city:             str | None = None
    country:          str | None = None
    latitude:         float | None = None
    longitude:        float | None = None
    is_remote:        bool | None = None

    # Candidature
    offer_url:        str  | None = None  
    is_direct:        bool | None = None
    source_platform:  str  | None = None

    # Description
    offer_description: str | None = None
    job_highlights:    str | None = None      # JSON sérialisé
    experience_level:  str | None = None  # ajout

    # Salaire
    salary_raw:       str | None = None
    salary_min:       float | None = None
    salary_max:       float | None = None
    salary_period:    str | None = None

    # Dates
    published_at:     str | None = None   # FOUILLER "job_posted_at" si date est null
    collected_at:     str | None = None   # DEFAULT NOW() géré en SQL
    


class Mapper(ABC):
    def __init__(self, source):
        self.source = source

    @abstractmethod 
    def normalise(self, raw: dict) -> tuple:
        pass



class JobMapper(Mapper):
    @staticmethod
    def getColumns(dataclass: Type[JobOffer]=JobOffer) -> list:
        return [f.name for f in fields(dataclass)]

    def getJobs(self, raw:dict) -> list:
        """ return a list of tuples representing each lines in databases"""
        data = self._findJobs(raw)
        jobs = [self.normalise(job) for job in data]
        return jobs
    
    def getData(self, raw: dict) -> dict:
        """ Return dictionnary : columns & data ready to bulk_insert into database"""
        jobs = self.getJobs(raw)
        return {
            "columns"   : self.getColumns(),
            "data"      : [astuple(job) for job in jobs]
        }

    @abstractmethod 
    def _findJobs(self, raw:dict) -> dict:
        """ Find jobs in the raw file """
        pass

class CareerjetMapper(JobMapper):
    def __init__(self):
        super().__init__(source='careerjet')
    
    def _findJobs(self, raw:dict) -> dict:
        return raw.get("raw", {}).get("jobs", [])
    
    def normalise(self, data: dict) -> tuple:
        return JobOffer(
            id_job            = "cj_" + hashlib.md5(data.get("url", "").encode()).hexdigest()[:20],
            api_source        = self.source,
            job_title         = data.get("title"),
            contract_type     = None,                    # pas disponible Careerjet
            job_publisher     = None,                    # pas disponible Careerjet
            company           = data.get("company"),
            company_website   = None,                    # pas disponible Careerjet
            location_raw      = data.get("locations"),
            city              = data.get("locations"),   # locations = ville directement
            country           = None,                    # à inférer depuis locale_code
            latitude          = None,
            longitude         = None,
            is_remote         = None,
            offer_url         = data.get("url"),
            is_direct         = None,
            source_platform   = data.get("site") or None,  # souvent vide → None
            offer_description = data.get("description"),
            job_highlights    = None,
            experience_level  = None,
            salary_raw        = data.get("salary") or None,  # souvent vide → None
            salary_min        = None,                    # pas structuré Careerjet
            salary_max        = None,
            salary_period     = None,
            collected_at      = datetime.utcnow().isoformat(),
            published_at      = self._parse_date(data.get("date"))
        )
    
    def _parse_date(self, date_str: str) -> str | None:
        """Parse date RFC 2822 Careerjet → ISO format."""
        if not date_str:
            return None
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str).isoformat()
        except:
            return None

class JsearchMapper(JobMapper):
    def __init__(self, experience_level: str=None):
        super().__init__(source='jsearch')
        self.experience_level = experience_level

    def _findJobs(self, raw:dict) -> list:
        return raw.get("raw", {}).get("data", {}).get("jobs", [])

    def normalise(self, data: dict) -> tuple:
        types     = data.get("job_employment_types", [])
        highlights = data.get("job_highlights")

        return JobOffer(
            id_job            = data.get("job_id"),
            api_source        = self.source,
            job_title         = data.get("job_title"),
            contract_type     = types[0] if types else None,
            job_publisher     = data.get("job_publisher"),
            company           = data.get("employer_name"),
            company_website   = data.get("employer_website"),
            location_raw      = data.get("job_location"),
            city              = data.get("job_city"),
            country           = data.get("job_country"),
            latitude          = data.get("job_latitude"),
            longitude         = data.get("job_longitude"),
            is_remote         = data.get("job_is_remote"),
            offer_url         = data.get("job_apply_link"),
            is_direct         = data.get("job_apply_is_direct"),
            source_platform   = data.get("job_publisher"),
            offer_description = self._extract_description(data.get("job_description")),
            job_highlights    = json.dumps(highlights) if highlights else None,
            experience_level  = self.experience_level,
            salary_raw        = data.get("job_salary_string"),
            salary_min        = data.get("job_min_salary"),
            salary_max        = data.get("job_max_salary"),
            salary_period     = data.get("job_salary_period"),
            collected_at      =  datetime.utcnow().isoformat(),
            published_at      = self._parse_posted_at(          
                                    data.get("job_posted_at"),
                                    data.get("job_posted_at_datetime_utc"),
            
            ),
        )


    def _parse_posted_at(self, job_posted_at: str, job_posted_at_utc: str) -> str | None:
        """Retourne la date UTC si dispo, sinon calcule depuis 'hace X días'."""
        
        # ✅ Date UTC disponible — priorité
        if job_posted_at_utc:
            return job_posted_at_utc

        if not job_posted_at:
            return None

        now = datetime.utcnow()

        # "hace 5 días" / "hace 1 día"
        match = re.search(r'hace\s+(\d+)\s+d[ií]a', job_posted_at, re.IGNORECASE)
        if match:
            days = int(match.group(1))
            return (now - timedelta(days=days)).isoformat()

        # "hace 2 semanas"
        match = re.search(r'hace\s+(\d+)\s+semana', job_posted_at, re.IGNORECASE)
        if match:
            weeks = int(match.group(1))
            return (now - timedelta(weeks=weeks)).isoformat()

        # "hace 1 mes"
        match = re.search(r'hace\s+(\d+)\s+mes', job_posted_at, re.IGNORECASE)
        if match:
            months = int(match.group(1))
            return (now - timedelta(days=months * 30)).isoformat()

        return None
    
    def _extract_description(self, description) -> str | None:
        """Extrait le texte brut depuis BlockNote JSON ou retourne la string directement."""
        if not description:
            return None
        
        # Si c'est déjà une string normale
        if isinstance(description, str):
            try:
                blocks = json.loads(description)
            except (json.JSONDecodeError, TypeError):
                return description  # texte brut — retourne tel quel
        else:
            blocks = description

        # Extraire le texte de chaque bloc
        texts = []
        for block in blocks:
            for content in block.get("content", []):
                if content.get("type") == "text":
                    texts.append(content.get("text", ""))
        
        return " ".join(texts).strip() or None
    

if __name__ == '__main__':
    
    with open("../ingestion/python/results/005/jsearch_search.json", "r", encoding="utf-8") as f:
        jsearchdata = json.load(f)

    with open("../ingestion/python/results/005/careerjet_search.json", "r", encoding="utf-8") as f:
        careerjetdata = json.load(f)


    c = CareerjetMapper()
    j = JsearchMapper()

    columns = j.getColumns()
    jobsC = c.getJobs(careerjetdata)
    jobsJ = c.getJobs(jsearchdata)
