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
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "ВСТАВТЕ_GROQ_КЛЮЧ_ТУТ")
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


async def rewrite_news(title: str, summary: str, link: str) -> str:
    prompt = f"""
    Ти — редактор крутого українського новинного каналу.
    Зроби органічний, цікавий та лаконічний пост на основі новини.
    
    Заголовок: {title}
    Опис: {summary}
    Посилання: {link}

    Вимоги:
    1. Перший рядок: привабливий заголовок українською мовою з емодзі.
    2. Порожній рядок.
    3. Коротко суть (2-3 пункти через маркер •).
    4. В кінці окремим рядком: [Читати повністю]({link})
    """
    response = await groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=400,
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
