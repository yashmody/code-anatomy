"""Migration script to transfer data from SQLite/JSON to PostgreSQL.

Ingests (v2 paths, post ARCH-2):
  1. data/question_bank.json -> questions table
  2. q0.db (SQLite) -> users and attempts tables
  3. ../content/source/feed/feed.json -> feed_items table
  4. ../media/Anatomy of Code.mp4 -> pg_largeobject + media_assets

NOTE (ARCH-3): Course content (course_chapters, frameworks) is no longer
seeded by this ETL. The course is now served from files via COURSE_SOURCE=files
(ARCH-2). The DB tables remain intact until ARCH-4's drop-tables migration.
"""
import os
import sys
import json
import uuid
import datetime
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

# Setup path to import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core import config
from app.core.db import init_db, get_session
from app.core.models import Question, User, Attempt, FeedItem, MediaAsset

# Constants
BASE_DIR = config.BASE_DIR
QUESTION_BANK_PATH = config.QUESTION_BANK
SQLITE_DB_PATH = BASE_DIR / "q0.db"
CONTENT_SOURCE = BASE_DIR.parent / "content" / "source"
FEED_JSON_PATH = CONTENT_SOURCE / "feed" / "feed.json"
VIDEO_PATH = BASE_DIR.parent / "media" / "Anatomy of Code.mp4"


def migrate_questions(pg_session: Session):
    print("[ETL] Migrating questions...")
    if not QUESTION_BANK_PATH.exists():
        print(f"[Warn] Question bank not found at {QUESTION_BANK_PATH}")
        return

    with open(QUESTION_BANK_PATH, "r") as f:
        data = json.load(f)

    questions_data = data if isinstance(data, list) else data.get("questions", [])
    count = 0
    for q in questions_data:
        # Check if question exists (by ID)
        existing = pg_session.get(Question, q["id"])
        if existing:
            continue
        
        # Insert question
        new_q = Question(
            id=q["id"],
            topic=q["topic"],
            difficulty=q.get("difficulty", "medium"),
            question=q["question"],
            options=q["options"],
            correct_index=q["correct"],
            explanation=q.get("explanation", ""),
            status="published",
            version=1,
            is_user_submitted=False
        )
        pg_session.add(new_q)
        count += 1

    pg_session.commit()
    print(f"[ETL] Ingested {count} new questions.")

def migrate_sqlite_data(pg_session: Session):
    print("[ETL] Migrating users and attempts from SQLite...")
    if not SQLITE_DB_PATH.exists():
        print(f"[Warn] SQLite database not found at {SQLITE_DB_PATH}")
        return

    # Connect to SQLite
    sqlite_engine = create_engine(f"sqlite:///{SQLITE_DB_PATH}")
    
    # Migrate Users
    users_count = 0
    with sqlite_engine.connect() as conn:
        users = conn.execute(text("SELECT email, name, picture, role, provider, created_at, updated_at FROM users")).fetchall()
        for u in users:
            # Check if user already in PostgreSQL
            existing = pg_session.get(User, u[0])
            if existing:
                continue
            new_u = User(
                email=u[0],
                name=u[1],
                picture=u[2],
                role=u[3],
                provider=u[4],
                preferences={},
                created_at=u[5] if isinstance(u[5], datetime.datetime) else datetime.datetime.fromisoformat(u[5]) if u[5] else datetime.datetime.utcnow(),
                updated_at=u[6] if isinstance(u[6], datetime.datetime) else datetime.datetime.fromisoformat(u[6]) if u[6] else datetime.datetime.utcnow()
            )
            pg_session.add(new_u)
            users_count += 1
    pg_session.commit()
    print(f"[ETL] Migrated {users_count} users.")

    # Migrate Attempts
    attempts_count = 0
    with sqlite_engine.connect() as conn:
        attempts = conn.execute(text("SELECT id, test_code, cert_id, quiz_id, user_email, difficulty, score, correct, total, passed, started_at, submitted_at, certificate_path, signature, payload FROM attempts")).fetchall()
        for a in attempts:
            existing = pg_session.scalar(select(Attempt).where(Attempt.test_code == a[1]))
            if existing:
                continue
            
            # JSON parsing payload if string
            payload_data = a[14]
            if isinstance(payload_data, str):
                try:
                    payload_data = json.loads(payload_data)
                except Exception:
                    payload_data = {}

            new_a = Attempt(
                test_code=a[1],
                cert_id=a[2],
                quiz_id=a[3],
                user_email=a[4],
                difficulty=a[5],
                score=float(a[6]),
                correct=int(a[7]),
                total=int(a[8]),
                passed=bool(a[9]),
                started_at=a[10] if isinstance(a[10], datetime.datetime) else datetime.datetime.fromisoformat(a[10]) if a[10] else datetime.datetime.utcnow(),
                submitted_at=a[11] if isinstance(a[11], datetime.datetime) else datetime.datetime.fromisoformat(a[11]) if a[11] else datetime.datetime.utcnow(),
                certificate_path=a[12],
                signature=a[13],
                payload=payload_data,
                metadata={}
            )
            pg_session.add(new_a)
            attempts_count += 1
    pg_session.commit()
    print(f"[ETL] Migrated {attempts_count} attempts.")

