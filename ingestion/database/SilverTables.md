# Schema analytics

```Mermaid
erDiagram
  job_offer {
    VARCHAR id_offer PK
    INT id_company FK
    INT id_location FK
    VARCHAR api_source
    VARCHAR job_title
    TEXT offer_description
    VARCHAR contract_type
    BOOLEAN is_remote
    VARCHAR job_publisher
    VARCHAR location_raw
    VARCHAR offer_url
    VARCHAR source_platform
    TIMESTAMPTZ published_at
    TIMESTAMPTZ collected_at
  }
  job_requirement {
    VARCHAR id_offer FK
    TEXT[] alternative_job_titles
    TEXT[] offer_languages
    VARCHAR seniority
    TEXT[] skills_languages
    TEXT[] skills_frameworks
    TEXT[] skills_aptitudes
    TEXT[] skills_soft
    TEXT prompt_version
    TIMESTAMPTZ collected_at
  }
  job_relevancy {
    VARCHAR id_offer FK
    FLOAT score_relevancy
    FLOAT score_job
    FLOAT score_skills
    FLOAT score_location
    FLOAT score_language
    FLOAT score_seniority
    FLOAT score_work_mode
    FLOAT score_company
    TEXT explanation
    INT id_prompt FK
    TIMESTAMPTZ collected_at
  }
  prompt_relevancy {
    INT id_prompt PK
    TEXT prompt 
  }
  company {
    INT id_company PK
    VARCHAR company_name
    VARCHAR website
    VARCHAR primary_type
    TIMESTAMPTZ collected_at
  }
  company_location {
    INT id_location PK
    INT id_company FK
    VARCHAR address
    VARCHAR city
    VARCHAR country
    FLOAT lat
    FLOAT lon
    VARCHAR phone
    VARCHAR business_status
    VARCHAR source
    TIMESTAMPTZ collected_at
  }
  company_contact {
    INT id_contact PK
    INT id_company FK
    INT id_location FK
    VARCHAR email
    FLOAT confidence
    TEXT explanation
    VARCHAR source
    TIMESTAMPTZ collected_at
  }

  job_offer }o--|| company : "entreprise"
  job_offer }o--|| company_location : "filiale"
  job_offer ||--o{ job_requirement : "enrichi par LLM"
  job_offer ||--o{ job_relevancy : "scoré par LLM"
  job_relevancy }o--|| prompt_relevancy : "possède"
  company ||--o{ company_location : "possède"
  company ||--o{ company_contact : "a"
  company_location ||--o{ company_contact : "rattaché à"
```