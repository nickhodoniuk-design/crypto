import os
import asyncio
import logging
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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8955162722:AAHxL1wUUNMn6V8a_qZZnemEpEBD9U05tgo")
PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Надійні тестові питання зі стабільними картинками знаків
QUESTIONS = [
    {
        "id": 1,
        "image": "https://i.ibb.co/2kscs8v/roundabout.png",  # Круговий рух
        "question": "Хто має перевагу в русі під час проїзду перехрестя з круговим рухом?",
        "options": [
            "1. Той, хто заїжджає на кільце (перешкода праворуч)",
            "2. Той, хто вже рухається по колу",
            "3. Водій вантажного автомобіля",
            "4. Той, у кого більша швидкість"
        ],
        "correct": 1,
        "explanation": "📖 <b>Пункт 16.12 ПДР:</b> Перевага в русі на перехрестях, де організовано круговий рух, завжди належить транспортним засобам, які вже рухаються по колу!"
    },
    {
        "id": 2,
        "image": "https://i.ibb.co/L6V2YvW/yield-sign.png",  # Знак 2.1
        "question": "Що вимагає від водія знак 2.1 «Дати дорогу»?",
        "options": [
            "1. Обов'язково повністю зупинити автомобіль",
            "2. Дати дорогу транспортним засобам на головній дорозі",
            "3. Подати звуковий сигнал перед перехрестям",
            "4. Збільшити швидкість"
        ],
        "correct": 1,
        "explanation": "📖 <b>Знак 2.1 «Дати дорогу»:</b> Водій повинен дати дорогу ТЗ, що рухаються по головній дорозі. Повна зупинка обов'язкова лише у разі потреби пропустити авто."
    }
]

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚦 Пройти тест ПДР"), KeyboardButton(text="🚨 Зупинила поліція")],
            [KeyboardButton(text="📖 Штрафи та Довідник"), KeyboardButton(text="⭐️ PRO-режим (Іспит МВС)")]
        ],
        resize_keyboard=True
    )

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    welcome_text = (
        f"👋 Вітаємо, <b>{message.from_user.first_name}</b>!\n\n"
        "Це ваш персональний кишеньковий помічник водія України 🚗🇺🇦\n\n"
        "Оберіть потрібний розділ у меню нижче:\n"
        "• <b>🚦 Пройти тест ПДР</b> — тренування на офіційних схемах\n"
        "• <b>🚨 Зупинила поліція</b> — права водія та покрокові інструкції\n"
        "• <b>📖 Штрафи</b> — актуальні суми та статті законів\n"
        "• <b>⭐️ PRO-режим</b> — симулятор справжнього іспиту МВС"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode="HTML")


# ================= 1. ТЕСТИ ПДР (З ГНУЧКИМ ПОШУКОМ) =================
@dp.message(F.text.lower().contains("тест"))
async def start_quiz(message: types.Message):
    q = QUESTIONS[0]
    buttons = [
        [InlineKeyboardButton(text=f"Варіант {idx+1}", callback_data=f"ans_{q['id']}_{idx}")]
        for idx in range(len(q["options"]))
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    options_text = "\n".join(q["options"])
    caption = (
        f"❓ <b>Питання №{q['id']}:</b>\n\n"
        f"{q['question']}\n\n"
        f"<b>Варіанти відповідей:</b>\n{options_text}"
    )

    try:
        # Пробуємо надіслати з картинкою
        await message.answer_photo(
            photo=q["image"],
            caption=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception as e:
        logging.warning(f"Не вдалося завантажити фото, шлемо текстом: {e}")
        # Якщо картинка не відкрилася сервером Telegram — гарантовано шлемо текстом
        await message.answer(caption, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data.startswith("ans_"))
async def handle_answer(call: CallbackQuery):
    _, q_id, chosen_idx = call.data.split("_")
    q_id = int(q_id)
    chosen_idx = int(chosen_idx)

    question_data = next((q for q in QUESTIONS if q["id"] == q_id), None)
    if not question_data:
        await call.answer()
        return

    if chosen_idx == question_data["correct"]:
        result_text = "✅ <b>ПРАВИЛЬНО! Відмінна робота!</b>\n\n"
    else:
        result_text = f"❌ <b>НЕПРАВИЛЬНО!</b> Ви обрали варіант {chosen_idx+1}.\n\n"

    result_text += question_data["explanation"]

    next_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Наступне питання", callback_data="next_question")]
    ])
    
    await call.message.answer(result_text, reply_markup=next_btn, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "next_question")
