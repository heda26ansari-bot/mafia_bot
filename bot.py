import logging
import asyncpg
import os
import uuid
import json
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

class OrderForm(StatesGroup):
    waiting_for_documents = State()

class SearchForm(StatesGroup):
    waiting_for_keyword = State()

class AdminAddService(StatesGroup):
    waiting_for_title = State()
    waiting_for_docs = State()

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
        
        # جدول پست‌ها
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            message_id BIGINT UNIQUE,
            title TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT now()
        )
        """)
        # جدول هشتگ‌ها
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS hashtags (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE
        )
        """)

        # رابطه بین پست‌ها و هشتگ‌ها
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS post_hashtags (
            post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
            hashtag_id INTEGER REFERENCES hashtags(id) ON DELETE CASCADE,
            PRIMARY KEY (post_id, hashtag_id)
        )
        """)


    print("✅ دیتابیس آماده شد.")

# ---------------- کیبورد ----------------
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# منوی اصلی
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("📋 سفارش خدمات"))
    kb.add(KeyboardButton("🔍 جستجو اطلاعیه/خبر"))
    kb.add(KeyboardButton("🔔 دریافت خودکار خبر"))
    kb.add(KeyboardButton("⚙️ مدیریت خدمات"))
    return kb

# زیرمنوی سفارشات
def orders_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("➕ ثبت سفارش"))
    kb.add(KeyboardButton("📦 سفارش‌های من"))
    kb.add(KeyboardButton("⬅️ بازگشت به منوی اصلی"))
    return kb
# ===========================
# کیبورد دسته بندی
# ===========================
async def service_categories_keyboard(prefix: str = "order"):
    kb = InlineKeyboardMarkup(row_width=2)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name FROM service_categories ORDER BY id")
    if not rows:
        kb.add(InlineKeyboardButton("⛔ هیچ دسته‌ای وجود ندارد", callback_data="none"))
        return kb

    for r in rows:
        cid = r["id"]
        name = r["name"]
        cb = f"{prefix}_cat_{cid}"
        kb.add(InlineKeyboardButton(name, callback_data=cb))

    return kb

# --------------------------
# مدیریت (افزودن / حذف) خدمات — FSM-based
# --------------------------

# 1) شروع افزودن خدمت (ریپلی کیبورد -> '➕ افزودن خدمات')
@dp.message_handler(lambda m: m.text == "➕ افزودن خدمات")
async def admin_add_service_start(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return await msg.answer("⛔ شما دسترسی به این بخش ندارید.")
    # نمایش دسته‌بندی‌ها با callback_data مخصوص ادمین:
    async with pool.acquire() as conn:
        cats = await conn.fetch("SELECT id, name FROM service_categories ORDER BY id")
    kb = InlineKeyboardMarkup(row_width=1)
    for c in cats:
        kb.add(InlineKeyboardButton(c["name"], callback_data=f"admin_addcat_{c['id']}"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_back_main"))
    await msg.answer("📂 یک دسته‌بندی برای افزودن خدمت انتخاب کنید:", reply_markup=kb)


# 2) ادمین یک دسته را انتخاب می‌کند -> درخواست عنوان (FSM set)
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_addcat_"))
async def admin_addcat_choose(call: types.CallbackQuery, state: FSMContext):
    await call.answer()  # برداشتن لودینگ
    try:
        category_id = int(call.data.split("_")[-1])
    except:
        return await call.message.answer("❌ داده نامعتبر.")
    await state.update_data(category_id=category_id, documents=[])
    await AdminAddService.waiting_for_title.set()
    await call.message.answer("✍️ لطفاً عنوان خدمت جدید را ارسال کنید:")


# 3) دریافت عنوان -> می‌رویم به مرحله دریافت مدارک/توضیحات
@dp.message_handler(state=AdminAddService.waiting_for_title, content_types=types.ContentTypes.TEXT)
async def admin_add_title(msg: types.Message, state: FSMContext):
    title = msg.text.strip()
    if not title:
        return await msg.answer("❌ لطفاً یک عنوان معتبر وارد کنید.")
    await state.update_data(title=title)
    await AdminAddService.waiting_for_docs.set()
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ ثبت خدمت", callback_data="admin_confirm_add_service"),
        InlineKeyboardButton("❌ انصراف", callback_data="admin_cancel_add_service"),
    )
    await msg.answer(
        "📑 حالا توضیحات و مدارک لازم برای این خدمت را ارسال کنید.\n"
        "🔸 می‌توانید چند پیام ارسال کنید.\n"
        "🔸 پس از اتمام، دکمه «✅ ثبت خدمت» را بزنید.",
        reply_markup=kb
    )


# 4) دریافت مدارک/پیام‌ها (می‌تواند چند پیام باشد) — فقط ذخیره می‌کنیم (text/file_id/caption)
@dp.message_handler(state=AdminAddService.waiting_for_docs, content_types=types.ContentTypes.ANY)
async def admin_add_docs(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    docs = data.get("documents", [])

    entry = {}
    entry["type"] = msg.content_type
    if msg.content_type == "text":
        entry["text"] = msg.text
    elif msg.content_type == "photo":
        entry["file_id"] = msg.photo[-1].file_id
        entry["caption"] = msg.caption or ""
    elif msg.content_type == "document":
        entry["file_id"] = msg.document.file_id
        entry["file_name"] = msg.document.file_name
        entry["caption"] = msg.caption or ""
    else:
        # دیگر نوع‌ها را به صورت خلاصه ثبت کن
        try:
            attr = getattr(msg, msg.content_type)
            entry["file_id"] = getattr(attr, "file_id", None)
        except Exception:
            entry["text"] = f"<{msg.content_type} received>"

    docs.append(entry)
    await state.update_data(documents=docs)
    await msg.answer("✅ دریافت شد. اگر همه مدارک را فرستادید، دکمه «✅ ثبت خدمت» را بزنید.")


# 5) ادمین دکمه ثبت را می‌زند -> ذخیره در DB
@dp.callback_query_handler(lambda c: c.data == "admin_confirm_add_service", state=AdminAddService.waiting_for_docs)
async def admin_confirm_add(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    category_id = data.get("category_id")
    title = data.get("title") or "بدون عنوان"
    documents = data.get("documents", [])

    # ذخیره به صورت JSON (TEXT در جدول)
    docs_json = json.dumps(documents, ensure_ascii=False)

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO services (category_id, title, documents) VALUES ($1, $2, $3)",
            category_id, title, docs_json
        )

    await call.message.answer(f"✅ خدمت «{title}» با موفقیت ثبت شد.", reply_markup=main_menu())
    await state.finish()


# 6) انصراف از افزودن
@dp.callback_query_handler(lambda c: c.data == "admin_cancel_add_service", state=AdminAddService.waiting_for_docs)
async def admin_cancel_add(call: types.CallbackQuery, state: FSMContext):
    await call.answer("❌ افزودن خدمت لغو شد.")
    await state.finish()
    await call.message.answer("❌ افزودن خدمت لغو شد.", reply_markup=main_menu())

# شروع حذف: نمایش دسته‌ها با callback admin_delcat_
@dp.message_handler(lambda m: m.text == "❌ حذف خدمات")
async def admin_delete_start(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return await msg.answer("⛔ شما دسترسی به این بخش ندارید.")
    async with pool.acquire() as conn:
        cats = await conn.fetch("SELECT id, name FROM service_categories ORDER BY id")
    kb = InlineKeyboardMarkup(row_width=1)
    for c in cats:
        kb.add(InlineKeyboardButton(c["name"], callback_data=f"admin_delcat_{c['id']}"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_back_main"))
    await msg.answer("📂 یک دسته‌بندی برای حذف خدمت انتخاب کنید:", reply_markup=kb)


# وقتی ادمین یک دسته را انتخاب کرد -> لیست خدمات آن گروه
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_delcat_"))
async def admin_delcat_choose(call: types.CallbackQuery):
    await call.answer()
    try:
        cat_id = int(call.data.split("_")[-1])
    except:
        return await call.message.answer("❌ داده نامعتبر.")
    async with pool.acquire() as conn:
        services = await conn.fetch("SELECT id, title FROM services WHERE category_id=$1 ORDER BY id", cat_id)

    if not services:
        await call.message.answer("⛔ خدمتی در این دسته موجود نیست.")
        return

    kb = InlineKeyboardMarkup(row_width=1)
    for s in services:
        kb.add(InlineKeyboardButton(f"❌ {s['title']}", callback_data=f"admin_delservice_{s['id']}"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_back_main"))
    await call.message.answer("🗑 یکی از خدمات را برای حذف انتخاب کنید:", reply_markup=kb)


# انتخاب خدمت -> نمایش پیغام تایید (حذف نهایی)
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_delservice_"))
async def admin_delservice_confirm(call: types.CallbackQuery):
    await call.answer()
    service_id = int(call.data.split("_")[-1])
    async with pool.acquire() as conn:
        s = await conn.fetchrow("SELECT title FROM services WHERE id=$1", service_id)
    if not s:
        return await call.message.answer("⛔ خدمت پیدا نشد.")

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ حذف نهایی", callback_data=f"admin_confirm_del_{service_id}"),
        InlineKeyboardButton("❌ انصراف", callback_data="admin_cancel_del"),
    )
    await call.message.answer(f"⚠️ آیا مطمئن هستید که می‌خواهید خدمت «{s['title']}» را حذف کنید؟", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data and c.data.startswith("admin_confirm_del_"))
async def admin_confirm_del(call: types.CallbackQuery):
    await call.answer()
    service_id = int(call.data.split("_")[-1])
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM services WHERE id=$1", service_id)
    await call.message.answer("✅ خدمت حذف شد.", reply_markup=main_menu())


@dp.callback_query_handler(lambda c: c.data == "admin_cancel_del")
async def admin_cancel_del(call: types.CallbackQuery):
    await call.answer("❌ حذف لغو شد.")
    await call.message.answer("❌ حذف لغو شد.", reply_markup=main_menu())


# بازگشت به منوی اصلی
@dp.message_handler(lambda m: m.text == "⬅️ بازگشت به منوی اصلی")
async def back_to_main(message: types.Message):
    await message.answer("🔙 بازگشت به منوی اصلی", reply_markup=main_menu())


# رفتن به زیرمنوی سفارشات
@dp.message_handler(lambda m: m.text == "📋 سفارش خدمات")
async def show_orders_menu(message: types.Message):
    await message.answer("📋 لطفاً یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=orders_menu())

# ===== سفارش خدمات =====
@dp.message_handler(lambda m: m.text == "➕ ثبت سفارش")
async def add_order(message: types.Message):
    kb = await service_categories_keyboard()
    await message.answer("📋 لطفاً یک دسته‌بندی برای سفارش انتخاب کنید:", reply_markup=kb)


@dp.message_handler(lambda m: m.text == "📦 سفارش‌های من")
async def my_orders(message: types.Message):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT o.order_code, o.status, s.title 
            FROM orders o
            JOIN services s ON o.service_id = s.id
            WHERE o.user_id=$1
            ORDER BY o.created_at DESC
            LIMIT 5
        """, message.from_user.id)

    if not rows:
        await message.answer("⛔ سفارشی برای شما ثبت نشده است.")
    else:
        text = "📦 <b>آخرین سفارش‌های شما:</b>\n\n"
        for r in rows:
            text += f"▫️ {r['title']} | کد: <code>{r['order_code']}</code> | وضعیت: {r['status']}\n"
        await message.answer(text)


