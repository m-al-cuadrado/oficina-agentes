"""Cronometra cada pieza por separado para localizar qué va lento.
Ejecutar desde la raíz del proyecto:  python scripts/diagnose.py
Hace UNA llamada mínima al modelo (5 tokens). No modifica tus correos."""
import os
import socket
import sys
import time

sys.path.insert(0, os.getcwd())


def timed(label, fn):
    t = time.perf_counter()
    try:
        res = fn()
        dt = time.perf_counter() - t
        flag = "  <-- LENTO" if dt > 3 else ""
        print(f"{label:<46} {dt:7.2f} s{flag}")
        return res
    except Exception as e:
        dt = time.perf_counter() - t
        print(f"{label:<46} {dt:7.2f} s  ERROR: {type(e).__name__}: {str(e)[:120]}")
        return None


def tcp(host, family, port=443, timeout=15):
    infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(infos[0][4])
    finally:
        s.close()


print("== 1. Red: DNS y conexión TCP (IPv4 vs IPv6) ==")
for host in ("gmail.googleapis.com", "api.anthropic.com"):
    timed(f"{host} IPv4", lambda h=host: tcp(h, socket.AF_INET))
    timed(f"{host} IPv6", lambda h=host: tcp(h, socket.AF_INET6))

print("\n== 2. Base de datos ==")
try:
    import config
    import psycopg

    def db():
        with psycopg.connect(config.DATABASE_URL, connect_timeout=10) as c:
            return c.execute("SELECT 1").fetchone()

    for i in range(3):
        timed(f"Postgres conexión + SELECT 1 (intento {i + 1})", db)
except Exception as e:
    print("No se pudo cargar config/psycopg:", e)
    config = None

print("\n== 3. Gmail ==")
try:
    import gmail_tools as g
    timed("Construir servicio de Gmail", g._service)
    refs = timed("Listar correos sin procesar (1)", lambda: g.list_unprocessed(1))
    if refs:
        timed("Leer metadatos de un correo", lambda: g.get_message(refs[0]["id"]))
        timed("Comprobar etiqueta 'oficina'", lambda: g.ensure_label("oficina"))
    else:
        print("(sin correos nuevos para probar lectura)")
except Exception as e:
    print("Gmail no disponible:", type(e).__name__, e)

print("\n== 4. Modelo ==")
if config:
    try:
        import anthropic
        client = anthropic.Anthropic(max_retries=0, timeout=60)
        timed("Llamada mínima al modelo",
              lambda: client.messages.create(
                  model=config.MODEL_CHEAP, max_tokens=5,
                  messages=[{"role": "user", "content": "di ok"}]))
    except Exception as e:
        print("Modelo no disponible:", type(e).__name__, e)

print("\nListo. Pégame esta salida completa.")
