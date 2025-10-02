
# Minimal, self-contained aiogram v2 bot with asyncpg DB integration.
# Save as bot_fixed.py and set environment variables: BOT_TOKEN, DATABASE_URL, ADMIN_ID
import os, logging, uuid, json
import asyncpg
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN or not DATABASE_URL or not ADMIN_ID:
    raise RuntimeError("Please set BOT_TOKEN, DATABASE_URL and ADMIN_ID environment variables")

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
pool = None

class AddService(StatesGroup):
    waiting_for_title = State()
    waiting_for_docs = State()

class OrderForm(StatesGroup):
    waiting_for_documents = State()

class SearchForm(StatesGroup):
    waiting_for_keyword = State()

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE,
    first_name TEXT,
    username TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS service_categories (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    category_id INTEGER REFERENCES service_categories(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    documents TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
    service_id INTEGER REFERENCES services(id) ON DELETE CASCADE,
    order_code TEXT UNIQUE,
    docs TEXT,
    status TEXT DEFAULT 'new',
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hashtags (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id SERIAL PRIMARY KEY,
    title TEXT,
    content TEXT,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS post_hashtags (
    post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
    hashtag_id INTEGER REFERENCES hashtags(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, hashtag_id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id BIGINT,
    hashtag_id INTEGER REFERENCES hashtags(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, hashtag_id)
);
"""

async def init_db_pool():
    global pool
    pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        for s in CREATE_TABLES_SQL.split(";"):
            s = s.strip()
            if s:
                await conn.execute(s + ";")
    logger.info("Database initialized")

def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("📋 سفارش خدمات"))
    kb.add(KeyboardButton("🔍 جستجو اطلاعیه/خبر"))
    kb.add(KeyboardButton("🔔 دریافت خودکار خبر"))
    kb.add(KeyboardButton("⚙️ مدیریت خدمات"))
    return kb

def orders_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("➕ ثبت سفارش"))
    kb.add(KeyboardButton("📦 سفارش‌های من"))
    kb.add(KeyboardButton("⬅️ بازگشت به منوی اصلی"))
    return kb

async def service_categories_keyboard(prefix: str = "order"):
    kb = InlineKeyboardMarkup(row_width=2)
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name FROM service_categories ORDER BY id")
    if not rows:
        kb.add(InlineKeyboardButton("⛔ هیچ دسته‌ای وجود ندارد", callback_data="none"))
        return kb
    for r in rows:
        cid = r["id"]; name = r["name"]
        if prefix == "add": cb = f"addcat_{cid}"
        elif prefix == "del": cb = f"delete_cat_{cid}"
        elif prefix == "order": cb = f"ordercat_{cid}"
        else: cb = f"{prefix}_{cid}"
        kb.add(InlineKeyboardButton(name, callback_data=cb))
    return kb

async def ensure_user(u: types.User):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, first_name, username) VALUES ($1,$2,$3) ON CONFLICT (user_id) DO NOTHING
        """, u.id, u.first_name or "", u.username or "")

@dp.message_handler(commands=["start"])
async def cmd_start(msg: types.Message):
    await ensure_user(msg.from_user)
    await msg.answer("سلام! منو را انتخاب کنید:", reply_markup=main_menu())

@dp.message_handler(lambda m: m.text == "📋 سفارش خدمات")
async def show_orders_menu(message: types.Message):
    await message.answer("📋 لطفاً یکی از گزینه‌ها را انتخاب کنید:", reply_markup=orders_menu())

@dp.message_handler(lambda m: m.text == "⬅️ بازگشت به منوی اصلی")
async def back_to_main(message: types.Message):
    await message.answer("🔙 بازگشت", reply_markup=main_menu())

@dp.message_handler(lambda m: m.text == "➕ ثبت سفارش")
async def add_order(message: types.Message):
    kb = await service_categories_keyboard(prefix="order")
    await message.answer("📋 یک دسته‌بندی انتخاب کنید:", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "📦 سفارش‌های من")
async def my_orders(message: types.Message):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT o.order_code,o.status,s.title FROM orders o JOIN services s ON o.service_id=s.id WHERE o.user_id=$1 ORDER BY o.created_at DESC LIMIT 10""", message.from_user.id)
    if not rows:
        await message.answer("⛔ سفارشی ندارید.")
        return
    text = "📦 سفارش‌های شما:\n\n"
    for r in rows:
        text += f"▫️ {r['title']} | کد: <code>{r['order_code']}</code> | وضعیت: {r['status']}\n"
    await message.answer(text, parse_mode="HTML")

@dp.message_handler(lambda m: m.text == "⚙️ مدیریت خدمات")
async def manage_services_menu(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ دسترسی ندارید")
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("➕ افزودن خدمات"))
    kb.add(KeyboardButton("❌ حذف خدمات"))
    kb.add(KeyboardButton("⬅️ بازگشت به منوی اصلی"))
    await message.answer("مدیریت خدمات:", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "❌ حذف خدمات")
async def delete_service_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ دسترسی ندارید")
    kb = await service_categories_keyboard(prefix="del")
    await message.answer("دسته‌ای انتخاب کنید:", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "➕ افزودن خدمات")
async def add_service_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("⛔ دسترسی ندارید")
    kb = await service_categories_keyboard(prefix="add")
    await message.answer("دسته‌ای انتخاب کنید برای افزودن خدمت:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("addcat_"))
async def process_add_service_category(call: types.CallbackQuery):
    await call.answer()
    category_id = int(call.data.split("_",1)[1])
    await AddService.waiting_for_title.set()
    await dp.current_state(user=call.from_user.id).update_data(category_id=category_id)
    await call.message.answer("✍️ عنوان خدمت را ارسال کنید:")

@dp.message_handler(state=AddService.waiting_for_title, content_types=types.ContentTypes.TEXT)
async def get_service_title(msg: types.Message, state: FSMContext):
    title = msg.text.strip()
    if not title:
        return await msg.answer("عنوان معتبر نیست")
    await state.update_data(title=title)
    await AddService.waiting_for_docs.set()
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("✅ ثبت خدمت", callback_data="confirm_add_service"), InlineKeyboardButton("❌ انصراف", callback_data="cancel_add_service"))
    await msg.answer("عنوان ذخیره شد. حالا مدارک/توضیحات را ارسال کنید و سپس دکمه ثبت را بزنید.", reply_markup=kb)

@dp.message_handler(state=AddService.waiting_for_docs, content_types=types.ContentTypes.ANY)
async def get_service_docs(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    docs = data.get("documents", [])
    entry = {"content_type": msg.content_type}
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
        entry["text"] = getattr(msg, "text", f"<{msg.content_type}>")
    docs.append(entry)
    await state.update_data(documents=docs)
    await msg.answer("✅ دریافت شد. برای پایان '✅ ثبت خدمت' را بزنید.")

@dp.callback_query_handler(lambda c: c.data in ("confirm_add_service","cancel_add_service"))
async def handle_confirm_or_cancel_add_service(call: types.CallbackQuery):
    await call.answer()
    state = dp.current_state(user=call.from_user.id)
    data = await state.get_data()
    if call.data == "cancel_add_service":
        await state.finish()
        return await call.message.answer("افزودن لغو شد.", reply_markup=main_menu())
    cat_id = data.get("category_id"); title = data.get("title","")
    docs = data.get("documents",[])
    docs_json = json.dumps(docs, ensure_ascii=False)
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO services (category_id, title, documents) VALUES ($1,$2,$3)", cat_id, title, docs_json)
    await state.finish()
    await call.message.answer(f"✅ خدمت «{title}» ثبت شد.", reply_markup=main_menu())

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("delete_cat_"))
async def process_delete_category(call: types.CallbackQuery):
    await call.answer()
    cat_id = int(call.data.split("_",1)[1])
    async with pool.acquire() as conn:
        services = await conn.fetch("SELECT id,title FROM services WHERE category_id=$1", cat_id)
    if not services:
        return await call.message.edit_text("⛔ خدمتی وجود ندارد.")
    kb = InlineKeyboardMarkup()
    for s in services:
        kb.add(InlineKeyboardButton(f"❌ {s['title']}", callback_data=f"delete_service_{s['id']}"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="manage_services"))
    await call.message.edit_text("یک خدمت برای حذف انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("delete_service_"))
async def process_delete_service(call: types.CallbackQuery):
    await call.answer()
    sid = int(call.data.split("_",2)[2])
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM services WHERE id=$1", sid)
    await call.message.edit_text("✅ خدمت حذف شد.", reply_markup=main_menu())

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("ordercat_"))
async def process_order_category(call: types.CallbackQuery):
    await call.answer()
    cat_id = int(call.data.split("_",1)[1])
    async with pool.acquire() as conn:
        services = await conn.fetch("SELECT id,title,documents FROM services WHERE category_id=$1", cat_id)
    if not services:
        return await call.message.edit_text("⛔ خدمتی موجود نیست.")
    kb = InlineKeyboardMarkup(row_width=1)
    for s in services:
        kb.add(InlineKeyboardButton(s["title"], callback_data=f"service_{s['id']}"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main"))
    await call.message.edit_text("یکی از خدمات را انتخاب کنید:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("service_"))
async def start_order_form(call: types.CallbackQuery):
    await call.answer()
    sid = int(call.data.split("_",1)[1])
    async with pool.acquire() as conn:
        service = await conn.fetchrow("SELECT id,title,documents FROM services WHERE id=$1", sid)
    if not service:
        return await call.message.answer("⛔ خدمت پیدا نشد.")
    await OrderForm.waiting_for_documents.set()
    await dp.current_state(user=call.from_user.id).update_data(service_id=sid, messages=[], documents=[])
    # prepare docs text
    docs_text = ""
    try:
        docs_json = json.loads(service["documents"]) if service["documents"] else []
        if isinstance(docs_json, list):
            docs_text = "\n".join([ entry.get("text") or entry.get("caption") or entry.get("file_name") or "<فایل>" for entry in docs_json ])
        else:
            docs_text = str(service["documents"])
    except Exception:
        docs_text = str(service["documents"] or "")
    kb = InlineKeyboardMarkup().add(InlineKeyboardButton("✅ ثبت سفارش", callback_data="submit_order"))
    await call.message.answer(f"📌 <b>{service['title']}</b>\n\nمدارک لازم:\n{docs_text}\n\nلطفاً مدارک و توضیحات را ارسال کنید. وقتی آماده شدید «✅ ثبت سفارش» را بزنید.", reply_markup=kb, parse_mode="HTML")

@dp.message_handler(state=OrderForm.waiting_for_documents, content_types=types.ContentTypes.ANY)
async def collect_documents(message: types.Message, state: FSMContext):
    data = await state.get_data()
    docs = data.get("documents", [])
    messages = data.get("messages", [])
    if message.text:
        docs.append(message.text)
    elif message.photo:
        docs.append("📷 عکس ارسال شد")
    elif message.document:
        docs.append(f"📄 {message.document.file_name}")
    else:
        docs.append(f"<{message.content_type}>")
    messages.append(message.message_id)
    await state.update_data(documents=docs, messages=messages)
    await message.answer("✅ مدرک ثبت شد. برای پایان روی «✅ ثبت سفارش» بزنید.")

@dp.callback_query_handler(lambda c: c.data == "submit_order", state=OrderForm.waiting_for_documents)
async def submit_order(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    service_id = data.get("service_id")
    documents_list = data.get("documents", [])
    msg_ids = data.get("messages", [])
    if not service_id:
        await call.message.answer("خطا، دوباره تلاش کنید")
        await state.finish()
        return
    documents_text = "\n".join(documents_list) if documents_list else "⛔ مدرکی ارسال نشد"
    order_code = str(uuid.uuid4())[:8]
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO orders (user_id,service_id,order_code,docs,status) VALUES ($1,$2,$3,$4,'new')", call.from_user.id, service_id, order_code, documents_text)
        service = await conn.fetchrow("SELECT title FROM services WHERE id=$1", service_id)
    await call.message.answer(f"✅ سفارش شما برای <b>{service['title']}</b> ثبت شد.\nکد رهگیری: <code>{order_code}</code>", reply_markup=main_menu(), parse_mode="HTML")
    user = call.from_user
    full_name = (user.first_name or "") + ((" " + user.last_name) if getattr(user, "last_name", None) else "")
    mention = f"<a href='tg://user?id={user.id}'>{full_name or user.username or user.id}</a>"
    keyboard = InlineKeyboardMarkup().add(InlineKeyboardButton("✅ تکمیل سفارش", callback_data=f"complete_{order_code}"))
    await bot.send_message(ADMIN_ID, f"📢 سفارش جدید ثبت شد\n👤 مشتری: {mention}\n📌 خدمت: {service['title']}\n📎 کد رهگیری: <code>{order_code}</code>\n\n📝 مدارک ارسالی در ادامه فوروارد می‌شوند 👇", reply_markup=keyboard, parse_mode="HTML")
    for mid in msg_ids:
        try:
            await bot.forward_message(ADMIN_ID, call.from_user.id, mid)
        except Exception:
            pass
    await state.finish()

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("complete_"))
async def complete_order(call: types.CallbackQuery):
    await call.answer()
    code = call.data.split("_",1)[1]
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT user_id FROM orders WHERE order_code=$1", code)
        if not order:
            return await call.message.answer("سفارش یافت نشد.")
        await conn.execute("UPDATE orders SET status='completed', docs=NULL WHERE order_code=$1", code)
    await call.message.answer("✅ سفارش تکمیل شد و مدارک پاک شد.")
    try:
        await bot.send_message(order["user_id"], f"🎉 سفارش شما با کد رهگیری <code>{code}</code> تکمیل شد.", parse_mode="HTML")
    except Exception:
        pass

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("order_"))
async def back_handlers(call: types.CallbackQuery):
    await call.answer()
    # placeholder for other order_* callbacks
    await call.message.answer("عملیات انجام شد.")

@dp.message_handler(lambda m: m.text == "🔍 جستجو اطلاعیه/خبر")
async def ask_keyword(msg: types.Message):
    await msg.answer("🔎 لطفاً کلیدواژه را وارد کنید:")
    await SearchForm.waiting_for_keyword.set()

@dp.message_handler(state=SearchForm.waiting_for_keyword)
async def process_search(message: types.Message, state: FSMContext):
    keyword = message.text.strip()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT p.id,p.title,p.content,array_agg(h.name) AS hashtags FROM posts p LEFT JOIN post_hashtags ph ON p.id=ph.post_id LEFT JOIN hashtags h ON ph.hashtag_id=h.id WHERE p.title ILIKE $1 GROUP BY p.id ORDER BY p.created_at DESC LIMIT 10", f"%{keyword}%")
    if not rows:
        await message.answer("هیچ پستی یافت نشد.")
        await state.finish()
        return
    for row in rows:
        summary = (row['content'][:200] + "...") if row['content'] else "—"
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔽 نمایش کامل خبر", callback_data=f"full_{row['id']}"))
        if row['hashtags']:
            for h in row['hashtags']:
                if h:
                    kb.add(InlineKeyboardButton(f"#{h}", callback_data=f"tag_{h}"))
        await message.answer(f"📌 <b>{row['title']}</b>\n\n📝 {summary}", reply_markup=kb, parse_mode="HTML")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("full_"))
async def show_full(callback_query: types.CallbackQuery):
    await callback_query.answer()
    post_id = int(callback_query.data.split("_",1)[1])
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT title,content FROM posts WHERE id=$1", post_id)
    if row:
        await bot.send_message(callback_query.from_user.id, f"📌 <b>{row['title']}</b>\n\n{row['content']}", parse_mode="HTML")

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("tag_"))
async def show_tag_posts(callback_query: types.CallbackQuery):
    await callback_query.answer()
    tag = callback_query.data.split("_",1)[1]
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT p.title,p.content FROM posts p JOIN post_hashtags ph ON p.id=ph.post_id JOIN hashtags h ON ph.hashtag_id=h.id WHERE h.name=$1 ORDER BY p.created_at DESC LIMIT 10", tag)
    if not rows:
        await bot.send_message(callback_query.from_user.id, "هیچ خبری برای این هشتگ نیافت شد.")
    else:
        for r in rows:
            summary = (r['content'][:200] + "...") if r['content'] else "—"
            await bot.send_message(callback_query.from_user.id, f"📌 <b>{r['title']}</b>\n\n📝 {summary}", parse_mode="HTML")

@dp.message_handler()
async def fallback(msg: types.Message):
    await msg.answer("از منو استفاده کنید.", reply_markup=main_menu())

async def on_startup(dp_obj):
    await init_db_pool()
    logger.info("Bot is up")

async def on_shutdown(dp_obj):
    await bot.close()
    if pool:
        await pool.close()

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
