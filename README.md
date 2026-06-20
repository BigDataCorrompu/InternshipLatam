# InternshipLatam
# Project Documentation: Automated Data Engineering & AI Pipeline

## Preamble

As part of the Summer 2026 semester at UQAC, this personal project aims to apply the skills acquired in **8INF950 Special Topics (Data Engineering Specialization)** and **8INF896 Thematic Seminar in Artificial Intelligence**. The objective is to build a fully automated pipeline for data collection, transformation, storage, and visualization.

---

## 🎯 Project Goals

### 1. Data Ingestion

Develop an automated pipeline to scrape and collect job offers and company data for Junior Data Engineer positions in Latin America.

* **Target Countries:** Chile, Argentina, Uruguay
* **Target Cities:** Santiago, Buenos Aires, Montevideo

### 2. Serving & AI Integration

* Perform automated data visualization using AI agents and LangGraph, fulfilling the requirements for the AI Thematic Seminar.
* Automatically apply to job offers using a combination of APIs, web scraping, and AI agents.

---

## ⚙️ System Requirements

### Functional Requirements

* Collect data-related internship and job offers in Latin America.
* Filter relevant offers based on specific criteria (role, language, city, country, company size, remote work availability).
* Visualize data through interactive dashboards.
* Send spontaneous job applications automatically.
* Track the status of sent applications (Status: Sent, Replied, Follow-up).

### Target Audience

* Single personal use.

### Project Management Methodology

* **SCRUM Framework:** Ad-hoc sprints organized at the request of the supervising professor or the student to address technical challenges or present the current project state.

### Non-Functional Requirements

* **Maintainability:** The codebase must be highly readable and version-controlled on GitHub.
* **Reproducibility:** The pipeline must be fully portable and executable on any machine.
* **Reliability:** The system must gracefully handle collection failures without crashing the entire pipeline.

### Constraints

* **Budget:** $0 (Free-tier only).
* **Timeline:** Limited to 4 weeks for ingestion, LLM-assisted transformation, and the Streamlit Cloud interface with a chatbot.
* **Workload:** Conducted in parallel with ongoing university studies.
* **Scraping Rules:** No standard web scraping for job offers (APIs must be used). Dynamic scraping assisted by AI is only authorized for finding email addresses.

---

## 🔄 Data Flow

* **Ingestion:** Scheduled batch ingestion. (Streaming architecture is oversized and unnecessary for this specific use case).
* **Database:** A single, relational database with a highly structured schema.

* **OLAP (Fast Read & Dashboards)**
    * 🥉 **Raw (Bronze):** Initial ingestion and raw storage.
    * 🥇 **Serving (Gold):** Batch insertion, optimized for fast dashboard queries.

* **OLTP (Transformations & Transactions)**
    * 🥈 **Analytics (Silver):** Maintainable structure facilitating updates during complex transformations.
    * ⚙️ **Operations:** Transactional management (`INSERT`/`UPDATE`) for tracking automated job applications.
    
---

## 🛠️ Tools & Technologies

### Stack

* **Languages:** Python (Scripting, ingestion, automation), SQL (In-database transformations and querying).
* **Collection & APIs:**
* `requests` — HTTP calls
* `pandas` — Tabular data manipulation
* **JSearch & CareerJet** — Job offer APIs
* **DuckDuckGo API** — Web search for email addresses
* **Google Maps API** — Geographic location mapping


* **Database:**
* **PostgreSQL** — Core database engine (OLAP + OLTP)
* **Neon** — Free, serverless Cloud PostgreSQL


* **Orchestration & AI:**
* **Apache Airflow** — Pipeline orchestration and scheduling
* **LangGraph** — LLM transformations, DB enrichment, and interactive filtering


* **Visualization & Serving:**
* **Streamlit Cloud** — Web interface deployment
* **Plotly** — Interactive dashboards


* **Virtualization:**
* **Docker Compose** — Local multi-container orchestration


* **Version Control:**
* **GitHub** — Code versioning and public portfolio hosting



### Industry Standards Adopted

* **Architecture:** **ELT over ETL** (Transformations handled in the database) / Medallion Architecture (Bronze/Silver/Gold schemas).
* **Extraction Pattern:** Extract → Save locally as JSON → Load (Ensures process reproducibility).
* **Infrastructure:** * **Cloud DB (Neon) over Local DB** for universal accessibility.
* **Docker over Local Installation** to guarantee identical environments across machines.
* **Airflow over Cron** for monitoring, automatic retries, and execution history.


* **Security:** strict use of `.env` and environment variables (no hardcoded credentials).
* **Code Quality:** Object-Oriented Programming (OOP) with inheritance for uniform API interfaces, and `dataclasses` over dictionaries for strong typing and auto-completion.

---

## 🏗️ Build, Evaluate, Iterate & Evolve (Medallion Architecture)

### Extraction & Normalization

The process is designed to never break the table enrichment chain, ensuring every step is reproducible. We use an **Append-Only Pattern** where the LLM inserts new rows into dedicated tables rather than modifying existing ones.

1. **Extraction:** Save payloads as local `*.json` files.
2. **Ingestion:** Push JSON data to the **Bronze** schema with no constraints.
3. **LLM-Assisted Transformation (Bronze → Silver):** Row-by-row normalization (company, city, country, remote status, language) to make data usable.
4. **AI Enrichment (Silver → Silver):** Append-only updates. Enriched data is added to *new* tables specifically designed for LLM/API data.
5. **Load (Silver → Gold):** Normalize the tables to extract relevant information, creating a highly performant OLAP table for the Streamlit interface. Aggregations are performed directly in the cloud PostgreSQL database.

> **Why create new tables instead of adding columns to `silver.job_offer`?**
> If the LLM runs a second iteration, only the targeted enrichment tables are affected, isolating the impact of the agents into distinct clusters. Furthermore, if the DB is enriched with general company data, it is architecturally incorrect to insert that into the specific job offer rows.

### Pipeline Steps Overview

* **Extraction:** Local `*.json` files.
* **Ingestion:** Push to Bronze schema (Raw).
* **Transformation (Bronze → Silver):**
* Normalizes: `company`, `city`, `country`, `is_remote`, `language` (including translations).
* Resolves: `company_id` and `location_id`.
* Deduplicates: Based on `offer_url`.
* *Result:* Usable `silver.job_offer` table.


* **LLM/API Enrichment (Silver → Silver):** * Append-only to dedicated tables:
* `silver.offer_requirement` (skills, seniority, contract_type)
* `silver.offer_relevancy` (score, reason, prompt_version)
* `silver.company_contact` (email, source, confidence)
* **Serving (Silver → Gold):**
* PostgreSQL SQL Aggregations:
* `gold.job_offer` (Flat OLAP table for Streamlit)
* `gold.application` (Application tracking)





---

### Layer Definitions

* 🥉 **Bronze Layer:** Denormalized table of raw data directly extracted from the job offer APIs.
* 🥈 **Silver Layer:** Normalized tables based on Bronze data, heavily enriched with LLM and API information. Follows the append-only pattern (adding an enrichment adds a new table). This open architecture allows extending the LLM's behavior easily by simply adding a new table.
* 🥇 **Gold Layer:** Denormalized tables based on Silver aggregations. Follows a **Fact + Dimension** pattern:
* *Dimension tables:* Represent the job offers (adding info on an offer adds a column).
* *Fact tables:* Represent actions (e.g., sending automated applications, following up). Every new type of event is a new business entity, and therefore a new table.