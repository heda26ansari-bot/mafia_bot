import logging
import asyncpg
import os
import uuid
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext

class OrderForm(StatesGroup):
    waiting_for_documents = State()

class SearchForm(StatesGroup):
    waiting_for_keyword = State()

# ---------------- تنظیمات ----------------
API_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(level=logging.INFO)
ADMIN_ID = 7918162941

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

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            service_id INTEGER REFERENCES services(id) ON DELETE CASCADE,
            docs TEXT,
            created_at TIMESTAMP DEFAULT now()
        )
        """)



    async with pool.acquire() as conn:
        # جدول orders (اگر نبود ساخته میشه)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            service_id INTEGER,
            order_code TEXT UNIQUE,
            docs TEXT,
            status TEXT DEFAULT 'new',
            created_at TIMESTAMP DEFAULT now()
        )
        """)

        # اگر ستون docs قبلاً ساخته نشده باشه، اضافه بشه
        await conn.execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS docs TEXT
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
        await conn.execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS service_id INTEGER REFERENCES services(id) ON DELETE CASCADE
        """)
        # اطمینان از وجود ستون service_id
        await conn.execute("""
        ALTER TABLE orders
        ADD COLUMN IF NOT EXISTS service_id INTEGER REFERENCES services(id) ON DELETE CASCADE
        """)
        
        # 📌 جدول جدید برای订 خبر
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id BIGINT,
            hashtag_id INTEGER REFERENCES hashtags(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, hashtag_id)
        )
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

@dp.message_handler(lambda m: m.text == "مدیریت خدمات")
async def show_manage_services(msg: types.Message):
    await msg.answer("📋 یکی از گزینه‌های مدیریت خدمات را انتخاب کنید:", reply_markup=manage_services_menu())


def manage_services_menu():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("➕ افزودن خدمات", callback_data="manage_add_service"),
        InlineKeyboardButton("🗑 حذف خدمات", callback_data="manage_delete_service"),
        InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")
    )
    return kb

@dp.callback_query_handler(lambda c: c.data == "manage_add_service")
async def manage_add_service(callback: types.CallbackQuery):
    async with pool.acquire() as conn:
        categories = await conn.fetch("SELECT * FROM service_categories")
    kb = InlineKeyboardMarkup(row_width=1)
    for cat in categories:
        kb.add(InlineKeyboardButton(cat["name"], callback_data=f"add_service_cat_{cat['id']}"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="manage_services"))
    await callback.message.edit_text("📂 یک دسته‌بندی انتخاب کنید:", reply_markup=kb)

from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

class AddServiceFSM(StatesGroup):
    waiting_for_title = State()
    waiting_for_docs = State()
    category_id = State()

@dp.callback_query_handler(lambda c: c.data.startswith("add_service_cat_"))
async def choose_category(callback: types.CallbackQuery, state: FSMContext):
    category_id = int(callback.data.split("_")[-1])
    await state.update_data(category_id=category_id)
    await AddServiceFSM.waiting_for_title.set()
    await callback.message.answer("📝 عنوان خدمت جدید را بفرستید:")


@dp.message_handler(state=AddServiceFSM.waiting_for_title, content_types=types.ContentTypes.TEXT)
async def get_service_title(msg: types.Message, state: FSMContext):
    await state.update_data(title=msg.text)
    await AddServiceFSM.waiting_for_docs.set()
    await msg.answer("📑 توضیحات و مدارک لازم برای این خدمت را ارسال کنید:")

@dp.message_handler(state=AddServiceFSM.waiting_for_docs, content_types=types.ContentTypes.TEXT)
async def get_service_docs(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    category_id = data["category_id"]
    title = data["title"]
    docs = msg.text

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO services (category_id, title, documents) VALUES ($1, $2, $3)
        """, category_id, title, docs)

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ افزودن خدمات", callback_data="manage_add_service"),
        InlineKeyboardButton("⬅️ بازگشت", callback_data="manage_services")
    )
    await msg.answer(f"✅ خدمت <b>{title}</b> با موفقیت ثبت شد.", reply_markup=kb)
    await state.finish()


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


