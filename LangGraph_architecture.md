
```mermaid
graph LR
    START --> 1A_extract_location
    START --> 2A_extract_company
    START --> 3A_extract_seniority
    START --> 4A_extract_language
    START --> 5A_extract_is_remote
    START --> 6A_extract_contract_type
    START --> 7A_extract_skills

    1A_extract_location --> 1B_find_location
    1A_extract_location --> 2B_find_mail
    2A_extract_company --> 1B_find_location
    2A_extract_company --> 2B_find_mail
    1A_extract_location --> 4B_find_website
    2A_extract_company --> 4B_find_website

    1B_find_location --> END
    2B_find_mail --> END

    3A_extract_seniority --> 3B_calculate_relevancy
    4A_extract_language --> 3B_calculate_relevancy
    5A_extract_is_remote --> 3B_calculate_relevancy
    6A_extract_contract_type --> 3B_calculate_relevancy
    7A_extract_skills --> 3B_calculate_relevancy
    1A_extract_location --> 3B_calculate_relevancy
    2A_extract_company --> 3B_calculate_relevancy

    3B_calculate_relevancy --> END
```