# ===== مدیریت خدمات =====
@dp.message_handler(lambda m: m.text == "⚙️ مدیریت خدمات")
async def manage_services(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ شما دسترسی به این بخش ندارید.")

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("➕ افزودن خدمات"))
    kb.add(KeyboardButton("❌ حذف خدمات"))
    kb.add(KeyboardButton("⬅️ بازگشت به منوی اصلی"))

    await message.answer("⚙️ بخش مدیریت خدمات", reply_markup=kb)
    


@dp.message_handler(lambda m: m.text == "❌ حذف خدمات")
async def delete_service_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ شما دسترسی به این بخش ندارید.")

    kb = await service_categories_keyboard()
    await message.answer("📂 یک دسته‌بندی برای حذف خدمت انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("delete_"))
async def process_delete_service(callback_query: types.CallbackQuery):
    service_id = int(callback_query.data.split("_")[1])

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM services WHERE id=$1", service_id)

    await bot.answer_callback_query(callback_query.id, "✅ خدمت حذف شد")
    await bot.send_message(callback_query.from_user.id, "خدمت مورد نظر حذف شد.", reply_markup=await main_menu())


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
        "به ربات کافی نت مجازی خوش اومدی.",
        reply_markup=main_menu()
    )

# بازگشت به منوی اصلی
@dp.message_handler(lambda m: m.text == "⬅️ بازگشت به منوی اصلی")
async def back_to_main(message: types.Message):
    await message.answer("🔙 بازگشت به منوی اصلی", reply_markup=main_menu())


