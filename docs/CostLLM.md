## LLM Cost Optimization & Deployment Strategy

* **Cloud Production:** The live Streamlit Cloud application relies primarily on **Mistral** for reasoning and enrichment tasks — **Ministral 8B** for Silver-layer extraction (job attributes, skills, seniority, relevancy scoring) and **Mistral Small** for the conversational dashboard agent. Mistral's automatic prompt caching significantly reduces token costs thanks to a stable context prefix across calls.
* **Email Discovery:** The `find_mails` pipeline uses **Gemini 3.1 Flash-Lite** as part of a multi-provider cascade (DDG scraping, Gemini native grounding, Hunter.io as last resort for high-relevance targets).

### Future Upgrades
The data ingestion pipeline will be upgraded to improve extraction reliability, including a more robust scraping workflow to better handle intricate web page layouts and semi-structured job postings.


### Infrastructure Cost Breakdown

| Component | Usage | Monthly Cost |
|---|---|---|
| OVH VPS | Airflow orchestration + Docker Compose | $5.35 |
| LLM enrichment (Silver) | Job offer extraction & scoring | ~$1.50 |
| LLM dashboard agent | Streamlit conversational agent (variable, usage-based) | ~$0.10 |
| Email discovery (`find_mails`) | Multi-provider cascade (DDG, grounding) | ~$0.10 |
| **Total estimated** | | **~$7/month** |

APIs, Streamlit Cloud, Neon PostgreSQL, and Backblaze B2 remain within their respective free tiers at current volume.