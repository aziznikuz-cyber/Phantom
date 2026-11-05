# language: Python, file: app.py
# target: Render Web Service (Free), Python 3.11+
# deps: aiogram, aiohttp, flask
import asyncio, secrets, datetime, sqlite3, os, threading
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from flask import Flask

# ===== ВПИСАНО =====
BOT_TOKEN = "9127693195:AAEHydjthMjNzZDHv1LRWAKQM5SqC7q8BWU"
ADMIN_IDS = [8234498887]
DOMAIN    = "https://example.com"
# ===================

DB = "oxide.db"

web = Flask(__name__)

@web.route("/")
def home(): return "Bot is running"

@web.route("/health")
def health(): return "OK"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web.run(host="0.0.0.0", port=port)

def db_init():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS plans(
      id TEXT PRIMARY KEY, name TEXT, price INTEGER, days INTEGER, descr TEXT);
    CREATE TABLE IF NOT EXISTS orders(
      id TEXT PRIMARY KEY, uid INTEGER, email TEXT, plan TEXT,
      amount INTEGER, status TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS keys(
      key TEXT PRIMARY KEY, order_id TEXT, plan TEXT, days INTEGER,
      uid INTEGER, hwid TEXT, activated TEXT, expires TEXT, ts TEXT);
    """)
    for pid, nm, pr, dy, ds in [
        ("d1",  "1 день",   90,   1,  "Доступ · 1 устройство"),
        ("d7",  "7 дней",   370,  7,  "Доступ · 1 устройство"),
        ("d30", "30 дней",  1400, 30, "Доступ · 2 устройства"),
        ("life","Навсегда", 2800, 0,  "Доступ · 3 устройства"),
    ]:
        c.execute("INSERT OR REPLACE INTO plans VALUES(?,?,?,?,?)", (pid, nm, pr, dy, ds))
    c.commit(); c.close()
db_init()

def q(sql, args=()):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    r = c.execute(sql, args).fetchall(); c.close(); return r

def x(sql, args=()):
    c = sqlite3.connect(DB); c.execute(sql, args); c.commit(); c.close()

bot = Bot(BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())
rt  = Router()
dp.include_router(rt)

class Buy(StatesGroup):
    email = State()

def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Тарифы", callback_data="plans")],
        [InlineKeyboardButton(text="🔑 Мои ключи", callback_data="mykeys")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq")],
    ])

def kb_plans():
    rows = []
    for p in q("SELECT * FROM plans ORDER BY price"):
        rows.append([InlineKeyboardButton(
            text=f"{p['name']} — {p['price']}₽", callback_data=f"buy:{p['id']}")])
    rows.append([InlineKeyboardButton(text="◀ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@rt.message(CommandStart())
async def start(m: Message):
    await m.answer(
        "👋 <b>OxideWH</b>\n\nВыбери действие:",
        reply_markup=kb_main(), parse_mode="HTML")

@rt.callback_query(F.data == "back")
async def back(cb: CallbackQuery):
    await cb.message.edit_text("Меню:", reply_markup=kb_main()); await cb.answer()

@rt.callback_query(F.data == "plans")
async def plans(cb: CallbackQuery):
    txt = "<b>Тарифы</b>\n\n"
    for p in q("SELECT * FROM plans ORDER BY price"):
        txt += f"<b>{p['name']}</b> — {p['price']}₽\n<i>{p['descr']}</i>\n\n"
    await cb.message.edit_text(txt, reply_markup=kb_plans(), parse_mode="HTML"); await cb.answer()

@rt.callback_query(F.data.startswith("buy:"))
async def buy(cb: CallbackQuery, state: FSMContext):
    pid = cb.data.split(":")[1]
    p = q("SELECT * FROM plans WHERE id=?", (pid,))[0]
    await state.update_data(plan=pid, amount=p["price"])
    await cb.message.answer(f"Выбран <b>{p['name']}</b> — {p['price']}₽\nВведите email:", parse_mode="HTML")
    await state.set_state(Buy.email); await cb.answer()

@rt.message(Buy.email)
async def get_email(m: Message, state: FSMContext):
    em = m.text.strip().lower()
    if "@" not in em or "." not in em.split("@")[-1]:
        await m.answer("Некорректный email."); return
    d = await state.get_data()
    oid = "OX-" + secrets.token_hex(4).upper()
    x("INSERT INTO orders VALUES(?,?,?,?,?,?,?)",
      (oid, m.from_user.id, em, d["plan"], d["amount"], "pending", datetime.datetime.now().isoformat()))
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=f"{DOMAIN}/pay/{oid}")],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"check:{oid}")],
    ])
    await m.answer(f"Заказ <b>{oid}</b>.\nК оплате: <b>{d['amount']}₽</b>", reply_markup=kb, parse_mode="HTML")

@rt.callback_query(F.data.startswith("check:"))
async def check(cb: CallbackQuery):
    oid = cb.data.split(":")[1]
    o = q("SELECT * FROM orders WHERE id=?", (oid,))
    if not o: await cb.answer("Не найден", show_alert=True); return
    if o[0]["status"] == "paid":
        k = q("SELECT * FROM keys WHERE order_id=?", (oid,))
        if k: await cb.message.answer(f"✅ Ключ:\n<code>{k[0]['key']}</code>", parse_mode="HTML")
    else: await cb.answer("Не оплачен", show_alert=True)

@rt.callback_query(F.data == "mykeys")
async def mykeys(cb: CallbackQuery):
    ks = q("SELECT * FROM keys WHERE uid=? ORDER BY ts DESC LIMIT 10", (cb.from_user.id,))
    if not ks: await cb.message.answer("Ключей нет."); await cb.answer(); return
    txt = "<b>Ключи:</b>\n\n"
    for k in ks: txt += f"<code>{k['key']}</code> — {k['plan']}\n"
    await cb.message.answer(txt, parse_mode="HTML"); await cb.answer()

@rt.callback_query(F.data == "faq")
async def faq(cb: CallbackQuery):
    await cb.message.answer(
        "<b>FAQ</b>\n\n"
        "<b>Сервер?</b> Доступ клиентский, сервер не видит.\n"
        "<b>Ключ?</b> Приходит после оплаты.",
        parse_mode="HTML"); await cb.answer()

@rt.message(Command("admin"))
async def admin(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    await m.answer("<b>Админка</b>\n/orders\n/stats\n/give email plan", parse_mode="HTML")

@rt.message(Command("orders"))
async def orders(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    rows = q("SELECT * FROM orders ORDER BY ts DESC LIMIT 20")
    txt = "\n".join(f"{o['id']} | {o['email']} | {o['plan']} | {o['status']}" for o in rows)
    await m.answer(f"<pre>{txt or 'пусто'}</pre>", parse_mode="HTML")

@rt.message(Command("stats"))
async def stats(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    o = q("SELECT COUNT(*) c, SUM(amount) s FROM orders WHERE status='paid'")[0]
    await m.answer(f"Оплачено: {o['c']}\nВыручка: {o['s'] or 0}₽")

@rt.message(Command("give"))
async def give(m: Message):
    if m.from_user.id not in ADMIN_IDS: return
    parts = m.text.split()
    if len(parts) < 3: await m.answer("/give email plan"); return
    em, plan = parts[1], parts[2]
    p = q("SELECT * FROM plans WHERE id=?", (plan,))
    if not p: await m.answer("Нет тарифа"); return
    p = p[0]
    key = "WH-" + secrets.token_hex(8).upper()
    exp = (datetime.datetime.now() + datetime.timedelta(days=p["days"])).isoformat() if p["days"] else None
    x("INSERT INTO keys VALUES(?,?,?,?,?,?,?,?)",
      (key, "MANUAL", plan, p["days"], 0, None, None, exp, datetime.datetime.now().isoformat()))
    await m.answer(f"Ключ:\n<code>{key}</code>", parse_mode="HTML")

async def run_bot():
    await dp.start_polling(bot)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    asyncio.run(run_bot())