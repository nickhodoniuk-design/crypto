import os
import asyncio
import logging
import feedparser
import aiosqlite
from aiohttp import web
from aiogram import Bot
from groq import AsyncGroq

# Читаємо змінні з Render (або якщо їх немає — використовуємо запасні значення)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8955162722:AAHxL1wUUNMn6V8a_qZZnemEpEBD9U05tgo")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@crypsignalsa")

# Порт для Render (обов'язково для безкоштовного тарифу Web Service)
PORT = int(os.getenv("PORT", 8080))

RSS_FEEDS = [
    "https://mezha.media/feed/",
    "https://itc.ua/ua/feed/",
]

CHECK_INTERVAL_SECONDS = 1800 
DATABASE_NAME = "news_history.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
bot = Bot(token=TELEGRAM_BOT_TOKEN)
groq_client = AsyncGroq(api_key=GROQ_API_KEY)


async def init_db():
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posted_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash TEXT UNIQUE
            )
        """)
        await db.commit()


async def is_news_posted(url: str) -> bool:
    async with aiosqlite.connect(DATABASE_NAME) as db:
        cursor = await db.execute("SELECT 1 FROM posted_news WHERE url_hash = ?", (url,))
        result = await cursor.fetchone()
        return result is not None


async def mark_news_as_posted(url: str):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO posted_news (url_hash) VALUES (?)", (url,))
        await db.commit()


# ШІ-редактор: образний переказ без посилань у стилі крутого Telegram-каналу
async def rewrite_news(title: str, summary: str, link: str) -> str:
    prompt = f"""
    Ти — автор популярного, стильного українського Telegram-каналу з власною харизмою та легким гумором.
    Твоє завдання — взяти суху новину і образно, цікаво та своїми словами переказати її для підписників.

    Вхідні дані:
    Тема: {title}
    Деталі події: {summary}

    СУВОРІ ПРАВИЛА:
    1. ЖОДНИХ ПОСИЛАНЬ ТА ДЖЕРЕЛ! Взагалі не пиши URL-адрес і не згадуй сайти (не пиши "за даними видання", "читайте за лінком" тощо). Текст має виглядати як твій особистий авторський пост.
    2. Стиль: жива мова, легка образність, метафори, без сухої нудної журналістики та канцелярщини.
    3. Структура поста:
       • **Заголовок**: яскравий, чіпляючий, жирним шрифтом з одним класним емодзі.
       • Порожній рядок.
       • **Суть**: 2-3 короткі, динамічні абзаци, які читаються на одному диханні.
       • Порожній рядок.
       • **Фінал**: коротка влучна думка, іронічний коментар або питання до аудиторії.
    4. Мова: виключно соковита, грамотна українська мова.
    """

    response = await groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.75,  # Трохи більше креативності для образності
        max_tokens=500,
    )
    return response.choices[0].message.content


async def news_worker():
    while True:
        logging.info("Перевірка новин...")
        posted = False

        for feed_url in RSS_FEEDS:
            if posted:
                break
            parsed_feed = feedparser.parse(feed_url)

            for entry in parsed_feed.entries:
                link = entry.link
                title = entry.title
                summary = getattr(entry, "summary", "")

                if not await is_news_posted(link):
                    logging.info(f"Свіжа новина: {title}")
                    try:
                        text = await rewrite_news(title, summary, link)
                        await bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="Markdown")
                        await mark_news_as_posted(link)
                        logging.info("Успішно опубліковано!")
                        posted = True
                        break
                    except Exception as e:
                        logging.error(f"Помилка публікації: {e}")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# Фіктивний вебсервер, щоб Render бачив живий порт і не вбивав бота
async def handle_ping(request):
    return web.Response(text="Bot is running!")


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
    # Запускаємо вебсервер для Render і воркер новин одночасно
    await asyncio.gather(
        start_web_server(),
        news_worker()
    )


if __name__ == "__main__":
    asyncio.run(main())
