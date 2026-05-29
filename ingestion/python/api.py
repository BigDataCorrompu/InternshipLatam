from abc import ABC, abstractmethod


class BaseAPI(ABC):
    def __init__(self, endpoint):
        self.endpoint = endpoint


    @abstractmethod
    def search_jobs(self, query, **kwargs) -> list:
        """
        Function to seek offert
        """
        pass

    @abstractmethod
    def normalize(self, raw: dict) -> dict:
        """Normalisation au bon format
        {
        {
            "job_title"     : str,
            "employer_name" : str,
            "city"          : str,

        }
        """
        
        pass



"""
QUERY PARAM 

query : It is highly recommended to include job title and location as part of the query ("developer jobs in chicago", "marketing manager in new york via linkedin")
cursor : Pagination cursor returned from a previous request. Pass the cursor value from data.cursor to retrieve the next page of results. Omit or leave empty to start from the first page.
num_pages : Maximum number of pages to return (Allowed values : 1-20, each page 10 results)
country : us, al, uy, cl
language : Language code in which to return job postings. Leave empty to use the primary language in the specified country (country parameter).
location from where you post the search (irrelevent for now)
date_posted (all): all, today, 3days, week, month
work_from_home (false): false, true 
employment_types : Find jobs of particular employment types, specified as a comma delimited list of the following values: FULLTIME, CONTRACTOR, PARTTIME, INTERN
job_requirements : Find jobs with specific requirements, specified as a comma delimited list of the following values: under_3_years_experience, more_than_3_years_experience, no_experience, no_degree.
radius : Return jobs within a certain distance from location as specified as part of the query (in km). This internally sent as the Google lrad parameter and although it might affect the results, it is not strictly followed by Google for Jobs.
exclude_job_publishers : Exclude jobs published by specific publishers, specified as a comma (,) separated list of publishers to exclude. (BeeBe,Dice)
fields : A comma separated list of job fields to include in the response (field projection). By default all fields are returned. (employer_name,job_publisher,job_title,job_country)
"""
class JsearchAPI(BaseAPI):
    def __init__(self):
