import logging
import asyncpg
import os
import uuid
import json
import csv
import asyncio
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.types import ReplyKeyboardRemove

class OrderForm(StatesGroup):
    waiting_for_documents = State()

class SearchForm(StatesGroup):
    waiting_for_keyword = State()
    
class AdminAddService(StatesGroup):
    waiting_for_title = State()
    waiting_for_docs = State()

class UserStates(StatesGroup):
    waiting_for_post_limit = State()
    waiting_for_tracking_code = State()


add_tool_state = {}
edit_tool_state = {}
user_manage_state = {}
cafenet_manage_state = {}
user_search_state = {}
broadcast_state = {}
cafenet_location_state = {}
cafenet_state = {}
cafenet_page_state = {}
cafenet_filter_state = {}


# ---------------- تنظیمات ----------------
API_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(level=logging.INFO)
ADMIN_ID = 7918162941
ADMINS = [ADMIN_ID]

# ---------------- اتصال بات ----------------
bot = Bot(token=API_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

pool = None  # اتصال دیتابیس

# ---------------- دیتابیس ----------------
async def init_db():
    global pool
    try:
        pool = await asyncpg.create_pool(DATABASE_URL)
    except Exception as e:
        print(f"❌ خطا در ایجاد pool دیتابیس: {e}")
        raise

    try:
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

            # خدمات (اطمینان از ستون documents)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id SERIAL PRIMARY KEY,
                category_id INTEGER REFERENCES service_categories(id) ON DELETE CASCADE,
                title TEXT
            );
            """)
            await conn.execute("""
            ALTER TABLE services
            ADD COLUMN IF NOT EXISTS documents TEXT
            """)

            # orders (یکبار و کامل)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                service_id INTEGER REFERENCES services(id) ON DELETE CASCADE,
                order_code TEXT UNIQUE,
                docs TEXT,
                status TEXT DEFAULT 'new',
                created_at TIMESTAMP DEFAULT now()
            );
            """)

            # تنظیمات کاربر
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                user_id BIGINT PRIMARY KEY,
                post_limit INTEGER DEFAULT 5,
                notifications_enabled BOOLEAN DEFAULT TRUE
                );
            """)

            # جدول های مربوط به پست/هشتگ — ابتدا هشتگ‌ها و پست‌ها
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS hashtags (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id SERIAL PRIMARY KEY,
                message_id BIGINT UNIQUE,
                title TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT now()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS post_hashtags (
                post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
                hashtag_id INTEGER REFERENCES hashtags(id) ON DELETE CASCADE,
                PRIMARY KEY (post_id, hashtag_id)
            );
            """)

            # جدول اشتراک (اکنون که hashtags وجود دارد)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id BIGINT,
                hashtag_id INTEGER REFERENCES hashtags(id) ON DELETE CASCADE,
                PRIMARY KEY (user_id, hashtag_id)
            );
            """)

            # بقیه جداول (provinces, cities, cafenets)
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS provinces (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS cities (
                id SERIAL PRIMARY KEY,
                province_id INTEGER REFERENCES provinces(id) ON DELETE CASCADE,
                name TEXT
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS cafenets (
                id SERIAL PRIMARY KEY,
                province_id INTEGER REFERENCES provinces(id) ON DELETE CASCADE,
                city_id INTEGER REFERENCES cities(id) ON DELETE CASCADE,
                name TEXT,
                address TEXT,
                phone TEXT,
                created_at TIMESTAMP DEFAULT now()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS tools (
                id SERIAL PRIMARY KEY,
                name TEXT,
                message TEXT
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                created_at TIMESTAMP DEFAULT now()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
               id SERIAL PRIMARY KEY,
               user_id BIGINT NOT NULL,
               subject TEXT,
               message TEXT,
               status TEXT DEFAULT 'open', -- open | answered | closed
               admin_reply TEXT,
               created_at TIMESTAMP DEFAULT now(),
               updated_at TIMESTAMP
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS auto_replies (
                id SERIAL PRIMARY KEY,
                trigger TEXT NOT NULL,
                reply TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT now()
            );
            """)

            # *** خطای اصلی در این ناحیه بود ***
            # شما تعریف تکراری جدول tools را داشتید اما گیومه بسته را فراموش کرده بودید.
            # من آن را حذف کردم و خطای سینتکسی برطرف شد.

            # به‌روزرسانی جدول users
            await conn.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE;
            """)
            await conn.execute("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP DEFAULT NOW();
            """)

            # به‌روزرسانی جدول cafenets (ستون‌های موقعیت مکانی و متصدی)
            await conn.execute("""
                ALTER TABLE cafenets
                ADD COLUMN IF NOT EXISTS location_lat DOUBLE PRECISION
            """)

            await conn.execute("""
                ALTER TABLE cafenets
                ADD COLUMN IF NOT EXISTS location_lon DOUBLE PRECISION
            """)

            await conn.execute("""
                ALTER TABLE cafenets
                ADD COLUMN IF NOT EXISTS owner_user_id BIGINT
            """)
            

        print("✅ دیتابیس آماده شد.")
    except Exception as e:
        print(f"❌ خطا در init_db: {e}")
        raise


# ---------------- کیبورد ----------------
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# منوی اصلی
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("📋 سفارش خدمات"))
    kb.add(KeyboardButton("🔍 جستجو اطلاعیه/خبر"))
    kb.add(KeyboardButton("🔔 دریافت خودکار خبر"))
    kb.add(KeyboardButton("🛠 ابزارهای کافی نتی"))
    kb.add(KeyboardButton("🧭 مراجعه حضوری"))
    kb.add(KeyboardButton("⚙️ مدیریت خدمات"))
    kb.add(KeyboardButton("⚙️ تنظیمات"))
    kb.add(KeyboardButton("📘 راهنما"))
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
    
