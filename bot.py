import logging
import asyncpg
import asyncio
import os
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage

# ---------------- تنظیمات ----------------
API_TOKEN = os.getenv("BOT_TOKEN")         # ست شده روی Railway
DATABASE_URL = os.getenv("DATABASE_URL")   # ست شده روی Railway

logging.basicConfig(level=logging.INFO)

# ---------------- اتصال بات ----------------
bot = Bot(token=API_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ---------------- دیتابیس ----------------
async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)

    async with pool.acquire() as conn:
        # جدول کاربران
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE,
            first_name TEXT,
            username TEXT,
            created_at TIMESTAMP DEFAULT now()
        );
        """)

        # جدول سفارش‌ها
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            service TEXT,
            created_at TIMESTAMP DEFAULT now()
        );
        """)

    print("✅ دیتابیس آماده شد.")

# ---------------- هندلرها ----------------
@dp.message_handler(commands=["start"])
async def start_cmd(msg: types.Message):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, first_name, username)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO NOTHING
        """, msg.from_user.id, msg.from_user.first_name, msg.from_user.username)

    await msg.answer(f"سلام {msg.from_user.first_name} 👋\nخوش اومدی به ربات!")

@dp.message_handler(commands=["order"])
async def order_cmd(msg: types.Message):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO orders (user_id, service)
            VALUES ($1, $2)
        """, msg.from_user.id, "نمونه سرویس")

    await msg.answer("✅ سفارش شما ثبت شد!")

# ---------------- راه‌اندازی ----------------
async def on_startup(dp):
    await init_db()
    print("🚀 ربات شروع به کار کرد.")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
