import asyncio
import logging
import sys
import json

with open("config.json", "r") as config_file:
    config = json.load(config_file)

TOKEN = config["TOKEN"]
CHAT_ID = config["CHAT_ID"]

APPS = config["APPS"]

REQUIRED_MODULES = ["aiohttp", "aiogram", "apscheduler", "google_play_scraper"]

for module in REQUIRED_MODULES:
    try:
        __import__(module)
    except ImportError:
        print(f"Ошибка: {module} не установлен. Установите командой: pip install {module}")
        sys.exit(1)

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.markdown import bold
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.client.default import DefaultBotProperties
from datetime import datetime
from google_play_scraper import reviews, app, Sort

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
                print("Ошибка: получен unexpected content-type")

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

async def send_reviews(chat_id: int = None):
    """Отправляет новые отзывы"""
    logging.info("Функция send_reviews() запущена")
    reviews = await get_reviews()
    try:
        with open("groups.json", "r") as f:
            chat_ids = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        chat_ids = []

    for app, app_reviews in reviews.items():
        message_text = f"<b>{app}</b>\n\n"
        if app_reviews:
            for review in app_reviews:
                message_text += f"<b>{review['source']}</b>\n⭐ {review['rating']} — {review['date']}\n<i>«{review['content']}»</i>\n\n"
            if len(message_text) > 4000:
                chunks = [message_text[i:i+4000] for i in range(0, len(message_text), 4000)]
                for chunk in chunks:
                    for chat_id in chat_ids:
                        await bot.send_message(chat_id, chunk)
            else:
                for chat_id in chat_ids:
                    await bot.send_message(chat_id, message_text)
        else:
            for chat_id in chat_ids:
                await bot.send_message(chat_id, f"<b>{app}</b>\n\nНовых отзывов нет.")

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
        message_text += f"Google Play: ⭐ {rating_data['google']}\n"
        message_text += f"App Store: ⭐ {rating_data['apple']}\n\n"
    await message.answer(message_text)

@dp.message(Command("history"))
async def cmd_history(message: Message):
    try:
        with open("sent_reviews.json", "r") as f:
            sent_reviews_list = json.load(f)
        if not sent_reviews_list:
            await message.answer("История пуста. Отзывы еще не отправлялись.")
            return
        
        history_text = "<b>История отправленных отзывов:</b>\n\n"
        for review in sent_reviews_list[-10:]:  # Показываем последние 10 записей
            history_text += f"{review}\n\n"
        
        await message.answer(history_text)
    except (FileNotFoundError, json.JSONDecodeError):
        await message.answer("История пуста или повреждена.")

@dp.message(Command("clear_history"))
async def cmd_clear_history(message: Message):
    with open("sent_reviews.json", "w") as f:
        json.dump([], f)
    await message.answer("История отправленных отзывов очищена.")

@dp.message(Command("addgroup"))
async def cmd_addgroup(message: Message):
    if message.chat.type in ["group", "supergroup"]:
        try:
            with open("groups.json", "r") as f:
                chat_ids = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            chat_ids = []
        
        if message.chat.id not in chat_ids:
            chat_ids.append(message.chat.id)
            with open("groups.json", "w") as f:
                json.dump(chat_ids, f)
            await message.answer("Группа добавлена для автоотправки отзывов.")
        else:
            await message.answer("Эта группа уже добавлена.")

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "Этот бот отслеживает отзывы пользователей о приложениях activ и Kcell.\n\n"
        "<b>Доступные команды:</b>\n"
        "/reviews — получить новые отзывы\n"
        "/ratings — средний рейтинг приложений\n"
        "/history — история отправленных отзывов\n"
        "/clear_history — очистить историю ранее полученных отзывов\n"
        "/help — справка\n"
    )
    await message.answer(text)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "Этот бот отслеживает отзывы пользователей о приложениях activ и Kcell.\n\n"
        "<b>Доступные команды:</b>\n"
        "/reviews — получить новые отзывы\n"
        "/ratings — средний рейтинг приложений\n"
        "/history — история отправленных отзывов\n"
        "/clear_history — очистить историю ранее полученных отзывов\n"
    )
    await message.answer(text)

@dp.message(Command("reviews"))
async def cmd_new(message: Message):
    await send_reviews(message.chat.id)

# --- Планировщик задач ---
scheduler = AsyncIOScheduler()
scheduler.add_job(send_reviews, "cron", hour=13, minute=59, timezone="Asia/Almaty")  # Отправка в 13:59

# --- Функция main ---
async def main():
    scheduler.start()  # Запуск планировщика
    await dp.start_polling(bot)  # Запуск бота

# --- Запуск бота ---
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}", exc_info=True)
