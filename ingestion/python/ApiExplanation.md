# API Documentation — InternshipLatam

---

## JSearch API

**Base URL** : `https://jsearch.p.rapidapi.com`  
**Auth** : `X-RapidAPI-Key` + `X-RapidAPI-Host` dans les headers

---

### Endpoint : `/search-v2`

**Description** : Recherche d'offres d'emploi depuis Google for Jobs (LinkedIn, Indeed, Glassdoor...)

#### Paramètres

| Paramètre | Type | Obligatoire | Défaut | Description |
|---|---|---|---|---|
| `query` | String | ✅ | — | Recherche libre — inclure titre + ville recommandé |
| `cursor` | String | ❌ | — | Curseur de pagination retourné par la requête précédente |
| `num_pages` | Number | ❌ | `1` | Nombre de pages (1-20) — 1 page = 10 résultats = 1 crédit |
| `country` | String | ❌ | `us` | Code pays ISO 3166-1 alpha-2 (ex. `cl`, `ar`, `uy`) |
| `language` | String | ❌ | langue du pays | Code langue ISO 639 (ex. `en`, `es`) |
| `location` | String | ❌ | — | Localisation de la recherche (paramètre UULE Google) |
| `date_posted` | Enum | ❌ | `all` | Ancienneté des offres : `all`, `today`, `3days`, `week`, `month` |
| `work_from_home` | Boolean | ❌ | `false` | Offres remote uniquement — ne pas inclure si `false` |
| `employment_types` | String | ❌ | — | Types de contrat séparés par virgule : `FULLTIME`, `CONTRACTOR`, `PARTTIME`, `INTERN` |
| `job_requirements` | String | ❌ | — | Exigences : `under_3_years_experience`, `more_than_3_years_experience`, `no_experience`, `no_degree` |
| `radius` | Number | ❌ | — | Rayon de recherche en km autour de `location` |
| `exclude_job_publishers` | String | ❌ | — | Exclure des sources séparées par virgule (ex. `BeeBe,Dice`) |
| `fields` | String | ❌ | tous | Projection de champs — liste séparée par virgule |

#### Paramètres utilisés dans le projet

```python
params = {
    "query":            "data engineer Santiago Chile",
    "country":          "cl",
    "num_pages":        "1",
    "date_posted":      "month",
    "employment_types": "INTERN,FULLTIME",
    "language":         "es",
    "fields":           "job_id,job_title,employer_name,job_city,job_country,job_apply_link,job_posted_at_datetime_utc,job_description,job_min_salary,job_max_salary,job_salary_currency"
}
```

#### Pays cibles

| Pays | Code |
|---|---|
| Chili | `cl` |
| Argentine | `ar` |
| Uruguay | `uy` |

---

### Endpoint : `/job-details`

**Description** : Détails complets d'une offre par ID — supporte le batching jusqu'à 20 IDs par requête

| Paramètre | Type | Obligatoire | Défaut | Description |
|---|---|---|---|---|
| `job_id` | String | ✅ | — | ID retourné par `/search-v2` — plusieurs IDs séparés par virgule (max 20) |
| `country` | String | ❌ | `us` | Code pays ISO 3166-1 alpha-2 (ex. `cl`, `ar`, `uy`) |
| `language` | String | ❌ | langue du pays | Code langue ISO 639 (ex. `en`, `es`) |
| `fields` | String | ❌ | tous | Projection de champs séparés par virgule (ex. `employer_name,job_title,job_country`) |

#### Note quota
Chaque `job_id` dans une requête batch est compté comme **une requête séparée** pour le calcul du quota.

#### Paramètres utilisés dans le projet

```python
# Requête simple
params = {
    "job_id":   "GiBe5bGWa5ml9P-7AAAAAA==",
    "country":  "cl",
    "language": "es",
    "fields":   "job_id,job_title,employer_name,employer_website,job_description,job_apply_link"
}

# Requête batch — 3 offres en 1 appel (= 3 crédits)
params = {
    "job_id":  "ID1==,ID2==,ID3==",
    "country": "cl"
}
```

---

### Endpoint : `/estimated-salary`

**Description** : Estimation salariale par titre de poste et localisation

