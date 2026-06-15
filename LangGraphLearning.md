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
| Lesson 6 : Agent | ⬜ | Agent d'enrichissement complet |
| Lesson 7 : Agent with Memory | ⬜ | Contexte entre les offres |


## Lesson 4

### `BlindTool`
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

---

## Module 2 — State and Memory ⭐ Indispensable

| Leçon | Statut | Pertinence projet |
|---|---|---|
| Lesson 1 : State Schema | ⬜ | Définir l'état de l'offre en cours d'enrichissement |
| Lesson 2 : State Reducers | ⬜ | `Annotated[list, operator.add]` — accumulation des messages |
| Lesson 3 : Multiple Schemas | ⬜ | Séparer state interne et state output vers PostgreSQL |
| Lesson 4 : Trim and Filter Messages | ⬛ | Peu utile — pas de longue conversation |
| Lesson 5 : Chatbot w/ Summarizing | ⬛ | Hors scope |
| Lesson 6 : Chatbot w/ External Memory | ⬛ | Hors scope |

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
| Lesson 1 : Parallelization | ⬜ | Enrichir plusieurs offres en parallèle |
| Lesson 2 : Sub-graphs | ⬛ | Avancé — pas nécessaire pour commencer |
| Lesson 3 : Map-reduce | ⬜ | Traiter une liste d'offres et agréger les résultats |
| Lesson 4 : Research Assistant | ⬜ | Pattern proche du pipeline find_mail + extract_skills |

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