# رفتن به زیرمنوی سفارشات
@dp.message_handler(lambda m: m.text == "📋 سفارش خدمات")
async def show_orders_menu(message: types.Message):
    await message.answer("📋 لطفاً یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=orders_menu())


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


# مرحله ۲: نمایش خدمات یک دسته
@dp.callback_query_handler(lambda c: c.data.startswith("cat_"))
async def process_category(callback_query: types.CallbackQuery):
    cat_id = int(callback_query.data.split("_")[1])
    async with pool.acquire() as conn:
        services = await conn.fetch("SELECT id, title FROM services WHERE category_id=$1", cat_id)

    if not services:
        await bot.answer_callback_query(callback_query.id, "⛔ خدمتی در این دسته ثبت نشده.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(row_width=1)
    for s in services:
        kb.add(InlineKeyboardButton(s["title"], callback_data=f"service_{s['id']}"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="order"))

    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "🔎 یکی از خدمات زیر را انتخاب کنید:", reply_markup=kb)


# مرحله ۳: شروع فرم سفارش
@dp.callback_query_handler(lambda c: c.data.startswith("service_"))
async def start_order_form(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        service_id = int(callback_query.data.split("_")[1])
        print("🟢 Service ID دریافت شد:", service_id)  # دیباگ

        async with pool.acquire() as conn:
            service = await conn.fetchrow("SELECT title, documents FROM services WHERE id=$1", service_id)
            print("🟢 Service از DB:", service)  # دیباگ

        if not service:
            await bot.answer_callback_query(callback_query.id, "⛔ خدمت پیدا نشد.", show_alert=True)
            return

        await state.update_data(service_id=service_id, documents=[])

        await bot.send_message(
            callback_query.from_user.id,
            f"📌 <b>{service['title']}</b>\n\n"
            f"📝 مدارک لازم: {service['documents'] or '—'}\n\n"
            "لطفاً مدارک و توضیحات رو ارسال کنید.\n"
            "بعد روی دکمه زیر بزنید 👇",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("✅ ثبت سفارش", callback_data="submit_order")
            )
        )

        await OrderForm.waiting_for_documents.set()
        await bot.answer_callback_query(callback_query.id)

    except Exception as e:
        print("❌ خطا در start_order_form:", e)
        await bot.answer_callback_query(callback_query.id, "⚠️ خطا در پردازش خدمت.", show_alert=True)



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

# =========================
# 🔍 جستجو اطلاعیه/خبر
# =========================
@dp.message_handler(lambda m: m.text == "🔍 جستجو اطلاعیه/خبر")
async def start_search(message: types.Message):
    await message.answer("🔎 لطفاً کلیدواژه مورد نظر رو وارد کنید:")
    await SearchForm.waiting_for_keyword.set()

@dp.message_handler(state=SearchForm.waiting_for_keyword)
async def process_search(message: types.Message, state: FSMContext):
    keyword = message.text.strip()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, content FROM posts WHERE title ILIKE $1 ORDER BY created_at DESC LIMIT 5",
            f"%{keyword}%"
        )

    if not rows:
        await message.answer("⛔ موردی یافت نشد.")
    else:
        for row in rows:
            summary = (row["content"][:100] + "...") if row["content"] else "—"
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("📖 نمایش کامل خبر", callback_data=f"post_{row['id']}")
            )
            hashtags = await conn.fetch("""
                SELECT h.name FROM post_hashtags ph
                JOIN hashtags h ON ph.hashtag_id=h.id
                WHERE ph.post_id=$1
            """, row["id"])
            for h in hashtags:
                keyboard.add(InlineKeyboardButton(f"#{h['name']}", callback_data=f"tag_{h['name']}"))

            await message.answer(
                f"📰 <b>{row['title']}</b>\n\n"
                f"{summary}",
                reply_markup=keyboard
            )

    await state.finish()

