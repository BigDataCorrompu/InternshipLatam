import streamlit as st
import pandas as pd
import numpy as np
import time
import sys
import os

# 1. Récupère le chemin du dossier parent commun
dossier_parent = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# 2. Construit le chemin pour le premier dossier voisin
voisin_1 = os.path.join(dossier_parent, 'src')

# 3. Construit le chemin pour le deuxième dossier voisin
voisin_2 = os.path.join(dossier_parent, 'LangGraph_Agent')

# 4. Ajoute les deux dossiers au système de recherche de Python
for dossier in [voisin_1, voisin_2]:
    if dossier not in sys.path:
        sys.path.append(dossier)

# 5. Importe vos fichiers respectifs 
import database
import silver_enrichment



import database


st.title('Tutoriel')
"""
st.cache_data : pas utile pour le projet charge les données dans pandas et manipule les

st.cache_ressource : utile pour la connexion bdd ou la clé grok ou un objet llm groq

Session state :
1. Garder l'offre sélectionnée dans ton interface de bulles D3
2. Garder le score calculer par l'ia si je lui demande de match mon profil 
3. Garder le zoom de la map pour pas qu'elle se refresh a chaque fois

Pages : 
1. Dashboard (peut etre séparer ou afficher le détails des offres dans une autre page)
2. Suivi des candidatures
3. Readme interactible et assisté par ia accessible depuis streamlit sans fouiller le github

AI CORRECTION

Tu as noté "pas utile pour le projet" — c'est l'inverse qui est vrai. cache_data est justement le plus utile des deux pour toi : c'est lui qui sert à mettre en cache le résultat d'une requête SQL sur ta base Gold (un DataFrame pandas, sérialisable). Sans lui, chaque clic dans ton interface (sélection d'offre, changement d'onglet, etc.) relance ton script de zéro et donc retape Neon en SQL inutilement. Règle simple : si la fonction retourne de la donnée (DataFrame, liste, dict) → cache_data. Si elle retourne un objet vivant qu'on veut garder ouvert (connexion DB, client Groq, modèle chargé) → cache_resource. Ta définition de cache_resource est correcte.
Sur ta liste Session State — les 3 cas sont valides, avec une nuance importante sur chacun :

Offre sélectionnée → OK, c'est le cas d'usage classique.
Score IA matching profil → bonne idée, mais pense à aussi persister ce score en base (table job_relevancy ou équivalent) plutôt que de compter uniquement sur session_state. Le session state disparaît si la session expire ou si l'utilisateur recharge la page — pas un vrai cache long terme.
Zoom de la map → attention, c'est le cas le plus piégeux des trois. Si tu utilises un composant de carte tiers (ex. streamlit-folium, pydeck), le zoom n'est pas automatiquement renvoyé vers Python pour être stocké en session_state — ça dépend si le composant supporte la communication bidirectionnelle (retour de valeur composant → Python). Vérifie la doc du composant spécifique que tu choisiras avant de supposer que ça marche tout seul, même problème que pour ta bulle D3.

Sur tes 3 pages

Regarde st.Page et st.navigation (API moderne de multipage, dans develop/concepts/multipage-apps) plutôt que l'ancienne convention de dossier pages/ — plus flexible pour ce que tu veux (dashboard avec vue détail séparée).

Pour le README interactif assisté par IA, c'est en gros un mini chatbot sur un document : regarde st.chat_message et st.chat_input dans develop/api-reference/chat.
Vu que tu as très peu de temps, je veux caler une vraie priorité avant que tu commences demain plutôt que de tout faire en parallèle.
"""


@st.cache_resource
def get_database():
    return Database(**st.secrets["database"])