import asyncio
import logging
import feedparser
import aiosqlite
from aiogram import Bot
from groq import AsyncGroq

# ================= НАЛАШТУВАННЯ (0 ГРИВЕНЬ) =================
# 1. Твій токен від BotFather
TELEGRAM_BOT_TOKEN = "СЮДИ_ВСТАВ_ТОКЕН_ВІД_BOTFATHER"

# 2. Твій канал (юзернейм типу "@my_channel" або ID)
CHANNEL_ID = "@СЮДИ_НАЗВУ_КАНАЛУ"

# 3. Безкоштовний ключ від Groq (починається на gsk_...)
GROQ_API_KEY = "СЮДИ_ВСТАВ_GROQ_КЛЮЧ"

# RSS-стрічки новин (можеш міняти на будь-які українські сайти)
RSS_FEEDS = [
    "https://mezha.media/feed/",   # Новини технологій та гаджетів
    "https://itc.ua/ua/feed/",     # IT та техніка
]

# Пауза між публікаціями: 1800 сек = 30 хвилин (можеш змінити, наприклад, на 3600 = 1 година)
CHECK_INTERVAL_SECONDS = 1800 

DATABASE_NAME = "news_history.db"
# ==========================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
bot = Bot(token=TELEGRAM_BOT_TOKEN)
groq_client = AsyncGroq(api_key=GROQ_API_KEY)


# Створення локальної бази даних для пам'яті новин
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


# Безкоштовний ШІ-редактор на базі моделі Llama 3.3 від Meta
async def rewrite_news(title: str, summary: str, link: str) -> str:
    prompt = f"""
    Ти — редактор крутого українського новинного каналу.
    Зроби органічний, цікавий та лаконічний пост на основі новини.
    
    Заголовок новини: {title}
    Короткий опис: {summary}
    Посилання: {link}

    Вимоги до поста:
    1. Перший рядок: привабливий заголовок українською мовою з емодзі.
    2. Порожній рядок.
    3. Коротко суть (2-3 пункти через маркер •). Без клікбейту і "води".
    4. В кінці окремим рядком: [Читати повністю]({link})
    """

    response = await groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",  # Потужна і повністю безкоштовна модель
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=400,
    )
    return response.choices[0].message.content


# Головний процес роботи
async def news_worker():
    while True:
        logging.info("Перевіряю стрічки новин на наявність свіжого...")
        posted_in_this_round = False

        for feed_url in RSS_FEEDS:
            if posted_in_this_round:
                break

            parsed_feed = feedparser.parse(feed_url)

            for entry in parsed_feed.entries:
                link = entry.link
                title = entry.title
                summary = getattr(entry, "summary", "")

                # Якщо новини ще не було в каналі
                if not await is_news_posted(link):
                    logging.info(f"Знайдено нову новину: {title}")

                    try:
                        # ШІ переписує пост
                        post_text = await rewrite_news(title, summary, link)

                        # Відправляємо в канал
                        await bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=post_text,
                            parse_mode="Markdown",
                            disable_web_page_preview=False
                        )

                        await mark_news_as_posted(link)
                        logging.info("Пост успішно опубліковано в канал!")

                        # Робимо паузу, щоб не постити 10 штук одночасно
                        posted_in_this_round = True
                        break

                    except Exception as e:
                        logging.error(f"Помилка при публікації: {e}")

        logging.info(f"Чекаємо {CHECK_INTERVAL_SECONDS // 60} хвилин перед наступним постом...")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def main():
    await init_db()
    logging.info("Бот запущений і працює!")
    await news_worker()


if __name__ == "__main__":
    asyncio.run(main())
    
