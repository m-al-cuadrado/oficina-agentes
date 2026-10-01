"""Proceso principal: bot de Telegram (long polling) + revisión periódica del correo
+ resumen matinal a las 8:00 (hora de Madrid)."""
import asyncio
import logging
import os
from datetime import date, time
from zoneinfo import ZoneInfo

from telegram import BotCommand
from telegram.ext import Application, ContextTypes

import telegram_bot
from config import ALLOWED_CHAT_ID, DAILY_BUDGET_USD, TELEGRAM_TOKEN
from llm import _spent_today
from pipeline import process_new_mail
from summary import build_summary

log = logging.getLogger("oficina")
MADRID = ZoneInfo("Europe/Madrid")


async def _say(bot, text):
    try:
        await bot.send_message(chat_id=ALLOWED_CHAT_ID, text=text)
    except Exception:
        log.exception("No se pudo enviar el mensaje a Telegram")


async def check_mail(context: ContextTypes.DEFAULT_TYPE):
    bd = context.bot_data
    try:
        important = await asyncio.to_thread(process_new_mail)
    except Exception as e:
        log.exception("Fallo en el ciclo de correo")
        name = type(e).__name__
        if bd.get("last_error") != name:      # avisa una vez por tipo de error, no cada ciclo
            bd["last_error"] = name
            await _say(context.bot, f"⚠️ Error al revisar el correo: {name}. Revisa los logs.")
        return
    bd.pop("last_error", None)

    for mail, res in important:
        try:
            await telegram_bot.send_mail_alert(context.bot, mail, res)
            await asyncio.to_thread(telegram_bot.mark_notified, mail["id"])
        except Exception:
            log.exception("No se pudo avisar del correo %s (queda en /pendientes)", mail["id"])

    try:
        spent = await asyncio.to_thread(_spent_today)
        if spent >= DAILY_BUDGET_USD and bd.get("budget_warned") != date.today():
            bd["budget_warned"] = date.today()
            await _say(context.bot, f"💸 Tope diario alcanzado ({DAILY_BUDGET_USD} USD). "
                                    "El correo se retoma mañana.")
    except Exception:
        log.exception("No se pudo comprobar el gasto")


async def morning_summary(context: ContextTypes.DEFAULT_TYPE):
    try:
        text = await asyncio.to_thread(build_summary)
        await _say(context.bot, text)
    except Exception:
        log.exception("Fallo al construir el resumen matinal")


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Comprobar que la oficina está activa"),
        BotCommand("pendientes", "Correos importantes sin gestionar"),
        BotCommand("idea", "Criticar una idea: /idea <texto>"),
        BotCommand("gasto", "Gasto en modelos hoy y este mes"),
        BotCommand("resumen", "Resumen de las últimas 24 h"),
    ])
    await _say(app.bot, "🟢 Oficina en marcha")


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx registra la URL de cada petición, y la URL de Telegram contiene el token.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    telegram_bot.register(app)
    minutes = float(os.getenv("POLL_MINUTES", "10"))
    app.job_queue.run_repeating(
        check_mail, interval=minutes * 60, first=15, name="check_mail",
        job_kwargs={"max_instances": 1, "coalesce": True},
    )
    app.job_queue.run_daily(morning_summary, time=time(8, 0, tzinfo=MADRID), name="morning_summary")
    log.info("Arrancando; revisión de correo cada %s min; resumen a las 08:00 Madrid", minutes)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
