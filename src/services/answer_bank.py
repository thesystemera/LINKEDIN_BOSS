import re
import json
import sqlite3
import hashlib
from datetime import datetime
from typing import Dict, List, Optional

from src.services.form_engine.matching import norm, match_option

CHOICE_KINDS = {"select", "radio", "checkbox", "combobox", "toggle"}


def question_key(question: str) -> str:
    q = norm(re.sub(r"[*✱]|\(required\)|\brequired\b|\(optional\)", " ", question or ""))
    q = re.sub(r"\s+", " ", q).strip()
    return hashlib.sha1(q.encode("utf-8")).hexdigest()[:20]


def kind_family(kind: str) -> str:
    return "choice" if kind in CHOICE_KINDS else ("long" if kind == "textarea" else "short")


class AnswerBank:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure()

    def _conn(self):
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def _ensure(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS answer_bank (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qkey TEXT NOT NULL,
                question TEXT NOT NULL,
                family TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'global',
                region TEXT NOT NULL DEFAULT '',
                options_json TEXT,
                answer TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                source TEXT,
                uses INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(qkey, family, region)
            )""")

    def lookup(self, question: str, kind: str, options: List[str], region: str, allow_pending: bool = True) -> Optional[Dict]:
        qk, fam = question_key(question), kind_family(kind)
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM answer_bank WHERE qkey=? AND family=? AND (region=? OR region='') AND status NOT IN ('rejected', 'failed') "
                "ORDER BY CASE WHEN region=? THEN 0 ELSE 1 END, CASE status WHEN 'approved' THEN 0 ELSE 1 END",
                (qk, fam, region, region)).fetchall()
        for r in rows:
            if r["status"] == "pending" and not allow_pending:
                continue
            ans = r["answer"]
            if fam == "choice" and options:
                parts = [p for p in re.split(r"\s*;\s*", ans) if p]
                if not parts or any(match_option(p, options) is None for p in parts):
                    continue
            with self._conn() as c:
                c.execute("UPDATE answer_bank SET uses=uses+1 WHERE id=?", (r["id"],))
            return dict(r)
        return None

    def store(self, question: str, kind: str, options: List[str], answer: str, scope: str, region: str, source: str = "ai", status: str = "pending"):
        if scope == "job" or answer is None or str(answer).strip() == "":
            return
        qk, fam = question_key(question), kind_family(kind)
        reg = region if scope == "region" else ""
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as c:
            existing = c.execute("SELECT id, status FROM answer_bank WHERE qkey=? AND family=? AND region=?", (qk, fam, reg)).fetchone()
            if existing and existing["status"] == "rejected" and status != "approved":
                return
            if existing and existing["status"] == "approved" and status != "approved":
                return
            if existing:
                c.execute("UPDATE answer_bank SET answer=?, options_json=?, source=?, status=?, updated_at=? WHERE id=?",
                          (str(answer), json.dumps(options[:60]), source, status, now, existing["id"]))
            else:
                c.execute("INSERT INTO answer_bank (qkey, question, family, scope, region, options_json, answer, status, source, created_at, updated_at) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (qk, question[:600], fam, scope, reg, json.dumps(options[:60]), str(answer), status, source, now, now))

    def demote(self, question: str, kind: str, region: str):
        qk, fam = question_key(question), kind_family(kind)
        with self._conn() as c:
            c.execute("UPDATE answer_bank SET status='failed', updated_at=? WHERE qkey=? AND family=? AND (region=? OR region='') AND status='pending'",
                      (datetime.now().isoformat(timespec="seconds"), qk, fam, region))

    def pending(self, limit: int = 200) -> List[Dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM answer_bank WHERE status='pending' ORDER BY uses DESC, created_at LIMIT ?", (limit,))]

    def all(self, status: str = None) -> List[Dict]:
        with self._conn() as c:
            if status:
                return [dict(r) for r in c.execute("SELECT * FROM answer_bank WHERE status=? ORDER BY question", (status,))]
            return [dict(r) for r in c.execute("SELECT * FROM answer_bank ORDER BY status, question")]

    def set_status(self, row_id: int, status: str, answer: str = None):
        now = datetime.now().isoformat(timespec="seconds")
        with self._conn() as c:
            if answer is not None:
                c.execute("UPDATE answer_bank SET status=?, answer=?, source='you', updated_at=? WHERE id=?", (status, answer, now, row_id))
            else:
                c.execute("UPDATE answer_bank SET status=?, updated_at=? WHERE id=?", (status, now, row_id))

    def counts(self) -> Dict[str, int]:
        with self._conn() as c:
            return {r[0]: r[1] for r in c.execute("SELECT status, COUNT(*) FROM answer_bank GROUP BY status")}
