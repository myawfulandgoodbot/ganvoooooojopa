import os
import logging
import random
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from scraper import search
from database import add_query, remove_query, list_queries, get_all_queries, is_item_sent, mark_item_sent
from utils import send_photo_with_caption, format_item_message

# ---------- Настройки ----------
TOKEN = os.environ.get("YOKU_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Переменная окружения YOKU_BOT_TOKEN не установлена")

MIN_INTERVAL_MIN = 10
MAX_INTERVAL_MIN = 120

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Обработчики команд ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    text = (
        "👋 Привет! Я бот для отслеживания новых лотов на Yahoo Auctions.\n\n"
        "Команды:\n"
        "/add_brand <бренд> – добавить бренд\n"
        "/remove_brand <бренд> – удалить бренд\n"
        "/my_brands – список брендов\n"
        "/search_last <бренд> – последние 5 лотов\n\n"
        "Пример: /add_brand undercover"
    )
    await update.message.reply_text(text)

async def add_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("Укажите бренд: /add_brand nike")
        return
    brand = " ".join(context.args).lower()
    add_query(chat_id, brand)
    await update.message.reply_text(f"✅ Бренд '{brand}' добавлен.")

async def remove_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("Укажите бренд: /remove_brand nike")
        return
    brand = " ".join(context.args).lower()
    remove_query(chat_id, brand)
    await update.message.reply_text(f"🗑️ Бренд '{brand}' удалён.")

async def my_brands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    brands = list_queries(chat_id)
    if not brands:
        await update.message.reply_text("📭 У вас нет отслеживаемых брендов.")
    else:
        await update.message.reply_text("📋 Ваши бренды:\n" + "\n".join(f"• {b}" for b in brands))

async def search_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not context.args:
        await update.message.reply_text("Укажите бренд: /search_last undercover")
        return
    brand = " ".join(context.args)
    await update.message.reply_text(f"🔍 Ищу последние 5 лотов по '{brand}'...")
    try:
        results = search(brand, count=5)
        if not results:
            await update.message.reply_text(f"❌ Ничего не найдено по '{brand}'.")
            return
        for item in results[:5]:
            caption = format_item_message(item)
            await send_photo_with_caption(context.bot, chat_id, item["img"], caption)
    except Exception as e:
        logger.exception("Ошибка при поиске")
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ---------- Фоновая проверка (Job) ----------
async def periodic_check(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет все подписки и отправляет новые товары."""
    all_queries = get_all_queries()
    if not all_queries:
        return
    logger.info(f"Плановая проверка для {len(all_queries)} подписок...")
    for chat_id, query in all_queries:
        try:
            results = search(query, count=10)  # проверим последние 10
            for item in results:
                if not is_item_sent(chat_id, item["item_id"]):
                    caption = format_item_message(item)
                    await send_photo_with_caption(context.bot, chat_id, item["img"], caption)
                    mark_item_sent(chat_id, item["item_id"], item)
                    # Небольшая задержка между отправками, чтобы не флудить
                    await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка при проверке {query} для {chat_id}: {e}")
    # После проверки перенастроим интервал случайным образом
    new_interval = random.randint(MIN_INTERVAL_MIN, MAX_INTERVAL_MIN) * 60
    job = context.job
    if job:
        job.interval = new_interval
        logger.info(f"Следующая проверка через {new_interval//60} минут")

# ---------- Запуск ----------
async def post_init(application: Application):
    """После запуска бота добавляем периодическую задачу с случайным интервалом."""
    interval = random.randint(MIN_INTERVAL_MIN, MAX_INTERVAL_MIN) * 60
    application.job_queue.run_repeating(
        periodic_check,
        interval=interval,
        first=10,
        name="yahoo_checker"
    )
    logger.info(f"Планировщик запущен: интервал {interval//60} минут")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add_brand", add_brand))
    app.add_handler(CommandHandler("remove_brand", remove_brand))
    app.add_handler(CommandHandler("my_brands", my_brands))
    app.add_handler(CommandHandler("search_last", search_last))

    app.post_init = post_init
    app.run_polling()

if __name__ == "__main__":
    import asyncio
    main()