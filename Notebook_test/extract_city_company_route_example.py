
@tool
def extract_company(job_title: str, job_description: str) -> str:
    """Extrait le nom de l'entreprise depuis le titre et la description de l'offre."""
    response = llm.invoke([HumanMessage(content=f"""
Extrais uniquement le nom de l'entreprise.
Titre : {job_title}
Description : {job_description}
""")])
    return response.content.strip()

@tool  
def extract_city(location_raw: str, job_title: str, job_description: str) -> str:
    """Extrait la ville depuis un texte de localisation brut."""
    response = llm.invoke([HumanMessage(content=f"""
Location : {location_raw}
Titre : {job_title}
Description : {job_description}
""")])
    return response.content.strip()

def update_state(state: JobOfferState) -> JobOfferState:
    """Lit les résultats des tools et met à jour le state."""
    updates = {}

    for message in state["messages"]:
        if isinstance(message, ToolMessage):
            if message.name == "extract_company":
                updates["company"] = message.content
            elif message.name == "extract_city":
                updates["city"] = message.content

    return updates

def tool_calling_llm(state: JobOfferState) -> dict:
    system = SystemMessage(content="""
    Tu es un assistant d'extraction de données d'offres d'emploi.

    - Si company est null ou vide → appelle extract_company
    - Si location_raw est null ou vide et que city est vide ou null également → appelle extract_city  
    - Sinon → ne fais rien et termine
    """)

    user = HumanMessage(content=f"""
company: {state.get('company')}
city: {state.get('city')}
location_raw: {state.get('location_raw')}
job_title: {state.get('job_title')}
job_description: {state.get('job_description')}
""")

    return {"messages": [llm_with_tools.invoke([system, user])]}