# ======================
# 🔔 دریافت خودکار خبر
# ======================
@dp.message_handler(lambda m: m.text == "🔔 دریافت خودکار خبر")
async def show_subscriptions(message: types.Message):
    async with pool.acquire() as conn:
        hashtags = await conn.fetch("SELECT * FROM hashtags ORDER BY name")

        keyboard = InlineKeyboardMarkup()
        for h in hashtags:
            subscribed = await conn.fetchrow(
                "SELECT 1 FROM subscriptions WHERE user_id=$1 AND hashtag_id=$2",
                message.from_user.id, h["id"]
            )
            status = "✅" if subscribed else "❌"
            keyboard.add(
                InlineKeyboardButton(f"{h['name']} {status}", callback_data=f"toggle_sub_{h['id']}")
            )

    await message.answer("🔔 هشتگ‌هایی که می‌خواهید دنبال کنید رو انتخاب کنید:", reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data.startswith("toggle_sub_"))
async def toggle_subscription(callback_query: types.CallbackQuery):
    hashtag_id = int(callback_query.data.split("_")[2])
    user_id = callback_query.from_user.id

    async with pool.acquire() as conn:
        sub = await conn.fetchrow("SELECT 1 FROM subscriptions WHERE user_id=$1 AND hashtag_id=$2", user_id, hashtag_id)
        if sub:
            await conn.execute("DELETE FROM subscriptions WHERE user_id=$1 AND hashtag_id=$2", user_id, hashtag_id)
        else:
            await conn.execute(
                "INSERT INTO subscriptions (user_id, hashtag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                user_id, hashtag_id
            )

        hashtags = await conn.fetch("SELECT * FROM hashtags ORDER BY name")
        keyboard = InlineKeyboardMarkup()
        for h in hashtags:
            subscribed = await conn.fetchrow(
                "SELECT 1 FROM subscriptions WHERE user_id=$1 AND hashtag_id=$2",
                user_id, h["id"]
            )
            status = "✅" if subscribed else "❌"
            keyboard.add(InlineKeyboardButton(f"{h['name']} {status}", callback_data=f"toggle_sub_{h['id']}"))

    await callback_query.message.edit_reply_markup(reply_markup=keyboard)
    await callback_query.answer("وضعیت بروزرسانی شد ✅")