| Paramètre | Type | Obligatoire | Défaut | Description |
|---|---|---|---|---|
| `job_title` | String | ✅ | — | Titre du poste (ex. `data engineer`) |
| `location` | String | ✅ | — | Localisation libre (ex. `Santiago, Chile`) |
| `location_type` | Enum | ❌ | `ANY` | Type de localisation : `ANY`, `CITY`, `STATE`, `COUNTRY` |
| `years_of_experience` | Enum | ❌ | `ALL` | Niveau d'expérience : `ALL`, `LESS_THAN_ONE`, `ONE_TO_THREE`, `FOUR_TO_SIX`, `SEVEN_TO_NINE`, `TEN_TO_FOURTEEN`, `ABOVE_FIFTEEN` |
| `fields` | String | ❌ | tous | Projection de champs séparés par virgule |

#### Paramètres utilisés dans le projet

```python
# Salaire Data Engineer junior à Santiago
params = {
    "job_title":           "data engineer",
    "location":            "Santiago, Chile",
    "location_type":       "CITY",
    "years_of_experience": "LESS_THAN_ONE",  # profil stage / junior
    "fields":              "location,job_title,min_salary,max_salary,median_salary,salary_currency,salary_period,salary_count,confidence"
}
```

#### Combinaisons utiles pour le projet

```python
targets = [
    {"location": "Santiago, Chile",      "location_type": "CITY"},
    {"location": "Buenos Aires, Argentina", "location_type": "CITY"},
    {"location": "Montevideo, Uruguay",  "location_type": "CITY"},
]
roles = ["data engineer", "data analyst", "data scientist"]
```

---

### Endpoint : `/company-job-salary`

**Description** : Estimation salariale par entreprise et titre de poste

| Paramètre | Type | Obligatoire | Défaut | Description |
|---|---|---|---|---|
| `company` | String | ✅ | — | Nom de l'entreprise (ex. `Globant`, `NTT DATA`) |
| `job_title` | String | ✅ | — | Titre du poste (ex. `data engineer`) |
| `location` | String | ❌ | — | Localisation libre (ex. `Buenos Aires, Argentina`) |
| `location_type` | Enum | ❌ | `ANY` | Type de localisation : `ANY`, `CITY`, `STATE`, `COUNTRY` |
| `years_of_experience` | Enum | ❌ | `ALL` | Niveau d'expérience : `ALL`, `LESS_THAN_ONE`, `ONE_TO_THREE`, `FOUR_TO_SIX`, `SEVEN_TO_NINE`, `TEN_TO_FOURTEEN`, `ABOVE_FIFTEEN` |

#### Paramètres utilisés dans le projet

```python
# Salaire Data Engineer junior chez Globant à Buenos Aires
params = {
    "company":             "Globant",
    "job_title":           "data engineer",
    "location":            "Buenos Aires, Argentina",
    "location_type":       "CITY",
    "years_of_experience": "LESS_THAN_ONE"
}
```

#### Entreprises cibles LATAM

```python
companies = [
    "Globant",        # Buenos Aires
    "NTT DATA",       # Santiago
    "Stefanini",      # Santiago / Buenos Aires
    "Accenture",      # Santiago / Buenos Aires / Montevideo
    "IBM",            # Buenos Aires
    "dLocal",         # Montevideo
]
```

---

### Plan gratuit

| Limite | Valeur |
|---|---|
| Requêtes/mois | 200 |
| Rate limit | 1000 req/heure |
| Carte bancaire | Non requise |

---


---
## Careerjet API

**Base URL** : `https://search.api.careerjet.net/v4/query`
**Auth** : Basic Auth — API key comme *username*, mot de passe vide
**Agrégateur** : indépendant de Google for Jobs — meilleure couverture des sites d'emploi locaux d'Amérique latine.

```
Authorization: Basic {Base64(api_key + ":")}
```

---

### ⚠️ Conditions d'accès — 3 prérequis cumulatifs

L'API v4 vérifie **trois** choses indépendantes. Tant que les trois ne sont pas réunies, tu reçois un `401` ou un `403` (voir tableau des erreurs). Chaque échec a un message explicite qui dit lequel des trois manque.

