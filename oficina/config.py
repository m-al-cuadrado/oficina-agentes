import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ALLOWED_CHAT_ID = int(os.environ["ALLOWED_CHAT_ID"])
DATABASE_URL = os.environ["DATABASE_URL"]
DAILY_BUDGET_USD = float(os.getenv("DAILY_BUDGET_USD", "2.0"))

MODEL_CHEAP = "claude-haiku-4-5-20251001"
MODEL_WRITER = "claude-sonnet-5-5"
MODEL_REASONER = "claude-opus-5-5"

# Precios en USD por millón de tokens (entrada, salida).
# VERIFÍCALOS en la web oficial: cambian y las fuentes se contradicen.
PRICES = {
    MODEL_CHEAP:    (1.0, 5.0),
    MODEL_WRITER:   (2.0, 10.0),
    MODEL_REASONER: (4.0, 20.0),
}

# --- Lectura del cuerpo del correo ---
# "fallback": clasifica con el snippet y, si sale 'otro', relee con el cuerpo (uso personal).
# "always":   lee el cuerpo desde el principio (pensado para empresas).
READ_BODY_MODE = os.getenv("READ_BODY_MODE", "fallback")
BODY_CHARS_FALLBACK = int(os.getenv("BODY_CHARS_FALLBACK", "1500"))
BODY_CHARS_ALWAYS = int(os.getenv("BODY_CHARS_ALWAYS", "6000"))