async def next_question(call: CallbackQuery):
    q = QUESTIONS[1]
    buttons = [
        [InlineKeyboardButton(text=f"Варіант {idx+1}", callback_data=f"ans_{q['id']}_{idx}")]
        for idx in range(len(q["options"]))
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    options_text = "\n".join(q["options"])
    caption = (
        f"❓ <b>Питання №{q['id']}:</b>\n\n"
        f"{q['question']}\n\n"
        f"<b>Варіанти відповідей:</b>\n{options_text}"
    )

    try:
        await call.message.answer_photo(
            photo=q["image"],
            caption=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception:
        await call.message.answer(caption, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()


# ================= 2. ЗУПИНИЛА ПОЛІЦІЯ =================
def get_police_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛑 10 законних причин зупинки (ст. 35)", callback_data="police_reasons")],
        [InlineKeyboardButton(text="🍷 Тест на алкоголь / Драгер (Інструкція)", callback_data="police_drager")],
        [InlineKeyboardButton(text="🔍 Огляд авто чи Обшук? Ваші права", callback_data="police_search")],
        [InlineKeyboardButton(text="✍️ Що писати в протоколі при незгоді", callback_data="police_protocol")]
    ])

@dp.message(F.text.lower().contains("поліція"))
async def show_police_menu(message: types.Message):
    text = (
        "🚨 <b>Вас зупинив екіпаж патрульної поліції?</b>\n\n"
        "Зберігайте спокій, не виходьте з авто без законної вимоги і не віддавайте документи в руки — ви маєте право лише <b>пред'явити</b> їх (зокрема в «Дії»).\n\n"
        "Оберіть тему, яка вас цікавить прямо зараз:"
    )
    await message.answer(text, reply_markup=get_police_menu(), parse_mode="HTML")

@dp.callback_query(F.data == "police_reasons")
async def callback_police_reasons(call: CallbackQuery):
    text = (
        "🛑 <b>10 законних підстав зупинки авто (ст. 35 ЗУ «Про Нацполіцію»):</b>\n\n"
        "1. Порушення правил дорожнього руху.\n"
        "2. Очевидні ознаки технічної несправності авто.\n"
        "3. Інформація про причетність до ДТП чи правопорушення.\n"
        "4. Авто перебуває в розшуку.\n"
        "5. Опитування водія/пасажирів як свідків ДТП.\n"
        "6. Допомога іншим учасникам руху або поліцейським.\n"
        "7. Небезпечне кріплення вантажу.\n"
        "8. Порушення правил використання спецсигналів.\n"
        "9. Рішення про обмеження руху.\n"
        "10. Перевірка на блокпостах під час воєнного стану.\n\n"
        "❗️ <i>«Просто перевірка документів» поза межами блокпостів є незаконною.</i>"
    )
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "police_drager")
async def callback_police_drager(call: CallbackQuery):
    text = (
        "🍷 <b>Перевірка на алкоголь (Драгер):</b>\n\n"
        "1. <b>Вимагайте сертифікат</b> та свідоцтво про повірку приладу.\n"
        "2. Мундштук (трубка) має розпаковуватися <b>виключно у вашій присутності</b>.\n"
        "3. <b>Обов'язкова умова:</b> процедура проводиться у присутності <b>2 свідків</b> АБО під безперервний відеозапис нагрудної бодікамери патрульного.\n"
        "4. Якщо ви не згодні з цифрою Драгера — кажіть: <b>«З результатом не згоден, вимагаю огляду в медичному закладі»</b>.\n"
        "5. Поліція зобов'язана доставити вас до найближчої лікарні протягом 2 годин."
    )
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "police_search")
async def callback_police_search(call: CallbackQuery):
    text = (
        "🔍 <b>Поверхнева перевірка vs Обшук:</b>\n\n"
        "• <b>Поверхнева перевірка (ст. 34 ЗУ «Про Нацполіцію»):</b>\n"
        "Поліцейський має право лише <b>візуально оглянути</b> салон і багажник. При цьому водій <b>САМ</b> відкриває двері чи кришку багажника. Поліцейський НЕ має права торкатися ваших речей руками!\n\n"
        "• <b>Обшук:</b>\n"
        "Будь-яке порпання в речах — це обшук. Він дозволений лише на підставі ухвали слідчого судді або при затриманні за протоколом."
    )
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "police_protocol")
async def callback_police_protocol(call: CallbackQuery):
    text = (
        "✍️ <b>Що писати в постанові/протоколі при незгоді:</b>\n\n"
        "У графі для пояснень особи напишіть:\n\n"
        "<code>«З постановою не згоден. Правил не порушував. Доказів вини інспектором не надано. Юридичної допомоги не забезпечено. Оскаржуватиму в суді.»</code>\n\n"
        "У вас є <b>10 днів</b> на оскарження штрафу з дня винесення постанови."
    )
    await call.message.answer(text, parse_mode="HTML")
    await call.answer()