@dp.callback_query_handler(lambda c: c.data.startswith("order_cat_"))
async def process_order_category(call: types.CallbackQuery):
    category_id = int(call.data.split("_")[2])
    # گرفتن لیست خدمات این دسته
    async with pool.acquire() as conn:
        services = await conn.fetch("SELECT id, title FROM services WHERE category_id=$1", category_id)
    if not services:
        await call.message.edit_text("⛔ خدمتی برای این دسته ثبت نشده.")
        return
    kb = InlineKeyboardMarkup()
    for s in services:
        kb.add(InlineKeyboardButton(s["title"], callback_data=f"order_service_{s['id']}"))
    await call.message.edit_text("📋 یکی از خدمات را انتخاب کنید:", reply_markup=kb)

# ==========================
#  حذف خدمات
# ==========================
@dp.callback_query_handler(lambda c: c.data.startswith("delete_cat_"))
async def process_delete_category(call: types.CallbackQuery):
    category_id = int(call.data.split("_")[2])
    async with pool.acquire() as conn:
        services = await conn.fetch("SELECT id, title FROM services WHERE category_id=$1", category_id)
    if not services:
        await call.message.edit_text("⛔ خدمتی در این دسته وجود ندارد.")
        return
    kb = InlineKeyboardMarkup()
    for s in services:
        kb.add(InlineKeyboardButton(f"❌ {s['title']}", callback_data=f"delete_service_{s['id']}"))
    await call.message.edit_text("🗑 یکی از خدمات را برای حذف انتخاب کنید:", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data.startswith("delete_service_"))