1. **Clé API valide** — fournie par ton compte publisher CareerJet. Chaque site publisher a sa propre clé. Sans elle → `401 Invalid API key`.
2. **IP de sortie déclarée** — l'**IP publique** depuis laquelle part la requête doit figurer dans la liste des IP autorisées de ton compte (8 max). Si l'IP qui sort n'est pas déclarée → `403 Unauthorized access from IP …`.
   - ⚠️ C'est l'**IP publique de sortie**, pas ton IP locale (`ipconfig`/`ifconfig` affiche une IP privée type `172.16.x.x` ou `192.168.x.x` qui est invisible côté serveur, derrière le NAT).
   - Pour connaître la vraie IP vue par CareerJet, depuis la machine/conteneur qui fait l'appel :
     ```bash
     curl -s https://api.ipify.org
     ```
   - Sur un réseau NAT dynamique (réseau universitaire/entreprise), cette IP peut **changer** → re-déclaration nécessaire, ou utiliser un hôte à IP fixe.
3. **Header `Referer`** — l'API exige un header `Referer` correspondant à l'**URL du site déclaré** lors de la création de la clé. S'il est absent ou ne correspond pas → `403 Undeclared referrer. Please add a Referer header.`

---

### Configuration — variables d'environnement

| Variable | Rôle | Exemple |
|---|---|---|
| `CAREERJET_APP_KEY` | Clé API (username du Basic Auth) | `2182f89dea3e5b…` (32 caractères) |
| `CAREERJET_REFERER` | URL **exacte** du site déclaré → header `Referer` | `https://mon-portfolio.dev` |
| `SERVER_IP` | IP publique de sortie → paramètre `user_ip` | `132.212.25.30` |
| `CAREERJET_USER_AGENT` | User agent → paramètre `user_agent` | `InternshipLatam/1.0` |

> Le `Referer` (header) et le `user_ip` (paramètre) sont **deux choses distinctes** : le premier identifie ton site déclaré, le second l'IP « utilisateur final » de la recherche. Les deux doivent être fournis.

---

### Endpoint : `/v4/query`

**Description** : Recherche d'offres d'emploi.

#### Headers

| Header | Obligatoire | Description |
|---|---|---|
| `Authorization` | ✅ | `Basic {Base64(api_key + ":")}` |
| `Referer` | ✅ | URL du site déclaré dans le compte publisher |

#### Paramètres (query string)

| Paramètre | Type | Obligatoire | Défaut | Description |
|---|---|---|---|---|
| `keywords` | String | ❌ | — | Mots clés de recherche (URL-encoded) |
| `location` | String | ❌ | — | Localisation — si vide : recherche nationale |
| `locale_code` | String | ❌ | `en_GB` | Code locale `[langue]_[PAYS]` (ex. `es_CL`, `es_AR`, `es_UY`). Note: les locales `en_XX` pour l'Amérique latine ne sont pas supportées (ex. `en_AR`, `en_CL`, `en_UY` → HTTP 400) |
| `contract_type` | Enum | ❌ | — | `p` permanent, `c` contract, `t` temporaire, `i` stage, `v` bénévolat |
| `work_hours` | Enum | ❌ | — | `f` temps plein, `p` temps partiel |
| `sort` | Enum | ❌ | `relevance` | `relevance`, `date`, `salary` |
| `page` | Integer | ❌ | `1` | Page de résultats (1-10) — pagination |
| `page_size` | Integer | ❌ | `20` | Résultats par page (1-100) |
| `offset` | Integer | ❌ | `0` | Décalage de résultats (1-999) |
| `radius` | Integer | ❌ | `5` | Rayon de recherche en km/miles |
| `fragment_size` | Integer | ❌ | `120` | Taille de l'extrait de description en caractères |
| `user_ip` | String | ✅ | — | IP de l'utilisateur final (= `SERVER_IP`) |
| `user_agent` | String | ✅ | — | User agent (= `CAREERJET_USER_AGENT`) |

#### Codes locale cibles

| Pays | Locale ES | Locale EN |
|---|---|---|
| Chili | `es_CL` | `en_CL` |
| Argentine | `es_AR` | `en_AR` |
| Uruguay | `es_UY` | `en_UY` |

