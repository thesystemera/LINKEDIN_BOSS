import sqlite3
from datetime import date
from typing import List, Dict, Optional
from pathlib import Path

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS jobs
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           linkedin_job_id
                           TEXT
                           UNIQUE,
                           title
                           TEXT
                           NOT
                           NULL,
                           company
                           TEXT
                           NOT
                           NULL,
                           url
                           TEXT,
                           description
                           TEXT,
                           scraped_at
                           TIMESTAMP
                           DEFAULT
                           CURRENT_TIMESTAMP
                       )
                       ''')

        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS evaluations
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           job_id
                           INTEGER
                           NOT
                           NULL,
                           apply
                           BOOLEAN
                           NOT
                           NULL,
                           confidence
                           INTEGER
                           NOT
                           NULL,
                           reason
                           TEXT,
                           evaluated_at
                           TIMESTAMP
                           DEFAULT
                           CURRENT_TIMESTAMP,
                           FOREIGN
                           KEY
                       (
                           job_id
                       ) REFERENCES jobs
                       (
                           id
                       )
                           )
                       ''')

        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS applications
                       (
                           id
                           INTEGER
                           PRIMARY
                           KEY
                           AUTOINCREMENT,
                           job_id
                           INTEGER
                           NOT
                           NULL,
                           status
                           TEXT
                           NOT
                           NULL,
                           error_message
                           TEXT,
                           steps_completed
                           INTEGER,
                           applied_at
                           TIMESTAMP
                           DEFAULT
                           CURRENT_TIMESTAMP,
                           FOREIGN
                           KEY
                       (
                           job_id
                       ) REFERENCES jobs
                       (
                           id
                       )
                           )
                       ''')

        cursor.execute('''
                       CREATE TABLE IF NOT EXISTS daily_stats
                       (
                           date
                           DATE
                           PRIMARY
                           KEY,
                           applications
                           INTEGER
                           DEFAULT
                           0
                       )
                       ''')

        conn.commit()
        conn.close()

    def insert_job(self, job: Dict) -> int:
        from migrate_db import norm_title
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                           INSERT INTO jobs (linkedin_job_id, title, company, url, description, location, workplace, salary_text,
                                             apply_type, lane, search_keyword, search_location, norm_title)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ''', (job.get('linkedin_job_id'), job['title'], job['company'], job['url'], job.get('description', 'No Description Available'),
                                 job.get('location'), job.get('workplace'), job.get('salary_text'), job.get('apply_type'), job.get('lane'),
                                 job.get('search_keyword'), job.get('search_location'), norm_title(job['title'])))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            cursor.execute('SELECT id FROM jobs WHERE linkedin_job_id = ?', (job.get('linkedin_job_id'),))
            result = cursor.fetchone()
            return result[0] if result else -1
        except Exception as e:
            print(f"DB Error: {e}")
            return -1
        finally:
            conn.close()

    def update_job_details(self, job_id: int, details: Dict):
        cols = {"description": "description", "salary_text": "salary_text", "workplace": "workplace", "employment_type": "employment_type",
                "apply_type": "apply_type", "external_url": "external_url", "ats": "ats", "location": "location", "lane": "lane"}
        sets, vals = [], []
        for k, c in cols.items():
            v = details.get(k)
            if v:
                sets.append(f"{c} = ?")
                vals.append(v)
        if not sets:
            return
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", (*vals, job_id))
            conn.commit()
        finally:
            conn.close()

    def update_job_description(self, job_id: int, description: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute('''
                           UPDATE jobs
                           SET description = ?
                           WHERE id = ?
                           ''', (description, job_id))
            conn.commit()
        except Exception as e:
            print(f"DB Error updating description: {e}")
        finally:
            conn.close()

    def is_job_already_processed(self, job_id: int) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT id FROM evaluations WHERE job_id = ?', (job_id,))
        has_eval = cursor.fetchone() is not None

        conn.close()
        return has_eval

    def insert_evaluation(self, job_id: int, evaluation: Dict):
        import json
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute('''
                         INSERT INTO evaluations (job_id, apply, confidence, reason, lane, eligible, blockers, pay_nzd, pay_basis, employment_type, location)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                         ''', (job_id, bool(evaluation.get('apply')), int(evaluation.get('confidence') or 0), evaluation.get('reason', ''),
                               evaluation.get('lane'), int(bool(evaluation.get('eligible', True))), json.dumps(evaluation.get('blockers') or []),
                               evaluation.get('pay_nzd'), evaluation.get('pay_basis'), evaluation.get('employment_type'), evaluation.get('location')))
            if evaluation.get('lane'):
                conn.execute("UPDATE jobs SET lane = ? WHERE id = ?", (evaluation['lane'], job_id))
            conn.commit()
        finally:
            conn.close()

    def insert_application(self, job_id: int, result: Dict):
        import json
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute('''
                         INSERT INTO applications (job_id, status, error_message, steps_completed, channel, external_url, answers_json)
                         VALUES (?, ?, ?, ?, ?, ?, ?)
                         ''', (job_id, result['status'], result.get('error'), result.get('steps', 0), result.get('channel'),
                               result.get('external_url'), json.dumps(result.get('qa') or [], ensure_ascii=False)[:60000]))
            if result.get('external_url'):
                conn.execute("UPDATE jobs SET external_url = COALESCE(external_url, ?), ats = COALESCE(ats, ?) WHERE id = ?",
                             (result['external_url'], result.get('channel'), job_id))
            if result['status'] in ('success', 'submitted_unconfirmed'):
                conn.execute('''
                             INSERT INTO daily_stats (date, applications)
                             VALUES (?, 1) ON CONFLICT(date) DO
                             UPDATE SET applications = applications + 1
                             ''', (date.today().isoformat(),))
            conn.commit()
        finally:
            conn.close()

    def recent_duplicate(self, company: str, title: str, days: int, exclude_job_id: int = None) -> bool:
        from migrate_db import norm_title
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute('''
                               SELECT 1 FROM applications a JOIN jobs j ON j.id = a.job_id
                               WHERE a.status IN ('success', 'submitted_unconfirmed') AND lower(j.company) = lower(?) AND j.norm_title = ?
                                 AND a.applied_at >= datetime('now', ?) AND j.id != ?
                               LIMIT 1
                               ''', (company, norm_title(title), f'-{int(days)} days', exclude_job_id or -1)).fetchone()
            return row is not None
        finally:
            conn.close()

    def log_search(self, keyword: str, location: str, results: int):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("INSERT INTO search_log (keyword, location, last_run, results) VALUES (?, ?, datetime('now'), ?) "
                         "ON CONFLICT(keyword, location) DO UPDATE SET last_run = datetime('now'), results = excluded.results",
                         (keyword, location, results))
            conn.commit()
        finally:
            conn.close()

    def search_last_runs(self) -> Dict:
        conn = sqlite3.connect(self.db_path)
        try:
            return {(k, l): t or "" for k, l, t in conn.execute("SELECT keyword, location, last_run FROM search_log")}
        except sqlite3.OperationalError:
            return {}
        finally:
            conn.close()

    def _job_from_row(self, row) -> Dict:
        keys = row.keys()
        job = {k: row[k] for k in keys if k not in ('confidence', 'reason', 'apply', 'pay_nzd', 'pay_basis', 'eval_lane')}
        if 'eval_lane' in keys and row['eval_lane']:
            job['lane'] = row['eval_lane']
        if 'confidence' in keys and row['confidence'] is not None:
            job['evaluation'] = {'confidence': row['confidence'], 'reason': row['reason'], 'apply': row['apply'],
                                 'pay_nzd': row['pay_nzd'] if 'pay_nzd' in keys else None,
                                 'pay_basis': row['pay_basis'] if 'pay_basis' in keys else None}
        return job

    def get_daily_count(self, target_date: Optional[date] = None) -> int:
        if target_date is None:
            target_date = date.today()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
                       SELECT applications
                       FROM daily_stats
                       WHERE date = ?
                       ''', (target_date.isoformat(),))

        result = cursor.fetchone()
        conn.close()

        return result[0] if result else 0

    # ── AI result cache (table created by migrate_db.apply_v2) ──
    def ai_cache_get(self, key: str, retention_days: int) -> Optional[str]:
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("SELECT result_json FROM ai_cache WHERE key = ? AND last_used_at >= datetime('now', ?)",
                               (key, f"-{int(retention_days)} days")).fetchone()
            if row:
                conn.execute("UPDATE ai_cache SET hits = hits + 1, last_used_at = CURRENT_TIMESTAMP WHERE key = ?", (key,))
                conn.commit()
            return row[0] if row else None
        finally:
            conn.close()

    def ai_cache_put(self, key: str, role: str, model: str, result_json: str, usage: Dict, retention_days: int, max_entries: int):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""INSERT OR REPLACE INTO ai_cache (key, role, model, result_json, prompt_tokens, cached_tokens, thinking_tokens, output_tokens)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                         (key, role, model, result_json, usage.get("prompt", 0), usage.get("cached", 0), usage.get("thinking", 0), usage.get("output", 0)))
            conn.execute("DELETE FROM ai_cache WHERE last_used_at < datetime('now', ?)", (f"-{int(retention_days)} days",))
            conn.execute("DELETE FROM ai_cache WHERE key NOT IN (SELECT key FROM ai_cache ORDER BY last_used_at DESC LIMIT ?)", (int(max_entries),))
            conn.commit()
        finally:
            conn.close()

    def ai_cache_stats(self) -> Dict:
        conn = sqlite3.connect(self.db_path)
        try:
            n, hits, saved_in, saved_out = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(hits), 0), COALESCE(SUM(hits * prompt_tokens), 0), COALESCE(SUM(hits * (thinking_tokens + output_tokens)), 0) FROM ai_cache").fetchone()
            return {"entries": n, "hits": hits, "input_tokens_saved": saved_in, "output_tokens_saved": saved_out}
        except sqlite3.OperationalError:
            return {"entries": 0, "hits": 0, "input_tokens_saved": 0, "output_tokens_saved": 0}
        finally:
            conn.close()

    def get_stats(self) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}

        cursor.execute('SELECT COUNT(*) FROM jobs')
        stats['total_jobs'] = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM evaluations')
        stats['total_evaluated'] = cursor.fetchone()[0]

        cursor.execute('''
                       SELECT status, COUNT(*)
                       FROM applications
                       GROUP BY status
                       ''')
        stats['applications_by_status'] = dict(cursor.fetchall())

        stats['applications_today'] = self.get_daily_count()

        total_apps = sum(stats['applications_by_status'].values())
        successes = stats['applications_by_status'].get('success', 0) + stats['applications_by_status'].get('submitted_unconfirmed', 0)
        stats['success_rate'] = (successes / total_apps * 100) if total_apps > 0 else 0

        conn.close()
        return stats

    def get_jobs_for_manual_review(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
                       SELECT j.title, j.company, j.url, a.error_message, a.applied_at
                       FROM applications a
                                JOIN jobs j ON a.job_id = j.id
                       WHERE a.status = 'manual_review_needed'
                       ORDER BY a.applied_at DESC
                       ''')

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_unevaluated_jobs(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
                       SELECT j.id, j.linkedin_job_id, j.title, j.company, j.url, j.location, j.workplace, j.salary_text,
                              j.apply_type, j.lane, j.search_keyword, j.search_location
                       FROM jobs j
                                LEFT JOIN evaluations e ON j.id = e.job_id
                       WHERE e.id IS NULL
                       ORDER BY j.scraped_at DESC
                       ''')

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_unapplied_good_jobs(self, sort_by_pay: bool = True, include_external: bool = True, max_age_days: int = 21) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            ext = "" if include_external else "AND COALESCE(j.apply_type, 'easy') IN ('easy', 'unknown')"
            ext += f" AND j.scraped_at >= datetime('now', '-{int(max_age_days)} days')"
            order = "COALESCE(e.pay_nzd, 0) DESC, e.confidence DESC" if sort_by_pay else "e.confidence DESC, COALESCE(e.pay_nzd, 0) DESC"
            rows = conn.execute(f'''
                                SELECT j.id, j.linkedin_job_id, j.title, j.company, j.url, j.description, j.location, j.workplace,
                                       j.employment_type, j.salary_text, j.apply_type, j.external_url, j.ats, j.lane,
                                       e.lane AS eval_lane, e.confidence, e.reason, e.apply, e.pay_nzd, e.pay_basis
                                FROM jobs j
                                         JOIN evaluations e ON j.id = e.job_id
                                         LEFT JOIN applications a ON j.id = a.job_id
                                WHERE e.apply = 1
                                  AND a.id IS NULL
                                  AND COALESCE(j.apply_type, '') NOT IN ('closed', 'applied')
                                  {ext}
                                GROUP BY j.id
                                ORDER BY {order}
                                ''').fetchall()
            return [self._job_from_row(r) for r in rows]
        finally:
            conn.close()

    def get_jobs_for_retry(self, max_age_days: int = None, statuses=("manual_review_needed", "error")) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            q = f'''
                SELECT j.id, j.linkedin_job_id, j.title, j.company, j.url, j.description, j.location, j.workplace,
                       j.employment_type, j.salary_text, j.apply_type, j.external_url, j.ats, j.lane,
                       e.lane AS eval_lane, e.confidence, e.reason, e.apply, e.pay_nzd, e.pay_basis, MAX(a.applied_at) AS last_try
                FROM jobs j
                         JOIN evaluations e ON j.id = e.job_id
                         JOIN applications a ON j.id = a.job_id
                WHERE a.status IN ({",".join("?" * len(statuses))})
                  AND j.id NOT IN (SELECT job_id FROM applications WHERE status IN ('success', 'submitted_unconfirmed', 'expired', 'already_applied'))
            '''
            params = list(statuses)
            if max_age_days is not None:
                q += " AND j.scraped_at >= datetime('now', ?)"
                params.append(f'-{max_age_days} days')
            q += " GROUP BY j.id ORDER BY COALESCE(e.pay_nzd, 0) DESC, last_try DESC"
            return [self._job_from_row(r) for r in conn.execute(q, params).fetchall()]
        finally:
            conn.close()

    def get_external_queue(self) -> List[Dict]:
        return [j for j in self.get_jobs_for_retry(None, ("manual_review_needed", "external")) if j.get("external_url") or j.get("apply_type") == "external"]

    def channel_stats(self) -> List[tuple]:
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute('''
                                SELECT COALESCE(channel, 'linkedin_easy (v1)'), status, COUNT(*) FROM applications
                                GROUP BY 1, 2 ORDER BY 1, 3 DESC
                                ''').fetchall()
        finally:
            conn.close()

    def get_job_by_linkedin_id(self, linkedin_job_id: str) -> Optional[Dict]:
        """Look up a job by its LinkedIn job number (e.g. '4346719111')."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
                       SELECT j.id,
                              j.linkedin_job_id,
                              j.title,
                              j.company,
                              j.url,
                              j.description,
                              e.confidence,
                              e.reason,
                              e.apply
                       FROM jobs j
                                LEFT JOIN evaluations e ON j.id = e.job_id
                       WHERE j.linkedin_job_id = ?
                       ''', (linkedin_job_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        job = {
            'id': row['id'],
            'linkedin_job_id': row['linkedin_job_id'],
            'title': row['title'],
            'company': row['company'],
            'url': row['url'],
            'description': row['description'],
        }
        if row['confidence'] is not None:
            job['evaluation'] = {
                'confidence': row['confidence'],
                'reason': row['reason'],
                'apply': row['apply']
            }
        return job

    def search_jobs(self, keyword: str) -> List[Dict]:
        """Search jobs by keyword across title, company, and description."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        search_term = f"%{keyword}%"

        cursor.execute('''
                       SELECT j.id,
                              j.title,
                              j.company,
                              j.url,
                              j.description,
                              j.scraped_at,
                              e.confidence,
                              e.reason,
                              e.apply,
                              e.evaluated_at,
                              a.status AS app_status,
                              a.error_message,
                              a.applied_at
                       FROM jobs j
                                LEFT JOIN evaluations e ON j.id = e.job_id
                                LEFT JOIN applications a ON j.id = a.job_id
                       WHERE j.title LIKE ?
                          OR j.company LIKE ?
                          OR j.description LIKE ?
                       ORDER BY j.scraped_at DESC
                       ''', (search_term, search_term, search_term))

        results = []
        for row in cursor.fetchall():
            job = {
                'id': row['id'],
                'title': row['title'],
                'company': row['company'],
                'url': row['url'],
                'description': row['description'],
                'scraped_at': row['scraped_at'],
                'evaluation': {
                    'confidence': row['confidence'],
                    'reason': row['reason'],
                    'apply': row['apply'],
                    'evaluated_at': row['evaluated_at']
                } if row['confidence'] is not None else None,
                'application': {
                    'status': row['app_status'],
                    'error_message': row['error_message'],
                    'applied_at': row['applied_at']
                } if row['app_status'] is not None else None
            }
            results.append(job)

        conn.close()
        return results