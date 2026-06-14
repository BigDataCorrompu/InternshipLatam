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
| Lesson 2 : Simple Graph | ⬜ | Base du pipeline d'enrichissement |
| Lesson 3 : LangSmith Studio | ⬜ | Debug des nodes LLM |
| Lesson 4 : Chain | ⬜ | Chaîner extract_skills → extract_seniority |
| Lesson 5 : Router | ⬜ | Router selon api_source (jsearch / careerjet) |
| Lesson 6 : Agent | ⬜ | Agent d'enrichissement complet |
| Lesson 7 : Agent with Memory | ⬜ | Contexte entre les offres |

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