# شروع فرم بعد از انتخاب خدمت
@dp.callback_query_handler(lambda c: c.data.startswith("service_"))
async def start_order_form(callback_query: types.CallbackQuery, state: FSMContext):
    service_id = int(callback_query.data.split("_")[1])

    async with pool.acquire() as conn:
        service = await conn.fetchrow(
            "SELECT title, documents FROM services WHERE id=$1", service_id
        )

    await state.update_data(service_id=service_id, documents=[])

    # ارسال توضیحات خدمت و درخواست مدارک
    await bot.send_message(
        callback_query.from_user.id,
        f"📌 <b>{service['title']}</b>\n\n"
        f"مدارک لازم: {service['documents']}\n\n"
        "لطفاً مدارک و توضیحات لازم را ارسال کنید.\n"
        "می‌توانید چند پیام مختلف بفرستید.\n"
        "وقتی آماده شدید، روی دکمه زیر بزنید 👇",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("✅ ثبت سفارش", callback_data="submit_order")
        )
    )

    await OrderForm.waiting_for_documents.set()

# دریافت پیام‌های کاربر (مدارک / متن / فایل)

@dp.message_handler(state=OrderForm.waiting_for_documents, content_types=types.ContentTypes.ANY)
async def collect_documents(message: types.Message, state: FSMContext):
    data = await state.get_data()
    documents = data.get("documents", [])

    # ذخیره فقط متن کوتاه برای دیتابیس (نه فایل واقعی)
    if message.text:
        documents.append(message.text)
    elif message.photo:
        documents.append("📷 عکس ارسال شد")
    elif message.document:
        documents.append(f"📄 فایل: {message.document.file_name}")
    else:
        documents.append("📝 مدرک ارسال شد")

    await state.update_data(documents=documents)

    await message.answer("✅ مدرک شما ثبت شد. می‌توانید مدارک بیشتری ارسال کنید یا روی «ثبت سفارش» بزنید.")
    
    msg_ids = data.get("messages", [])
    msg_ids.append(message.message_id)
    await state.update_data(messages=msg_ids)



# ثبت سفارش نهایی
import uuid
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

