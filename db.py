"""PostgreSQL modellari (users, arenas, questions) va yordamchi funksiyalar."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    delete,
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Render/Heroku "postgres://" yoki "postgresql://" beradi — asyncpg uchun moslab olamiz
for _prefix in ("postgres://", "postgresql://"):
    if DATABASE_URL.startswith(_prefix):
        DATABASE_URL = "postgresql+asyncpg://" + DATABASE_URL[len(_prefix):]
        break
DATABASE_URL = DATABASE_URL.replace("sslmode=", "ssl=")  # asyncpg "sslmode" ni tanimaydi
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL topilmadi. .env faylga qo'shing.")

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)


# --------------------------------------------------------------------------- #
# Modellar
# --------------------------------------------------------------------------- #
class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64))  # ismi
    login: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Arena(Base):
    __tablename__ = "arenas"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100))
    is_open: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint("correct_answer IN ('a','b','c','d')", name="questions_correct_answer_chk"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    arena_id: Mapped[int] = mapped_column(ForeignKey("arenas.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    option_a: Mapped[str] = mapped_column(Text)
    option_b: Mapped[str] = mapped_column(Text)
    option_c: Mapped[str] = mapped_column(Text)
    option_d: Mapped[str] = mapped_column(Text)
    correct_answer: Mapped[str] = mapped_column(String(1))  # faqat a/b/c/d


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose() -> None:
    await engine.dispose()


# --------------------------------------------------------------------------- #
# Parol
# --------------------------------------------------------------------------- #
_ITER = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITER)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, hexhash = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITER)
    return hmac.compare_digest(dk.hex(), hexhash)


# --------------------------------------------------------------------------- #
# Userlar
# --------------------------------------------------------------------------- #
def _norm_login(login: str) -> str:
    return login.strip().lower()


async def get_user(user_id: int) -> User | None:
    async with Session() as s:
        return await s.get(User, user_id)


async def get_user_by_tg(tg_id: int) -> User | None:
    async with Session() as s:
        res = await s.execute(select(User).where(User.telegram_id == tg_id))
        return res.scalar_one_or_none()


async def list_users() -> list[User]:
    async with Session() as s:
        res = await s.execute(select(User).order_by(User.id))
        return list(res.scalars())


async def login_exists(login: str, exclude_id: int | None = None) -> bool:
    async with Session() as s:
        stmt = select(User.id).where(User.login == _norm_login(login))
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        return (await s.execute(stmt)).first() is not None


async def create_user(username: str, login: str, password: str) -> User:
    user = User(username=username.strip(), login=_norm_login(login), password_hash=hash_password(password))
    async with Session() as s:
        s.add(user)
        try:
            await s.commit()
        except IntegrityError as e:
            await s.rollback()
            raise ValueError("login_taken") from e
    return user


async def update_user(user_id: int, field: str, value: str) -> bool:
    async with Session() as s:
        user = await s.get(User, user_id)
        if not user:
            return False
        if field == "username":
            user.username = value.strip()
        elif field == "login":
            user.login = _norm_login(value)
        elif field == "password":
            user.password_hash = hash_password(value)
        else:
            raise ValueError("bad_field")
        try:
            await s.commit()
        except IntegrityError as e:
            await s.rollback()
            raise ValueError("login_taken") from e
        return True


async def delete_user(user_id: int) -> bool:
    async with Session() as s:
        res = await s.execute(delete(User).where(User.id == user_id))
        await s.commit()
        return res.rowcount > 0


async def authenticate(login: str, password: str) -> User | None:
    async with Session() as s:
        res = await s.execute(select(User).where(User.login == _norm_login(login)))
        user = res.scalar_one_or_none()
    if user and verify_password(password, user.password_hash):
        return user
    return None


async def bind_telegram(user_id: int, tg_id: int) -> None:
    async with Session() as s:
        # bitta Telegram — bitta akkaunt
        others = await s.execute(select(User).where(User.telegram_id == tg_id, User.id != user_id))
        for o in others.scalars():
            o.telegram_id = None
        await s.flush()
        user = await s.get(User, user_id)
        if user:
            user.telegram_id = tg_id
        await s.commit()


async def unlink_telegram(user_id: int) -> None:
    async with Session() as s:
        user = await s.get(User, user_id)
        if user:
            user.telegram_id = None
            await s.commit()


# --------------------------------------------------------------------------- #
# Arenalar
# --------------------------------------------------------------------------- #
async def create_arena(title: str) -> Arena:
    arena = Arena(title=title.strip(), is_open=False)
    async with Session() as s:
        s.add(arena)
        await s.commit()
    return arena


async def list_arenas() -> list[tuple[Arena, int]]:
    async with Session() as s:
        stmt = (
            select(Arena, func.count(Question.id))
            .outerjoin(Question, Question.arena_id == Arena.id)
            .group_by(Arena.id)
            .order_by(Arena.id)
        )
        return [(a, n) for a, n in (await s.execute(stmt)).all()]


async def get_arena(arena_id: int) -> Arena | None:
    async with Session() as s:
        return await s.get(Arena, arena_id)


async def toggle_arena(arena_id: int) -> bool | None:
    """Yangi holatni qaytaradi (True=ochiq). Arena yo'q bo'lsa None."""
    async with Session() as s:
        arena = await s.get(Arena, arena_id)
        if not arena:
            return None
        arena.is_open = not arena.is_open
        await s.commit()
        return arena.is_open


async def delete_arena(arena_id: int) -> bool:
    async with Session() as s:
        await s.execute(delete(Question).where(Question.arena_id == arena_id))
        res = await s.execute(delete(Arena).where(Arena.id == arena_id))
        await s.commit()
        return res.rowcount > 0


# --------------------------------------------------------------------------- #
# Savollar
# --------------------------------------------------------------------------- #
async def add_question(arena_id: int, text: str, a: str, b: str, c: str, d: str, correct: str) -> Question:
    correct = correct.strip().lower()
    if correct not in ("a", "b", "c", "d"):
        raise ValueError("correct_answer faqat a/b/c/d bo'lishi kerak")
    q = Question(
        arena_id=arena_id, text=text.strip(),
        option_a=a.strip(), option_b=b.strip(), option_c=c.strip(), option_d=d.strip(),
        correct_answer=correct,
    )
    async with Session() as s:
        s.add(q)
        await s.commit()
    return q


async def get_questions(arena_id: int) -> list[Question]:
    async with Session() as s:
        res = await s.execute(select(Question).where(Question.arena_id == arena_id).order_by(Question.id))
        return list(res.scalars())


async def count_questions(arena_id: int) -> int:
    async with Session() as s:
        res = await s.execute(select(func.count(Question.id)).where(Question.arena_id == arena_id))
        return res.scalar_one()


async def get_question(question_id: int) -> Question | None:
    async with Session() as s:
        return await s.get(Question, question_id)


async def delete_question(question_id: int) -> int | None:
    """O'chirilgan savolning arena_id sini qaytaradi."""
    async with Session() as s:
        q = await s.get(Question, question_id)
        if not q:
            return None
        arena_id = q.arena_id
        await s.delete(q)
        await s.commit()
        return arena_id
