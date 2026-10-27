import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
import pytz
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from groq import AsyncGroq
import aiosqlite

# ================= КОНФІГУРАЦІЯ =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8955162722:AAHxL1wUUNMn6V8a_qZZnemEpEBD9U05tgo")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
PORT = int(os.getenv("PORT", 8080))

KYIV_TZ = pytz.timezone("Europe/Kyiv")
DB_NAME = "reminders.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
groq_client = AsyncGroq(api_key=GROQ_API_KEY)


# ================= БАЗА ДАНИХ =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT,
                category TEXT,
                trigger_time TEXT,
                repeat_type TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.commit()


# ================= СТАНИ FSM =================
class ReminderForm(StatesGroup):
    waiting_for_text = State()


# ================= ГОЛОВНЕ МЕНЮ =================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Створити нагадування"), KeyboardButton(text="📋 Мої нагадування")],
            [KeyboardButton(text="🎂 Дні народження"), KeyboardButton(text="🚗 Авто & ТО")],
            [KeyboardButton(text="💡 Комуналка & Рахунки")]
        ],
        resize_keyboard=True
    )


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await init_db()
    text = (
        f"👋 Привіт, <b>{message.from_user.first_name}</b>!\n\n"
        "Я твій розумний персональний помічник-нагадувальник 🧠\n\n"
        "Я розумію <b>звичайну людську мову</b>. Ти можеш просто написати мені:\n"
        "• <i>«Завтра о 15:00 забрати посилку»</i>\n"
        "• <i>«1 числа щомісяця передати показники світла о 09:00»</i>\n"
        "• <i>«18 серпня день народження у брата, нагадувати щороку»</i>\n"
        "• <i>«Заміна мастила через 5 місяців»</i>\n\n"
        "Обери категорію нижче або просто напиши повідомлення!"
    )
    await message.answer(text, reply_markup=get_main_keyboard(), parse_mode="HTML")


# ================= ШІ-ПАРСИНГ ЗВИЧАЙНОЇ МОВИ =================
async def parse_reminder_with_ai(user_text: str) -> dict | None:
    now = datetime.now(KYIV_TZ)
    current_time_str = now.strftime("%Y-%m-%d %H:%M (%A)")

    prompt = f"""
    Ти — точний парсер нагадувань. Твоя задача — отримати людський текст українською та витягти з нього дату, час і суть нагадування.
    
    Поточний точний час і дата зараз в Україні: {current_time_str}.
    
    Текст користувача: "{user_text}"
    
    ПРАВИЛА РОЗРАХУНКУ:
    1. Якщо рік не вказано, а дата вже минула в цьому році — бери наступний рік.
    2. Якщо час не вказано, став за замовчуванням 09:00 ранку.
    3. Типи повторення:
       - "none" (разове)
       - "monthly" (щомісяця, наприклад комуналка)
       - "yearly" (щороку, наприклад дні народження, свята)
       - "daily" (щодня)
    4. Категорії: "birthday", "car", "utility", "general".
    
    ВІДПОВІДЬ НАДАЙ ВИКЛЮЧНО У ФОРМАТІ ЧИСТОГО JSON БЕЗ ЗАЙВИХ СЛІВ І БЕЗ БЛОКІВ КОДУ:
    {{
        "title": "Коротка суть нагадування",
        "datetime": "YYYY-MM-DD HH:MM",
        "repeat": "none|monthly|yearly|daily",
        "category": "birthday|car|utility|general"
    }}
    """

    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200
        )
        content = response.choices[0].message.content.strip()
        # Очищуємо від можливих markdown-лапок
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return json.loads(content.strip())
    except Exception as e:
        logging.error(f"Помилка парсингу ШІ: {e}")
        return None


# ================= ОБРОБКА ПОВІДОМЛЕНЬ =================
@dp.message(F.text == "➕ Створити нагадування")
async def ask_for_reminder(message: types.Message, state: FSMContext):
    await message.answer(
        "✍️ Напишіть мені будь-яке нагадування своїми словами.\n\n"
        "<i>Наприклад:\n"
        "• «Завтра о 10:00 зателефонувати юристу»\n"
        "• «14 травня день народження мами»\n"
        "• «Заміна мастила через 6 місяців»</i>",
        parse_mode="HTML"
    )
    await state.set_state(ReminderForm.waiting_for_text)


# Швидкі шаблони
@dp.message(F.text == "🎂 Дні народження")
async def template_birthday(message: types.Message):
    await message.answer(
        "🎂 <b>Додавання дня народження:</b>\n\n"
        "Напишіть, наприклад:\n"
        "<code>День народження Андрія 25 вересня о 09:00</code>\n\n"
        "<i>Я автоматично запам'ятаю дату і повторюватиму її щороку!</i>",
        parse_mode="HTML"
    )

@dp.message(F.text == "🚗 Авто & ТО")
async def template_car(message: types.Message):
    await message.answer(
        "🚗 <b>Автомобільні нагадування:</b>\n\n"
        "Напишіть будь-що, наприклад:\n"
        "• <code>Заміна мастила та фільтрів через 6 місяців</code>\n"
        "• <code>Закінчується автоцивілка 1 грудня</code>\n"
        "• <code>Перевзути зимову гуму 15 листопада</code>",
        parse_mode="HTML"
    )

@dp.message(F.text == "💡 Комуналка & Рахунки")
async def template_utility(message: types.Message):
    await message.answer(
        "💡 <b>Комуналка та щомісячні рахунки:</b>\n\n"
        "Напишіть, наприклад:\n"
        "• <code>1 числа щомісяця о 09:00 передати показники газу і води</code>\n"
        "• <code>18 числа щомісяця сплатити комунальні послуги</code>\n"
        "• <code>Оплата інтернету 25 числа щомісяця</code>",
        parse_mode="HTML"
    )