@dp.callback_query_handler(lambda c: c.data == "submit_order", state=OrderForm.waiting_for_documents)
async def submit_order(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    service_id = data.get("service_id")
    documents_list = data.get("documents", [])          # متن خلاصه مدارک برای ذخیره در DB
    msg_ids = data.get("messages", [])                  # شناسهٔ پیام‌ها برای فوروارد

    documents_text = "\n".join(documents_list) if documents_list else "⛔ مدرکی ارسال نشد"
    order_code = str(uuid.uuid4())[:8]

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO orders (user_id, service_id, order_code, docs, status)
            VALUES ($1, $2, $3, $4, 'new')
            """,
            callback_query.from_user.id, service_id, order_code, documents_text
        )
        service = await conn.fetchrow("SELECT title FROM services WHERE id=$1", service_id)

    # پیام تأیید به کاربر (در همان چت)
    await callback_query.message.answer(
        f"✅ سفارش شما برای <b>{service['title']}</b> ثبت شد.\n"
        f"کد رهگیری: <code>{order_code}</code>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

    # آماده‌سازی منشن امن (fallback برای first/last/username)
    user = callback_query.from_user
    full_name = (user.first_name or "") + ((" " + user.last_name) if getattr(user, "last_name", None) else "")
    mention = f"<a href='tg://user?id={user.id}'>{full_name or user.username or user.id}</a>"

    # پیام به مدیر با دکمه "تکمیل سفارش"
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("✅ تکمیل سفارش", callback_data=f"complete_{order_code}"))

    await bot.send_message(
        ADMIN_ID,
        f"📢 سفارش جدید ثبت شد\n"
        f"👤 مشتری: {mention}\n"
        f"📌 خدمت: {service['title']}\n"
        f"📎 کد رهگیری: <code>{order_code}</code>\n\n"
        f"📝 مدارک ارسالی در ادامه فوروارد می‌شوند 👇",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    # فوروارد کردن همهٔ پیام‌های مدارک به مدیر (با همان فرمت اصلی)
    for mid in msg_ids:
        try:
            await bot.forward_message(ADMIN_ID, callback_query.from_user.id, mid)
        except Exception as e:
            # لاگ خطا ولی ادامه بده
            print("⚠️ خطا در فوروارد پیام:", e)

    # پایان FSM و پاسخ به callback تا دک لودینگ برداشته شود
    await state.finish()
    await callback_query.answer("سفارش شما ثبت شد ✅")


# هندلر برای تکمیل سفارش
@dp.callback_query_handler(lambda c: c.data.startswith("complete_"))
async def complete_order(callback_query: types.CallbackQuery):
    order_code = callback_query.data.split("_")[1]

    async with pool.acquire() as conn:
        # گرفتن سفارش برای پیدا کردن user_id
        order = await conn.fetchrow("SELECT user_id FROM orders WHERE order_code=$1", order_code)
        if not order:
            await bot.answer_callback_query(callback_query.id, "⛔ سفارش پیدا نشد.", show_alert=True)
            return

        user_id = order["user_id"]

        # تغییر وضعیت به completed و پاک کردن مدارک
        await conn.execute("""
            UPDATE orders
            SET status='completed', docs=NULL
            WHERE order_code=$1
        """, order_code)

    # پیام به مدیر
    await bot.answer_callback_query(callback_query.id, "✅ سفارش تکمیل شد.", show_alert=True)

    # پیام به کاربر
    await bot.send_message(
        user_id,
        f"🎉 سفارش شما با کد رهگیری <code>{order_code}</code> در حالت <b>تکمیل شده</b> قرار گرفت."
    )




# مرحله ۳: ثبت سفارش
@dp.callback_query_handler(lambda c: c.data.startswith("service_"))
async def process_service(callback_query: types.CallbackQuery):
    service_id = int(callback_query.data.split("_")[1])

    # تولید کد سفارش (۸ کاراکتری یکتا)
    order_code = str(uuid.uuid4())[:8]

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO orders (user_id, service_id, order_code, status)
            VALUES ($1, $2, $3, 'new')
        """, callback_query.from_user.id, service_id, order_code)

        service = await conn.fetchrow(
            "SELECT title FROM services WHERE id=$1", service_id
        )

    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        f"✅ سفارش شما برای <b>{service['title']}</b> ثبت شد.\n"
        f"کد پیگیری: <code>{order_code}</code>",
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

# مرحله ۱: درخواست کلیدواژه
@dp.message_handler(lambda m: m.text == "🔍 جستجو در اطلاعیه/خبر")
async def ask_keyword(msg: types.Message):
    await msg.answer("🔎 لطفاً کلیدواژه مورد نظر خود را وارد کنید:")
    await SearchForm.waiting_for_keyword.set()

