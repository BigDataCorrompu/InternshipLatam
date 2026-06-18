# Suivi d'apprentissage LangGraph
## InternshipLatam — Pipeline d'enrichissement IA
https://academy.langchain.com/courses/intro-to-langgraph
---
---

## Légende

| Symbole | Signification |
|---|---|
| ⬜ | À faire |
| ✅ | Terminé |
| ⬛ | Hors scope — ignoré volontairement |
| 🔄 | En cours |

## Module 1 — Introduction ⭐ Indispensable

| Leçon | Statut | Pertinence projet |
|---|---|---|
| Lesson 1 : Motivation | ⬜ | Comprendre pourquoi LangGraph |
| Lesson 2 : Simple Graph | ✅ | Base du pipeline d'enrichissement |
| Lesson 3 : LangSmith Studio | ⬛ | Debug des nodes LLM |
| Lesson 4 : Chain | ✅ | Chaîner extract_skills → extract_seniority |
| Lesson 5 : Router | ✅ | Router selon api_source (jsearch / careerjet) |
| Lesson 6 : Agent | ✅ | Agent d'enrichissement complet |
| Lesson 7 : Agent with Memory | ✅ | Contexte entre les offres |


## Lesson 4

### `BindTool`
```python
llm_with_tools = llm.bind_tools([multiply])
```
Le LLM n'exécute pas la fonction mais retourne l'appel à faire avec les arguments.  
Permet au LLM de décider dynamiquement quels tools appeler (ex. `extract_city` ou `extract_company`).  
Résultat : graph dynamique au lieu d'un graph linéaire.

### `MessagesState`
```python
class MessagesState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
```
Accumule l'historique des messages sans écraser les précédents.  
Utile pour l'agent de génération de candidature — le LLM garde le contexte complet pour réviser son brouillon.

## Lesson 5
### `Routeur`
```python
builder.add_conditional_edges(
    "tool_calling_llm",
    # If the latest message (result) from assistant is a tool call -> tools_condition routes to tools
    # If the latest message (result) from assistant is a not a tool call -> tools_condition routes to END
    tools_condition,
)


def extract_city(location_raw: str) -> str:
    """Extrait la ville depuis un texte de localisation brut."""
    ...

def skip_city(location_raw: str) -> str:
    """Retourne la ville déjà présente sans traitement."""
    ...

llm_with_tools = llm.bind_tools([extract_city, skip_city])
```
Permet de faire des routes dynamique pour savoir si des tools doivent etre appeler.
## Lesson 6
### `Agent`
```python
llm_with_tools = llm.bind_tools(tools, parallel_tool_calls=False)
```
Permet de paralleliser l'appel de tools.
Agent appel les tools 

```python
messages = react_graph.invoke({"messages": messages})
```
Agent mail avec historque des messages.

## Lesson 7
### `Agent Memory`
```python
from langgraph.checkpoint.memory import MemorySaver
memory = MemorySaver()
react_graph_memory = builder.compile(checkpointer=memory)

# Specify a thread
config = {"configurable": {"thread_id": "1"}}

# Specify an input
messages = [HumanMessage(content="Add 3 and 4.")]

# Run
messages = react_graph_memory.invoke({"messages": messages},config)
for m in messages['messages']:
    m.pretty_print()
```
Reprise après crash — si le pipeline plante sur l'offre 50, tu reprends à l'offre 50 sans tout recommencer
Agent email multi-tours — l'utilisateur révise le brouillon en plusieurs échanges, le LLM se souvient du contexte


---

## Module 2 — State and Memory ⭐ Indispensable

| Leçon | Statut | Pertinence projet |
|---|---|---|
| Lesson 1 : State Schema | ✅ | Définir l'état de l'offre en cours d'enrichissement |
| Lesson 2 : State Reducers | ✅ | `Annotated[list, operator.add]` — accumulation des messages |
| Lesson 3 : Multiple Schemas | ✅ | Séparer state interne et state output vers PostgreSQL |
| Lesson 4 : Trim and Filter Messages | ⬛ | Peu utile — pas de longue conversation |
| Lesson 5 : Chatbot w/ Summarizing | ⬛ | Hors scope |
| Lesson 6 : Chatbot w/ External Memory | ⬛ | Hors scope |

```python
```

## Lesson 1

### pydantic
```python
from typing_extensions import TypedDict
from typing import Literal
from pydantic import BaseModel

class TypedDictState(BaseModel):
    id_offer: str
    company: str
    contract_type: Literal["INTERN","FULLTIME", "PARTTIME", "unknow"]

# Build graph
builder = StateGraph(PydanticState)
```
pydantic gestion du respect des valeur de renvoyé par exemple litteral. 
Pui un Callback au llm permet de corriger


## Lesson 2
## Private state
```python
class JobOfferState(TypedDict):
    job_title:   str
    company:     str
    city:        str

class DDGSearchState(TypedDict):
    ddg_raw_results: str   # résultats bruts DDG — pas besoin dans le state final

def find_email_ddg(state: JobOfferState) -> DDGSearchState:
    results = search_duckduckgo(f"{state['company']} {state['city']} email")
    return {"ddg_raw_results": results}

def extract_email_llm(state: DDGSearchState) -> JobOfferState:
    email = llm.invoke(...)
    return {"email": email}
```
PrivateState c'est un state intermédiaire qui circule entre deux nœuds sans être exposé dans l'état global du graph.PrivateState c'est un state intermédiaire qui circule entre deux noeuds sans être exposé dans l'état global du graph.

