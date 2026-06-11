-- init_journal.sql (canonical)
-- TGPS Journal DB bootstrap (DuckDB)
-- Idempotent. Safe to run multiple times.

PRAGMA enable_progress_bar=false;
PRAGMA threads=4;
INSTALL json;
LOAD json;

CREATE SCHEMA IF NOT EXISTS journal;
SET schema 'journal';

------------------------------------------------------------
-- trades (fills from Orders API execution legs)
-- Dedupe key: (account_hash, order_id, exec_id, trade_time, symbol, qty, price)
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
  account_hash TEXT NOT NULL,
  order_id     BIGINT NOT NULL,
  exec_id      TEXT NOT NULL,
  trade_time   TIMESTAMP NOT NULL,
  symbol       TEXT NOT NULL,
  asset_type   TEXT,
  side         TEXT,
  qty          DOUBLE NOT NULL,
  price        DOUBLE NOT NULL,
  amount       DOUBLE,
  fees         DOUBLE,
  put_call     TEXT,
  expiry       DATE,
  strike       DOUBLE,
  source       TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS trades_dedupe_idx
  ON trades (account_hash, order_id, exec_id, trade_time, symbol, qty, price);

CREATE INDEX IF NOT EXISTS trades_time_idx ON trades (trade_time);

-- staging for MERGE (same schema, empty)
CREATE TABLE IF NOT EXISTS trades_stage AS SELECT * FROM trades WHERE 1=0;

------------------------------------------------------------
-- transactions (accounting trail) + transaction_items (unnest transferItems)
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS transactions (
  account_hash     TEXT        NOT NULL,
  activity_id      BIGINT      NOT NULL,
  time             TIMESTAMP   NOT NULL,        -- UTC from API
  type             TEXT        NOT NULL,        -- TRADE / DIVIDEND / INTEREST / FEE / WITHHOLDING / REORG / TRANSFER / MISC ...
  status           TEXT,
  sub_account      TEXT,
  trade_date       DATE,
  settlement_date  DATE,
  order_id         BIGINT,
  net_amount       DOUBLE,
  description      TEXT,
  extras           TEXT,                        -- JSON/text blob (optional)
  PRIMARY KEY (account_hash, activity_id)
);

CREATE INDEX IF NOT EXISTS transactions_time_idx ON transactions (time);
CREATE INDEX IF NOT EXISTS transactions_type_idx ON transactions (type);

CREATE TABLE IF NOT EXISTS transaction_items (
  account_hash     TEXT        NOT NULL,
  activity_id      BIGINT      NOT NULL,
  leg_index        INTEGER     NOT NULL,        -- 1-based
  symbol           TEXT,
  asset_type       TEXT,
  position_effect  TEXT,                        -- OPENING/CLOSING
  price            DOUBLE,
  amount           DOUBLE,
  fee_type         TEXT,
  put_call         TEXT,
  strike           DOUBLE,
  expiry           DATE,
  PRIMARY KEY (account_hash, activity_id, leg_index),
  FOREIGN KEY (account_hash, activity_id) REFERENCES transactions(account_hash, activity_id)
);

CREATE INDEX IF NOT EXISTS idx_tx_items_symbol ON transaction_items (symbol);

------------------------------------------------------------
-- open_orders (snapshot)
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS open_orders (
  account_hash     TEXT        NOT NULL,
  order_id         BIGINT      NOT NULL,
  status           TEXT        NOT NULL,
  entered_time     TIMESTAMP   NOT NULL,
  close_time       TIMESTAMP,
  session          TEXT,
  duration         TEXT,
  order_type       TEXT,
  tag              TEXT,
  -- first-leg summary (if present)
  leg_type         TEXT,
  symbol           TEXT,
  instruction      TEXT,
  qty              DOUBLE,
  price            DOUBLE,
  stop_price       DOUBLE,
  complex_strategy TEXT,
  -- option hints
  put_call         TEXT,
  strike           DOUBLE,
  expiry           DATE,
  raw_json         JSON,
  PRIMARY KEY (account_hash, order_id)
);

CREATE INDEX IF NOT EXISTS open_orders_status_time_idx
  ON open_orders (status, entered_time);

------------------------------------------------------------
-- accounts / streamer_info (lightweight caches)
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
  account_hash     TEXT PRIMARY KEY,
  display_acct_id  TEXT,
  nickname         TEXT,
  type             TEXT,
  primary_account  BOOLEAN
);

CREATE TABLE IF NOT EXISTS streamer_info (
  schwab_client_customer_id TEXT,
  schwab_client_correl_id   TEXT,
  schwab_client_channel     TEXT,
  schwab_client_function_id TEXT,
  streamer_socket_url       TEXT
);

------------------------------------------------------------
-- run_log (etl bookkeeping)
------------------------------------------------------------
CREATE TABLE IF NOT EXISTS run_log (
  run_id        UUID        DEFAULT uuid(),
  started_at    TIMESTAMP   DEFAULT now(),
  completed_at  TIMESTAMP,
  task          TEXT        NOT NULL,          -- fetch_orders / fetch_transactions / fetch_open_orders
  params_json   JSON,
  rows_written  BIGINT      DEFAULT 0,
  status        TEXT        DEFAULT 'STARTED', -- STARTED / OK / ERROR
  message       TEXT
);

------------------------------------------------------------
-- Views (recreated on each run)
------------------------------------------------------------
CREATE OR REPLACE VIEW v_trades_recent AS
SELECT * FROM trades ORDER BY trade_time DESC;

CREATE OR REPLACE VIEW v_transactions_recent AS
SELECT * FROM transactions ORDER BY time DESC;

CREATE OR REPLACE VIEW transactions_symbols_exploded AS
SELECT
  t.account_hash, t.activity_id, t.time, t.type, t.status, t.sub_account,
  t.trade_date, t.settlement_date, t.order_id, t.net_amount, t.description, t.extras,
  i.leg_index, i.symbol, i.asset_type, i.position_effect, i.price, i.amount,
  i.fee_type, i.put_call, i.strike, i.expiry
FROM transactions t
LEFT JOIN transaction_items i
  ON i.account_hash = t.account_hash AND i.activity_id = t.activity_id;

CREATE OR REPLACE VIEW transactions_with_symbol AS
WITH picked AS (
  SELECT
    i.account_hash, i.activity_id, i.symbol,
    ROW_NUMBER() OVER (
      PARTITION BY i.account_hash, i.activity_id
      ORDER BY
        (i.put_call IS NOT NULL) DESC,
        (i.asset_type = 'VANILLA') DESC,
        i.leg_index ASC
    ) AS rn
  FROM transaction_items i
  WHERE i.symbol IS NOT NULL
)
SELECT t.*, p.symbol AS any_symbol
FROM transactions t
LEFT JOIN picked p
  ON p.account_hash = t.account_hash AND p.activity_id = t.activity_id AND p.rn = 1;

CREATE OR REPLACE VIEW v_income AS
SELECT time::DATE AS dt, type, description, net_amount
FROM transactions
WHERE type IN ('DIVIDEND','DIVIDEND_OR_INTEREST','INTEREST');

CREATE OR REPLACE VIEW v_fees AS
SELECT time::DATE AS dt, type, description, net_amount
FROM transactions
WHERE type IN ('FEE','WITHHOLDING','TAX');
