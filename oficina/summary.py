"""Resumen diario construido solo con consultas a la base de datos (sin LLM: coste 0)."""
import psycopg

from config import DAILY_BUDGET_USD, DATABASE_URL

ICONS = {"urgente": "🔴", "cliente": "🟠", "factura": "🧾", "newsletter": "📰",
         "spam": "🗑️", "otro": "📩"}


def _cut(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def build_summary() -> str:
    with psycopg.connect(DATABASE_URL) as c:
        cats = c.execute(
            "SELECT category, COUNT(*) FROM emails "
            "WHERE created_at > now() - interval '24 hours' GROUP BY category ORDER BY 2 DESC"
        ).fetchall()
        pend = c.execute(
            "SELECT category, subject, summary FROM emails "
            "WHERE status IN ('classified','notified') "
            "AND (category IN ('urgente','cliente') OR needs_reply) "
            "ORDER BY created_at DESC LIMIT 5").fetchall()
        drafts = c.execute("SELECT COUNT(*) FROM emails WHERE status='drafted' "
                           "AND updated_at > now() - interval '24 hours'").fetchone()[0]
        errors = c.execute("SELECT COUNT(*) FROM agent_log WHERE event='error' "
                           "AND created_at > now() - interval '24 hours'").fetchone()[0]
        spent = float(c.execute("SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage "
                                "WHERE day = CURRENT_DATE - 1").fetchone()[0])

    total = sum(n for _, n in cats)
    lines = ["☀️ Resumen de la oficina", ""]
    if total:
        lines.append(f"Correos clasificados (24 h): {total}")
        lines.append(" · ".join(f"{ICONS.get(k, '📩')} {k} {n}" for k, n in cats))
    else:
        lines.append("Sin correos nuevos en las últimas 24 h.")
    lines.append(f"Borradores creados: {drafts}")
    if pend:
        lines += ["", "Pendientes importantes:"]
        lines += [f"• {_cut(s, 70)} — {_cut(m, 100)}" for _, s, m in pend]
    else:
        lines += ["", "Nada importante pendiente ✅"]
    lines += ["", f"Gasto de ayer: {spent:.3f} USD (tope diario {DAILY_BUDGET_USD} USD)"]
    if errors:
        lines.append(f"⚠️ Errores registrados en 24 h: {errors}")
    return "\n".join(lines)