### Reducer
```python
class JobOfferState(TypedDict):
    city:      str                              # écrase — par défaut
    seniority: str                              # écrase — par défaut
    skills:    Annotated[list[str], operator.add]  # accumule
```
Définie comment modifier l'état dans l'état

### Custom Reducer

```python
def reduce_list(left: list | None, right: list | None) -> list:
    """Safely combine two lists, handling cases where either or both inputs might be None.

    Args:
        left (list | None): The first list to combine, or None.
        right (list | None): The second list to combine, or None.

    Returns:
        list: A new list containing all elements from both input lists.
               If an input is None, it's treated as an empty list.
    """
    if not left:
        left = []
    if not right:
        right = []
    return left + right

class DefaultState(TypedDict):
    foo: Annotated[list[int], add]

class CustomReducerState(TypedDict):
    foo: Annotated[list[int], reduce_list]
```

### Message reducer
```python
messages = [AIMessage("Hi.", name="Bot", id="1")]
messages.append(AIMessage("So you said you were researching ocean mammals?", name="Bot", id="3"))
messages.append(HumanMessage("Yes, I know about whales. But what others should I learn about?", name="Lance", id="4"))
# Isolate messages to add 
new_message = HumanMessage(content="I'm looking for information on whales, specifically", name="Lance", id="2")
add_messages(initial_messages , new_message)
# Isolate messages to delete 
delete_messages = [RemoveMessage(id=m.id) for m in messages[:-2]]
add_messages(messages , delete_messages)
```

## Lesson 3
### Private state
```python
from typing_extensions import TypedDict
from IPython.display import Image, display
from langgraph.graph import StateGraph, START, END

class OverallState(TypedDict):
    foo: int

class PrivateState(TypedDict):
    baz: int

def node_1(state: OverallState) -> PrivateState:
    print("---Node 1---")
    return {"baz": state['foo'] + 1}

def node_2(state: PrivateState) -> OverallState:
    print("---Node 2---")
    return {"foo": state['baz'] + 1}
```
Permet de séparer un schema privé et public exposé dans le graph

### Input/Output Schema
```python
class InputState(TypedDict):
    question: str

class OutputState(TypedDict):
    answer: str

class OverallState(TypedDict):
    question: str
    answer: str
    notes: str

def thinking_node(state: InputState):
    return {"answer": "bye", "notes": "... his is name is Lance"}

def answer_node(state: OverallState) -> OutputState:
    return {"answer": "bye Lance"}

graph = StateGraph(OverallState, input_schema=InputState, output_schema=OutputState)
graph.add_node("answer_node", answer_node)
graph.add_node("thinking_node", thinking_node)
graph.add_edge(START, "thinking_node")
graph.add_edge("thinking_node", "answer_node")
graph.add_edge("answer_node", END)

graph = graph.compile()

graph.invoke({"question":"hi"})
```
Le schema overall contient tous les champs qui circulent en interne pendant l'exécution du graph — inputs, outputs et données intermédiaires privées que les nœuds utilisent entre eux mais qui ne sont jamais exposées à l'extérieur.





---

## Module 3 — UX and Human-in-the-Loop ⚠️ Partiel

| Leçon | Statut | Pertinence projet |
|---|---|---|
| Lesson 1 : Streaming | ⬜ | Affichage temps réel dans Streamlit (génération email) |
| Lesson 2 : Breakpoints | ⬛ | Hors scope |
| Lesson 3 : Editing State and Human Feedback | ⬛ | Hors scope |
| Lesson 4 : Dynamic Breakpoints | ⬛ | Hors scope |
| Lesson 5 : Time Travel | ⬛ | Hors scope |

---

## Module 4 — Building Your Assistant ⭐ Utile

| Leçon | Statut | Pertinence projet |
|---|---|---|
| Lesson 1 : Parallelization | ✅ | Enrichir plusieurs offres en parallèle |
| Lesson 2 : Sub-graphs | ⬛ | Avancé — pas nécessaire pour commencer |
| Lesson 3 : Map-reduce | ✅ | Traiter une liste d'offres et agréger les résultats |
| Lesson 4 : Research Assistant | ⬜ | Pattern proche du pipeline find_mail + extract_skills |

```python
```
## Lesson 3
### `llm_structured.invoke(messages_with_system)`
```python
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    mail: list[dict]

class EmailItem(BaseModel):
    email: str
    score: float
    reason: str

class EmailResults(BaseModel):
    emails: list[EmailItem]
    career_portal_url: str | None

llm_structured = llm.with_structured_output(EmailResults)
response = llm_structured.invoke(messages_with_system)
```
Permet directement structurer sans parser json

---

## Module 5 — Long-Term Memory ⬛ Hors scope

| Leçon | Statut | Pertinence projet |
|---|---|---|
| Lesson 1 : Short vs Long-Term Memory | ⬛ | Hors scope |
| Lesson 2 : LangGraph Store | ⬛ | Hors scope |
| Lesson 3 : Memory Schema + Profile | ⬛ | Hors scope |
| Lesson 4 : Memory Schema + Collection | ⬛ | Hors scope |
| Lesson 5 : Build an Agent with Long-Term Memory | ⬛ | Hors scope |

---

## Ordre recommandé