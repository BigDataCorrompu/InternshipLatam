
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
    VARCHAR offer_language
    TIMESTAMPTZ published_at
    TIMESTAMPTZ collected_at
  }
  job_requirement {
    VARCHAR id_offer FK
    VARCHAR seniority
    TEXT[] skills_languages
    TEXT[] skills_frameworks
    TEXT[] skills_aptitudes
    TEXT[] skills_soft_skills
    VARCHAR prompt_version
    TIMESTAMPTZ collected_at
  }
  job_relevancy {
    VARCHAR id_offer FK
    FLOAT score_skills
    FLOAT score_location
    FLOAT score_language
    FLOAT score_seniority
    FLOAT score_contract
    FLOAT score_remote
    FLOAT score_company
    TEXT explanation
    VARCHAR prompt_version
    TIMESTAMPTZ collected_at
  }
  company {
    INT id_company PK
    VARCHAR name_normalized
    VARCHAR website
    TIMESTAMPTZ collected_at
  }
  company_location {
    INT id_location PK
    INT id_company FK
    VARCHAR city
    VARCHAR country
    FLOAT lat
    FLOAT lon
    VARCHAR source
    TIMESTAMPTZ collected_at
  }
  company_contact {
    INT id_contact PK
    INT id_company FK
    VARCHAR city
    VARCHAR country
    VARCHAR email
    VARCHAR source
    TIMESTAMPTZ collected_at
  }
  offer_contact {
    VARCHAR id_offer FK
    INT id_contact FK
    FLOAT confidence
  }

  job_offer }o--|| company : "entreprise"
  job_offer }o--|| company_location : "filiale"
  job_offer ||--o{ job_requirement : "enrichi par LLM"
  job_offer ||--o{ job_relevancy : "scoré par LLM"
  company ||--o{ company_location : "possède"
  company ||--o{ company_contact : "a"
  offer_contact }o--|| job_offer : ""
  offer_contact }o--|| company_contact : ""
```