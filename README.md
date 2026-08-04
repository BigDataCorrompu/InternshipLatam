# InternshipLatam 🌎

An automated end-to-end data pipeline that collects, enriches, and scores Data Engineering internship opportunities across Latin America — built as both a personal job-search tool and a portfolio project.

> **Target locations:** Santiago 🇨🇱 · Buenos Aires 🇦🇷 · Montevideo 🇺🇾

> 📖 **Full documentation:** [internshiplatam.streamlit.app/doc](https://internshiplatam.streamlit.app/doc) — detailed pipeline docs also available in [`/docs`](./docs)

---

## What it does

Most job boards give you a list. This pipeline gives you a ranked, enriched dataset — with company contacts, relevancy scores, and an interactive dashboard — fully automated and running on a schedule.

1. **Collects** job offers from JSearch (RapidAPI) and CareerJet across Chile, Argentina, and Uruguay
2. **Lands** raw JSON payloads in Backblaze B2 (immutable object storage)
3. **Stores** structured data in a Bronze layer on Neon PostgreSQL (cloud)
4. **Enriches** each offer through a LangGraph pipeline: company extraction, geolocation, skill parsing, contact discovery, and LLM-based relevancy scoring
5. **Serves** the results through a Streamlit dashboard with an AI agent for conversational data exploration

---

## Architecture

```
APIs (JSearch, CareerJet)
        │
        ▼
[ Backblaze B2 ]  ──── immutable landing zone (raw JSON)
        │
        ▼
[ Bronze Layer ]  ──── raw.job_offer (Neon PostgreSQL)
        │
        ▼
[ LangGraph Enrichment Pipeline ]
  ├── Company extraction + anti-hallucination verification
  ├── Offer attributes (seniority, contract type, language, remote)
  ├── Skills extraction (languages, frameworks, aptitudes, soft skills)
  ├── Geolocation via Google Maps Places API
  ├── Contact discovery (DuckDuckGo + LLM extraction)
  └── Relevancy scoring (6 weighted criteria, LLM-based)
        │
        ▼
[ Silver Layer ]  ──── analytics.* (Neon PostgreSQL)
        │
        ▼
[ Gold / Serving Layer ]  ──── serving.* (Neon PostgreSQL)
        │
        ▼
[ Streamlit Dashboard ]  ──── Plotly map + AI agent (Mistral Small)
```

All orchestrated by **Apache Airflow** (TaskFlow API, Dataset-driven DAG chaining) running on an OVH VPS via Docker Compose.

---

## LangGraph Enrichment — Silver Pipeline

The core of the project is a `StateGraph` that processes each job offer through specialized nodes:

| Node | Role | Tools |
|---|---|---|
| `extract_company` | Extract company name from offer text | LLM |
| `verify_company` | Anti-hallucination fuzzy match check | — |
| `extract_attributes` | Seniority, remote, contract type, language | LLM |
| `find_location` | Company address, coordinates, website | Google Maps Places API |
| `find_mails` | HR/recruitment contact discovery | DuckDuckGo + LLM |
| `extract_skills` | Languages, frameworks, aptitudes, soft skills | LLM |
| `determine_relevancy` | 6-criteria relevancy scoring against candidate profile | LLM |
| `calculate_relevancy` | Weighted score aggregation | — |

**Design principles:**
- LLM never writes directly to DB — it produces JSON, Python validates, Python inserts
- Stable context prefix architecture enables high Mistral prompt cache hit rates
- `lingua` language detector as a post-LLM correction layer for language detection

---

## Stack

| Layer | Technology |
|---|---|
| Orchestration | Apache Airflow (TaskFlow API), Docker Compose |
| Object storage | Backblaze B2 (immutable landing zone) |
| Database | Neon PostgreSQL (Bronze / Silver / Gold medallion) |
| LLM — enrichment | Mistral (Ministral 8B) |
| LLM — dashboard agent | Mistral Small |
| LLM — contact discovery | Gemini Flash |
| Agent framework | LangGraph `StateGraph`, LangChain |
| Data validation | Pydantic (`mode="after"` validators) |
| Geolocation | Google Maps Places API + `reverse_geocoder` |
| Contact discovery | DuckDuckGo Search (DDGS), Hunter.io (last resort) |
| Frontend | Streamlit Cloud, Plotly `scatter_mapbox` |
| Job sources | JSearch (RapidAPI), CareerJet |

---

## Dashboard

The Streamlit dashboard exposes the Gold layer with:
- Interactive map (Plotly `scatter_mapbox`) with density/selection overlay
- Bidirectional map ↔ table selection
- A bounded ReAct AI agent (Mistral Small, max 4 iterations) with 3 tools: filters, web search (Tavily), and direct data queries
- Conversational memory across the session

→ **[internshiplatam.streamlit.app](https://internshiplatam.streamlit.app/doc)**

---

## Repository structure

```
├── data_vis/                       # Streamlit dashboard
│   ├── streamlit_app.py
│   ├── dashboard_agent.py          # ReAct AI agent
│   ├── agent/                      # Agent tools (filters, web search)
│   └── views/                      # Dashboard, insights, doc pages
├── database/
│   ├── migration/                  # Ordered SQL migrations (001→008)
│   └── sql/
│       └── staging_to_silver/      # Silver transformation SQL files
├── docs/                           # Detailed technical documentation
│   ├── Pipeline.md
│   ├── LangGraph_architecture.md
│   ├── BronzeTable.md
│   ├── SilverTables.md
│   ├── GoldTable.md
│   └── ...
├── ingestion/
│   ├── airflow/dags/               # Airflow DAGs (fetch, enrich, load, mail)
│   ├── config/                     # JSearch & CareerJet search configs
│   └── python/
│       ├── enrichment_agent/       # LangGraph graph + silver enrichment nodes
│       └── src/                    # Shared utilities (DB, LLM, bucket, API)
├── docker-compose.yml
└── requirements-*.txt              # Separate requirements per service
```

---

## Project context

Built during a dual master's in Data Engineering / LLMOps at UQAC (Université du Québec à Chicoutimi), combining coursework in Data Engineering (8INF950) and AI Seminars (8INF896).

The pipeline is live, running on a schedule, and actively used for my own internship search in Latin America.