#### Exemple d'utilisation dans le projet

```python
import base64
import os
import requests

api_key    = os.getenv("CAREERJET_APP_KEY")
referer    = os.getenv("CAREERJET_REFERER")           # URL exacte du site déclaré
user_ip    = os.getenv("SERVER_IP")                   # IP publique de sortie (déclarée)
user_agent = os.getenv("CAREERJET_USER_AGENT", "InternshipLatam/1.0")

credentials = base64.b64encode(f"{api_key}:".encode()).decode()

headers = {
    "Authorization": f"Basic {credentials}",
    "Referer": referer,        # OBLIGATOIRE — sinon 403 "Undeclared referrer"
}

params = {
    "keywords":      "data engineer",
    "location":      "Buenos Aires",
    "locale_code":   "es_AR",
    "contract_type": "i",      # i = stage / internship
    "work_hours":    "f",
    "sort":          "date",
    "page":          1,
    "page_size":     50,
    "user_ip":       user_ip,
    "user_agent":    user_agent,
}

resp = requests.get("https://search.api.careerjet.net/v4/query",
                    headers=headers, params=params)
resp.raise_for_status()
data = resp.json()
```

---

### Pagination

La pagination se fait par **numéro de page** (`page`, de 1 à 10). La réponse renvoie `pages` (nombre total de pages). On itère tant que `page < pages`.

```python
page, all_jobs = 1, []
raw = search(page=page)               # 1er appel
all_jobs += raw["jobs"]
while page < raw.get("pages", 1):
    page += 1
    raw = search(page=page)
    all_jobs += raw["jobs"]
```

> ℹ️ Contrairement à JSearch (qui pagine par `cursor`), CareerJet pagine par `page`. C'est pour ça que le code abstrait chaque API avec un attribut `PAGE_PARAM` (`"page"` ici, `"cursor"` pour JSearch).

---

### Structure de la réponse

#### Succès (HTTP 200)

```json
{
    "type": "JOBS",
    "hits": 62,
    "message": "62 matching jobs found",
    "pages": 4,
    "response_time": 0.322,
    "jobs": [...]
}
```

#### Structure d'une offre

| Champ | Type | Description |
|---|---|---|
| `title` | String | Intitulé du poste |
| `company` | String | Nom de l'entreprise |
| `date` | String | Date de publication (GMT) |
| `description` | String | Extrait de la description (taille = `fragment_size`) |
| `locations` | String | Localisation |
| `salary` | String | Fourchette salariale (texte) |
| `salary_currency_code` | String | Devise (ex. `USD`, `CLP`, `ARS`) |
| `salary_min` | Float | Salaire minimum |
| `salary_max` | Float | Salaire maximum |
| `salary_type` | Enum | `Y` annuel, `M` mensuel, `W` hebdo, `D` journalier, `H` horaire |
| `site` | String | Domaine source |
| `url` | String | Lien vers l'offre |

> Comme pour JSearch, les champs de salaire et de localisation sont **souvent vides** selon la source de l'offre. Prévoir des colonnes nullables côté schéma `analytics`.

---

### Erreurs

| HTTP | Message | Cause | Correctif |
|---|---|---|---|
| `400` | Unsupported locale code | `locale_code` invalide | Utiliser un code valide (`es_AR`, `es_CL`…) |
| `401` | Invalid API key provided | Clé absente / invalide | Vérifier `CAREERJET_APP_KEY` |
| `403` | Unauthorized access from IP `…` | IP de sortie non déclarée | Déclarer l'IP indiquée dans le compte publisher |
| `403` | Undeclared referrer. Please add a Referer header. | Header `Referer` manquant / non concordant | Envoyer `Referer` = URL du site déclaré (`CAREERJET_REFERER`) |
| `403` | Missing param user_ip or user_agent | Paramètres obligatoires manquants | Renseigner `user_ip` et `user_agent` |

---

### Plan gratuit

| Limite | Valeur |
|---|---|
| Requêtes | 500 (à confirmer : total ou mensuel) |
| IP déclarées | 8 maximum |
| Carte bancaire | Non requise |

---