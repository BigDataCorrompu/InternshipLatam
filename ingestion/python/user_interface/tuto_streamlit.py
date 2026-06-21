import streamlit as st
import pandas as pd
import numpy as np
import time
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

def load_data(nrows):
    data = pd.read_csv(DATA_URL, nrows=nrows)
    lowercase = lambda x: str(x).lower()
    data.rename(lowercase, axis='columns', inplace=True)
    data[DATE_COLUMN] = pd.to_datetime(data[DATE_COLUMN])
    return data

map_data = pd.DataFrame(
    np.random.randn(1000, 2) / [50, 50] + [37.76, -122.4],
    columns=['lat', 'lon'])

st.map(map_data)


x = st.slider('x')  # 👈 this is a widget
st.write(x, 'squared is', x * x)


st.text_input("Your name", key="name")

# You can access the value at any point with:
st.session_state.name


if st.checkbox('Show dataframe'):
    chart_data = pd.DataFrame(
       np.random.randn(20, 3),
       columns=['a', 'b', 'c'])

    chart_data


    # Add a selectbox to the sidebar:
add_selectbox = st.sidebar.selectbox(
    'How would you like to be contacted?',
    ('Email', 'Home phone', 'Mobile phone')
)

# Add a slider to the sidebar:
add_slider = st.sidebar.slider(
    'Select a range of values',
    0.0, 100.0, (25.0, 75.0)
)

left_column, right_column = st.columns(2)
# You can use a column just like st.sidebar:
left_column.button('Press me!')

# Or even better, call Streamlit functions inside a "with" block:
with right_column:
    chosen = st.radio(
        'Sorting hat',
        ("Gryffindor", "Ravenclaw", "Hufflepuff", "Slytherin"))
    st.write(f"You are in {chosen} house!")


'Starting a long computation...'

# Add a placeholder
latest_iteration = st.empty()
bar = st.progress(0)

for i in range(100):
  # Update the progress bar with each iteration.
  latest_iteration.text(f'Iteration {i+1}')
  bar.progress(i + 1)
  time.sleep(0.1)

'...and now we\'re done!'



if "counter" not in st.session_state:
    st.session_state.counter = 0

st.session_state.counter += 1

st.header(f"This page has run {st.session_state.counter} times.")
st.button("Run it again")


if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame(np.random.randn(20, 2), columns=["x", "y"])

st.header("Choose a datapoint color")
color = st.color_picker("Color", "#FF0000")
st.divider()
st.scatter_chart(st.session_state.df, x="x", y="y", color=color)

conn = st.connection("my_database")
df = conn.query("select * from my_table")
st.dataframe(df)

