import sqlite3
import os
import re
from collections import Counter

DB_PATH = os.path.join("data", "applications.db")

def add_description_column():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        return

    print(f"🔧 Adding description column to jobs table...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(jobs)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'description' in columns:
        print("✅ Description column already exists")
        conn.close()
        return

    cursor.execute('ALTER TABLE jobs ADD COLUMN description TEXT')
    cursor.execute("UPDATE jobs SET description = 'No Description Available' WHERE description IS NULL")

    conn.commit()
    conn.close()
    print("✅ Description column added successfully")


def extract_id_from_url(url):
    match = re.search(r"view/(\d+)", url)
    if match:
        return match.group(1)
    return None


def get_job_stage(cursor, job_id):
    cursor.execute("SELECT status FROM applications WHERE job_id = ?", (job_id,))
    app = cursor.fetchone()
    if app:
        return f"Applied: {app['status']}"

    cursor.execute("SELECT apply FROM evaluations WHERE job_id = ?", (job_id,))
    eval_row = cursor.fetchone()
    if eval_row:
        decision = "Qualified (Yes)" if eval_row['apply'] else "Disqualified (No)"
        return f"Evaluated: {decision}"

    return "Scanned Only"

def migrate_to_ids():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        return

    print(f"🔧 Connecting to {DB_PATH} for ID MIGRATION...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute('ALTER TABLE jobs ADD COLUMN linkedin_job_id TEXT')
        print("✅ Added 'linkedin_job_id' column.")
    except sqlite3.OperationalError:
        print("ℹ️  'linkedin_job_id' column already exists.")

    print("\n📊 ANALYZING DATABASE...")
    cursor.execute("SELECT * FROM jobs ORDER BY id DESC")  # Process newest first
    all_jobs = cursor.fetchall()

    seen_ids = {}

    to_update = []
    to_delete = []
    sample_transformations = []

    stage_counts = Counter()

    skipped_no_id = 0

    for job in all_jobs:
        linkedin_id = extract_id_from_url(job['url'])

        if not linkedin_id:
            skipped_no_id += 1
            continue

        if len(sample_transformations) < 5:
            sample_transformations.append({
                "url": job['url'],
                "extracted_id": linkedin_id
            })

        if linkedin_id in seen_ids:
            original_job = seen_ids[linkedin_id]
            to_delete.append((job, original_job))
        else:
            seen_ids[linkedin_id] = job
            to_update.append((linkedin_id, job['id']))

            stage = get_job_stage(cursor, job['id'])
            stage_counts[stage] += 1

    print("\n" + "=" * 60)
    print("                   MIGRATION PREVIEW")
    print("=" * 60)
    print(f"Total Jobs Scanned:     {len(all_jobs)}")
    print(f"Unique Jobs to Keep:    {len(to_update)}")
    print(f"Duplicates to DELETE:   {len(to_delete)}")
    print(f"Skipped (No ID found):  {skipped_no_id}")
    print("-" * 60)

    print("\n📈 PIPELINE STAGES (of the {0} Unique Jobs):".format(len(to_update)))
    for stage, count in sorted(stage_counts.items()):
        print(f"   • {stage}: {count}")

    print("\n🔍 EXAMPLES OF ID EXTRACTION (Verify this looks right):")
    for i, example in enumerate(sample_transformations):
        truncated_url = example['url'][:60] + "..." if len(example['url']) > 60 else example['url']
        print(f"   {i + 1}. URL: {truncated_url}")
        print(f"      🆔 -> {example['extracted_id']}")

    if to_delete:
        print(f"\n🗑️  Start of duplicates list ({len(to_delete)} total):")
        for i, (duplicate, keeper) in enumerate(to_delete[:3]):
            print(f"   ❌ Delete ID {duplicate['id']} (Duplicate of {keeper['id']})")

    print("\n" + "=" * 60)

    if not to_update and not to_delete:
        print("Nothing to do.")
        conn.close()
        return

    confirm = input("Type 'CONFIRM' to apply these changes (or anything else to cancel): ").strip()

    if confirm != "CONFIRM":
        print("❌ Cancelled. No changes made.")
        conn.close()
        return

    print("\n🚀 EXECUTING CHANGES...")

    if to_update:
        print(f"   Writing IDs to {len(to_update)} records...")
        cursor.executemany("UPDATE jobs SET linkedin_job_id = ? WHERE id = ?", to_update)

    if to_delete:
        print(f"   Deleting {len(to_delete)} duplicates...")
        for duplicate, _ in to_delete:
            job_id = duplicate['id']
            cursor.execute("DELETE FROM applications WHERE job_id = ?", (job_id,))
            cursor.execute("DELETE FROM evaluations WHERE job_id = ?", (job_id,))
            cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    conn.commit()

    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_linkedin_id ON jobs(linkedin_job_id)")
        print("✅ Created UNIQUE index on linkedin_job_id (Prevents future duplicates)")
    except Exception as e:
        print(f"⚠️ Could not create index: {e}")

    conn.close()
    print("\n✨ SUCCESS: Migration finished successfully.")

if __name__ == "__main__":
    print("=" * 50)
    print("DATABASE MIGRATION TOOL")
    print("=" * 50)
    print()
    print("[1] Add description column to jobs table")
    print("[2] Migrate to Job IDs (Deduplicate & Preview)")
    print()
    choice = input("Select migration (1 or 2): ").strip()

    if choice == "1":
        add_description_column()
    elif choice == "2":
        migrate_to_ids()
    else:
        print("Invalid choice")