# ================= 3. ТАБЛИЦЯ ШТРАФІВ =================
@dp.message(F.text.lower().contains("штраф") | F.text.lower().contains("довідник"))
async def show_fines(message: types.Message):
    fines_text = (
        "📖 <b>Популярні штрафи за порушення ПДР в Україні:</b>\n\n"
        "• <b>Непристебнутий ремінь / без шолома:</b> 510 грн\n"
        "• <b>Розмова телефоном без hands-free:</b> 510 грн\n"
        "• <b>Перевищення швидкості (20–50 км/год):</b> 340 грн\n"
        "• <b>Перевищення швидкості (> 50 км/год):</b> 1 700 грн\n"
        "• <b>Проїзд на червоне світло:</b> 510 грн\n"
        "• <b>Ненадання переваги пішоходам:</b> 340 грн\n"
        "• <b>Створення аварійної обстановки:</b> 1 445 грн або позбавлення прав на 6-12 міс.\n"
        "• <b>Керування напідпитку (ст. 130 КУпАП):</b>\n"
        "  1-й раз — <b>17 000 грн</b> + позбавлення прав на 1 рік.\n"
        "  2-й раз — <b>34 000 грн</b> + позбавлення на 3 роки.\n\n"
        "💡 <i>Підказка: якщо сплатити штраф за автофіксацію протягом 10 днів — діє знижка 50%!</i>"
    )
    await message.answer(fines_text, parse_mode="HTML")


# ================= 4. PRO-РЕЖИМ (ГНУЧКИЙ ФІЛЬТР) =================
@dp.message(F.text.lower().contains("pro") | F.text.lower().contains("про"))
async def show_pro(message: types.Message):
    pro_text = (
        "⭐️ <b>Преміум підготовка до іспиту в ТСЦ МВС:</b>\n\n"
        "Звичайна підготовка займає місяці. PRO-режим гарантує складання з 1-ї спроби:\n\n"
        "🎯 <b>Симулятор реального іспиту МВС:</b> 20 випадкових питань, таймер 20 хвилин, максимум 2 помилки.\n"
        "🧠 <b>Розумна робота над помилками:</b> бот запам'ятовує питання, де ви збилися, і тренує вас лише по них.\n"
        "💡 <b>ШІ-пояснення:</b> особистий віртуальний автоінструктор розбере будь-яке складне перехрестя.\n\n"
        "💰 <b>Вартість повного доступу:</b> всього 99 грн (назавжди)!"
    )
    buy_btn = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Отримати PRO за 99 грн", callback_data="buy_pro")]
    ])
    await message.answer(pro_text, reply_markup=buy_btn, parse_mode="HTML")

@dp.callback_query(F.data == "buy_pro")
async def callback_buy_pro(call: CallbackQuery):
    await call.message.answer(
        "🚀 Тут підключається оплата через <b>Telegram Stars</b> або <b>Monobank</b>!\n\n"
        "Користувач сплачує 99 грн — і бот автоматично відкриває необмежений доступ до екзаменатора.",
        parse_mode="HTML"
    )
    await call.answer()


# ================= ВЕБСЕРВЕР ДЛЯ RENDER =================
async def handle_ping(request):
    return web.Response(text="PDR Ukraine Bot is Running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Вебсервер активний на порті {PORT}")

async def main():
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
