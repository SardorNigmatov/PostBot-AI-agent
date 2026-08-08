import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence

from config import DB_PATH


logger = logging.getLogger(__name__)

DB_FILE = Path(DB_PATH)
DB_FILE.parent.mkdir(parents=True, exist_ok=True)

STATUS_PENDING = "pending"
STATUS_PUBLISHING = "publishing"
STATUS_REJECTED = "rejected"
STATUS_POSTED = "posted"

VALID_POST_STATUSES = frozenset(
    {
        STATUS_PENDING,
        STATUS_PUBLISHING,
        STATUS_REJECTED,
        STATUS_POSTED,
    }
)


class DatabaseError(RuntimeError):
    """Loyiha bazasi bilan ishlashdagi boshqariladigan xato."""


class PostNotFoundError(DatabaseError):
    """So‘ralgan post bazada topilmaganda chiqariladi."""


class InvalidPostStateError(DatabaseError):
    """Post holati so‘ralgan amalni bajarishga ruxsat bermaganda chiqariladi."""


def _utc_now_iso() -> str:
    """Timezone-aware UTC vaqtni ISO-8601 ko‘rinishida qaytaradi."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    """
    Har bir amal uchun alohida SQLite ulanishi yaratadi.

    timeout va busy_timeout parallel callback/scheduler yozuvlarida
    vaqtinchalik "database is locked" xatolarini kamaytiradi.

    Eslatma: journal_mode ataylab WAL emas (standart DELETE/rollback rejimi
    qoldirilgan). PythonAnywhere kabi NFS-asosli fayl tizimlarida WAL rejimi
    ishlamaydi va bazani buzishi (corruption) mumkin, chunki WAL uchun kerak
    bo‘lgan shared-memory locking mexanizmi NFS ustida qo‘llab-quvvatlanmaydi.
    Ushbu botning yozish hajmi past bo‘lgani uchun DELETE rejimi + busy_timeout
    yetarli darajada ishonchli.
    """
    conn = sqlite3.connect(
        str(DB_FILE),
        timeout=30.0,
        isolation_level=None,  # Transactionlarni o‘zimiz boshqaramiz.
    )
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")

    return conn


@contextmanager
def get_conn(*, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    """
    SQLite ulanishi va transaction context manager.

    immediate=True yozish transactionini darhol band qiladi. Bu round-robin
    navbat, postni publish qilish uchun claim qilish kabi read-modify-write
    amallarida race conditionni oldini oladi.
    """
    conn = _connect()

    try:
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            logger.exception("SQLite transaction rollback bajarilmadi.")
        raise
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_posts_schema(conn: sqlite3.Connection) -> None:
    """
    Eski posts.db faylidan foydalanilganda yetishmayotgan ustunlarni qo‘shadi.

    SQLite mavjud ustunga CHECK constraint qo‘sha olmaydi, shuning uchun status
    qiymatlari Python funksiyalarida tekshiriladi.
    """
    columns = _table_columns(conn, "posts")

    migrations: tuple[tuple[str, str], ...] = (
        ("channel_message_id", "INTEGER"),
        ("posted_at", "TEXT"),
        ("views", "INTEGER NOT NULL DEFAULT 0"),
        ("reactions_json", "TEXT NOT NULL DEFAULT '{}'"),
    )

    for column_name, definition in migrations:
        if column_name not in columns:
            conn.execute(
                f"ALTER TABLE posts ADD COLUMN {column_name} {definition}"
            )


def init_db() -> None:
    """Bazani, singleton sozlamalarni va indekslarni yaratadi."""
    with get_conn(immediate=True) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_type TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                channel_message_id INTEGER,
                created_at TEXT NOT NULL,
                posted_at TEXT,
                views INTEGER NOT NULL DEFAULT 0,
                reactions_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS topic_rotation (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_index INTEGER NOT NULL DEFAULT -1
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS used_news (
                url TEXT PRIMARY KEY,
                used_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                auto_post_mode INTEGER NOT NULL DEFAULT 0
                    CHECK (auto_post_mode IN (0, 1))
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_schedule (
                day TEXT PRIMARY KEY,
                run_at TEXT NOT NULL,
                executed INTEGER NOT NULL DEFAULT 0
                    CHECK (executed IN (0, 1))
            )
            """
        )

        _ensure_posts_schema(conn)

        conn.execute(
            """
            INSERT OR IGNORE INTO topic_rotation (id, last_index)
            VALUES (1, -1)
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO bot_settings (id, auto_post_mode)
            VALUES (1, 0)
            """
        )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_channel_message_id
            ON posts(channel_message_id)
            WHERE channel_message_id IS NOT NULL
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_posts_status_posted_at
            ON posts(status, posted_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_posts_created_at
            ON posts(created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_used_news_used_at
            ON used_news(used_at DESC)
            """
        )


# ---------------------------------------------------------------------------
# Bot sozlamalari
# ---------------------------------------------------------------------------

def get_auto_post_mode() -> bool:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT auto_post_mode
            FROM bot_settings
            WHERE id = 1
            """
        ).fetchone()

    return bool(row["auto_post_mode"]) if row is not None else False


def set_auto_post_mode(enabled: bool) -> None:
    value = 1 if bool(enabled) else 0

    with get_conn(immediate=True) as conn:
        cursor = conn.execute(
            """
            UPDATE bot_settings
            SET auto_post_mode = ?
            WHERE id = 1
            """,
            (value,),
        )

        if cursor.rowcount == 0:
            conn.execute(
                """
                INSERT INTO bot_settings (id, auto_post_mode)
                VALUES (1, ?)
                """,
                (value,),
            )


# ---------------------------------------------------------------------------
# Mavzu rotatsiyasi
# ---------------------------------------------------------------------------

def next_topic_type(topic_types: Sequence[str]) -> str:
    """
    Mavzularni atomik round-robin tartibida aylantiradi.

    Bir vaqtda scheduler va qo‘lda generatsiya ishlasa ham ikki chaqiruv bir xil
    indeksni o‘qib qolmaydi.
    """
    normalized_topics = tuple(
        str(topic).strip()
        for topic in topic_types
        if str(topic).strip()
    )

    if not normalized_topics:
        raise ValueError("topic_types kamida bitta mavzuni o‘z ichiga olishi kerak.")

    with get_conn(immediate=True) as conn:
        row = conn.execute(
            """
            SELECT last_index
            FROM topic_rotation
            WHERE id = 1
            """
        ).fetchone()

        last_index = int(row["last_index"]) if row is not None else -1
        next_index = (last_index + 1) % len(normalized_topics)

        if row is None:
            conn.execute(
                """
                INSERT INTO topic_rotation (id, last_index)
                VALUES (1, ?)
                """,
                (next_index,),
            )
        else:
            conn.execute(
                """
                UPDATE topic_rotation
                SET last_index = ?
                WHERE id = 1
                """,
                (next_index,),
            )

    return normalized_topics[next_index]


# ---------------------------------------------------------------------------
# Post CRUD va holat boshqaruvi
# ---------------------------------------------------------------------------

def create_post(topic_type: str, content: str) -> int:
    normalized_topic = str(topic_type).strip()
    normalized_content = str(content).strip()

    if not normalized_topic:
        raise ValueError("topic_type bo‘sh bo‘lishi mumkin emas.")

    if not normalized_content:
        raise ValueError("content bo‘sh bo‘lishi mumkin emas.")

    with get_conn(immediate=True) as conn:
        cursor = conn.execute(
            """
            INSERT INTO posts (
                topic_type,
                content,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                normalized_topic,
                normalized_content,
                STATUS_PENDING,
                _utc_now_iso(),
            ),
        )

        post_id = cursor.lastrowid

    if post_id is None:
        raise DatabaseError("Yangi post ID sini olishning imkoni bo‘lmadi.")

    return int(post_id)


def get_post(post_id: int) -> sqlite3.Row | None:
    if int(post_id) <= 0:
        return None

    with get_conn() as conn:
        return conn.execute(
            """
            SELECT *
            FROM posts
            WHERE id = ?
            """,
            (int(post_id),),
        ).fetchone()


def get_post_by_channel_message_id(
    channel_message_id: int,
) -> sqlite3.Row | None:
    if int(channel_message_id) <= 0:
        return None

    with get_conn() as conn:
        return conn.execute(
            """
            SELECT *
            FROM posts
            WHERE channel_message_id = ?
            """,
            (int(channel_message_id),),
        ).fetchone()


def update_content(post_id: int, new_content: str) -> None:
    normalized_content = str(new_content).strip()

    if not normalized_content:
        raise ValueError("Yangi post matni bo‘sh bo‘lishi mumkin emas.")

    with get_conn(immediate=True) as conn:
        cursor = conn.execute(
            """
            UPDATE posts
            SET content = ?
            WHERE id = ?
              AND status != ?
              AND channel_message_id IS NULL
            """,
            (
                normalized_content,
                int(post_id),
                STATUS_POSTED,
            ),
        )

        if cursor.rowcount == 1:
            return

        row = conn.execute(
            """
            SELECT status, channel_message_id
            FROM posts
            WHERE id = ?
            """,
            (int(post_id),),
        ).fetchone()

        if row is None:
            raise PostNotFoundError(f"Post topilmadi: id={post_id}")

        raise InvalidPostStateError(
            "Kanalga joylangan post matnini tahrirlab bo‘lmaydi."
        )


def claim_post_for_publishing(post_id: int) -> bool:
    """
    Pending postni atomik ravishda publishing holatiga o‘tkazadi.

    Faqat bitta process/callback True oladi. Ikkinchi parallel Approve False
    oladi va postni qayta yubormasligi kerak.
    """
    with get_conn(immediate=True) as conn:
        cursor = conn.execute(
            """
            UPDATE posts
            SET status = ?
            WHERE id = ?
              AND status = ?
              AND channel_message_id IS NULL
            """,
            (
                STATUS_PUBLISHING,
                int(post_id),
                STATUS_PENDING,
            ),
        )

        return cursor.rowcount == 1


def release_publish_claim(post_id: int) -> bool:
    """
    Telegramga yuborish muvaffaqiyatsiz bo‘lsa publishing holatini pendingga
    qaytaradi.
    """
    with get_conn(immediate=True) as conn:
        cursor = conn.execute(
            """
            UPDATE posts
            SET status = ?
            WHERE id = ?
              AND status = ?
              AND channel_message_id IS NULL
            """,
            (
                STATUS_PENDING,
                int(post_id),
                STATUS_PUBLISHING,
            ),
        )

        return cursor.rowcount == 1


def mark_posted(post_id: int, channel_message_id: int) -> None:
    message_id = int(channel_message_id)

    if message_id <= 0:
        raise ValueError("channel_message_id musbat butun son bo‘lishi kerak.")

    with get_conn(immediate=True) as conn:
        row = conn.execute(
            """
            SELECT status, channel_message_id
            FROM posts
            WHERE id = ?
            """,
            (int(post_id),),
        ).fetchone()

        if row is None:
            raise PostNotFoundError(f"Post topilmadi: id={post_id}")

        existing_message_id = row["channel_message_id"]

        # Idempotent takroriy chaqiruv.
        if (
            row["status"] == STATUS_POSTED
            and existing_message_id == message_id
        ):
            return

        if existing_message_id is not None:
            raise InvalidPostStateError(
                "Post boshqa channel_message_id bilan allaqachon joylangan."
            )

        if row["status"] not in {STATUS_PENDING, STATUS_PUBLISHING}:
            raise InvalidPostStateError(
                f"{row['status']!r} holatidagi postni posted qilib bo‘lmaydi."
            )

        try:
            conn.execute(
                """
                UPDATE posts
                SET status = ?,
                    channel_message_id = ?,
                    posted_at = ?
                WHERE id = ?
                """,
                (
                    STATUS_POSTED,
                    message_id,
                    _utc_now_iso(),
                    int(post_id),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise InvalidPostStateError(
                f"channel_message_id={message_id} boshqa postga biriktirilgan."
            ) from exc


def mark_status(post_id: int, status: str) -> None:
    normalized_status = str(status).strip().lower()

    if normalized_status not in VALID_POST_STATUSES:
        allowed = ", ".join(sorted(VALID_POST_STATUSES))
        raise ValueError(
            f"Noto‘g‘ri status: {status!r}. Ruxsat etilganlari: {allowed}."
        )

    with get_conn(immediate=True) as conn:
        row = conn.execute(
            """
            SELECT status, channel_message_id
            FROM posts
            WHERE id = ?
            """,
            (int(post_id),),
        ).fetchone()

        if row is None:
            raise PostNotFoundError(f"Post topilmadi: id={post_id}")

        if row["channel_message_id"] is not None and normalized_status != STATUS_POSTED:
            raise InvalidPostStateError(
                "Kanalga joylangan post statusini orqaga qaytarib bo‘lmaydi."
            )

        conn.execute(
            """
            UPDATE posts
            SET status = ?
            WHERE id = ?
            """,
            (
                normalized_status,
                int(post_id),
            ),
        )


# ---------------------------------------------------------------------------
# Statistika
# ---------------------------------------------------------------------------

def update_reactions(
    channel_message_id: int,
    reactions_json: str,
) -> None:
    message_id = int(channel_message_id)

    if message_id <= 0:
        raise ValueError("channel_message_id musbat bo‘lishi kerak.")

    try:
        parsed = json.loads(reactions_json or "{}")
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("reactions_json valid JSON bo‘lishi kerak.") from exc

    if not isinstance(parsed, dict):
        raise ValueError("reactions_json JSON object bo‘lishi kerak.")

    normalized_reactions: dict[str, int] = {}

    for emoji, count in parsed.items():
        try:
            normalized_count = int(count)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Reaksiya soni butun son bo‘lishi kerak: {emoji!r}"
            ) from exc

        if normalized_count < 0:
            raise ValueError("Reaksiya soni manfiy bo‘lishi mumkin emas.")

        normalized_reactions[str(emoji)] = normalized_count

    canonical_json = json.dumps(
        normalized_reactions,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    with get_conn(immediate=True) as conn:
        conn.execute(
            """
            UPDATE posts
            SET reactions_json = ?
            WHERE channel_message_id = ?
            """,
            (
                canonical_json,
                message_id,
            ),
        )


def update_views(channel_message_id: int, views: int) -> None:
    message_id = int(channel_message_id)
    normalized_views = int(views)

    if message_id <= 0:
        raise ValueError("channel_message_id musbat bo‘lishi kerak.")

    if normalized_views < 0:
        raise ValueError("views manfiy bo‘lishi mumkin emas.")

    with get_conn(immediate=True) as conn:
        conn.execute(
            """
            UPDATE posts
            SET views = ?
            WHERE channel_message_id = ?
            """,
            (
                normalized_views,
                message_id,
            ),
        )


def get_recent_posted(limit: int = 10) -> list[sqlite3.Row]:
    normalized_limit = max(1, min(int(limit), 5000))

    with get_conn() as conn:
        return conn.execute(
            """
            SELECT *
            FROM posts
            WHERE status = ?
            ORDER BY COALESCE(posted_at, created_at) DESC, id DESC
            LIMIT ?
            """,
            (
                STATUS_POSTED,
                normalized_limit,
            ),
        ).fetchall()


# ---------------------------------------------------------------------------
# Kunlik reja (webhook arxitekturasida tashqi cron shu jadval orqali
# "bugun uchun post vaqti kelib-kelmaganini" tekshiradi)
# ---------------------------------------------------------------------------

def get_or_create_daily_schedule(day_key: str, run_at_iso: str) -> str:
    """
    Berilgan kun uchun rejalashtirilgan vaqtni qaytaradi.

    Agar shu kun uchun yozuv mavjud bo‘lmasa, taklif qilingan run_at_iso bilan
    yaratadi (atomik — bir vaqtda bir nechta chaqiruv bo‘lsa ham faqat bittasi
    yozadi, qolganlari bazadagi mavjud qiymatni o‘qiydi).
    """
    normalized_day = str(day_key).strip()

    if not normalized_day:
        raise ValueError("day_key bo‘sh bo‘lishi mumkin emas.")

    with get_conn(immediate=True) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO daily_schedule (day, run_at, executed)
            VALUES (?, ?, 0)
            """,
            (normalized_day, str(run_at_iso)),
        )

        row = conn.execute(
            """
            SELECT run_at
            FROM daily_schedule
            WHERE day = ?
            """,
            (normalized_day,),
        ).fetchone()

    if row is None:
        raise DatabaseError(
            f"daily_schedule yozuvini o‘qib bo‘lmadi: day={normalized_day!r}"
        )

    return str(row["run_at"])


def claim_daily_run(day_key: str) -> bool:
    """
    Berilgan kun uchun kunlik postni bajarish huquqini atomik ravishda oladi.

    Faqat bitta chaqiruv True oladi (masalan, tashqi cron bir necha marta
    deyarli bir vaqtda so‘rov yuborsa ham, post faqat bir marta joylanadi).
    """
    normalized_day = str(day_key).strip()

    if not normalized_day:
        raise ValueError("day_key bo‘sh bo‘lishi mumkin emas.")

    with get_conn(immediate=True) as conn:
        cursor = conn.execute(
            """
            UPDATE daily_schedule
            SET executed = 1
            WHERE day = ?
              AND executed = 0
            """,
            (normalized_day,),
        )

        return cursor.rowcount == 1


# ---------------------------------------------------------------------------
# Ishlatilgan yangiliklar
# ---------------------------------------------------------------------------

def _normalize_news_url(url: str) -> str:
    normalized_url = str(url).strip()

    if not normalized_url:
        raise ValueError("Yangilik URL manzili bo‘sh bo‘lishi mumkin emas.")

    return normalized_url


def is_news_used(url: str) -> bool:
    normalized_url = _normalize_news_url(url)

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM used_news
            WHERE url = ?
            """,
            (normalized_url,),
        ).fetchone()

    return row is not None


def mark_news_used(url: str) -> None:
    normalized_url = _normalize_news_url(url)

    with get_conn(immediate=True) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO used_news (url, used_at)
            VALUES (?, ?)
            """,
            (
                normalized_url,
                _utc_now_iso(),
            ),
        )


def get_daily_schedule_status(day_key: str) -> tuple[str, bool] | None:
    """
    Berilgan kun uchun rejalashtirilgan vaqtni va bajarilgan-bajarilmaganini
    qaytaradi. Yozuv bo'lmasa None qaytaradi (yaratmaydi).

    Qaytadi: (run_at_iso, executed) yoki None
    """
    normalized_day = str(day_key).strip()

    if not normalized_day:
        raise ValueError("day_key bo‘sh bo‘lishi mumkin emas.")

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT run_at, executed
            FROM daily_schedule
            WHERE day = ?
            """,
            (normalized_day,),
        ).fetchone()

    if row is None:
        return None

    return str(row["run_at"]), bool(row["executed"])