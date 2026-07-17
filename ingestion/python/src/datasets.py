# ingestion/python/src/datasets.py
from airflow.datasets import Dataset

"""
Airflow chain scheduler
"""


# Zone raw B2 — produite par les fetchs
B2_RAW = Dataset("b2://job_offer") 

# Bronze Neon — produit par load_to_bronze
BRONZE_OFFERS = Dataset("neon://raw.job_offer")

# Staging local — produit par silver_enrichment
STAGING_ENRICHED = Dataset("neon://staging.enriched_offers")

# Silver Neon — produit par staging_to_silver
SILVER_OFFERS = Dataset("neon://analytics.job_offer")

GOLD_OFFERS = Dataset("neon://serving.job_offer")