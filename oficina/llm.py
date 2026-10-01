import anthropic
import psycopg
from config import DATABASE_URL, DAILY_BUDGET_USD, PRICES

client = anthropic.Anthropic()


class BudgetExceeded(Exception):
    pass


def _spent_today():
    with psycopg.connect(DATABASE_URL) as c:
        return float(c.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage WHERE day = CURRENT_DATE"
        ).fetchone()[0])


def call(agent, model, system, user, max_tokens=800):
    if _spent_today() >= DAILY_BUDGET_USD:
        raise BudgetExceeded(f"Tope diario de {DAILY_BUDGET_USD} USD alcanzado")
    r = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    pin, pout = PRICES[model]
    cost = (r.usage.input_tokens * pin + r.usage.output_tokens * pout) / 1_000_000
    with psycopg.connect(DATABASE_URL) as c:
        c.execute(
            "INSERT INTO llm_usage(agent, model, input_tokens, output_tokens, cost_usd) "
            "VALUES (%s,%s,%s,%s,%s)",
            (agent, model, r.usage.input_tokens, r.usage.output_tokens, cost),
        )
    return "".join(b.text for b in r.content if b.type == "text")
