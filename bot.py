import logging
import asyncpg
import os
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage

# ---------------- تنظیمات ----------------
API_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(level=logging.INFO)

# ---------------- اتصال بات ----------------
bot = Bot(token=API_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

pool = None  # اتصال دیتابیس

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

        # دسته‌بندی خدمات
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS service_categories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE
        );
        """)

        # خدمات
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id SERIAL PRIMARY KEY,
            category_id INTEGER REFERENCES service_categories(id) ON DELETE CASCADE,
            title TEXT
        );
        """)

        # سفارش‌ها
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            service_id INTEGER REFERENCES services(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT now()
        );
        """)

        # داده‌ی تستی (فقط بار اول)
        await conn.execute("""
        INSERT INTO service_categories (name) VALUES ('مدارک شخصی'), ('مدارک شرکتی')
        ON CONFLICT DO NOTHING;
        """)
        await conn.execute("""
        INSERT INTO services (category_id, title)
        SELECT 1, 'گواهینامه' WHERE NOT EXISTS (SELECT 1 FROM services WHERE title='گواهینامه');
        """)
        await conn.execute("""
        INSERT INTO services (category_id, title)
        SELECT 1, 'شناسنامه' WHERE NOT EXISTS (SELECT 1 FROM services WHERE title='شناسنامه');
        """)
        await conn.execute("""
        INSERT INTO services (category_id, title)
        SELECT 2, 'ثبت شرکت' WHERE NOT EXISTS (SELECT 1 FROM services WHERE title='ثبت شرکت');
        """)

    print("✅ دیتابیس آماده شد.")

# ---------------- کیبورد ----------------
def main_menu():
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🛒 ثبت سفارش", callback_data="order"),
        types.InlineKeyboardButton("📋 سفارش‌های من", callback_data="my_orders")
    )
    return kb

# ---------------- هندلرها ----------------
@dp.message_handler(commands=["start"])
async def start_cmd(msg: types.Message):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, first_name, username)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO NOTHING
        """, msg.from_user.id, msg.from_user.first_name, msg.from_user.username)

    await msg.answer(
        f"سلام {msg.from_user.first_name} 👋\n"
        "به ربات سفارش خوش اومدی.",
        reply_markup=main_menu()
    )

# مرحله ۱: نمایش دسته‌بندی
@dp.callback_query_handler(lambda c: c.data == "order")
async def process_order(callback_query: types.CallbackQuery):
    async with pool.acquire() as conn:
        cats = await conn.fetch("SELECT id, name FROM service_categories ORDER BY id")

    kb = types.InlineKeyboardMarkup(row_width=1)
    for c in cats:
        kb.add(types.InlineKeyboardButton(c["name"], callback_data=f"cat_{c['id']}"))
    kb.add(types.InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main"))

    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "📂 یک دسته‌بندی انتخاب کنید:", reply_markup=kb)

# مرحله ۲: نمایش سرویس‌های دسته
@dp.callback_query_handler(lambda c: c.data.startswith("cat_"))
async def process_category(callback_query: types.CallbackQuery):
    cat_id = int(callback_query.data.split("_")[1])

    async with pool.acquire() as conn:
        services = await conn.fetch("SELECT id, title FROM services WHERE category_id=$1", cat_id)

    kb = types.InlineKeyboardMarkup(row_width=1)
    for s in services:
        kb.add(types.InlineKeyboardButton(s["title"], callback_data=f"service_{s['id']}"))
    kb.add(types.InlineKeyboardButton("⬅️ بازگشت", callback_data="order"))

    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "🔎 یکی از خدمات زیر را انتخاب کنید:", reply_markup=kb)

# مرحله ۳: ثبت سفارش
@dp.callback_query_handler(lambda c: c.data.startswith("service_"))
async def process_service(callback_query: types.CallbackQuery):
    service_id = int(callback_query.data.split("_")[1])

    async with pool.acquire() as conn:
        # ثبت سفارش
        await conn.execute("""
            INSERT INTO orders (user_id, service_id) VALUES ($1, $2)
        """, callback_query.from_user.id, service_id)

        # گرفتن اطلاعات سرویس
        service = await conn.fetchrow("SELECT title FROM services WHERE id=$1", service_id)

    # این خط خیلی مهمه برای جلوگیری از لودینگ بی‌پایان
    await callback_query.answer()

    # ارسال پیام تأیید
    await callback_query.message.answer(
        f"✅ سفارش شما برای <b>{service['title']}</b> ثبت شد.",
        reply_markup=main_menu()
    )


# مشاهده سفارش‌های کاربر
@dp.callback_query_handler(lambda c: c.data == "my_orders")
async def my_orders(callback_query: types.CallbackQuery):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT o.id, s.title, o.created_at
            FROM orders o
            JOIN services s ON o.service_id = s.id
            WHERE o.user_id=$1
            ORDER BY o.created_at DESC
            LIMIT 5
        """, callback_query.from_user.id)

    if not rows:
        text = "📭 شما هنوز سفارشی ثبت نکردید."
    else:
        text = "📋 آخرین سفارش‌های شما:\n\n"
        for r in rows:
            text += f"🆔 {r['id']} | {r['title']} | {r['created_at'].strftime('%Y-%m-%d %H:%M')}\n"

    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, text, reply_markup=main_menu())

# بازگشت به منو
@dp.callback_query_handler(lambda c: c.data == "back_main")
async def back_main(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "🏠 منوی اصلی:", reply_markup=main_menu())

# ---------------- راه‌اندازی ----------------
async def on_startup(dispatcher):
    await init_db()
    print("🚀 ربات شروع به کار کرد.")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
