## LLM Cost Optimization & Deployment Strategy

During the initial development phase, Groq was utilized directly in the local environment. However, to mitigate underestimated API inference costs during heavy iteration and testing, the architecture was pivoted to a hybrid strategy. This ensures zero-cost local engineering while preserving high-performance LLM capabilities for the cloud.

* **Local Development (Cost Mitigation):** A lightweight **Llama 3.2** model runs locally for debugging, pipeline testing, and everyday development. This completely eliminates API token expenses during the build phase.
* **Cloud Production (Streamlit Cloud Constraints):** Due to deployment constraints and the need for reliable production-grade data enrichment, the live Streamlit Cloud application offloads reasoning tasks to Groq, leveraging the **groq/compound** and **groq/compound-mini** models.

### Future Upgrades
The data ingestion pipeline will be upgraded to improve extraction reliability. This includes migrating to a more robust scraping workflow using **BeautifulSoup** and routing the extracted data through a web-optimized **Llama 4** model on Groq to handle intricate web page layouts and semi-structured job postings. 
The email automation also needs a better model than the **Llama 3.2**.