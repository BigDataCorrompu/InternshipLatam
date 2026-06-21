import streamlit as st
import datetime

st.title("🎛️ Le Catalogue des Filtres Streamlit")

st.sidebar.header("🔍 Espace Filtrage")

# --- 1. RECHERCHE TEXTUELLE ---
st.sidebar.subheader("1. Texte")
search_text = st.sidebar.text_input("Mots-clés (titre, entreprise)", placeholder="Ex: Data Engineer...")

# --- 2. CATÉGORIES (Choix dans une liste) ---
st.sidebar.subheader("2. Catégories")
# Choix multiple (renvoie une liste)
choix_multi = st.sidebar.multiselect("Compétences", ["Python", "SQL", "AWS", "React"], default=["Python"])
# Choix unique menu déroulant (renvoie un string)
choix_unique = st.sidebar.selectbox("Niveau attendu", ["Junior", "Intermédiaire", "Senior", "Lead"])
# Choix unique boutons (renvoie un string)
choix_radio = st.sidebar.radio("Type d'entreprise", ["Startup", "PME", "Grand Groupe"])

# --- 3. VALEURS NUMÉRIQUES ---
st.sidebar.subheader("3. Nombres")
# Slider avec une plage [min, max] (renvoie un tuple)
slider_range = st.sidebar.slider("Score de pertinence", 0, 100, (50, 80))
# Slider avec une valeur unique (renvoie un int/float)
slider_unique = st.sidebar.slider("Jours de télétravail min.", 0, 5, 2)
# Saisie manuelle de nombre (très précis)
saisie_nombre = st.sidebar.number_input("Salaire minimum visé (k€)", min_value=30, max_value=200, value=45, step=5)

# --- 4. BOOLÉENS (Oui/Non) ---
st.sidebar.subheader("4. Boutons ON/OFF")
# Case à cocher classique
case_cocher = st.sidebar.checkbox("Masquer les offres expirées", value=True)
# Switch (plus moderne visuellement)
bouton_toggle = st.sidebar.toggle("Activer les alertes", value=False)

# --- 5. DATES ---
st.sidebar.subheader("5. Temps")
# Choix d'une plage de dates (renvoie un tuple de dates)
# Attention: st.date_input peut renvoyer 1 ou 2 dates selon les clics de l'utilisateur
today = datetime.date.today()
plage_dates = st.sidebar.date_input("Publié entre le", [today - datetime.timedelta(days=30), today])

# ==========================================
# AFFICHAGE DES RÉSULTATS DANS LA PAGE PRINCIPALE
# ==========================================
st.write("### Ce que ton code récupère en arrière-plan :")
st.info("Regarde les types de données générés par chaque widget, c'est ce que tu devras utiliser pour filtrer ton DataFrame Pandas.")

st.code(f"""
# 1. Texte
search_text = '{search_text}'

# 2. Catégories
choix_multi = {choix_multi}
choix_unique = '{choix_unique}'
choix_radio = '{choix_radio}'

# 3. Nombres
slider_range = {slider_range}  # Tuple (min, max)
slider_unique = {slider_unique}
saisie_nombre = {saisie_nombre}

# 4. Booléens
case_cocher = {case_cocher}
bouton_toggle = {bouton_toggle}

# 5. Dates
plage_dates = {plage_dates} # Tuple ou liste de dates
""")