async def process_delete_service(call: types.CallbackQuery):
    service_id = int(call.data.split("_")[2])
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM services WHERE id=$1", service_id)
    await call.answer("✅ خدمت حذف شد", show_alert=True)
    await call.message.edit_text("خدمت با موفقیت حذف شد.", reply_markup=main_menu())


# ==========================
#  مرحله: کاربر میزند ➕ افزودن خدمات (در ریپلای کیبورد)
# ==========================
@dp.message_handler(lambda m: m.text == "➕ افزودن خدمات")
async def cmd_add_service_menu(msg: types.Message):
    # فقط ادمین اجازه داره اضافه کنه
    if msg.from_user.id != ADMIN_ID:
        await msg.answer("⛔ شما دسترسی به این بخش ندارید.")
        return

    kb = await service_categories_keyboard(prefix="add")
    await msg.answer("📂 لطفاً دسته‌بندی موردنظر برای افزودن خدمت را انتخاب کنید:", reply_markup=kb)

# ======================
# ذخیره پست‌های جدید کانال
# ======================
@dp.channel_post_handler(content_types=types.ContentTypes.TEXT)
async def save_channel_post(message: types.Message):
    text = message.text or message.caption or ""
    title = text.split("\n")[0][:100] if text else "بدون عنوان"

    async with pool.acquire() as conn:
        # ذخیره پست
        post = await conn.fetchrow("""
            INSERT INTO posts (message_id, title, content)
            VALUES ($1, $2, $3)
            ON CONFLICT (message_id) DO NOTHING
            RETURNING id
        """, message.message_id, title, text)

        if not post:
            return

        post_id = post["id"]

        # استخراج هشتگ‌ها و ذخیره
        hashtags = [word.strip("#") for word in text.split() if word.startswith("#")]
        for tag in hashtags:
            tag_row = await conn.fetchrow("""
                INSERT INTO hashtags (name) VALUES ($1)
                ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name
                RETURNING id
            """, tag)
            await conn.execute("""
                INSERT INTO post_hashtags (post_id, hashtag_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
            """, post_id, tag_row["id"])


# ==========================
#  دریافت پست ها و هشتگ ها از کانال
# ==========================
@dp.channel_post_handler(content_types=types.ContentTypes.TEXT)
async def handle_channel_post(msg: types.Message):
    async with pool.acquire() as conn:
        # ذخیره پست
        post_id = await conn.fetchval("""
            INSERT INTO posts (message_id, title, content)
            VALUES ($1, $2, $3)
            ON CONFLICT (message_id) DO UPDATE SET title=$2, content=$3
            RETURNING id
        """, msg.message_id, msg.text.split("\n")[0], msg.text)

        # استخراج هشتگ‌ها
        if msg.entities:
            for ent in msg.entities:
                if ent.type == "hashtag":
                    tag = msg.text[ent.offset:ent.offset+ent.length].lstrip("#")
                    ht = await conn.fetchrow("INSERT INTO hashtags(name) VALUES($1) ON CONFLICT(name) DO UPDATE SET name=$1 RETURNING id", tag)
                    await conn.execute("INSERT INTO post_hashtags(post_id, hashtag_id) VALUES($1,$2) ON CONFLICT DO NOTHING", post_id, ht["id"])


# ---------------- راه‌اندازی ----------------
async def on_startup(dispatcher):
    await init_db()
    print("🚀 ربات شروع به کار کرد.")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
