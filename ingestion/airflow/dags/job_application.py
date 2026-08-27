from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException
import traceback
from datasets import BRONZE_OFFERS, STAGING_ENRICHED
from database import Database


from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


QUERY = """"""

def get_db() -> Database:
    return Database(
        db_host           = Variable.get("DB_HOST"),
        db_name           = Variable.get("DB_NAME"),
        db_user           = Variable.get("DB_USER"),
        db_password       = Variable.get("DB_PASSWORD"),
        db_sslmode        = Variable.get("DB_SSLMODE",       default_var="require"),
        db_channelbinding = Variable.get("DB_CHANNELBIDING", default_var="disable"),
    )



def fetch_offer():
    pass

def load_yaml():
    pass


@dag(
    dag_id='job_application',
    start_date=datetime(2026, 6, 7),
    schedule=[],
    catchup=False,
    max_active_runs=1,
    tags=["silver", "application", "llm"],
    default_args={'owner': 'internship_latam'},
)
def automated_application():

    @task(task_id="generate_application", outlets=[])
    def generate_application():
        """
        Fetch relevant offer
        Generate letter and cover letter
        Save them in locale
        """
        from graph_silver_enrichment import graph
        from silver_enrichment import map_bronze_to_JobOfferState, map_prompt_to_JobOfferState
        from LLMprovider import LLM
        from APIendpoint import PlacesAPIId, PlacesAPIDetails
        from utils import clean_location_raw
 
        llm = LLM()
        llm_model_name = llm.enrichement.model

        job_context = fetch_offer(QUERY)
        application_data = load_yaml()

        email_resolved = resolve_document(
            body_paragraphs=email_content["body_paragraphs"],
            default_greeting=email_content["greeting_line"],
            skills=skills,
            job_context=job_context,
            model=model,
        )

        letter_resolved = resolve_document(
            body_paragraphs=letter_content["body_paragraphs"],
            default_greeting=letter_content["greeting_line"],
            skills=skills,
            job_context=job_context,
            model=model,
        )

        
    # --- Formatage email (pur, aucun appel LLM) ---
    email_content_final = {
        **email_content,
        "greeting_line": email_resolved["greeting_line"],
        "body_paragraphs": email_resolved["body_paragraphs"],
    }
    email_context = build_context(profile, email_content_final)
    email_rendered = render_email(email_context)

    # --- Formatage PDF (pur, aucun appel LLM) ---
    letter_content_final = {
        **letter_content,
        "greeting_line": letter_resolved["greeting_line"],
        "body_paragraphs": letter_resolved["body_paragraphs"],
    }
    pdf_context = {**profile, **letter_content_final}

    # --- Écriture des sorties ---
    # Timestamp lisible pour l'homme, inclus dans le nom de fichier afin de
    # garder une trace de chaque test sans écraser les précédents.
    timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%M")

    pdf_path = OUTPUT_DIR / f"cover_letter_{timestamp}.pdf"
    render_pdf(pdf_context, output_path=str(pdf_path))

    email_path = OUTPUT_DIR / f"email_{timestamp}.txt"
    with open(email_path, "w", encoding="utf-8") as f:
        f.write(f"Généré le : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Offre     : {job_context['company_name']} — {job_context['job_title']}\n")
        f.write(f"id_offer  : {job_context['offer_id']}\n")
        f.write(f"To: {job_context['contact_email'] or '(aucun contact trouvé)'}\n")
        f.write(f"Subject: {email_rendered['subject']}\n")
        f.write("\n" + "-" * 60 + "\n\n")
        f.write(email_rendered["body"])

    print(f"\n✅ PDF généré  : {pdf_path}")
    print(f"✅ Email écrit : {email_path}")



    @task(task_id="send_application", outlets=[])
    def send_application():
        """
        Send the mails
        """
        # --- Envoi réel via Gmail, vers toi-même, avec CV + lettre en pièces jointes ---
        print(f"\n→ Envoi de l'email de test à {TEST_RECIPIENT}...")

        if not CV_PATH.exists():
            raise FileNotFoundError(
                f"CV introuvable à {CV_PATH} — ajuste CV_PATH en tête de fichier."
            )

        creds = load_gmail_credentials()
        service = build("gmail", "v1", credentials=creds)
        label_id = get_or_create_label(service, LABEL_NAME)

        message = build_message_with_attachments(
            to_address=TEST_RECIPIENT,
            subject=f"[TEST] {email_rendered['subject']}",
            body_text=(
                f"Offre testée : {job_context['company_name']} — {job_context['job_title']}\n"
                f"id_offer : {job_context['offer_id']}\n"
                f"Contact réel (non utilisé, envoi vers soi-même) : {job_context['contact_email']}\n\n"
                + "-" * 60 + "\n\n"
                + email_rendered["body"]
            ),
            attachment_paths=[CV_PATH, pdf_path],
        )

        sent = send_and_label(service, message, label_id)

    print(f"✅ Email envoyé et labellisé '{LABEL_NAME}'. Message ID : {sent['id']}")

    @task(task_id="track_application", outlets=[])
    def track_application():
        """
        Track application sent
        Save in bucket the cv and letter
        """

