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
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            description = job.get('description', 'No Description Available')
            cursor.execute('''
                           INSERT INTO jobs (linkedin_job_id, title, company, url, description)
                           VALUES (?, ?, ?, ?, ?)
                           ''', (job.get('linkedin_job_id'), job['title'], job['company'], job['url'], description))
            job_id = cursor.lastrowid
            conn.commit()
            return job_id
        except sqlite3.IntegrityError:
            cursor.execute('SELECT id FROM jobs WHERE linkedin_job_id = ?', (job.get('linkedin_job_id'),))
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else -1
        except Exception as e:
            print(f"DB Error: {e}")
            conn.close()
            return -1
        finally:
            if conn:
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
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
                       INSERT INTO evaluations (job_id, apply, confidence, reason)
                       VALUES (?, ?, ?, ?)
                       ''', (job_id, evaluation['apply'], evaluation['confidence'], evaluation['reason']))

        conn.commit()
        conn.close()

    def insert_application(self, job_id: int, result: Dict):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
                       INSERT INTO applications (job_id, status, error_message, steps_completed)
                       VALUES (?, ?, ?, ?)
                       ''', (job_id, result['status'], result.get('error'), result.get('steps', 0)))

        today = date.today().isoformat()
        if result['status'] == 'success':
            cursor.execute('''
                           INSERT INTO daily_stats (date, applications)
                           VALUES (?, 1) ON CONFLICT(date) DO
                           UPDATE SET applications = applications + 1
                           ''', (today,))

        conn.commit()
        conn.close()

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
        successes = stats['applications_by_status'].get('success', 0)
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
                       SELECT j.id, j.title, j.company, j.url
                       FROM jobs j
                                LEFT JOIN evaluations e ON j.id = e.job_id
                       WHERE e.id IS NULL
                       ORDER BY j.scraped_at DESC
                       ''')

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

    def get_unapplied_good_jobs(self) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
                       SELECT j.id,
                              j.title,
                              j.company,
                              j.url,
                              j.description,
                              e.confidence,
                              e.reason,
                              e.apply
                       FROM jobs j
                                JOIN evaluations e ON j.id = e.job_id
                                LEFT JOIN applications a ON j.id = a.job_id
                       WHERE e.apply = 1
                         AND a.id IS NULL
                       ORDER BY e.confidence DESC
                       ''')

        results = []
        for row in cursor.fetchall():
            job = {
                'id': row['id'],
                'title': row['title'],
                'company': row['company'],
                'url': row['url'],
                'description': row['description'],
                'evaluation': {
                    'confidence': row['confidence'],
                    'reason': row['reason'],
                    'apply': row['apply']
                }
            }
            results.append(job)

        conn.close()
        return results

    def get_jobs_for_retry(self, max_age_days: int = None) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = '''
                       SELECT DISTINCT j.id,
                                       j.title,
                                       j.company,
                                       j.url,
                                       j.description,
                                       e.confidence,
                                       e.reason,
                                       e.apply
                       FROM jobs j
                                JOIN evaluations e ON j.id = e.job_id
                                JOIN applications a ON j.id = a.job_id
                       WHERE a.status = 'manual_review_needed'
                         AND j.id NOT IN (SELECT job_id FROM applications WHERE status IN ('success', 'expired'))
                '''

        params = ()
        if max_age_days is not None:
            query += '''
                         AND j.scraped_at >= datetime('now', ?)
                    '''
            params = (f'-{max_age_days} days',)

        query += '''
                       ORDER BY a.applied_at DESC
                '''

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            job = {
                'id': row['id'],
                'title': row['title'],
                'company': row['company'],
                'url': row['url'],
                'description': row['description'],
                'evaluation': {
                    'confidence': row['confidence'],
                    'reason': row['reason'],
                    'apply': row['apply']
                }
            }
            results.append(job)

        conn.close()
        return results

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