# Універсальний обробник тексту (працює завжди, коли користувач щось пише)
@dp.message(F.text & ~F.text.startswith("/"))
async def process_reminder_text(message: types.Message, state: FSMContext):
    if message.text in ["➕ Створити нагадування", "📋 Мої нагадування", "🎂 Дні народження", "🚗 Авто & ТО", "💡 Комуналка & Рахунки"]:
        return

    wait_msg = await message.answer("⏳ Аналізую дату і час...")
    data = await parse_reminder_with_ai(message.text)

    if not data or "datetime" not in data or "title" not in data:
        await wait_msg.edit_text(
            "❌ Не вдалося розпізнати точну дату або час.\n"
            "Спробуйте написати чіткіше, наприклад: <i>«Завтра о 14:00 зустріч»</i> або <i>«1 травня о 09:00 день народження»</i>.",
            parse_mode="HTML"
        )
        return

    # Зберігаємо в базу даних
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO reminders (user_id, title, category, trigger_time, repeat_type)
            VALUES (?, ?, ?, ?, ?)
        """, (message.from_user.id, data["title"], data.get("category", "general"), data["datetime"], data.get("repeat", "none")))
        await db.commit()

    repeat_labels = {
        "none": "Один раз",
        "daily": "Щодня",
        "monthly": "Щомісяця",
        "yearly": "Щороку"
    }

    success_text = (
        "✅ <b>Нагадування успішно створено!</b>\n\n"
        f"📌 <b>Суть:</b> {data['title']}\n"
        f"📅 <b>Коли:</b> {data['datetime']}\n"
        f"🔁 <b>Повторення:</b> {repeat_labels.get(data.get('repeat', 'none'), 'Немає')}\n\n"
        "<i>Я надішлю вам повідомлення у вказаний момент!</i>"
    )
    await wait_msg.edit_text(success_text, parse_mode="HTML")
    await state.clear()


# ================= ПЕРЕГЛЯД ТА ВИДАЛЕННЯ =================
@dp.message(F.text == "📋 Мої нагадування")
async def list_reminders(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT id, title, trigger_time, repeat_type 
            FROM reminders 
            WHERE user_id = ? AND is_active = 1 
            ORDER BY trigger_time ASC
        """, (message.from_user.id,))
        rows = await cursor.fetchall()

    if not rows:
        await message.answer("📭 У вас поки що немає активних нагадувань. Створіть перше!")
        return

    text = "📋 <b>Ваші активні нагадування:</b>\n\n"
    buttons = []
    for r_id, title, trig_time, repeat in rows:
        repeat_mark = "🔁" if repeat != "none" else "⏳"
        text += f"• <b>{trig_time}</b>: {title} ({repeat_mark})\n"
        buttons.append([InlineKeyboardButton(text=f"❌ Видалити: {title[:20]}", callback_data=f"del_{r_id}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("del_"))
async def delete_reminder(call: CallbackQuery):
    r_id = int(call.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE reminders SET is_active = 0 WHERE id = ? AND user_id = ?", (r_id, call.from_user.id))
        await db.commit()
    
    await call.answer("Видалено!")
    await call.message.edit_text("✅ Нагадування видалено.")


# ================= ФОНОВИЙ ПЕРЕВІРНИК ТА СПОВІЩУВАЧ =================
async def reminder_scheduler():
    while True:
        try:
            now_str = datetime.now(KYIV_TZ).strftime("%Y-%m-%d %H:%M")
            async with aiosqlite.connect(DB_NAME) as db:
                cursor = await db.execute("""
                    SELECT id, user_id, title, trigger_time, repeat_type 
                    FROM reminders 
                    WHERE trigger_time <= ? AND is_active = 1
                """, (now_str,))
                due_reminders = await cursor.fetchall()

                for r_id, u_id, title, trig_time, repeat in due_reminders:
                    # Надсилаємо нагадування користувачу
                    try:
                        alert_text = (
                            "🔔 <b>НАГАДУВАННЯ!</b>\n\n"
                            f"📌 <b>{title}</b>\n\n"
                            f"<i>Час: {trig_time}</i>"
                        )
                        await bot.send_message(chat_id=u_id, text=alert_text, parse_mode="HTML")
                    except Exception as e:
                        logging.error(f"Помилка відправки користувачу {u_id}: {e}")

                    # Обробляємо повторення
                    if repeat == "none":
                        await db.execute("UPDATE reminders SET is_active = 0 WHERE id = ?", (r_id,))
                    else:
                        dt = datetime.strptime(trig_time, "%Y-%m-%d %H:%M")
                        if repeat == "daily":
                            next_dt = dt + timedelta(days=1)
                        elif repeat == "monthly":
                            # Переносимо на 30 днів вперед
                            next_dt = dt + timedelta(days=30)
                        elif repeat == "yearly":
                            # Переносимо на наступний рік
                            next_dt = dt.replace(year=dt.year + 1)
                        else:
                            next_dt = dt

                        next_time_str = next_dt.strftime("%Y-%m-%d %H:%M")
                        await db.execute("UPDATE reminders SET trigger_time = ? WHERE id = ?", (next_time_str, r_id))

                await db.commit()

        except Exception as e:
            logging.error(f"Помилка в планувальнику: {e}")

        # Перевіряємо щохвилини
        await asyncio.sleep(40)


# ================= ВЕБСЕРВЕР ДЛЯ RENDER =================
async def handle_ping(request):
    return web.Response(text="Smart Reminder Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Вебсервер запущено на порті {PORT}")

async def main():
    await init_db()
    await asyncio.gather(
        start_web_server(),
        reminder_scheduler(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
