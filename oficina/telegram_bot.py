"""Interfaz de Telegram: avisos con botones y comandos.
Solo responde al chat autorizado (ALLOWED_CHAT_ID); al resto lo ignora en silencio."""
import asyncio
import logging
import re

import psycopg
from psycopg.types.json import Jsonb
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, filters)

from agents.idea_critic import run_critic
from agents.mail_drafter import DraftError, draft_reply
from config import ALLOWED_CHAT_ID, DAILY_BUDGET_USD, DATABASE_URL
from llm import BudgetExceeded
from summary import build_summary

log = logging.getLogger(__name__)
ONLY_ME = filters.Chat(chat_id=ALLOWED_CHAT_ID)
ICONS = {"urgente": "🔴", "cliente": "🟠", "factura": "🧾", "otro": "📩"}
MAX_IDEA_CHARS = 2000


def _cut(text, n):
    """Una sola línea y longitud limitada. El texto del correo no es de fiar."""
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _split(text, n=3800):
    """Divide un texto largo en trozos aptos para Telegram (límite 4096)."""
    chunks = []
    while len(text) > n:
        cut = text.rfind("\n\n", 0, n)
        if cut < n // 2:
            cut = text.rfind("\n", 0, n)
        if cut < n // 2:
            cut = n
        chunks.append(text[:cut].strip())
        text = text[cut:].lstrip()
    if text.strip():
        chunks.append(text.strip())
    return chunks


# ---------- base de datos (síncrono; se llama con asyncio.to_thread) ----------
def mark_notified(mail_id):
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("UPDATE emails SET status='notified', updated_at=now() "
                  "WHERE id=%s AND status='classified'", (mail_id,))


def _set_status(mail_id, status):
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("UPDATE emails SET status=%s, updated_at=now() WHERE id=%s",
                  (status, mail_id))


def _log_event(event, detail):
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("INSERT INTO agent_log(agent, event, detail) VALUES ('telegram', %s, %s)",
                  (event, Jsonb(detail)))


def _pending():
    with psycopg.connect(DATABASE_URL) as c:
        return c.execute(
            "SELECT category, subject, summary FROM emails "
            "WHERE status IN ('classified','notified') "
            "AND (category IN ('urgente','cliente') OR needs_reply) "
            "ORDER BY created_at DESC LIMIT 10").fetchall()


def _spend():
    with psycopg.connect(DATABASE_URL) as c:
        today = c.execute(
            "SELECT agent, model, COUNT(*), COALESCE(SUM(cost_usd),0) FROM llm_usage "
            "WHERE day = CURRENT_DATE GROUP BY agent, model ORDER BY 4 DESC").fetchall()
        month = c.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage "
            "WHERE day >= date_trunc('month', CURRENT_DATE)::date").fetchone()[0]
    return today, float(month)


# ---------- avisos ----------
async def send_mail_alert(bot, mail, res):
    text = (
        f"{ICONS.get(res['category'], '📩')} {res['category'].upper()}"
        f"{' · requiere respuesta' if res.get('needs_reply') else ''}\n"
        f"De: {_cut(mail['sender'], 100)}\n"
        f"Asunto: {_cut(mail['subject'], 150)}\n\n"
        f"{_cut(res['summary'], 400)}"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✍️ Redactar borrador", callback_data=f"draft:{mail['id']}"),
        InlineKeyboardButton("🙈 Ignorar", callback_data=f"ignore:{mail['id']}"),
    ]])
    # Sin parse_mode: texto plano, para que el contenido del correo no pueda inyectar formato.
    await bot.send_message(chat_id=ALLOWED_CHAT_ID, text=text, reply_markup=keyboard)


# ---------- comandos ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Oficina activa ✅\n"
        "/pendientes — correos importantes sin gestionar\n"
        "/idea <texto> — critica una idea\n"
        "/gasto — gasto en modelos\n"
        "/resumen — resumen de las últimas 24 h")


async def cmd_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await asyncio.to_thread(_pending)
    if not rows:
        await update.message.reply_text("No hay correos importantes pendientes ✅")
        return
    lines = [f"{ICONS.get(cat, '📩')} {_cut(subj, 80)} — {_cut(summ, 120)}"
             for cat, subj, summ in rows]
    await update.message.reply_text("Pendientes:\n\n" + "\n\n".join(lines))