# مرحله ۲: جستجو
@dp.message_handler(state=SearchForm.waiting_for_keyword)
async def search_posts(msg: types.Message, state: FSMContext):
    keyword = msg.text
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.id, p.title, p.content, array_agg(h.name) AS hashtags
            FROM posts p
            LEFT JOIN post_hashtags ph ON p.id = ph.post_id
            LEFT JOIN hashtags h ON ph.hashtag_id = h.id
            WHERE p.title ILIKE $1
            GROUP BY p.id
            ORDER BY p.created_at DESC
            LIMIT 5
        """, f"%{keyword}%")

    if not rows:
        await msg.answer("⛔ هیچ خبری با این کلیدواژه یافت نشد.")
        await state.finish()
        return

    for row in rows:
        summary = (row["content"][:100] + "...") if row["content"] else "⛔ بدون توضیحات"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔽 نمایش کامل خبر", callback_data=f"full_{row['id']}"))

        # دکمه هشتگ‌ها
        if row["hashtags"]:
            for h in row["hashtags"]:
                kb.add(InlineKeyboardButton(f"#{h}", callback_data=f"tag_{h}"))

        await msg.answer(
            f"📌 <b>{row['title']}</b>\n\n"
            f"📝 {summary}",
            reply_markup=kb
        )

    await state.finish()

# مرحله ۳: نمایش کامل خبر
@dp.callback_query_handler(lambda c: c.data.startswith("full_"))
async def show_full(callback_query: types.CallbackQuery):
    post_id = int(callback_query.data.split("_")[1])
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT title, content FROM posts WHERE id=$1", post_id)

    if row:
        await bot.send_message(
            callback_query.from_user.id,
            f"📌 <b>{row['title']}</b>\n\n{row['content']}"
        )

    await bot.answer_callback_query(callback_query.id)

# مرحله ۴: نمایش پست‌های مرتبط با هشتگ
@dp.callback_query_handler(lambda c: c.data.startswith("tag_"))
async def show_tag_posts(callback_query: types.CallbackQuery):
    tag = callback_query.data.split("_")[1]
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.title, p.content
            FROM posts p
            JOIN post_hashtags ph ON p.id = ph.post_id
            JOIN hashtags h ON ph.hashtag_id = h.id
            WHERE h.name=$1
            ORDER BY p.created_at DESC
            LIMIT 5
        """, tag)

    if not rows:
        await bot.send_message(callback_query.from_user.id, "⛔ خبری برای این هشتگ یافت نشد.")
    else:
        for row in rows:
            summary = (row["content"][:100] + "...") if row["content"] else "⛔ بدون توضیحات"
            await bot.send_message(
                callback_query.from_user.id,
                f"📌 <b>{row['title']}</b>\n\n📝 {summary}"
            )

    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(lambda m: m.text == "🔔 دریافت خودکار خبر")
async def show_subscriptions(msg: types.Message):
    async with pool.acquire() as conn:
        hashtags = await conn.fetch("SELECT id, name FROM hashtags ORDER BY name")
        user_subs = await conn.fetch("SELECT hashtag_id FROM subscriptions WHERE user_id=$1", msg.from_user.id)
        user_subs_ids = [r["hashtag_id"] for r in user_subs]

    kb = InlineKeyboardMarkup(row_width=2)
    for h in hashtags:
        status = "✅" if h["id"] in user_subs_ids else "❌"
        kb.insert(InlineKeyboardButton(f"{status} #{h['name']}", callback_data=f"sub_{h['id']}"))

    await msg.answer("🔔 هشتگ‌هایی که می‌خواهید خبرهایشان خودکار برایتان ارسال شود را انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("sub_"))
async def toggle_subscription(callback_query: types.CallbackQuery):
    hashtag_id = int(callback_query.data.split("_")[1])
    user_id = callback_query.from_user.id

    async with pool.acquire() as conn:
        exists = await conn.fetchrow("SELECT 1 FROM subscriptions WHERE user_id=$1 AND hashtag_id=$2", user_id, hashtag_id)
        if exists:
            await conn.execute("DELETE FROM subscriptions WHERE user_id=$1 AND hashtag_id=$2", user_id, hashtag_id)
        else:
            await conn.execute("INSERT INTO subscriptions (user_id, hashtag_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", user_id, hashtag_id)

    # رفرش منو
    await show_subscriptions(callback_query.message)
    await bot.answer_callback_query(callback_query.id, "✅ بروزرسانی شد")


# ---------------- راه‌اندازی ----------------
async def on_startup(dispatcher):
    await init_db()
    print("🚀 ربات شروع به کار کرد.")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
