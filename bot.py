import os
import re
import asyncio
import logging
import hashlib
import tempfile
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery,
    FSInputFile
)
import yt_dlp

# ================= КОНФІГУРАЦІЯ =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "СЮДИ_ТОКЕН_ЯКЩО_НЕ_В_ENVIRONMENT")
PORT = int(os.getenv("PORT", 8080))

# ================= РЕКЛАМНИЙ БЛОК (СПОНСОР) =================
# Змініть посилання на свій канал або юзернейм для замовлення реклами
DEFAULT_AD = (
    "🔥 <b>Спонсор:</b> Найвигідніші знижки та товари 👉 <a href='https://t.me/telegram'>Перейти в канал</a>\n"
    "<i>(Купити рекламу в боті: @ваш_юзернейм)</i>"
)
AD_BANNER = os.getenv("AD_BANNER", DEFAULT_AD)
# ============================================================

# Швидка пам'ять для прив'язки кнопок аудіо до посилань
URL_CACHE = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# Регулярний вираз для перехоплення посилань із соцмереж
URL_PATTERN = re.compile(
    r'(https?://(?:www\.)?(?:tiktok\.com|instagram\.com|pinterest\.com|pin\.it|youtube\.com/shorts/|youtu\.be)[^\s]+)'
)


# ================= ВІТАЛЬНЕ ПОВІДОМЛЕННЯ (/start) =================
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    welcome_text = (
        f"👋 <b>Привіт, {message.from_user.first_name}!</b>\n\n"
        "Я твій швидкий помічник для збереження медіа без водяних знаків та очікування 🚀\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🌟 <b>ЩО Я ВМІЮ:</b>\n"
        "• 📱 <b>TikTok</b> — ролики у вихідній якості без логотипів\n"
        "• 📸 <b>Instagram</b> — Reels, відео та кліпи\n"
        "• 🔴 <b>YouTube Shorts</b> — ролики в один клік\n"
        "• 📌 <b>Pinterest</b> — відео та пін-ідеї\n"
        "• 🎵 <b>Екстрактор звуку</b> — кнопка для завантаження окремого треку (MP3) під кожним відео!\n"
        "• ⚡️ <b>Великі файли</b> — якщо відео важить більше 50 МБ, я дам пряме посилання на завантаження.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 <b>ЯК КОРИСТУВАТИСЬ (всього 2 кроки):</b>\n"
        "1. У TikTok, Instagram чи YouTube натисни кнопку <b>«Поділитися»</b> ➡️ <b>«Копіювати посилання»</b>.\n"
        "2. Просто <b>надішли це посилання сюди</b> в чат.\n\n"
        "<i>За кілька секунд я надішлю тобі чисте відео! Спробуй прямо зараз 👇</i>"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Наш канал / Спонсор", url="https://t.me/telegram")],
        [InlineKeyboardButton(text="💬 Зв'язок / Реклама", url="https://t.me/ваш_юзернейм")]
    ])

    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")


# ================= ФОНОВІ ФУНКЦІЇ ЗАВАНТАЖЕННЯ =================
def download_video_sync(url: str, download_dir: str):
    ydl_opts = {
        'outtmpl': os.path.join(download_dir, '%(id)s.%(ext)s'),
        # Розумний підбір якості: намагаємось вписатися в ліміт 50 МБ Telegram
        'format': 'bestvideo[filesize_approx<48M][ext=mp4]+bestaudio[ext=m4a]/best[filesize_approx<48M][ext=mp4]/best[height<=720]/best',
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if not f.endswith('.part')]
        video_path = files[0] if files else None
        direct_url = info.get('url') or url
        return video_path, info.get('title', 'Відео'), direct_url


def download_audio_sync(url: str, download_dir: str):
    ydl_opts = {
        'outtmpl': os.path.join(download_dir, '%(id)s.%(ext)s'),
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if not f.endswith('.part')]
        audio_path = files[0] if files else None
        return audio_path, info.get('title', 'Аудіотрек')


