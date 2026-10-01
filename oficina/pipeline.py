import logging

import psycopg
from psycopg.types.json import Jsonb

import gmail_tools as gmail
from agents.mail_classifier import classify
from config import DATABASE_URL, MODEL_CHEAP
from llm import BudgetExceeded

log = logging.getLogger(__name__)


def _alog(event, detail):
    """Registro en agent_log (solo ids y metadatos, nunca contenido de correos)."""
    try:
        with psycopg.connect(DATABASE_URL) as c:
            c.execute("INSERT INTO agent_log(agent, event, detail) VALUES ('clasificador', %s, %s)",
                      (event, Jsonb(detail)))
    except Exception:
        log.exception("No se pudo escribir en agent_log")


def process_new_mail():
    """Clasifica los correos nuevos y devuelve los importantes [(mail, resultado)].

    - Si se agota el tope diario, se detiene y devuelve lo ya procesado.
    - Si un correo concreto falla, se registra y se sigue con el siguiente.
    """
    important = []
    for ref in gmail.list_unprocessed():
        try:
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
            _alog("classified", {"mail_id": mail["id"], "category": res["category"],
                                 "classified_with": res["classified_with"],
                                 "body_chars": res["body_chars"]})
        except BudgetExceeded:
            log.warning("Tope diario alcanzado: se detiene el ciclo de correo")
            _alog("budget_exceeded", {"mail_id": ref.get("id")})
            break
        except Exception as e:
            log.exception("Fallo procesando el correo %s; se reintentará en el siguiente ciclo", ref.get("id"))
            _alog("error", {"mail_id": ref.get("id"), "type": type(e).__name__})
            continue
        if res["category"] in ("urgente", "cliente") or res["needs_reply"]:
            important.append((mail, res))
    return important
