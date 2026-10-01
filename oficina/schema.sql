-- Oficina de agentes: esquema v2
-- Ejecutar una vez:  psql -U oficina -d oficina -f schema.sql
-- Es idempotente (IF NOT EXISTS), se puede repetir sin romper nada.

-- El "día" del tope de gasto debe cambiar a medianoche en Madrid, no en UTC.
-- Aplica a las conexiones NUEVAS a partir de ahora.
ALTER DATABASE oficina SET timezone TO 'Europe/Madrid';

-- ---------------------------------------------------------------
-- Correos procesados (uno por mensaje de Gmail)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS emails (
  id           TEXT PRIMARY KEY,                 -- id del mensaje en Gmail
  thread_id    TEXT,                             -- hilo, para crear borradores en la conversación
  sender       TEXT NOT NULL DEFAULT '',
  subject      TEXT NOT NULL DEFAULT '',
  snippet      TEXT NOT NULL DEFAULT '',         -- fragmento inicial (no guardamos el cuerpo)
  category     TEXT NOT NULL DEFAULT 'otro'
               CHECK (category IN ('urgente','cliente','factura','newsletter','spam','otro')),
  summary      TEXT,                             -- resumen de una frase del modelo
  needs_reply  BOOLEAN NOT NULL DEFAULT FALSE,
  status       TEXT NOT NULL DEFAULT 'classified'
               CHECK (status IN ('classified','notified','drafted','ignored','error')),
  draft_id     TEXT,                             -- id del borrador en Gmail (evita duplicados)
  model        TEXT,                             -- modelo que clasificó (para comparar calidad)
  error        TEXT,                             -- mensaje si algo falló con este correo
  classified_with TEXT NOT NULL DEFAULT 'snippet'
               CHECK (classified_with IN ('snippet','body')),  -- qué texto vio el clasificador
  body_chars   INT NOT NULL DEFAULT 0,           -- cuántos caracteres del cuerpo se leyeron
  received_at  TIMESTAMPTZ,                      -- cuándo llegó el correo
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(), -- cuándo lo procesó el sistema
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Si la tabla ya existía de una versión anterior, esto añade las columnas nuevas:
ALTER TABLE emails ADD COLUMN IF NOT EXISTS classified_with TEXT NOT NULL DEFAULT 'snippet'
  CHECK (classified_with IN ('snippet','body'));
ALTER TABLE emails ADD COLUMN IF NOT EXISTS body_chars INT NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_emails_status     ON emails (status);
CREATE INDEX IF NOT EXISTS idx_emails_created_at ON emails (created_at DESC);

-- ---------------------------------------------------------------
-- Uso de modelos (una fila por llamada). Base del tope de gasto.
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS llm_usage (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  day           DATE NOT NULL DEFAULT CURRENT_DATE,   -- usa la zona horaria de la BD (Madrid)
  agent         TEXT,
  model         TEXT,
  input_tokens  INT NOT NULL DEFAULT 0,
  output_tokens INT NOT NULL DEFAULT 0,
  cost_usd      NUMERIC(10,5) NOT NULL DEFAULT 0,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_day ON llm_usage (day);

-- ---------------------------------------------------------------
-- Registro de eventos (trazabilidad)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_log (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  agent      TEXT,
  event      TEXT,                                -- p. ej. classified, draft_created, error
  detail     JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_log_created_at ON agent_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_log_agent      ON agent_log (agent, created_at DESC);

-- ---------------------------------------------------------------
-- Historial de ideas discutidas con /idea
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ideas (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  idea       TEXT NOT NULL,
  result     TEXT,                                -- crítica completa devuelta por el agente
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------
-- Limpieza de privacidad (ejecútala a mano o con cron cada semana):
--   DELETE FROM emails    WHERE created_at < now() - interval '90 days';
--   DELETE FROM agent_log WHERE created_at < now() - interval '90 days';
-- ---------------------------------------------------------------
