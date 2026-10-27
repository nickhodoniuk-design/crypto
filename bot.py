import os
import re
import asyncio
import logging
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

# ================= НАЛАШТУВАННЯ =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8955162722:AAHxL1wUUNMn6V8a_qZZnemEpEBD9U05tgo")
PORT = int(os.getenv("PORT", 8080))

# ================= РЕКЛАМНИЙ БЛОК (МІНЯЙТЕ ТУТ) =================
# Цей текст і посилання автоматично кріпляться під кожне завантажене відео та звук.
# Можна використовувати HTML: <b>жирний</b>, <i>курсив</i>, <a href="...">посилання</a>.
DEFAULT_AD = (
    "🔥 <b>Спонсор:</b> Найвигідніші знижки та товари 👉 <a href='https://t.me/telegram'>Перейти в канал</a>\n"
    "<i>(Купити рекламу в боті: @ваш_юзернейм)</i>"
)
AD_BANNER = os.getenv("AD_BANNER", DEFAULT_AD)
# ================================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

URL_PATTERN = re.compile(
    r'(https?://(?:www\.)?(?:tiktok\.com|instagram\.com|pinterest\.com|pin\.it|youtube\.com/shorts/|youtu\.be)[^\s]+)'
)


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    text = (
        f"👋 Привіт, <b>{message.from_user.first_name}</b>!\n\n"
        "Я завантажувач медіа без водяних знаків 🚀\n\n"
        "<b>Підтримувані соцмережі:</b>\n"
        "• <b>TikTok</b> (відео та звук)\n"
        "• <b>Instagram Reels</b>\n"
        "• <b>YouTube Shorts</b>\n"
        "• <b>Pinterest</b>\n\n"
        "Просто надішли мені <b>посилання</b> на відео!"
    )
    await message.answer(text, parse_mode="HTML")


def download_video_sync(url: str, download_dir: str):
    ydl_opts = {
        'outtmpl': os.path.join(download_dir, '%(id)s.%(ext)s'),
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'quiet': True,
        'no_warnings': True,
        'max_filesize': 50 * 1024 * 1024,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if not os.path.exists(filename):
            base, _ = os.path.splitext(filename)
            filename = f"{base}.mp4"
        return filename, info.get('title', 'Відео')


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
        filename = ydl.prepare_filename(info)
        return filename, info.get('title', 'Аудіодоріжка')


@dp.message(F.text.regexp(URL_PATTERN))
async def handle_media_url(message: types.Message):
    url = URL_PATTERN.search(message.text).group(1)
    status_msg = await message.answer("⏳ <b>Завантажую відео без водяних знаків...</b>", parse_mode="HTML")

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            video_path, title = await asyncio.to_thread(download_video_sync, url, temp_dir)

            if not os.path.exists(video_path):
                await status_msg.edit_text("❌ Не вдалося зберегти відео.")
                return

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎵 Завантажити лише аудіо (MP3)", callback_data="get_audio")]
            ])

            # Формуємо підпис: Назва + Галочка + Рекламний блок
            clean_title = re.sub(r'<[^>]+>', '', title)[:80]
            caption = (
                f"🎬 <b>{clean_title}</b>\n\n"
                f"✨ <i>Завантажено без водяних знаків</i>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{AD_BANNER}"
            )
            
            video_file = FSInputFile(video_path)
            await message.answer_video(
                video=video_file, 
                caption=caption, 
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await status_msg.delete()

        except Exception as e:
            logging.error(f"Помилка завантаження: {e}")
            await status_msg.edit_text(
                "❌ <b>Помилка:</b> не вдалося завантажити це відео.\n"
                "<i>(Можливо, акаунт автора приватний або файл більший за 50 МБ)</i>",
                parse_mode="HTML"
            )


@dp.callback_query(F.data == "get_audio")
async def extract_audio_callback(call: CallbackQuery):
    orig_msg = call.message.reply_to_message
    if not orig_msg or not orig_msg.text:
        await call.answer("Не вдалося знайти посилання", show_alert=True)
        return

    url = URL_PATTERN.search(orig_msg.text).group(1)
    await call.answer("⏳ Витягую аудіо...")
    wait_msg = await call.message.answer("🎵 Конвертую аудіо...")

    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            audio_path, title = await asyncio.to_thread(download_audio_sync, url, temp_dir)
            audio_file = FSInputFile(audio_path)
            
            audio_caption = (
                f"🎧 <i>Оригінальний звук із відео</i>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"{AD_BANNER}"
            )

            await call.message.answer_audio(
                audio=audio_file,
                title=title[:40],
                caption=audio_caption,
                parse_mode="HTML"
            )
            await wait_msg.delete()
        except Exception as e:
            logging.error(f"Помилка аудіо: {e}")
            await wait_msg.edit_text("❌ Не вдалося отримати аудіо.")


# ================= ВЕБСЕРВЕР ДЛЯ RENDER =================
async def handle_ping(request):
    return web.Response(text="Media Downloader Bot is Running!")

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