# =========================
# 🧭 مراجعه حضوری
# =========================
@dp.message_handler(lambda m: m.text == "🧭 مراجعه حضوری")
async def visit_in_person(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("📍 جستجوی کافی‌نت نزدیک شما", callback_data="search_cafenet"))
    kb.add(InlineKeyboardButton("➕ ثبت کافی‌نت شما", callback_data="register_cafenet"))
    await message.answer("لطفاً یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "search_cafenet")
async def choose_province_for_search(call: types.CallbackQuery):
    async with pool.acquire() as conn:
        provinces = await conn.fetch("SELECT id, name FROM provinces ORDER BY name")
    kb = InlineKeyboardMarkup(row_width=2)
    for p in provinces:
        kb.add(InlineKeyboardButton(p["name"], callback_data=f"search_province_{p['id']}"))
    await call.message.edit_text("🌍 استان خود را انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("search_province_"))
async def choose_city_for_search(call: types.CallbackQuery):
    province_id = int(call.data.split("_")[2])
    async with pool.acquire() as conn:
        cities = await conn.fetch("SELECT id, name FROM cities WHERE province_id=$1 ORDER BY name", province_id)
    kb = InlineKeyboardMarkup(row_width=2)
    for cty in cities:
        kb.add(InlineKeyboardButton(cty["name"], callback_data=f"search_city_{cty['id']}"))
    await call.message.edit_text("🏙 شهر خود را انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("search_city_"))
async def show_cafenets_in_city(call: types.CallbackQuery):
    city_id = int(call.data.split("_")[2])
    async with pool.acquire() as conn:
        cafenets = await conn.fetch("""
            SELECT name, address, phone FROM cafenets WHERE city_id=$1 ORDER BY name
        """, city_id)

    if not cafenets:
        await call.message.edit_text("⛔ هیچ کافی‌نتی برای این شهر ثبت نشده است.")
        return

    text = "📍 <b>کافی‌نت‌های ثبت‌شده در این شهر:</b>\n\n"
    for c in cafenets:
        text += f"🏠 <b>{c['name']}</b>\n📞 {c['phone']}\n📍 {c['address']}\n\n"

    await call.message.edit_text(text, parse_mode="HTML")

# ======================
# ثبت کافی‌نت
# ======================

class RegisterCafeNet(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()
    waiting_for_phone = State()
    waiting_for_location = State()
    finalize = State()

@dp.callback_query_handler(lambda c: c.data == "register_cafenet")
async def choose_province_for_register(call: types.CallbackQuery):
    async with pool.acquire() as conn:
        provinces = await conn.fetch("SELECT id, name FROM provinces ORDER BY name")

    kb = InlineKeyboardMarkup(row_width=2)
    for p in provinces:
        kb.add(InlineKeyboardButton(p["name"], callback_data=f"reg_province_{p['id']}"))

    await call.message.edit_text("📍 لطفاً استان خود را انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("reg_province_"))
async def choose_city_for_register(call: types.CallbackQuery):
    province_id = int(call.data.split("_")[2])

    async with pool.acquire() as conn:
        cities = await conn.fetch("SELECT id, name FROM cities WHERE province_id=$1 ORDER BY name", province_id)

    kb = InlineKeyboardMarkup(row_width=2)
    for cty in cities:
        kb.add(InlineKeyboardButton(cty["name"], callback_data=f"reg_city_{province_id}_{cty['id']}"))

    await call.message.edit_text("🏙 شهر خود را انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("reg_city_"))
async def ask_cafenet_name(call: types.CallbackQuery, state: FSMContext):
    _, _, province_id, city_id = call.data.split("_")

    await state.update_data(
        province_id=int(province_id),
        city_id=int(city_id)
    )

    await RegisterCafeNet.waiting_for_name.set()
    await call.message.answer("✍️ لطفاً نام کافی‌نت را وارد کنید:")

@dp.message_handler(state=RegisterCafeNet.waiting_for_name)
async def get_cafenet_name(msg: types.Message, state: FSMContext):
    await state.update_data(name=msg.text)

    await RegisterCafeNet.waiting_for_address.set()
    await msg.answer("📍 لطفاً آدرس کامل کافی‌نت را ارسال کنید:")

@dp.message_handler(state=RegisterCafeNet.waiting_for_address)
async def get_cafenet_address(msg: types.Message, state: FSMContext):
    await state.update_data(address=msg.text)

    await RegisterCafeNet.waiting_for_phone.set()
    await msg.answer("📞 لطفاً شماره تماس کافی‌نت را ارسال کنید:")

@dp.message_handler(state=RegisterCafeNet.waiting_for_phone)
async def ask_cafenet_location(msg: types.Message, state: FSMContext):
    await state.update_data(phone=msg.text)

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("📍 ارسال موقعیت مکانی", request_location=True))
    kb.add("⏭ بدون موقعیت")

    await RegisterCafeNet.waiting_for_location.set()
    await msg.answer(
        "📍 لطفاً موقعیت مکانی کافی‌نت را ارسال کنید:\n"
        "یا گزینه «⏭ بدون موقعیت» را انتخاب کنید.",
        reply_markup=kb
    )

@dp.message_handler(content_types=types.ContentType.LOCATION, state=RegisterCafeNet.waiting_for_location)
async def save_location(msg: types.Message, state: FSMContext):
    await state.update_data(
        location_lat=msg.location.latitude,
        location_lon=msg.location.longitude
    )

    await RegisterCafeNet.finalize.set()

    await msg.answer("✅ موقعیت ثبت شد.", reply_markup=ReplyKeyboardRemove())
    await finalize_cafenet_registration(msg, state)

@dp.message_handler(lambda m: m.text == "⏭ بدون موقعیت", state=RegisterCafeNet.waiting_for_location)
async def skip_location(msg: types.Message, state: FSMContext):
    await state.update_data(location_lat=None, location_lon=None)

    await RegisterCafeNet.finalize.set()

    await msg.answer("🔸 بدون موقعیت ادامه داده شد.", reply_markup=ReplyKeyboardRemove())
    await finalize_cafenet_registration(msg, state)

async def finalize_cafenet_registration(msg: types.Message, state: FSMContext):
    data = await state.get_data()

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO cafenets
            (name, province_id, city_id, address, phone, owner_user_id, location_lat, location_lon)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
            data["name"],
            data["province_id"],
            data["city_id"],
            data["address"],
            data["phone"],
            msg.from_user.id,
            data["location_lat"],
            data["location_lon"]
        )

    await msg.answer("🎉 کافی‌نت با موفقیت ثبت شد.", reply_markup=main_menu())
    await state.finish()


#===============================
# رفتن به زیرمنوی سفارشات
@dp.message_handler(lambda m: m.text == "📋 سفارش خدمات")
async def show_orders_menu(message: types.Message):
    await message.answer("📋 لطفاً یکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=orders_menu())

# ===== سفارش خدمات =====

# مرحله ۱: نمایش دسته‌بندی‌ها
@dp.message_handler(lambda m: m.text == "➕ ثبت سفارش")
async def add_order(message: types.Message):
    async with pool.acquire() as conn:
        cats = await conn.fetch("SELECT id, name FROM service_categories ORDER BY id")

    if not cats:
        await message.answer("⛔ هنوز هیچ دسته‌بندی ثبت نشده.")
        return

    kb = InlineKeyboardMarkup(row_width=1)
    for c in cats:
        kb.add(InlineKeyboardButton(c["name"], callback_data=f"order_cat_{c['id']}"))

    await message.answer("📂 لطفاً یک دسته‌بندی انتخاب کنید:", reply_markup=kb)


# مرحله ۲: نمایش خدمات یک دسته
@dp.callback_query_handler(lambda c: c.data.startswith("order_cat_"))
async def process_order_category(call: types.CallbackQuery):
    cat_id = int(call.data.split("_")[2])

    async with pool.acquire() as conn:
        services = await conn.fetch("SELECT id, title, documents FROM services WHERE category_id=$1", cat_id)

    if not services:
        await call.message.answer("⛔ برای این دسته خدمتی ثبت نشده.")
        return

    kb = InlineKeyboardMarkup(row_width=1)
    for s in services:
        kb.add(InlineKeyboardButton(s["title"], callback_data=f"order_service_{s['id']}"))

    await call.message.answer("🔎 یکی از خدمات زیر را انتخاب کنید:", reply_markup=kb)


# مرحله ۳: نمایش توضیحات و درخواست مدارک
@dp.callback_query_handler(lambda c: c.data.startswith("order_service_"))
async def start_order_form(call: types.CallbackQuery, state: FSMContext):
    service_id = int(call.data.split("_")[2])

    async with pool.acquire() as conn:
        service = await conn.fetchrow("SELECT id, title, documents FROM services WHERE id=$1", service_id)

    if not service:
        await call.message.answer("⛔ این خدمت یافت نشد.")
        return

    await state.update_data(service_id=service_id, docs=[], msg_ids=[])

    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("✅ ثبت سفارش", callback_data="submit_order"))
    await call.message.answer(
        f"📌 <b>{service['title']}</b>\n\n"
        f"📝 مدارک لازم: {service['documents'] or '—'}\n\n"
        "لطفاً مدارک خود را ارسال کنید (متن/عکس/فایل).\n"
        "بعد روی دکمه زیر بزنید 👇",
        reply_markup=kb
    )
    await OrderForm.waiting_for_documents.set()


# مرحله ۴: دریافت مدارک
@dp.message_handler(state=OrderForm.waiting_for_documents, content_types=types.ContentTypes.ANY)
async def collect_documents(message: types.Message, state: FSMContext):
    data = await state.get_data()
    docs = data.get("docs", [])
    msg_ids = data.get("msg_ids", [])

    if message.text:
        docs.append(message.text)
    elif message.photo:
        docs.append("📷 عکس ارسال شد")
    elif message.document:
        docs.append(f"📄 فایل: {message.document.file_name}")
    else:
        docs.append("📝 مدرک ارسال شد")

    msg_ids.append(message.message_id)

    await state.update_data(docs=docs, msg_ids=msg_ids)
    await message.answer("✅ مدرک ثبت شد. می‌توانید مدارک بیشتری بفرستید یا دکمه «ثبت سفارش» را بزنید.")


# مرحله ۵: ثبت سفارش نهایی
@dp.callback_query_handler(lambda c: c.data == "submit_order", state=OrderForm.waiting_for_documents)
async def submit_order(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    service_id = data["service_id"]
    docs = "\n".join(data["docs"]) if data["docs"] else "⛔ بدون مدرک"
    msg_ids = data.get("msg_ids", [])

    order_code = str(uuid.uuid4())[:8]

    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO orders (user_id, service_id, order_code, docs, status)
            VALUES ($1, $2, $3, $4, 'new')
        """, call.from_user.id, service_id, order_code, docs)

        service = await conn.fetchrow("SELECT title FROM services WHERE id=$1", service_id)

    # پیام تأیید به کاربر
    await call.message.answer(
        f"✅ سفارش شما برای <b>{service['title']}</b> ثبت شد.\n"
        f"📎 کد رهگیری: <code>{order_code}</code>",
        reply_markup=main_menu()
    )

    # آماده‌سازی اطلاعات مشتری برای منشن و گزارش به ادمین
    user = call.from_user
    full_name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    mention = f"<a href='tg://user?id={user.id}'>{full_name or user.username or user.id}</a>"
    username = f"@{user.username}" if user.username else "—"

    # پیام به مدیر
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("✅ تکمیل سفارش", callback_data=f"complete_{order_code}"))
    await bot.send_message(
        ADMIN_ID,
        f"📢 <b>سفارش جدید</b>\n\n"
        f"👤 مشتری: {mention}\n"
        f"🆔 آیدی عددی: <code>{user.id}</code>\n"
        f"🔗 نام کاربری: {username}\n\n"
        f"📌 خدمت: {service['title']}\n"
        f"📎 کد رهگیری: <code>{order_code}</code>\n\n"
        f"📝 مدارک ارسالی در ادامه 👇",
        reply_markup=kb
    )

    # فوروارد مدارک به ادمین
    for mid in msg_ids:
        try:
            await bot.forward_message(ADMIN_ID, call.from_user.id, mid)
        except:
            pass

    await state.finish()
    await call.answer("✅ سفارش ثبت شد")



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
    kb.add(KeyboardButton("➕ افزودن ابزار"))
    kb.add(KeyboardButton("👤 مدیریت کاربران"))
    kb.add(KeyboardButton("📨 ارسال پیام انبوه"))
    kb.add(KeyboardButton("🏢 مدیریت کافی‌نت"))
    kb.add(KeyboardButton("⬅️ بازگشت به منوی اصلی"))

    await message.answer("⚙️ بخش مدیریت خدمات", reply_markup=kb)
    

def admin_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ افزودن خدمات")
    kb.add("❌ حذف خدمات")
    kb.add("➕ افزودن ابزار")
    kb.add("👤 مدیریت کاربران")
    kb.add("📨 ارسال پیام انبوه")
    kb.add("🏢 مدیریت کافی‌نت")
    kb.add("⬅️ بازگشت به منوی اصلی")
    return kb


def admin_services_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ افزودن خدمات", "❌ حذف خدمات")
    kb.add("➕ افزودن ابزار", "👤 مدیریت کاربران")
    kb.add("🏢 مدیریت کافی‌نت", "📨 ارسال پیام انبوه")
    kb.add("⬅️ بازگشت به منوی اصلی")
    return kb

@dp.message_handler(lambda m: m.text == "⬅️ بازگشت به مدیریت خدمات")
async def back_to_admin_services(message: types.Message):
    await message.answer("به بخش مدیریت خدمات برگشتی.", reply_markup=admin_services_menu())



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
        "به ربات  مجازی خوش اومدی.",
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



# ======================
# افزودن ابزار
# =======================
@dp.message_handler(lambda m: m.text == "➕ افزودن ابزار")
async def start_add_tool(msg: types.Message):
    add_tool_state[msg.from_user.id] = {"step": 1}
    await msg.answer("🛠 نام ابزار را ارسال کنید:", reply_markup=ReplyKeyboardRemove())


@dp.message_handler(lambda m: m.from_user.id in add_tool_state and add_tool_state[m.from_user.id]["step"] == 1)
async def get_tool_name(msg: types.Message):
    add_tool_state[msg.from_user.id]["name"] = msg.text
    add_tool_state[msg.from_user.id]["step"] = 2
    await msg.answer("✏️ پیام مربوط به این ابزار را ارسال کنید:")


@dp.message_handler(lambda m: m.from_user.id in add_tool_state and add_tool_state[m.from_user.id]["step"] == 2)
async def get_tool_message(msg: types.Message):
    add_tool_state[msg.from_user.id]["message"] = msg.text
    add_tool_state[msg.from_user.id]["step"] = 3

    name = add_tool_state[msg.from_user.id]["name"]
    message = add_tool_state[msg.from_user.id]["message"]

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ تأیید", callback_data="confirm_add_tool"))
    kb.add(InlineKeyboardButton("❌ انصراف", callback_data="cancel_add_tool"))

    await msg.answer(
        f"نام ابزار: {name}\n"
        f"پیام ابزار:\n{message}\n\n"
        "تأیید می‌کنی؟",
        reply_markup=kb
    )

@dp.callback_query_handler(lambda c: c.data == "confirm_add_tool")
async def confirm_tool(call: types.CallbackQuery):
    user_id = call.from_user.id
    data = add_tool_state.get(user_id)

    if not data:
        return await call.answer("خطا! داده‌ای یافت نشد.", show_alert=True)

    name = data["name"]
    message = data["message"]

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tools (name, message) VALUES ($1, $2)",
            name, message
        )

    add_tool_state.pop(user_id, None)

    await call.message.edit_text("✅ ابزار با موفقیت اضافه شد.")
    await call.message.answer("به منو مدیریت برگشتی.", reply_markup=admin_menu())

@dp.callback_query_handler(lambda c: c.data == "cancel_add_tool")
async def cancel_tool(call: types.CallbackQuery):
    add_tool_state.pop(call.from_user.id, None)
    await call.message.edit_text("❌ افزودن ابزار لغو شد.")
    await call.message.answer("به منوی مدیریت برگشتی.", reply_markup=admin_menu())

# ==========================
# 🛠 نمایش ابزارهای کافی نتی
# ==========================
@dp.message_handler(lambda m: m.text == "🛠 ابزارهای کافی نتی")
async def show_tools(msg: types.Message):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name FROM tools ORDER BY id DESC")

    if not rows:
        return await msg.answer("هیچ ابزاری ثبت نشده است.", reply_markup=main_menu())

    kb = InlineKeyboardMarkup()
    for row in rows:
        kb.add(InlineKeyboardButton(row["name"], callback_data=f"tool_{row['id']}"))

    kb.add(InlineKeyboardButton("🔙 برگشت", callback_data="back_to_main"))

    await msg.answer("🛠 فهرست ابزارها:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("tool_"))
async def show_tool_message(call: types.CallbackQuery):
    tool_id = int(call.data.split("_")[1])

    async with pool.acquire() as conn:
        tool = await conn.fetchrow("SELECT name, message FROM tools WHERE id=$1", tool_id)

    kb = InlineKeyboardMarkup()

    # اگر مدیر است → گزینه‌های مدیریت نیز نمایش داده شود
    if call.from_user.id in ADMINS:
        kb.add(InlineKeyboardButton("✏️ ویرایش ابزار", callback_data=f"edit_tool_{tool_id}"))
        kb.add(InlineKeyboardButton("🗑 حذف ابزار", callback_data=f"delete_tool_{tool_id}"))

    # گزینه برگشت برای همه
    kb.add(InlineKeyboardButton("🔙 برگشت", callback_data="back_to_tools"))

    await call.message.edit_text(
        f"🛠 <b>{tool['name']}</b>\n\n{tool['message']}",
        parse_mode="HTML",
        reply_markup=kb
    )

@dp.callback_query_handler(lambda c: c.data.startswith("edit_tool_"))
async def edit_tool_start(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        return await call.answer("⛔ فقط مدیر می‌تواند ابزار را ویرایش کند.", show_alert=True)

@dp.callback_query_handler(lambda c: c.data.startswith("delete_tool_"))
async def delete_tool_confirm(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        return await call.answer("⛔ فقط مدیر می‌تواند ابزار را حذف کند.", show_alert=True)

@dp.callback_query_handler(lambda c: c.data.startswith("delete_yes_"))
async def delete_tool(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:
        return await call.answer("⛔ فقط مدیر می‌تواند حذف کند.", show_alert=True)


@dp.callback_query_handler(lambda c: c.data == "back_to_tools")
async def back_to_tools(call: types.CallbackQuery):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name FROM tools ORDER BY id DESC")

    kb = InlineKeyboardMarkup()
    for row in rows:
        kb.add(InlineKeyboardButton(row["name"], callback_data=f"tool_{row['id']}"))
    kb.add(InlineKeyboardButton("🔙 برگشت", callback_data="back_to_main"))

    await call.message.edit_text("🛠 فهرست ابزارها:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "back_to_main")
async def back_to_main(call: types.CallbackQuery):
    await call.message.edit_text("منو اصلی:")
    await call.message.answer("👇 انتخاب کن:", reply_markup=main_menu())

# ===============================
# ویرایش ابزار
# ===============================
@dp.callback_query_handler(lambda c: c.data.startswith("edit_tool_"))
async def edit_tool_start(call: types.CallbackQuery):
    tool_id = int(call.data.split("_")[2])
    edit_tool_state[call.from_user.id] = {"step": 1, "tool_id": tool_id}

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📝 ویرایش نام", callback_data=f"edit_name_{tool_id}"))
    kb.add(InlineKeyboardButton("💬 ویرایش پیام", callback_data=f"edit_msg_{tool_id}"))
    kb.add(InlineKeyboardButton("🔙 برگشت", callback_data=f"tool_{tool_id}"))

    await call.message.edit_text(
        "کدام بخش ابزار را می‌خواهی ویرایش کنی؟",
        reply_markup=kb
    )

@dp.callback_query_handler(lambda c: c.data.startswith("edit_name_"))
async def edit_name_request(call: types.CallbackQuery):
    tool_id = int(call.data.split("_")[2])

    edit_tool_state[call.from_user.id] = {"step": "name", "tool_id": tool_id}

    await call.message.edit_text("📝 نام جدید ابزار را ارسال کنید:")

@dp.message_handler(lambda m: m.from_user.id in edit_tool_state and edit_tool_state[m.from_user.id]["step"] == "name")
async def edit_name_save(msg: types.Message):
    data = edit_tool_state[msg.from_user.id]
    tool_id = data["tool_id"]

    async with pool.acquire() as conn:
        await conn.execute("UPDATE tools SET name=$1 WHERE id=$2", msg.text, tool_id)

    edit_tool_state.pop(msg.from_user.id, None)

    await msg.answer("✅ نام ابزار با موفقیت به‌روزرسانی شد.")

@dp.callback_query_handler(lambda c: c.data.startswith("edit_msg_"))
async def edit_message_request(call: types.CallbackQuery):
    tool_id = int(call.data.split("_")[2])

    edit_tool_state[call.from_user.id] = {"step": "message", "tool_id": tool_id}

    await call.message.edit_text("💬 پیام جدید ابزار را ارسال کنید:")

@dp.message_handler(lambda m: m.from_user.id in edit_tool_state and edit_tool_state[m.from_user.id]["step"] == "message")
async def edit_message_save(msg: types.Message):
    data = edit_tool_state[msg.from_user.id]
    tool_id = data["tool_id"]

    async with pool.acquire() as conn:
        await conn.execute("UPDATE tools SET message=$1 WHERE id=$2", msg.text, tool_id)

    edit_tool_state.pop(msg.from_user.id, None)

    await msg.answer("✅ پیام ابزار با موفقیت ویرایش شد.")

# ===============================
# حذف ابزار
# ===============================
@dp.callback_query_handler(lambda c: c.data.startswith("delete_tool_"))
async def delete_tool_confirm(call: types.CallbackQuery):
    tool_id = int(call.data.split("_")[2])

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🗑 حذف نهایی", callback_data=f"delete_yes_{tool_id}"))
    kb.add(InlineKeyboardButton("❌ لغو", callback_data=f"tool_{tool_id}"))

    await call.message.edit_text(
        "⚠️ آیا از حذف این ابزار مطمئن هستی؟",
        reply_markup=kb
    )

@dp.callback_query_handler(lambda c: c.data.startswith("delete_yes_"))
async def delete_tool(call: types.CallbackQuery):
    tool_id = int(call.data.split("_")[2])

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM tools WHERE id=$1", tool_id)

    await call.message.edit_text("🗑 ابزار با موفقیت حذف شد.")



# ======================
# مدیریت کاربران
# =======================
@dp.message_handler(lambda m: m.text == "👤 مدیریت کاربران")
async def manage_users(message: types.Message):
    if message.from_user.id not in ADMINS:
        return await message.answer("⛔ اجازه دسترسی ندارید.")

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("📅 کاربران امروز"))
    kb.add(KeyboardButton("📆 کاربران هفته"))
    kb.add(KeyboardButton("🗓 کاربران ماه"))
    kb.add(KeyboardButton("⏱ آخرین فعالیت کاربران"))
    kb.add(KeyboardButton("🔍 جستجوی کاربر"))
    kb.add(KeyboardButton("📊 تعداد کل کاربران"))
    kb.add(KeyboardButton("⬅️ بازگشت به مدیریت خدمات"))

    await message.answer("👤 مدیریت کاربران:", reply_markup=kb)

def admin_users_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📅 کاربران امروز", "📆 کاربران هفته")
    kb.add("🗓 کاربران ماه", "⏱ آخرین فعالیت کاربران")
    kb.add("📊 تعداد کل کاربران")
    kb.add("⬅️ بازگشت به مدیریت خدمات")
    return kb

def admin_cafenet_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ افزودن کافی‌نت")
    kb.add("📋 لیست کافی‌نت‌ها")
    kb.add("⬅️ بازگشت به مدیریت خدمات")
    return kb


async def fetch_users(filter_type):
    async with pool.acquire() as conn:
        if filter_type == "today":
            return await conn.fetch("SELECT user_id FROM users WHERE created_at::date = CURRENT_DATE")
        
        elif filter_type == "week":
            return await conn.fetch("""
                SELECT user_id FROM users 
                WHERE created_at >= NOW() - INTERVAL '7 days'
            """)
        
        elif filter_type == "month":
            return await conn.fetch("""
                SELECT user_id FROM users 
                WHERE created_at >= NOW() - INTERVAL '30 days'
            """)

@dp.callback_query_handler(lambda c: c.data in ["users_today", "users_week", "users_month"])
async def show_filtered_users(call: types.CallbackQuery):
    filter_map = {
        "users_today": "today",
        "users_week": "week",
        "users_month": "month"
    }

    filter_type = filter_map[call.data]
    rows = await fetch_users(filter_type)

    if not rows:
        return await call.message.edit_text("هیچ کاربری پیدا نشد.", reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("🔙 بازگشت", callback_data="user_mgmt_back")
        ))

    text = "👥 کاربران:\n\n"
    for r in rows:
        text += f"• <code>{r['user_id']}</code>\n"

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔎 مدیریت کاربر", callback_data=f"manage_user_select"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="user_mgmt_back"))

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

user_manage_state = {}

@dp.callback_query_handler(lambda c: c.data == "manage_user_select")
async def ask_user_id(call: types.CallbackQuery):
    user_manage_state[call.from_user.id] = "awaiting_user_id"
    await call.message.edit_text("🔎 آیدی عددی کاربر را ارسال کنید:")

@dp.message_handler(lambda m: user_manage_state.get(m.from_user.id) == "awaiting_user_id")
async def show_user_info(msg: types.Message):
    user_manage_state.pop(msg.from_user.id, None)
    
    try:
        uid = int(msg.text)
    except:
        return await msg.answer("❌ آیدی معتبر نیست.")

    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", uid)

        if not user:
            return await msg.answer("❌ کاربر پیدا نشد.")

        hashtags = await conn.fetch("""
            SELECT h.name FROM subscriptions s 
            JOIN hashtags h ON h.id = s.hashtag_id 
            WHERE s.user_id=$1
        """, uid)

        orders = await conn.fetch("""
            SELECT id FROM orders WHERE user_id=$1 AND status != 'done'
        """, uid)

        cafenet = await conn.fetchrow("""
            SELECT name FROM cafenets WHERE id =
              (SELECT cafenet_id FROM user_settings WHERE user_id=$1)
        """, uid)

    hashtag_list = ", ".join([h["name"] for h in hashtags]) if hashtags else "ندارد"
    order_list = ", ".join([str(o["id"]) for o in orders]) if orders else "ندارد"
    cafenet_name = cafenet["name"] if cafenet else "ثبت نشده"

    text = (
        f"👤 <b>مشخصات کاربر</b>\n\n"
        f"🆔 آیدی عددی: <code>{uid}</code>\n"
        f"👤 نام: {user['first_name']}\n"
        f"🔗 یوزرنیم: @{user['username'] if user['username'] else 'ندارد'}\n"
        f"📅 تاریخ عضویت: {user['created_at']}\n"
        f"🏷 هشتگ‌های فعال: {hashtag_list}\n"
        f"📦 سفارش‌های فعال: {order_list}\n"
        f"🏢 کافی‌نت ثبت‌شده: {cafenet_name}"
    )

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🗑 حذف کاربر", callback_data=f"del_user_{uid}"))
    kb.add(InlineKeyboardButton("🚫 بلاک کاربر", callback_data=f"block_user_{uid}"))
    kb.add(InlineKeyboardButton("♻️ آن‌بلاک کاربر", callback_data=f"unblock_user_{uid}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="user_mgmt_back"))

    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("del_user_"))
async def confirm_delete_user(call: types.CallbackQuery):
    uid = int(call.data.replace("del_user_", ""))

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🗑 حذف نهایی", callback_data=f"del_user_yes_{uid}"))
    kb.add(InlineKeyboardButton("❌ انصراف", callback_data="user_mgmt_back"))

    await call.message.edit_text("⚠️ آیا از حذف کاربر مطمئنی؟", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("del_user_yes_"))
async def delete_user(call: types.CallbackQuery):
    uid = int(call.data.replace("del_user_yes_", ""))

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM users WHERE user_id=$1", uid)
        await conn.execute("DELETE FROM subscriptions WHERE user_id=$1", uid)
        await conn.execute("DELETE FROM user_settings WHERE user_id=$1", uid)
        await conn.execute("DELETE FROM orders WHERE user_id=$1", uid)

    await call.message.edit_text("🗑 کاربر حذف شد.")

@dp.callback_query_handler(lambda c: c.data.startswith("block_user_"))
async def block_user(call: types.CallbackQuery):
    uid = int(call.data.replace("block_user_", ""))

    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_blocked=TRUE WHERE user_id=$1", uid)

    await call.message.edit_text("🚫 کاربر با موفقیت بلاک شد.")

@dp.callback_query_handler(lambda c: c.data.startswith("unblock_user_"))
async def unblock_user(call: types.CallbackQuery):
    uid = int(call.data.replace("unblock_user_", ""))

    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_blocked=FALSE WHERE user_id=$1", uid)

    await call.message.edit_text("♻️ کاربر با موفقیت آزاد شد.")



@dp.callback_query_handler(lambda c: c.data == "user_mgmt_back")
async def user_mgmt_back(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📅 کاربران امروز", callback_data="users_today"))
    kb.add(InlineKeyboardButton("📆 کاربران هفته", callback_data="users_week"))
    kb.add(InlineKeyboardButton("🗓 کاربران ماه", callback_data="users_month"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_admin"))

    await call.message.edit_text("یک فیلتر انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "users_count")
async def users_count(call: types.CallbackQuery):
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM users")

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="user_mgmt_back"))

    await call.message.edit_text(
        f"📊 تعداد کل کاربران ثبت‌شده:\n\n<b>{count} نفر</b>",
        parse_mode="HTML",
        reply_markup=kb
    )

user_search_state = {}

@dp.callback_query_handler(lambda c: c.data == "users_search")
async def user_search_start(call: types.CallbackQuery):
    user_search_state[call.from_user.id] = True
    await call.message.edit_text("🔍 نام یا یوزرنیم کاربر را وارد کنید:")

@dp.message_handler(lambda m: user_search_state.get(m.from_user.id))
async def user_search_result(msg: types.Message):
    term = msg.text.strip()
    user_search_state.pop(msg.from_user.id, None)

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id, first_name, username
            FROM users
            WHERE first_name ILIKE $1 OR username ILIKE $1
        """, f"%{term}%")

    if not rows:
        return await msg.answer("❌ هیچ کاربری با این مشخصات یافت نشد.")

    text = "🔍 نتایج جستجو:\n\n"
    for r in rows:
        text += f"👤 {r['first_name'] or ''} | @{r['username'] or '---'}\n"
        text += f"🆔 <code>{r['user_id']}</code>\n\n"

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔎 مدیریت کاربر", callback_data="manage_user_select"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="user_mgmt_back"))

    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "users_by_province")
async def users_by_province(call: types.CallbackQuery):
    async with pool.acquire() as conn:
        provinces = await conn.fetch("SELECT id, name FROM provinces ORDER BY name")

    kb = InlineKeyboardMarkup()
    for p in provinces:
        kb.add(InlineKeyboardButton(p["name"], callback_data=f"userprov_{p['id']}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="user_mgmt_back"))

    await call.message.edit_text("🗂 استان مورد نظر را انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("userprov_"))
async def users_by_province_list(call: types.CallbackQuery):
    prov_id = int(call.data.split("_")[1])

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id
            FROM users u
            JOIN user_settings us ON us.user_id = u.user_id
            JOIN cafenets c ON c.id = us.cafenet_id
            WHERE c.province_id = $1
        """, prov_id)

    if not rows:
        return await call.message.edit_text("❌ هیچ کاربری در این استان ثبت نشده.")

    text = "👥 کاربران این استان:\n\n"
    for r in rows:
        text += f"• <code>{r['user_id']}</code>\n"

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔎 مدیریت کاربر", callback_data="manage_user_select"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="user_mgmt_back"))

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "user_mgmt_back")
async def user_mgmt_back(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📅 کاربران امروز", callback_data="users_today"))
    kb.add(InlineKeyboardButton("📆 کاربران هفته", callback_data="users_week"))
    kb.add(InlineKeyboardButton("🗓 کاربران ماه", callback_data="users_month"))
    kb.add(InlineKeyboardButton("📊 تعداد کل کاربران", callback_data="users_count"))
    kb.add(InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="users_search"))
    kb.add(InlineKeyboardButton("🗂 کاربران بر اساس استان", callback_data="users_by_province"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_admin"))

    await call.message.edit_text("یک فیلتر انتخاب کنید:", reply_markup=kb)

broadcast_state = {}


# ==============================
#  مدیریت کاربران - آمار
# ==============================

@dp.message_handler(lambda m: m.text == "📅 کاربران امروز")
async def users_today(message: types.Message):
    async with pool.acquire() as conn:
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM users 
            WHERE created_at::date = CURRENT_DATE
        """)
    await message.answer(f"📅 تعداد کاربران امروز: {count}")


@dp.message_handler(lambda m: m.text == "📆 کاربران هفته")
async def users_week(message: types.Message):
    async with pool.acquire() as conn:
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM users 
            WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
        """)
    await message.answer(f"📆 تعداد کاربران هفته: {count}")


@dp.message_handler(lambda m: m.text == "🗓 کاربران ماه")
async def users_month(message: types.Message):
    async with pool.acquire() as conn:
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM users 
            WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
        """)
    await message.answer(f"🗓 تعداد کاربران ماه: {count}")


@dp.message_handler(lambda m: m.text == "⏱ آخرین فعالیت کاربران")
async def last_seen_users(message: types.Message):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id, last_seen FROM users 
            ORDER BY last_seen DESC 
            LIMIT 20
        """)
    txt = "⏱ آخرین فعالیت 20 کاربر اخیر:\n\n"
    for r in rows:
        txt += f"👤 {r['user_id']} — {r['last_seen']}\n"
    await message.answer(txt)


@dp.message_handler(lambda m: m.text == "📊 تعداد کل کاربران")
async def total_users(message: types.Message):
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM users")
    await message.answer(f"📊 تعداد کل کاربران: {count}")


@dp.message_handler(lambda m: m.text == "🔍 جستجوی کاربر")
async def search_user_start(message: types.Message):
    await message.answer("🔍 لطفاً آیدی عددی کاربر را وارد کنید:")
    user_states[message.from_user.id] = "search_user"


@dp.message_handler(lambda m: user_states.get(m.from_user.id) == "search_user")
async def search_user_process(message: types.Message):
    uid = message.text.strip()

    if not uid.isdigit():
        return await message.answer("❌ آیدی باید فقط عدد باشد.")

    uid = int(uid)

    async with pool.acquire() as conn:
        user = await conn.fetchrow("""
            SELECT * FROM users WHERE user_id=$1
        """, uid)

    if not user:
        await message.answer("❌ کاربری با این مشخصات پیدا نشد.")
    else:
        await message.answer(f"👤 کاربر پیدا شد:\n\n"
                             f"ID: {user['user_id']}\n"
                             f"نام: {user['first_name']}\n"
                             f"نام‌کاربری: @{user['username']}\n"
                             f"آخرین فعالیت: {user['last_seen']}")

    user_states.pop(message.from_user.id, None)


# ===================================
@dp.message_handler(lambda m: m.text == "⬅️ بازگشت به مدیریت کافی‌نت")
async def back_to_cafenet_menu(message: types.Message):
    await message.answer("🏢 مدیریت کافی‌نت", reply_markup=admin_cafenet_menu())

@dp.message_handler(lambda m: m.text == "⬅️ بازگشت به مدیریت خدمات")
async def back_to_services(message: types.Message):
    await message.answer("⚙️ مدیریت خدمات", reply_markup=admin_services_menu())


@dp.message_handler(lambda m: m.text == "📨 ارسال پیام انبوه")
async def broadcast_start(message: types.Message):
    if message.from_user.id not in ADMINS:
        return await message.answer("⛔ اجازه دسترسی ندارید.")

    broadcast_state[message.from_user.id] = True
    await message.answer("📨 لطفاً پیام موردنظر برای ارسال انبوه را ارسال کنید:")

@dp.message_handler(lambda m: broadcast_state.get(m.from_user.id))
async def broadcast_send(message: types.Message):
    text = message.text
    del broadcast_state[message.from_user.id]

    async with pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users WHERE is_blocked=FALSE")

    sent = 0
    failed = 0

    for u in users:
        try:
            await bot.send_message(u["user_id"], text)
            await asyncio.sleep(0.05)
            sent += 1
        except:
            failed += 1

    await message.answer(f"✔️ ارسال موفق: {sent}\n❌ ارسال ناموفق: {failed}")


@dp.callback_query_handler(lambda c: c.data == "users_last_seen")
async def users_last_seen(call: types.CallbackQuery):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id, first_name, username, last_seen
            FROM users
            ORDER BY last_seen DESC
            LIMIT 20
        """)

    if not rows:
        return await call.message.edit_text("هیچ کاربری یافت نشد.")

    text = "⏱ <b>آخرین فعالیت کاربران:</b>\n\n"
    for r in rows:
        text += (
            f"👤 {r['first_name']} | @{r['username'] or '---'}\n"
            f"🆔 <code>{r['user_id']}</code>\n"
            f"📅 {r['last_seen']}\n\n"
        )

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔎 مدیریت کاربر", callback_data="manage_user_select"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="user_mgmt_back"))

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# ======================
# مدیریت کافی‌نت
# =======================
@dp.message_handler(lambda m: m.text == "🏢 مدیریت کافی‌نت")
async def manage_cafenet(message: types.Message):
    if message.from_user.id not in ADMINS:
        return await message.answer("⛔ اجازه دسترسی ندارید.")

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("📋 نمایش همه کافی‌نت‌ها"))
    kb.add(KeyboardButton("🌍 فیلتر بر اساس استان"))
    kb.add(KeyboardButton("🏙 فیلتر بر اساس شهر"))
    kb.add(KeyboardButton("🔍 جستجو با نام"))
    kb.add(KeyboardButton("⬅️ بازگشت به مدیریت خدمات"))

    await message.answer("🏢 مدیریت کافی‌نت‌ها:", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "🌍 فیلتر بر اساس استان")
async def filter_by_province(message: types.Message):
    cafenet_filter_state[message.from_user.id] = "province"

    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name FROM provinces ORDER BY name")

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    for p in rows:
        kb.add(f"{p['id']} - {p['name']}")

    kb.add("⬅️ بازگشت")

    await message.answer("🌍 استان موردنظر را انتخاب کنید:", reply_markup=kb)


@dp.message_handler(lambda m: " - " in m.text and cafenet_filter_state.get(m.from_user.id) == "province")
async def show_by_province(message: types.Message):
    prov_id = int(message.text.split(" - ")[0])
    del cafenet_filter_state[message.from_user.id]

    async with pool.acquire() as conn:
        nets = await conn.fetch("""
            SELECT id, name FROM cafenets WHERE province_id=$1
        """, prov_id)

    if not nets:
        return await message.answer("❌ هیچ کافی‌نتی در این استان نیست.")

    text = f"🌍 کافی‌نت‌های این استان:\n\n"
    for n in nets:
        text += f"• {n['name']} (ID: {n['id']})\n"

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔎 مدیریت کافی‌نت")
    kb.add("⬅️ بازگشت")

    await message.answer(text, reply_markup=kb)

@dp.message_handler(lambda m: m.text == "📋 نمایش همه کافی‌نت‌ها")
async def show_all_cafenets(message: types.Message):
    cafenet_page_state[message.from_user.id] = 1
    await send_cafenet_list(message)


async def send_cafenet_list(message):
    uid = message.from_user.id
    page = cafenet_page_state.get(uid, 1)
    limit = 20
    offset = (page - 1) * limit

    async with pool.acquire() as conn:
        nets = await conn.fetch("""
            SELECT id, name FROM cafenets
            ORDER BY id
            LIMIT $1 OFFSET $2
        """, limit, offset)

        total = await conn.fetchval("SELECT COUNT(*) FROM cafenets")

    if not nets:
        return await message.answer("❌ هیچ کافی‌نتی ثبت نشده.")

    text = f"📋 لیست کافی‌نت‌ها — صفحه {page}\n\n"

    for n in nets:
        text += f"• {n['name']} (ID: {n['id']})\n"

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    if page > 1:
        kb.add("⬅️ صفحه قبل")
    if offset + limit < total:
        kb.add("➡️ صفحه بعد")

    kb.add("🔎 مدیریت کافی‌نت")
    kb.add("⬅️ بازگشت")

    await message.answer(text, reply_markup=kb)

@dp.message_handler(lambda m: m.text in ["⬅️ صفحه قبل", "➡️ صفحه بعد"])
async def paginate_cafenets(message: types.Message):
    uid = message.from_user.id
    page = cafenet_page_state.get(uid, 1)

    if message.text == "⬅️ صفحه قبل":
        page -= 1
    else:
        page += 1

    cafenet_page_state[uid] = max(1, page)

    await send_cafenet_list(message)



@dp.message_handler(lambda m: cafenet_manage_state.get(m.from_user.id))
async def show_cafenet_info(msg: types.Message):
    cafenet_manage_state.pop(msg.from_user.id, None)

    try:
        cid = int(msg.text)
    except:
        return await msg.answer("❌ آیدی معتبر نیست.")

    async with pool.acquire() as conn:
        cnet = await conn.fetchrow("""
            SELECT c.id, c.name, c.address, c.phone,
                   p.name AS province, ci.name AS city,
                   c.owner_user_id
            FROM cafenets c
            JOIN provinces p ON p.id = c.province_id
            JOIN cities ci ON ci.id = c.city_id
            WHERE c.id=$1
        """, cid)

        if not cnet:
            return await msg.answer("❌ کافی‌نت پیدا نشد.")

        # متصدی کافی‌نت
        owner_id = cnet["owner_user_id"]

        if owner_id:
            # گرفتن نام کاربر
            user = await conn.fetchrow("""
                SELECT full_name, username FROM users WHERE user_id=$1
            """, owner_id)

            if user:
                owner_text = (
                    f"{user['full_name']} " +
                    (f"(@{user['username']})" if user['username'] else "")
                )
            else:
                owner_text = f"<code>{owner_id}</code>"
        else:
            owner_text = "— ثبت نشده —"

    text = (
        f"🏢 <b>مشخصات کافی‌نت</b>\n\n"
        f"🆔 ID: <code>{cid}</code>\n"
        f"📛 نام: {cnet['name']}\n"
        f"📍 استان: {cnet['province']}\n"
        f"🏙 شهر: {cnet['city']}\n"
        f"📬 آدرس: {cnet['address']}\n"
        f"📞 تلفن: {cnet['phone']}\n\n"
        f"👤 <b>متصدی کافی‌نت:</b> {owner_text}\n"
    )

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_cafenet"))

    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "back_cafenet")
async def back_to_cafenet_menu(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🌍 فیلتر بر اساس استان", callback_data="cn_filter_province"))
    kb.add(InlineKeyboardButton("🏙 فیلتر بر اساس شهر", callback_data="cn_filter_city"))
    kb.add(InlineKeyboardButton("🔍 جستجو با نام", callback_data="cn_search"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_admin"))

    await call.message.edit_text("🏢 مدیریت کافی‌نت‌ها:", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "cn_filter_province")
async def select_cafenet_province(call: types.CallbackQuery):
    async with pool.acquire() as conn:
        provinces = await conn.fetch("SELECT id, name FROM provinces ORDER BY name")

    kb = InlineKeyboardMarkup()
    for p in provinces:
        kb.add(InlineKeyboardButton(p["name"], callback_data=f"cn_prov_{p['id']}"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_cafenet"))

    await call.message.edit_text("🌍 یک استان انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("cn_prov_"))
async def show_cafenets_by_province(call: types.CallbackQuery):
    prov_id = int(call.data.split("_")[2])

    async with pool.acquire() as conn:
        nets = await conn.fetch("""
            SELECT id, name, city_id FROM cafenets WHERE province_id=$1
        """, prov_id)

    if not nets:
        return await call.message.edit_text("❌ هیچ کافی‌نتی در این استان ثبت نشده.")

    text = "🏢 لیست کافی‌نت‌ها:\n\n"
    for cnet in nets:
        text += f"• {cnet['name']} (ID: <code>{cnet['id']}</code>)\n"

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔎 مدیریت کافی‌نت", callback_data="cn_manage_select"))
    kb.add(InlineKeyboardButton("🔙 بازگشت", callback_data="back_cafenet"))

    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "🏙 فیلتر بر اساس شهر")
async def filter_by_city(message: types.Message):
    cafenet_filter_state[message.from_user.id] = "city"

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.id, c.name, p.name AS province
            FROM cities c
            JOIN provinces p ON p.id=c.province_id
            ORDER BY p.name, c.name
        """)

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    for row in rows:
        kb.add(f"{row['id']} - {row['province']} / {row['name']}")

    kb.add("⬅️ بازگشت")

    await message.answer("🏙 شهر را انتخاب کنید:", reply_markup=kb)

@dp.message_handler(lambda m: " - " in m.text and cafenet_filter_state.get(m.from_user.id) == "city")
async def show_by_city(message: types.Message):
    city_id = int(message.text.split(" - ")[0])
    del cafenet_filter_state[message.from_user.id]

    async with pool.acquire() as conn:
        nets = await conn.fetch("""
            SELECT id, name FROM cafenets WHERE city_id=$1
        """, city_id)

    if not nets:
        return await message.answer("❌ هیچ کافی‌نتی در این شهر نیست.")

    text = f"🏙 کافی‌نت‌های این شهر:\n\n"
    for n in nets:
        text += f"• {n['name']} (ID: {n['id']})\n"

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔎 مدیریت کافی‌نت")
    kb.add("⬅️ بازگشت")

    await message.answer(text, reply_markup=kb)



cafenet_search_state = {}


@dp.message_handler(lambda m: m.text == "🔍 جستجو با نام")
async def ask_cafenet_name(message: types.Message):
    cafenet_search_state[message.from_user.id] = True
    await message.answer("🔍 نام کافی‌نت را وارد کنید:")

@dp.message_handler(lambda m: cafenet_search_state.get(m.from_user.id))
async def search_cafenet(message: types.Message):
    term = message.text
    del cafenet_search_state[message.from_user.id]

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name FROM cafenets
            WHERE name ILIKE $1
        """, f"%{term}%")

    if not rows:
        return await message.answer("❌ هیچ کافی‌نتی یافت نشد.")

    text = "🔍 نتایج جستجو:\n\n"
    for r in rows:
        text += f"• {r['name']} (ID: {r['id']})\n"

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🔎 مدیریت کافی‌نت")
    kb.add("⬅️ بازگشت")

    await message.answer(text, reply_markup=kb)

@dp.message_handler(lambda m: m.text == "🔎 مدیریت کافی‌نت")
async def ask_cafenet_id(message: types.Message):
    cafenet_state[message.from_user.id] = True
    await message.answer("🔎 آیدی عددی کافی‌نت را ارسال کنید:")


@dp.message_handler(lambda m: cafenet_state.get(m.from_user.id))
async def show_cafenet_info(message: types.Message):
    del cafenet_state[message.from_user.id]

    try:
        cid = int(message.text)
    except:
        return await message.answer("❌ آیدی معتبر نیست.")

    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT c.*, p.name AS province, ci.name AS city
            FROM cafenets c
            JOIN provinces p ON p.id=c.province_id
            JOIN cities ci ON ci.id=c.city_id
            WHERE c.id=$1
        """, cid)

        if not row:
            return await message.answer("❌ کافی‌نت یافت نشد.")

        owner_id = row["owner_user_id"]

        if owner_id:
            user = await conn.fetchrow("SELECT full_name, username FROM users WHERE user_id=$1", owner_id)
            if user:
                owner_text = f"{user['full_name']} (@{user['username'] or '---'})"
            else:
                owner_text = f"{owner_id}"
        else:
            owner_text = "ثبت نشده"

    text = (
        f"🏢 <b>{row['name']}</b>\n"
        f"🆔 ID: {cid}\n"
        f"📍 استان: {row['province']}\n"
        f"🏙 شهر: {row['city']}\n"
        f"📞 تلفن: {row['phone']}\n"
        f"🌐 آدرس: {row['address']}\n\n"
        f"👤 <b>متصدی:</b> {owner_text}"
    )

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⬅️ بازگشت")

    await message.answer(text, parse_mode="HTML", reply_markup=kb)



# ========================
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
# مرحله ۱: درخواست کلیدواژه
@dp.message_handler(lambda m: m.text == "🔍 جستجو اطلاعیه/خبر")
async def ask_keyword(msg: types.Message):
    await msg.answer("🔎 لطفاً کلیدواژه مورد نظر خود را وارد کنید:")
    await SearchForm.waiting_for_keyword.set()


# مرحله ۲: جستجو
@dp.message_handler(state=SearchForm.waiting_for_keyword)
async def search_posts(msg: types.Message, state: FSMContext):
    keyword = msg.text.strip()

    async with pool.acquire() as conn:
        # 🔹 تعداد پست مجاز را از تنظیمات کاربر بخوان
        post_limit = await conn.fetchval(
            "SELECT post_limit FROM user_settings WHERE user_id=$1", msg.from_user.id
        )
        if not post_limit:
            post_limit = 5  # پیش‌فرض

        rows = await conn.fetch("""
            SELECT p.id, p.title, p.content, array_agg(h.name) AS hashtags
            FROM posts p
            LEFT JOIN post_hashtags ph ON p.id = ph.post_id
            LEFT JOIN hashtags h ON ph.hashtag_id = h.id
            WHERE p.title ILIKE $1
            GROUP BY p.id
            ORDER BY p.created_at DESC
            LIMIT $2
        """, f"%{keyword}%", post_limit)

    if not rows:
        await msg.answer("⛔ هیچ خبری با این کلیدواژه یافت نشد.")
        await state.finish()
        return

    for row in rows:
        summary = (row["content"][:120] + "...") if row["content"] else "⛔ بدون توضیحات"
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔽 نمایش کامل خبر", callback_data=f"full_{row['id']}"))

        # دکمه هشتگ‌ها
        if row["hashtags"]:
            for h in row["hashtags"]:
                if h:  # حذف None
                    kb.add(InlineKeyboardButton(f"#{h}", callback_data=f"tag_{h}"))

        await msg.answer(
            f"📌 <b>{row['title']}</b>\n\n"
            f"📝 {summary}",
            reply_markup=kb,
            parse_mode="HTML"
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
            f"📌 <b>{row['title']}</b>\n\n{row['content']}",
            parse_mode="HTML"
        )

    await bot.answer_callback_query(callback_query.id)


# مرحله ۴: نمایش پست‌های مرتبط با هشتگ
@dp.callback_query_handler(lambda c: c.data.startswith("tag_"))
async def show_tag_posts(callback_query: types.CallbackQuery):
    tag = callback_query.data.split("_", 1)[1]

    async with pool.acquire() as conn:
        # 🔹 تعداد پست مجاز را از تنظیمات کاربر بخوان
        post_limit = await conn.fetchval(
            "SELECT post_limit FROM user_settings WHERE user_id=$1", callback_query.from_user.id
        )
        if not post_limit:
            post_limit = 5  # پیش‌فرض

        rows = await conn.fetch("""
            SELECT p.title, p.content
            FROM posts p
            JOIN post_hashtags ph ON p.id = ph.post_id
            JOIN hashtags h ON ph.hashtag_id = h.id
            WHERE h.name=$1
            ORDER BY p.created_at DESC
            LIMIT $2
        """, tag, post_limit)

    if not rows:
        await bot.send_message(callback_query.from_user.id, "⛔ خبری برای این هشتگ یافت نشد.")
    else:
        for row in rows:
            summary = (row["content"][:120] + "...") if row["content"] else "⛔ بدون توضیحات"
            await bot.send_message(
                callback_query.from_user.id,
                f"📌 <b>{row['title']}</b>\n\n📝 {summary}",
                parse_mode="HTML"
            )

    await bot.answer_callback_query(callback_query.id)


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
@dp.channel_post_handler(content_types=types.ContentTypes.ANY)
async def process_channel_post(message: types.Message):

    try:
        if pool is None:
            print("⚠️ pool دیتابیس آماده نشده — نمی‌توان پست را ذخیره کرد.")
            return

        # --- ۱. استخراج اطلاعات پست ---
        title = (message.caption or message.text or "").split("\n")[0][:150]
        content = message.caption or message.text or ""
        hashtags = [tag.lstrip("#") for tag in content.split() if tag.startswith("#")]

        if not title:
            title = "پست بدون عنوان"

        # --- ۲. ذخیره پست در دیتابیس ---
        async with pool.acquire() as conn:
            # استفاده از ON CONFLICT تا duplicate باعث crash نشود
            post_row = await conn.fetchrow("""
                INSERT INTO posts (message_id, title, content, created_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (message_id) DO UPDATE
                  SET title=EXCLUDED.title, content=EXCLUDED.content
                RETURNING id
            """, message.message_id, title, content)
            post_id = post_row["id"]

            # ذخیره هشتگ‌ها و اتصال آنها به پست
            for tag in hashtags:
                # اگر رشته خالی بود نادیده بگیر
                if not tag:
                    continue
                hashtag_row = await conn.fetchrow(
                    "INSERT INTO hashtags (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id",
                    tag
                )
                hashtag_id = hashtag_row["id"]
                await conn.execute(
                    "INSERT INTO post_hashtags (post_id, hashtag_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    post_id, hashtag_id
                )

            # --- محدودیت حداکثر ۱۰۰ پست ---
            count = await conn.fetchval("SELECT COUNT(*) FROM posts")
            if count > 100:
                excess = count - 100
                old_ids = await conn.fetch(
                    "SELECT id FROM posts ORDER BY created_at ASC LIMIT $1", excess
                )
                old_ids = [r["id"] for r in old_ids]
                if old_ids:
                    await conn.execute(
                        "DELETE FROM post_hashtags WHERE post_id = ANY($1::int[])", old_ids
                    )
                    await conn.execute(
                        "DELETE FROM posts WHERE id = ANY($1::int[])", old_ids
                    )
                    print(f"🧹 {len(old_ids)} پست قدیمی حذف شد (برای حفظ محدودیت ۱۰۰ پست).")


        # --- ۳. ارسال خودکار به کاربران مشترک ---
        async with pool.acquire() as conn:
            for tag in hashtags:
                if not tag:
                    continue
                hashtag_row = await conn.fetchrow("SELECT id FROM hashtags WHERE name=$1", tag)
                if not hashtag_row:
                    continue
                hashtag_id = hashtag_row["id"]

                users = await conn.fetch("""
                    SELECT s.user_id FROM subscriptions s
                    JOIN user_settings us ON us.user_id = s.user_id
                    WHERE s.hashtag_id=$1 AND us.notifications_enabled=TRUE
                """, hashtag_id)

                for u in users:
                    try:
                        summary = (content[:200] + "...") if len(content) > 200 else content
                        kb = InlineKeyboardMarkup().add(
                            InlineKeyboardButton("🔽 نمایش کامل", callback_data=f"full_{post_id}")
                        )
                        await bot.send_message(
                            u["user_id"],
                            f"📢 <b>{title}</b>\n\n{summary}",
                            parse_mode="HTML",
                            reply_markup=kb
                        )
                    except Exception as e:
                        print(f"⚠️ خطا در ارسال خودکار برای کاربر {u['user_id']}: {e}")

        print(f"✅ پست {post_id} ذخیره و به کاربران مرتبط ارسال شد.")

    except Exception as e:
        print(f"❌ خطا در process_channel_post: {e}")




# ===============================
# 📢 هندلر پست‌های جدید کانال (با ارسال خودکار به مشترکین)
# ===============================

# ===============================
# تنظیمات
# ===============================

@dp.message_handler(lambda m: m.text == "⚙️ تنظیمات")
async def settings_menu(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📊 تنظیم تعداد پست در جستجو", callback_data="set_post_limit"),
        InlineKeyboardButton("🚫 غیرفعال کردن موقت اعلان‌ها", callback_data="disable_notifications"),
        InlineKeyboardButton("✅ فعال کردن اعلان‌ها", callback_data="enable_notifications"),
        InlineKeyboardButton("🔎 پیگیری سفارش", callback_data="track_order"),
        InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main")
    )
    await message.answer("⚙️ تنظیمات ربات:", reply_markup=kb)

# ===============================
# محدودیت پست
# ===============================
@dp.callback_query_handler(lambda c: c.data == "set_post_limit")
async def ask_post_limit(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "📊 لطفاً تعداد پست‌های قابل نمایش در جستجو را وارد کنید (مثلاً 5 یا 10):")
    await UserStates.waiting_for_post_limit.set()


@dp.message_handler(state=UserStates.waiting_for_post_limit)
async def save_post_limit(message: types.Message, state: FSMContext):
    try:
        limit = int(message.text)
        if limit < 1 or limit > 50:
            await message.reply("⚠️ عدد باید بین ۱ تا ۵۰ باشد.")
            return

        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_settings (user_id, post_limit)
                VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET post_limit = $2
            """, message.from_user.id, limit)

        await message.reply(f"✅ تعداد پست‌ها روی {limit} تنظیم شد.", reply_markup=main_menu())
        await state.finish()

    except ValueError:
        await message.reply("❌ لطفاً فقط عدد وارد کنید.")

# ===============================
# غیرفعال سازی اشتراک
# ===============================
@dp.callback_query_handler(lambda c: c.data == "disable_notifications")
async def disable_notifications(callback_query: types.CallbackQuery):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_settings (user_id, notifications_enabled)
            VALUES ($1, FALSE)
            ON CONFLICT (user_id) DO UPDATE SET notifications_enabled = FALSE
        """, callback_query.from_user.id)

    await bot.answer_callback_query(callback_query.id, "🚫 اعلان‌ها غیرفعال شد.")
    await bot.send_message(callback_query.from_user.id, "اعلان‌های خودکار موقتاً غیرفعال شدند ✅")

# ===============================
# فعالسازی اشتراک
# ===============================
@dp.callback_query_handler(lambda c: c.data == "enable_notifications")
async def enable_notifications(callback_query: types.CallbackQuery):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_settings (user_id, notifications_enabled)
            VALUES ($1, TRUE)
            ON CONFLICT (user_id) DO UPDATE SET notifications_enabled = TRUE
        """, callback_query.from_user.id)

    await bot.answer_callback_query(callback_query.id, "✅ اعلان‌ها فعال شدند.")
    await bot.send_message(callback_query.from_user.id, "اعلان‌های خودکار دوباره فعال شدند 🔔")

# ===============================
# رهگیری سفارش
# ===============================
@dp.callback_query_handler(lambda c: c.data == "track_order")
async def ask_tracking_code(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "🔎 لطفاً کد رهگیری سفارش را وارد کنید:")
    await UserStates.waiting_for_tracking_code.set()


@dp.message_handler(state=UserStates.waiting_for_tracking_code)
async def show_order_status(message: types.Message, state: FSMContext):
    code = message.text.strip()

    async with pool.acquire() as conn:
        order = await conn.fetchrow("""
            SELECT 
                o.order_code, 
                o.status, 
                o.docs, 
                o.created_at, 
                s.title
            FROM orders o
            JOIN services s ON o.service_id = s.id
            WHERE o.order_code = $1 AND o.user_id = $2
        """, code, message.from_user.id)

    if not order:
        await message.answer("❌ سفارشی با این کد پیگیری پیدا نشد.")
        return

    text = (
        f"📄 <b>وضعیت سفارش</b>\n\n"
        f"🔖 کد سفارش: <code>{order['order_code']}</code>\n"
        f"📌 خدمت: {order['title']}\n"
        f"🕒 زمان ثبت: {order['created_at']:%Y/%m/%d - %H:%M}\n"
        f"📊 وضعیت: <b>{order['status']}</b>"
    )

    await message.answer(text, parse_mode="HTML")
    await state.finish()



# ===============================
# راهنما
# ===============================
@dp.message_handler(lambda m: m.text == "📘 راهنما")
async def show_help(message: types.Message):
    help_text = (
        "📘 <b>راهنمای استفاده از ربات</b>\n\n"

        "🛍 <b>سفارش خدمات</b>\n"
        "از طریق این بخش می‌توانید یکی از دسته‌بندی‌ها را انتخاب کرده و خدمات موردنظر خود را ثبت کنید. "
        "در پایان پس از ارسال مدارک لازم، کد پیگیری سفارش برای شما صادر می‌شود.\n\n"

        "🧾 <b>سفارش‌های من</b>\n"
        "در این بخش می‌توانید وضعیت سفارش‌های قبلی خود را مشاهده کنید.\n\n"

        "🔍 <b>جستجو اطلاعیه/خبر</b>\n"
        "با وارد کردن یک کلیدواژه، اطلاعیه‌ها و خبرهای منتشرشده  نمایش داده می‌شوند. "
        "با زدن دکمه «🔽 نمایش کامل خبر» می‌توانید متن کامل را ببینید. "
        "همچنین می‌توانید با انتخاب هر هشتگ مرتبط با خبر، ۵ پست آخر مرتبط با آن را مشاهده کنید.\n\n"

        "🔔 <b>دریافت خودکار خبر</b>\n"
        "در این بخش می‌توانید موضوع مورد علاقه خود را انتخاب کنید. "
        "هر زمان پستی با آن موضوع  منتشر شود، به‌صورت خودکار برای شما ارسال خواهد شد. "
        "می‌توانید از طریق بخش تنظیمات، اعلان خودکار را موقتاً غیرفعال یا فعال کنید.\n\n"

        "⚙️ <b>تنظیمات</b>\n"
        "• تغییر تعداد پست‌های قابل‌نمایش در نتایج جستجو (پیش‌فرض: ۵ عدد)\n"
        "• فعال/غیرفعال کردن موقت اعلان خودکار اخبار\n"
        "• پیگیری وضعیت سفارش با وارد کردن کد رهگیری\n\n"

        "ℹ️ در صورت بروز هرگونه مشکل می‌توانید با پشتیبانی تماس بگیرید."
    )
    
    # تلاش برای ساخت URL مطمئن برای ادمین:
    admin_username = os.getenv("ADMIN_USERNAME")  # optional
    admin_url = None

    if admin_username:
        admin_url = f"https://t.me/{admin_username.lstrip('@')}"
    else:
        # اگر username در ENV نبود، تلاش می‌کنیم از get_chat استفاده کنیم
        try:
            admin_chat = await bot.get_chat(ADMIN_ID)
            if getattr(admin_chat, "username", None):
                admin_url = f"https://t.me/{admin_chat.username}"
            else:
                # اگر username نداشت از لینک tg:// استفاده کن (موبایل ها آن را باز می‌کنند)
                admin_url = f"tg://user?id={ADMIN_ID}"
        except Exception:
            # اگر get_chat هم خطا داد، از tg:// به عنوان آخرین راه استفاده می‌کنیم
            admin_url = f"tg://user?id={ADMIN_ID}"

    # کیبورد: دکمه URL + دکمه fallback که اطلاعات تماس را می‌فرستد
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("📞 تماس با پشتیبانی", url=admin_url))
    kb.add(InlineKeyboardButton("✉️ روش‌های تماس (نمایش در چت)", callback_data="contact_support"))

    # متن را هم با لینک اضافه می‌کنیم تا در صورت عدم نمایش دکمه، کاربر لینک را ببیند
    help_text_with_link = help_text + f"\n\n🔗 لینک تماس: {admin_url}"

    await message.answer(help_text_with_link, parse_mode="HTML", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "contact_support")
async def contact_support_callback(call: types.CallbackQuery):
    await call.answer()  # برداشتن لودینگ
    try:
        admin_chat = await bot.get_chat(ADMIN_ID)
    except Exception:
        admin_chat = None

    lines = ["📬 <b>روش‌های تماس با پشتیبانی</b>\n"]
    if admin_chat and getattr(admin_chat, "username", None):
        lines.append(f"• لینک مستقیم: https://t.me/{admin_chat.username}")
    # همیشه آیدی را هم نشان می‌دهیم (کاربر می‌تواند آن را ذخیره یا کپی کند)
    lines.append(f"• شناسه پشتیبانی: <code>{ADMIN_ID}</code>")
    lines.append("\nلطفاً روی لینک کلیک کنید یا شناسه را جهت شروع گفتگو استفاده کنید.")

    await call.message.answer("\n".join(lines), parse_mode="HTML")


class LastSeenMiddleware(BaseMiddleware):
    async def _update_last_seen(self, uid: int):
        if pool is None or uid is None:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE users SET last_seen = NOW() WHERE user_id=$1",
                    uid
                )
        except Exception:
            logging.exception("error updating last_seen")

    async def on_pre_process_message(self, message: types.Message, data: dict):
        await self._update_last_seen(message.from_user.id)

    async def on_pre_process_update(self, update: types.Update, data: dict):
        # این متد هم callback_query و message و ... را پوشش می‌دهد
        try:
            if update.message:
                await self._update_last_seen(update.message.from_user.id)
            elif update.callback_query:
                await self._update_last_seen(update.callback_query.from_user.id)
        except Exception:
            # لاگ کن و ادامه بده
            logging.exception("LastSeenMiddleware.on_pre_process_update error")


# ---------------- راه‌اندازی ----------------
async def on_startup(dispatcher):
    await init_db()
    print("🚀 ربات شروع به کار کرد.")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
