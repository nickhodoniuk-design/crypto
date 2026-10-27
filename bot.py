import os
import re
import asyncio
import logging
import feedparser
import aiosqlite
from aiohttp import web
from aiogram import Bot
from groq import AsyncGroq

# Налаштування змінних (читаються з Render або з коду)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8955162722:AAHxL1wUUNMn6V8a_qZZnemEpEBD9U05tgo")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@crypsignalsa")
PORT = int(os.getenv("PORT", 8080))

# ТОП українські джерела: економіка, фінанси, війна, суспільство
RSS_FEEDS = [
    "https://www.epravda.com.ua/rss/",       # Економічна правда (гроші, бізнес, енергетика)
    "https://minfin.com.ua/rss/news/",       # Мінфін (курси валют, виплати, банки, кредити)
    "https://suspilne.media/rss/news.xml",   # Суспільне (люди, фронт, життя країни)
    "https://www.pravda.com.ua/rss/",        # Українська правда (головні події)
]

# Інтервал між публікаціями: 1800 сек = 30 хвилин
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


# Функція витягування фотографії зі стрічки новини
def extract_image(entry) -> str | None:
    # 1. Шукаємо у вкладеннях (enclosures)
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href')
    # 2. Шукаємо в media_content
    if hasattr(entry, 'media_content') and entry.media_content:
        for media in entry.media_content:
            if 'url' in media:
                return media['url']
    # 3. Шукаємо тег <img> у тексті опису
    html_content = getattr(entry, 'summary', '')
    match = re.search(r'<img[^>]+src=["\'](http[^"\']+)["\']', html_content)
    if match:
        return match.group(1)
    return None


# ШІ-редактор новин України
async def rewrite_news(title: str, summary: str) -> str:
    # Очищуємо вхідний опис від зайвих HTML тегів
    clean_summary = re.sub(r'<[^>]+>', '', summary)

    prompt = f"""
    Ти — автор провідного українського Telegram-каналу про реальне життя в країні: людей, економіку, фінанси та війну.
    Твоя задача — образно, змістовно та зрозуміло переказати цю подію для простих людей.

    Тема: {title}
    Опис події: {clean_summary}

    ПРАВИЛА:
    1. ЖОДНИХ ПОСИЛАНЬ ТА ДЖЕРЕЛ! Не пиши "за інформацією ЗМІ", "як повідомляє..." тощо.
    2. Тональність:
       - Якщо новина про війну/обстріли/людей — пиши серйозно, зі співчуттям та повагою. Жодних недоречних жартів.
       - Якщо новина про економіку, виплати, ціни, податки, курс валют — поясни людською мовою, як це вплине на гаманці звичайних українців.
    3. Оформлення (Telegram-стиль):
       - Перший рядок: сильний, чіпляючий заголовок з доречним емодзі (наприклад: 🇺🇦, 📉, 💰, ⚡️).
       - Порожній рядок.
       - Основна суть: 2-3 короткі абзаци (максимум до 700 символів загалом, текст має бути компактним!).
       - Фінальний рядок: висновок або важливий акцент.
    """

    response = await groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=400,
    )
    return response.choices[0].message.content


async def news_worker():
    while True:
        logging.info("Моніторимо новини України (економіка, суспільство, війна)...")
        posted = False

        for feed_url in RSS_FEEDS:
            if posted:
                break
            
            try:
                parsed_feed = feedparser.parse(feed_url)
            except Exception as e:
                logging.error(f"Не вдалося зчитати стрічку {feed_url}: {e}")
                continue

            for entry in parsed_feed.entries:
                link = entry.link
                title = entry.title
                summary = getattr(entry, "summary", "")

                if not await is_news_posted(link):
                    logging.info(f"Свіжа новина: {title}")
                    try:
                        post_text = await rewrite_news(title, summary)
                        image_url = extract_image(entry)

                        # Обрізаємо текст до 1024 символів (ліміт Telegram для підпису до фото)
                        if len(post_text) > 1020:
                            post_text = post_text[:1015] + "..."

                        # Якщо є картинка — шлемо фото з підписом
                        if image_url:
                            try:
                                await bot.send_photo(
                                    chat_id=CHANNEL_ID,
                                    photo=image_url,
                                    caption=post_text,
                                    parse_mode="Markdown"
                                )
                            except Exception:
                                # Якщо раптом лінк на фото не спрацював — шлемо як звичайний текст
                                await bot.send_message(chat_id=CHANNEL_ID, text=post_text, parse_mode="Markdown")
                        else:
                            # Якщо картинки в новині не було
                            await bot.send_message(chat_id=CHANNEL_ID, text=post_text, parse_mode="Markdown")

                        await mark_news_as_posted(link)
                        logging.info("Пост з новиною успішно вийшов у каналі!")
                        posted = True
                        break

                    except Exception as e:
                        logging.error(f"Помилка публікації: {e}")

        # Пауза 30 хвилин для збереження органічності каналу
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def handle_ping(request):
    return web.Response(text="Ukrainian News Bot is Live!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Вебсервер активний на порті {PORT}")


async def main():
    await init_db()
    await asyncio.gather(
        start_web_server(),
        news_worker()
    )


if __name__ == "__main__":
    asyncio.run(main())
