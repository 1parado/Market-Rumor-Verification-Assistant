"""SQLite 持久化（stdlib sqlite3，零额外依赖）。

数据文件：backend/veritas.db（已加入 .gitignore，含 API Key，不入库仓库）。

表结构：
  model_configs  模型配置（名称唯一，upsert）
  runs           一次核查运行：传闻、状态、结论、完整结果 JSON、报告 Markdown
  run_events     运行过程事件流（SSE 事件逐条落库，支持回放）
  messages       用户与 Agent 的会话消息（挂在 run 下）

所有函数短连接 + 进程内锁，FastAPI 线程池下安全。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "veritas.db"
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_configs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  protocol   TEXT NOT NULL,
  base_url   TEXT NOT NULL,
  api_key    TEXT NOT NULL DEFAULT '',
  model      TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  title         TEXT NOT NULL,
  rumor_text    TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'running',   -- running | done | error
  final_verdict TEXT,
  basis         TEXT,
  data_date     TEXT,
  result_json   TEXT,
  report_md     TEXT,
  created_at    TEXT NOT NULL,
  finished_at   TEXT
);
CREATE TABLE IF NOT EXISTS run_events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id       INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  ts           TEXT NOT NULL,
  event        TEXT NOT NULL,                      -- start | node | done | error
  payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id);
CREATE TABLE IF NOT EXISTS messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  role       TEXT NOT NULL,                        -- user | assistant
  content    TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_run ON messages(run_id);
CREATE TABLE IF NOT EXISTS feishu_instances (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  name               TEXT NOT NULL,
  channel            TEXT NOT NULL DEFAULT 'feishu',   -- feishu | lark
  app_id             TEXT NOT NULL,
  app_secret         TEXT NOT NULL,
  encrypt_key        TEXT NOT NULL DEFAULT '',          -- webhook 可选，本次预留
  verification_token TEXT NOT NULL DEFAULT '',          -- webhook 可选，本次预留
  enabled            INTEGER NOT NULL DEFAULT 1,
  status             TEXT NOT NULL DEFAULT 'configured', -- configured | connected | error | stopped
  last_error         TEXT NOT NULL DEFAULT '',
  owner_open_id      TEXT NOT NULL DEFAULT '',
  model_config_id    INTEGER,                           -- 关联 model_configs.id，IM 触发核查用
  created_at         TEXT NOT NULL,
  updated_at         TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _lock, closing(_conn()) as conn:
        conn.executescript(_SCHEMA)
        # 轻量迁移：旧库补列
        cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
        if "error" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN error TEXT")
        if "prompt_tokens" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN prompt_tokens INTEGER NOT NULL DEFAULT 0")
        if "completion_tokens" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN completion_tokens INTEGER NOT NULL DEFAULT 0")
        conn.commit()


# ===== 模型配置 =====

def upsert_config(name: str, protocol: str, base_url: str, api_key: str, model: str) -> dict:
    """按名称 upsert 模型配置，返回该行。"""
    now = _now()
    with _lock, closing(_conn()) as conn:
        conn.execute(
            """
            INSERT INTO model_configs(name, protocol, base_url, api_key, model, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
              protocol=excluded.protocol, base_url=excluded.base_url,
              api_key=excluded.api_key, model=excluded.model, updated_at=excluded.updated_at
            """,
            (name, protocol, base_url, api_key, model, now, now),
        )
        conn.commit()
        # ON CONFLICT 更新路径下 lastrowid 不可靠，按唯一键 name 回查
        row = conn.execute("SELECT * FROM model_configs WHERE name = ?", (name,)).fetchone()
        return dict(row)


def list_configs() -> list[dict]:
    with closing(_conn()) as conn:
        rows = conn.execute("SELECT * FROM model_configs ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


def delete_config(config_id: int) -> bool:
    with _lock, closing(_conn()) as conn:
        cur = conn.execute("DELETE FROM model_configs WHERE id = ?", (config_id,))
        conn.commit()
        return cur.rowcount > 0


# ===== 核查运行 =====

def create_run(rumor_text: str) -> int:
    title = rumor_text.strip().replace("\n", " ")[:40] or "未命名核查"
    with _lock, closing(_conn()) as conn:
        cur = conn.execute(
            "INSERT INTO runs(title, rumor_text, status, created_at) VALUES(?,?,'running',?)",
            (title, rumor_text, _now()),
        )
        conn.commit()
        return cur.lastrowid


def add_event(run_id: int, event: str, payload: dict[str, Any]) -> None:
    with _lock, closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO run_events(run_id, ts, event, payload_json) VALUES(?,?,?,?)",
            (run_id, _now(), event, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()


def finish_run(
    run_id: int,
    status: str,
    result: dict | None = None,
    report_md: str = "",
    error: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """运行结束：写入结论/结果/报告，失败时写入失败原因，附带 token 用量。"""
    with _lock, closing(_conn()) as conn:
        conn.execute(
            """
            UPDATE runs SET status=?, finished_at=?, final_verdict=?, basis=?, data_date=?,
                            result_json=?, report_md=?, error=?,
                            prompt_tokens=MAX(prompt_tokens, ?), completion_tokens=MAX(completion_tokens, ?)
            WHERE id=?
            """,
            (
                status, _now(),
                (result or {}).get("final_verdict"),
                (result or {}).get("basis"),
                (result or {}).get("data_date"),
                json.dumps(result, ensure_ascii=False) if result else None,
                report_md or None,
                error,
                prompt_tokens, completion_tokens,
                run_id,
            ),
        )
        conn.commit()


def add_tokens(run_id: int, prompt_tokens: int, completion_tokens: int) -> None:
    """会话追问等增量消耗：累加到运行总用量。"""
    with _lock, closing(_conn()) as conn:
        conn.execute(
            "UPDATE runs SET prompt_tokens = prompt_tokens + ?, completion_tokens = completion_tokens + ? WHERE id = ?",
            (prompt_tokens, completion_tokens, run_id),
        )
        conn.commit()


def fail_stale_runs() -> int:
    """启动时清理：把上次进程中断遗留的 running 运行标记为 error。

    单进程 MVP 下，任何跨启动仍为 running 的记录必然是服务中断所致
    （事件流停在最后一个已落库节点，结果缺失），不可能仍在执行。
    """
    with _lock, closing(_conn()) as conn:
        cur = conn.execute(
            """UPDATE runs SET status='error', finished_at=?, error=?,
                   basis=COALESCE(basis, '服务中断：核查未完成，结论缺失')
               WHERE status='running'""",
            (_now(), "服务中断：进程在核查完成前退出"),
        )
        conn.commit()
        return cur.rowcount


def list_runs(limit: int = 50) -> list[dict]:
    with closing(_conn()) as conn:
        rows = conn.execute(
            """SELECT id, title, rumor_text, status, final_verdict, error, data_date,
                      prompt_tokens, completion_tokens, created_at, finished_at
               FROM runs ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_run(run_id: int) -> dict | None:
    """运行详情：run + 事件流 + 会话消息（结果 JSON 已反序列化）。"""
    with closing(_conn()) as conn:
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return None
        events = conn.execute(
            "SELECT id, ts, event, payload_json FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        messages = conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    d = dict(run)
    if d.get("result_json"):
        try:
            d["result"] = json.loads(d.pop("result_json"))
        except json.JSONDecodeError:
            d["result"] = None
    else:
        d["result"] = None
    d["events"] = [{**dict(e), "payload": json.loads(e["payload_json"])} for e in events]
    d["messages"] = [dict(m) for m in messages]
    return d


def delete_run(run_id: int) -> bool:
    with _lock, closing(_conn()) as conn:
        cur = conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        conn.commit()
        return cur.rowcount > 0


# ===== 会话消息 =====

def add_message(run_id: int, role: str, content: str) -> dict:
    with _lock, closing(_conn()) as conn:
        cur = conn.execute(
            "INSERT INTO messages(run_id, role, content, created_at) VALUES(?,?,?,?)",
            (run_id, role, content, _now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)


# ===== 飞书实例 =====
# secrets（app_id/app_secret）与 model_configs.api_key 同等处理：存 SQLite（veritas.db 已 gitignore）。
# 给前端的响应在 app.py 路由层抹掉 app_secret，storage 层返回完整行供后端内部使用。

def upsert_feishu_instance(
    name: str,
    channel: str,
    app_id: str,
    app_secret: str,
    owner_open_id: str = "",
    model_config_id: int | None = None,
    enabled: bool = True,
    instance_id: int | None = None,
) -> dict:
    """新建或更新飞书实例。instance_id 为空时插入，否则按 id 更新。返回该行。"""
    now = _now()
    with _lock, closing(_conn()) as conn:
        if instance_id:
            conn.execute(
                """UPDATE feishu_instances SET name=?, channel=?, app_id=?, app_secret=?,
                       owner_open_id=?, model_config_id=?, enabled=?, updated_at=?
                   WHERE id=?""",
                (name, channel, app_id, app_secret, owner_open_id, model_config_id,
                 1 if enabled else 0, now, instance_id),
            )
        else:
            conn.execute(
                """INSERT INTO feishu_instances
                   (name, channel, app_id, app_secret, owner_open_id, model_config_id,
                    enabled, status, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?, 'configured', ?, ?)""",
                (name, channel, app_id, app_secret, owner_open_id, model_config_id,
                 1 if enabled else 0, now, now),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM feishu_instances WHERE id = ?", (instance_id,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM feishu_instances WHERE rowid = last_insert_rowid()"
            ).fetchone()
        return dict(row)


def list_feishu_instances() -> list[dict]:
    with closing(_conn()) as conn:
        rows = conn.execute("SELECT * FROM feishu_instances ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def get_feishu_instance(instance_id: int) -> dict | None:
    with closing(_conn()) as conn:
        row = conn.execute("SELECT * FROM feishu_instances WHERE id = ?", (instance_id,)).fetchone()
        return dict(row) if row else None


def delete_feishu_instance(instance_id: int) -> bool:
    with _lock, closing(_conn()) as conn:
        cur = conn.execute("DELETE FROM feishu_instances WHERE id = ?", (instance_id,))
        conn.commit()
        return cur.rowcount > 0


def update_feishu_status(instance_id: int, status: str, last_error: str = "") -> None:
    with _lock, closing(_conn()) as conn:
        conn.execute(
            "UPDATE feishu_instances SET status=?, last_error=?, updated_at=? WHERE id=?",
            (status, last_error, _now(), instance_id),
        )
        conn.commit()


def set_feishu_enabled(instance_id: int, enabled: bool) -> None:
    with _lock, closing(_conn()) as conn:
        conn.execute(
            "UPDATE feishu_instances SET enabled=?, status=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, "connected" if enabled else "stopped", _now(), instance_id),
        )
        conn.commit()


def get_model_config(config_id: int) -> dict | None:
    """读 model_configs 一行（供 IM 触发核查时构造 LLMConfig）。"""
    with closing(_conn()) as conn:
        row = conn.execute("SELECT * FROM model_configs WHERE id = ?", (config_id,)).fetchone()
        return dict(row) if row else None
