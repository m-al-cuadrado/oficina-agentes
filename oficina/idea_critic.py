"""Agente crítico (abogado del diablo + pre-mortem + síntesis) con LangGraph.
Flujo lineal de 3 pasos. Modelo medio en los dos primeros; Opus solo en la síntesis,
que es donde hace falta razonar."""
from typing import TypedDict

import psycopg
from langgraph.graph import END, START, StateGraph

from config import DATABASE_URL, MODEL_REASONER, MODEL_WRITER
from llm import call

SYS_OBJECIONES = """Eres un abogado del diablo riguroso y honesto. Recibirás una idea entre etiquetas <idea>.
Devuelve EXACTAMENTE 5 objeciones numeradas, de la más grave a la menos grave. Para cada una:
la objeción en una frase, por qué importa y qué prueba barata la confirmaría o la descartaría.
No halagues. No inventes datos ni cifras de mercado; si das una cifra, márcala como [estimación].
Si falta información clave, di qué falta en lugar de suponerla. Responde en español."""

SYS_PREMORTEM = """Haz un pre-mortem. Recibirás una idea entre <idea> y objeciones ya detectadas entre <objeciones>.
Imagina que pasaron 12 meses y la idea fracasó. Escribe 4 causas de fracaso plausibles y DISTINTAS
de las objeciones ya dadas. Para cada una, añade una señal temprana observable. Sin cifras inventadas.
Responde en español."""

SYS_SINTESIS = """Eres un consultor crítico. Recibirás una idea, sus objeciones y un pre-mortem.
Entrega, en español y sin relleno:
1) VEREDICTO en una línea: seguir / ajustar / parar, con la razón principal.
2) IDEA MEJORADA en 5 líneas como máximo.
3) TRES EXPERIMENTOS baratos para esta semana, cada uno con criterio de éxito y de fracaso.
4) LA SUPOSICIÓN MÁS PELIGROSA y cómo comprobarla primero.
No inventes datos; marca lo no verificado como [no verificado]."""


class State(TypedDict, total=False):
    idea: str
    objeciones: str
    premortem: str
    sintesis: str


def _objeciones(s: State):
    return {"objeciones": call("critico", MODEL_WRITER, SYS_OBJECIONES,
                               f"<idea>\n{s['idea']}\n</idea>", max_tokens=1000)}


def _premortem(s: State):
    user = f"<idea>\n{s['idea']}\n</idea>\n<objeciones>\n{s['objeciones']}\n</objeciones>"
    return {"premortem": call("critico", MODEL_WRITER, SYS_PREMORTEM, user, max_tokens=800)}


def _sintesis(s: State):
    user = (f"<idea>\n{s['idea']}\n</idea>\n<objeciones>\n{s['objeciones']}\n</objeciones>\n"
            f"<premortem>\n{s['premortem']}\n</premortem>")
    return {"sintesis": call("critico", MODEL_REASONER, SYS_SINTESIS, user, max_tokens=1200)}


def _build():
    g = StateGraph(State)
    g.add_node("objeciones", _objeciones)
    g.add_node("premortem", _premortem)
    g.add_node("sintesis", _sintesis)
    g.add_edge(START, "objeciones")
    g.add_edge("objeciones", "premortem")
    g.add_edge("premortem", "sintesis")
    g.add_edge("sintesis", END)
    return g.compile()


_graph = _build()


def run_critic(idea: str) -> str:
    """Ejecuta los 3 pasos, guarda el resultado en `ideas` y lo devuelve como texto."""
    out = _graph.invoke({"idea": idea})
    text = (f"{out['sintesis']}\n\n— OBJECIONES —\n{out['objeciones']}\n\n"
            f"— PRE-MORTEM —\n{out['premortem']}")
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("INSERT INTO ideas(idea, result) VALUES (%s, %s)", (idea, text))
    return text