# ================= ОБРОБКА ПОСИЛАНЬ =================
@dp.message(F.text.regexp(URL_PATTERN))
async def handle_media_url(message: types.Message):
    url = URL_PATTERN.search(message.text).group(1)
    status_msg = await message.reply("⏳ <b>Завантажую та оптимізую відео...</b>", parse_mode="HTML")

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            video_path, title, direct_url = await asyncio.to_thread(download_video_sync, url, temp_dir)

            if not video_path or not os.path.exists(video_path):
                await status_msg.edit_text("❌ Не вдалося зберегти відео. Спробуйте інше посилання.")
                return

            file_size_mb = os.path.getsize(video_path) / (1024 * 1024)

            # Генеруємо короткий ключ для кнопки аудіо
            url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
            URL_CACHE[url_hash] = url

            clean_title = re.sub(r'<[^>]+>', '', title)[:80]

            # ЯКЩО ФАЙЛ БІЛЬШИЙ ЗА 49.5 МБ — НАДСИЛАЄМО КНОПКУ ПРЯМОГО СКАЧУВАННЯ
            if file_size_mb > 49.5:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📥 Завантажити напряму на телефон", url=direct_url)],
                    [InlineKeyboardButton(text="🎵 Отримати лише аудіо (MP3)", callback_data=f"audio_{url_hash}")]
                ])
                text = (
                    f"🎬 <b>{clean_title}</b>\n\n"
                    f"⚠️ <b>Відео важить {file_size_mb:.1f} МБ</b> (Telegram не дозволяє ботам надсилати файли понад 50 МБ).\n\n"
                    f"Ви можете безкоштовно завантажити його у вихідній якості через браузер:\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"{AD_BANNER}"
                )
                await message.reply(text, reply_markup=keyboard, parse_mode="HTML")
                await status_msg.delete()
                return

            # ЯКЩО ФАЙЛ ВПИСАВСЯ В ЛІМІТ — ВІДПРАВЛЯЄМО ВІДЕО В ЧАТ
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎵 Завантажити лише аудіо (MP3)", callback_data=f"audio_{url_hash}")]
            ])

            caption = (
                f"🎬 <b>{clean_title}</b>\n\n"
                f"✨ <i>Завантажено без водяних знаків ({file_size_mb:.1f} МБ)</i>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{AD_BANNER}"
            )

            video_file = FSInputFile(video_path)
            await message.reply_video(
                video=video_file, 
                caption=caption, 
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await status_msg.delete()

        except Exception as e:
            logging.error(f"Помилка завантаження: {e}")
            await status_msg.edit_text(
                "❌ <b>Помилка:</b> не вдалося обробити це відео.\n"
                "<i>(Можливо, профіль автора приватний або відео було видалено)</i>",
                parse_mode="HTML"
            )


# ================= ОБРОБКА КНОПКИ АУДІО =================
@dp.callback_query(F.data.startswith("audio_"))
async def extract_audio_callback(call: CallbackQuery):
    url_hash = call.data.split("_")[1]
    url = URL_CACHE.get(url_hash)

    # Якщо пам'ять оновилася — шукаємо посилання в повідомленні, на яке була відповідь
    if not url and call.message.reply_to_message and call.message.reply_to_message.text:
        match = URL_PATTERN.search(call.message.reply_to_message.text)
        if match:
            url = match.group(1)

    if not url:
        await call.answer("⚠️ Посилання застаріло. Надішліть відео ще раз!", show_alert=True)
        return

    await call.answer("⏳ Витягую музику...")
    wait_msg = await call.message.reply("🎵 Конвертую оригінальне аудіо...", parse_mode="HTML")

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            audio_path, title = await asyncio.to_thread(download_audio_sync, url, temp_dir)
            
            if not audio_path or not os.path.exists(audio_path):
                await wait_msg.edit_text("❌ Не вдалося знайти аудіодоріжку.")
                return

            audio_file = FSInputFile(audio_path)
            clean_title = re.sub(r'<[^>]+>', '', title)[:60]
            
            audio_caption = (
                f"🎧 <b>{clean_title}</b>\n"
                f"✨ <i>Оригінальний звук</i>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{AD_BANNER}"
            )

            await call.message.reply_audio(
                audio=audio_file,
                title=clean_title,
                caption=audio_caption,
                parse_mode="HTML"
            )
            await wait_msg.delete()
        except Exception as e:
            logging.error(f"Помилка аудіо: {e}")
            await wait_msg.edit_text("❌ Не вдалося отримати аудіо.")


# ================= ВЕБСЕРВЕР ДЛЯ RENDER (ЖИТТЯ БОТА 24/7) =================
async def handle_ping(request):
    return web.Response(text="Media Downloader Bot is Running 24/7!")

async def start_web_server():
    app = web.Application()
    a
