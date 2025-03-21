import asyncio
import logging
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.markdown import bold
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.client.default import DefaultBotProperties
import json
from datetime import datetime
from google_play_scraper import reviews, app, Sort

# --- Настройки ---
TOKEN = "7684331016:AAGC7kDbiROGcHOBmzr73PCNHi0hY36iISs"
CHAT_ID = "125844966"

APPS = {
    "activ SuperApp": {
        "google_package": "com.kcell.myactiv",
        "apple_id": "917517216"
    },
    "Kcell SuperApp": {
        "google_package": "com.kcell.mykcell",
        "apple_id": "915329046"
    }
}

# --- Логирование ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# --- Функции для парсинга ---
async def fetch_reviews_google(package_name):
    """Получает отзывы из Google Play"""
    result, _ = reviews(package_name, lang='ru', country='RU', sort=Sort.NEWEST)
    result = result[:10]  # Ограничение до 10 отзывов
    return [
        {
            "rating": review["score"],
            "title": review.get("title", "Без заголовка"),
            "content": review["content"][:300] + "…" if len(review["content"]) > 300 else review["content"],
            "date": datetime.utcfromtimestamp(review["at"].timestamp()).strftime('%d %B %Y года'),
            "source": "Google Play"
        }
        for review in result
    ]

async def fetch_reviews_apple(app_id):
    """Получает отзывы из App Store"""
    url = f"https://itunes.apple.com/rss/customerreviews/id={app_id}/json"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            text = await response.text()  # Получаем данные в виде строки
            try:
                data = json.loads(text)  # Корректный парсинг
            except aiohttp.ContentTypeError:
                print("Ошибка: полученunexpected content-type")

            if "feed" in data and "entry" in data["feed"]:
                reviews = data["feed"]["entry"][1:]  # Первый элемент — это мета-информация
                reviews = sorted(reviews, key=lambda x: x["updated"]["label"], reverse=True)[:10]  # Ограничение до 10 отзывов
                for review in reviews:
                    print(review["updated"]["label"])  # Проверка дат
                print("Полученные отзывы:", reviews)
                return [
                    {
                        "rating": review["im:rating"]["label"],
                        "title": review["title"]["label"],
                        "content": review["content"]["label"][:300] + "…" if len(review["content"]["label"]) > 300 else review["content"]["label"],
                        "date": datetime.strptime(review["updated"]["label"], '%Y-%m-%dT%H:%M:%S%z').strftime('%d %B %Y года'),
                        "source": "App Store"
                    }
                    for review in reviews
                    if review.get("updated", {}).get("label")
                ]
    return []

async def fetch_rating_google(package_name):
    """Получает средний рейтинг из Google Play"""
    app_info = app(package_name)
    return round(app_info['score'], 1)

async def fetch_rating_apple(app_id):
    """Получает средний рейтинг из App Store"""
    url = f"https://itunes.apple.com/lookup?id={app_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            text = await response.text()
            data = json.loads(text)
            if "results" in data and data["results"]:
                print(data["results"][0]["averageUserRating"])  # Отладка
                return round(data["results"][0]["averageUserRating"], 1)
    return None

async def get_reviews():
    """Получает и форматирует отзывы для всех приложений"""
    all_reviews = {}
    for app_name, app_data in APPS.items():
        google_reviews = await fetch_reviews_google(app_data["google_package"])
        apple_reviews = await fetch_reviews_apple(app_data["apple_id"])
        all_reviews[app_name] = google_reviews + apple_reviews
    return all_reviews

async def send_reviews():
    """Отправляет новые отзывы"""
    reviews = await get_reviews()
    for app, app_reviews in reviews.items():
        message_text = f"📱 <b>{app}</b>\n"
        if app_reviews:
            for review in app_reviews:
                message_text += f"🛍 <b>{review['source']}</b>\n⭐ {review['rating']} — {review['date']}\n\"{review['content']}\"\n\n"
            if len(message_text) > 4000:
                chunks = [message_text[i:i+4000] for i in range(0, len(message_text), 4000)]
                for chunk in chunks:
                    await bot.send_message(CHAT_ID, chunk)
            else:
                await bot.send_message(CHAT_ID, message_text)
        else:
            await bot.send_message(CHAT_ID, f"📱 <b>{app}</b>\nНовых отзывов нет.")

async def get_ratings():
    """Получает средний рейтинг приложений"""
    ratings = {}
    for app_name, app_data in APPS.items():
        google_rating = await fetch_rating_google(app_data["google_package"])
        apple_rating = await fetch_rating_apple(app_data["apple_id"])
        ratings[app_name] = {
            "google": google_rating,
            "apple": apple_rating
        }
    return ratings

@dp.message(Command("ratings"))
async def cmd_ratings(message: Message):
    ratings = await get_ratings()
    message_text = ""
    for app, rating_data in ratings.items():
        message_text += f"<b>{app}</b>\n"
        message_text += f"🛍 <b>Google Play</b>: ⭐ {rating_data['google']}\n"
        message_text += f"🍏 <b>App Store</b>: ⭐ {rating_data['apple']}\n\n"
    await message.answer(message_text)

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "👋 Привет! Я бот для мониторинга отзывов в Google Play и App Store.\n\n"
        "📌 Доступные команды:\n"
        "🔹 /reviews — новые отзывы\n"
        "🔹 /ratings — средний рейтинг приложений\n"
        "🔹 /help — справка\n"
    )
    await message.answer(text)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "ℹ️ Этот бот отслеживает отзывы пользователей о приложениях activ SuperApp и Kcell SuperApp.\n\n"
        "📌 Доступные команды:\n"
        "🔹 /reviews — получить новые отзывы\n"
        "🔹 /ratings — средний рейтинг приложений\n"
    )
    await message.answer(text)

@dp.message(Command("reviews"))
async def cmd_new(message: Message):
    await send_reviews()

# --- Планировщик задач ---
scheduler = AsyncIOScheduler()
scheduler.add_job(send_reviews, "cron", hour=9)  # Отправка в 09:00

# --- Запуск бота ---
async def main():
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