def migrate_feed(pg_session: Session):
    print("[ETL] Migrating feed items...")
    if not FEED_JSON_PATH.exists():
        print(f"[Warn] Feed JSON not found at {FEED_JSON_PATH}")
        return

    with open(FEED_JSON_PATH, "r") as f:
        data = json.load(f)

    feed_items = data if isinstance(data, list) else data.get("feed", [])
    count = 0
    for item in feed_items:
        existing = pg_session.get(FeedItem, item["id"])
        if existing:
            continue
        
        # Extract fields
        author = item.get("author", {})
        author_email = author.get("userId")  # best display email map
        if author_email and "@" not in author_email:
            author_email = f"{author_email}@deptagency.com" # fallback to allowed domain
            
        # Ensure author exists in DB
        if author_email and not pg_session.get(User, author_email.lower()):
            new_u = User(
                email=author_email.lower(),
                name=author.get("name") or author.get("userId"),
                picture="",
                role="FeedCreator",
                provider="dev"
            )
            pg_session.add(new_u)
            pg_session.commit()

        # Insert feed item
        created_at_val = item.get("createdAt", datetime.datetime.utcnow().isoformat())
        if isinstance(created_at_val, str):
            created_at_val = datetime.datetime.fromisoformat(created_at_val.replace("Z", ""))

        new_item = FeedItem(
            id=item["id"],
            type=item["type"],
            status=item.get("status", "published"),
            author_id=author_email.lower() if author_email else None,
            framework_ref=item.get("frameworkRef"),
            topics=item.get("topics", []),
            created_at=created_at_val,
            data=item
        )
        pg_session.add(new_item)
        count += 1
        
    pg_session.commit()
    print(f"[ETL] Ingested {count} feed items.")

def migrate_media(pg_session: Session):
    print("[ETL] Migrating media file to Large Objects...")
    if "postgresql" not in config.DATABASE_URL:
        print("[ETL] SQLite is being used locally. Skipping pg_largeobject migration.")
        return
        
    if not VIDEO_PATH.exists():
        print(f"[Warn] Video file not found at {VIDEO_PATH}")
        return
        
    # Check if video already exists in media_assets
    existing = pg_session.scalar(select(MediaAsset).where(MediaAsset.filename == VIDEO_PATH.name))
    if existing:
        print(f"[ETL] Video {VIDEO_PATH.name} already ingested with OID {existing.large_object_oid}")
        return

    # Ingest using raw connection and pg large objects interface
    engine = pg_session.bind
    raw_conn = engine.raw_connection()
    try:
        # Create a new large object
        lobj = raw_conn.lobject(0, 'w')
        oid = lobj.oid
        
        # Read and write chunks
        print(f"[ETL] Ingesting {VIDEO_PATH.name} into Large Object OID {oid}...")
        size = VIDEO_PATH.stat().st_size
        with open(VIDEO_PATH, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024) # 1MB chunks
                if not chunk:
                    break
                lobj.write(chunk)
        
        lobj.close()
        raw_conn.commit()
        
        # Save metadata to media_assets
        media_id = str(uuid.uuid4())
        asset = MediaAsset(
            id=media_id,
            large_object_oid=oid,
            filename=VIDEO_PATH.name,
            mime_type="video/mp4",
            size_bytes=size,
            uploaded_by=None
        )
        pg_session.add(asset)
        pg_session.commit()
        print(f"[ETL] Media ingestion complete. ID: {media_id}, OID: {oid}")
        
    except Exception as e:
        raw_conn.rollback()
        print(f"[Error] Failed to ingest large object media: {e}")
    finally:
        raw_conn.close()

def main():
    # Verify we can connect to the target database and initialize schema
    print(f"[ETL] Connecting to database: {config.DATABASE_URL}")
    try:
        init_db()
    except Exception as e:
        print(f"[Error] Failed to initialize database: {e}")
        print("Please ensure PostgreSQL is running and DATABASE_URL is correctly configured in your environment.")
        sys.exit(1)
        
    with get_session() as pg_session:
        migrate_questions(pg_session)
        migrate_sqlite_data(pg_session)
        migrate_feed(pg_session)
        migrate_media(pg_session)

    print("[ETL] Migration completed successfully.")

if __name__ == "__main__":
    main()