async def cmd_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today, month = await asyncio.to_thread(_spend)
    total = sum(float(r[3]) for r in today)
    lines = [f"💸 Hoy: {total:.3f} / {DAILY_BUDGET_USD} USD"]
    lines += [f"• {a or '?'} ({m}): {n} llamadas · {float(c):.3f} USD" for a, m, n, c in today]
    lines.append(f"Este mes: {month:.3f} USD")
    await update.message.reply_text("\n".join(lines))


async def cmd_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(await asyncio.to_thread(build_summary))


async def _run_idea(update, context, idea):
    msg = update.message
    try:
        await msg.reply_text("🧠 Analizando la idea (1-2 minutos)…")
        text = await asyncio.to_thread(run_critic, idea)
        for part in _split(text):
            await msg.reply_text(part)
    except BudgetExceeded:
        await msg.reply_text("💸 Tope diario de gasto alcanzado. Inténtalo mañana.")
    except Exception:
        log.exception("Fallo en el agente crítico")
        await msg.reply_text("⚠️ Falló el análisis. Mira los logs.")
    finally:
        context.bot_data["idea_busy"] = False


async def cmd_idea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    idea = re.sub(r"^/idea(@\w+)?\s*", "", update.message.text or "").strip()
    if not idea:
        await update.message.reply_text("Uso: /idea <describe tu idea en pocas frases>")
        return
    if len(idea) > MAX_IDEA_CHARS:
        await update.message.reply_text(f"Idea demasiado larga (máx. {MAX_IDEA_CHARS} caracteres).")
        return
    if context.bot_data.get("idea_busy"):
        await update.message.reply_text("Ya hay un análisis en curso. Espera a que termine.")
        return
    context.bot_data["idea_busy"] = True
    # En segundo plano, para no bloquear los botones mientras dura el análisis.
    context.application.create_task(_run_idea(update, context, idea), update=update)


# ---------- botones ----------
async def _do_draft(q, context, mail_id):
    busy = context.bot_data.setdefault("drafting", set())
    if mail_id in busy:
        await q.answer("Ya se está redactando…")
        return
    busy.add(mail_id)
    await q.answer("Redactando borrador…")
    try:
        r = await asyncio.to_thread(draft_reply, mail_id)
    except BudgetExceeded:
        await q.message.reply_text("💸 Tope diario de gasto alcanzado. Inténtalo mañana.")
    except DraftError as e:
        await q.message.reply_text(f"⚠️ {e}")
    except Exception:
        log.exception("Fallo al redactar el borrador de %s", mail_id)
        await q.message.reply_text("⚠️ Falló la redacción. Mira los logs.")
    else:
        if r["created"]:
            await q.edit_message_text(f"{q.message.text}\n\n✍️ Borrador creado")
            await q.message.reply_text(
                "✅ Borrador creado en Gmail (NO enviado). Revísalo en Borradores.\n\n"
                f"Vista previa:\n{r['text'][:1200]}")
        else:
            await q.message.reply_text("Ya existía un borrador para este correo. Búscalo en Gmail > Borradores.")
    finally:
        busy.discard(mail_id)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if update.effective_chat is None or update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    action, _, mail_id = (q.data or "").partition(":")

    if action == "ignore":
        await q.answer()
        await asyncio.to_thread(_set_status, mail_id, "ignored")
        await asyncio.to_thread(_log_event, "mail_ignored", {"mail_id": mail_id})
        await q.edit_message_text(f"{q.message.text}\n\n✔ Ignorado")
    elif action == "draft":
        await _do_draft(q, context, mail_id)
    else:
        await q.answer()


def register(app: Application):
    app.add_handler(CommandHandler("start", cmd_start, filters=ONLY_ME))
    app.add_handler(CommandHandler("pendientes", cmd_pendientes, filters=ONLY_ME))
    app.add_handler(CommandHandler("idea", cmd_idea, filters=ONLY_ME))
    app.add_handler(CommandHandler("gasto", cmd_gasto, filters=ONLY_ME))
    app.add_handler(CommandHandler("resumen", cmd_resumen, filters=ONLY_ME))
    app.add_handler(CallbackQueryHandler(on_button))
