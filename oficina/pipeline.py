import psycopg

import gmail_tools as gmail
from agents.mail_classifier import classify
from config import DATABASE_URL, MODEL_CHEAP


def process_new_mail():
    """Clasifica los correos nuevos y devuelve los importantes [(mail, resultado)]."""
    important = []
    for ref in gmail.list_unprocessed():
        mail = gmail.get_message(ref["id"])
        res = classify(mail)
        gmail.apply_labels(mail["id"], ["oficina", f"oficina/{res['category']}"])
        with psycopg.connect(DATABASE_URL) as c:
            c.execute(
                "INSERT INTO emails(id, thread_id, sender, subject, snippet, category, "
                "summary, needs_reply, model, classified_with, body_chars) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (mail["id"], mail["thread_id"], mail["sender"], mail["subject"],
                 mail["snippet"], res["category"], res["summary"], res["needs_reply"],
                 MODEL_CHEAP, res["classified_with"], res["body_chars"]),
            )
        if res["category"] in ("urgente", "cliente") or res["needs_reply"]:
            important.append((mail, res))
    return important
