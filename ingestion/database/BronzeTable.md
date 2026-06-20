```mermaid
erDiagram
    job_offer {
        VARCHAR id_job
        VARCHAR api_source

        VARCHAR job_title
        VARCHAR contract_type
        VARCHAR job_publisher

        VARCHAR company
        VARCHAR company_website

        VARCHAR location_raw
        VARCHAR city
        VARCHAR country
        FLOAT latitude
        FLOAT longitude
        BOOLEAN is_remote

        VARCHAR offer_url
        BOOLEAN is_direct
        VARCHAR source_platform

        TEXT offer_description
        TEXT job_highlights

        VARCHAR salary_raw
        FLOAT salary_min
        FLOAT salary_max
        VARCHAR salary_period

        TIMESTAMPTZ published_at
        TIMESTAMPTZ collected_at

        JSONB query_parameters
    }
```