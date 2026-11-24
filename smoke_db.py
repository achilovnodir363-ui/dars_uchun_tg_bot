"""DB tezkor testi: python smoke_db.py  ->  SMOKE OK"""
import asyncio
import uuid

import db


async def run() -> None:
    await db.init_db()
    tag = uuid.uuid4().hex[:8]
    arena = user = None
    try:
        arena = await db.create_arena(f"smoke-{tag}")
        assert (await db.toggle_arena(arena.id)) is True
        await db.add_question(arena.id, "2+2?", "3", "4", "5", "6", "B")
        qs = await db.get_questions(arena.id)
        assert len(qs) == 1 and qs[0].correct_answer == "b"

        try:
            await db.add_question(arena.id, "x", "1", "2", "3", "4", "z")
            raise AssertionError("noto'g'ri correct_answer qabul qilindi")
        except ValueError:
            pass

        user = await db.create_user("Smoke", f"smoke_{tag}", "pass1234")
        assert await db.login_exists(f"SMOKE_{tag}")
        assert await db.authenticate(f"smoke_{tag}", "pass1234")
        assert not await db.authenticate(f"smoke_{tag}", "wrong")
        await db.bind_telegram(user.id, 999_000_000 + int(tag[:4], 16))
        await db.update_user(user.id, "password", "newpass")
        assert await db.authenticate(f"smoke_{tag}", "newpass")
        print("SMOKE OK")
    finally:
        if user:
            await db.delete_user(user.id)
        if arena:
            await db.delete_arena(arena.id)
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(run())
