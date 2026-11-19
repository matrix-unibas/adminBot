"""Upgrades that move existing data."""
from mautrix.util.async_db import Database

from adminbot.db import Store
from adminbot.migrations import upgrade_table


async def test_v4_records_existing_bot_accounts_as_ours(tmp_path):
    """Bots provisioned before the bot_account table exist must still pass the guard."""
    db = Database.create(f"sqlite:{tmp_path}/bot.db", upgrade_table=upgrade_table)
    await db.start()
    try:
        await db.execute("DELETE FROM bot_account")
        await db.execute("INSERT INTO user_bot VALUES ('@p:x', 'quiz', 'p.quiz', 'p-quiz', '@bot.p.quiz:x', 'h', 'deleted')")
        await db.execute("INSERT INTO bot_recovery_key VALUES ('@bot.p.quiz:x', 'k')")
        await db.execute("INSERT INTO bot_recovery_key VALUES ('@bot.p.old:x', 'k')")
        [v4] = [step for step in upgrade_table.upgrades if step.__name__ == "upgrade_v4"]
        await db.execute("DROP TABLE bot_account")
        async with db.acquire() as conn:
            await v4(conn, db.scheme)
        store = Store(db)
        assert await store.is_bot_account("@bot.p.quiz:x") and await store.is_bot_account("@bot.p.old:x")
        assert not await store.is_bot_account("@bot.p.other:x")
    finally:
        await db.stop()
