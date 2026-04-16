import asyncio
import logging
import sqlite3
import time
import random
from datetime import datetime
from typing import Dict, List, Set

import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, JobQueue

# ------------------ Configuration ------------------
TELEGRAM_TOKEN = "8697949456:AAEKEACbg8xb21KOiXatCc24iI8St2Vqe9k"  # Замените на токен вашего бота
CHECK_INTERVAL_MINUTES = 10  # Интервал проверки в минутах
YAHOO_SEARCH_URL = "https://auctions.yahoo.co.jp/search/search"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
CATEGORY_ID = "2084049715"  # Категория "Брендовая одежда" (измените при необходимости)

# ------------------ Database Setup ------------------
conn = sqlite3.connect('yahoo_bot.db', check_same_thread=False)
cursor = conn.cursor()

# Таблица для подписок пользователей
cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_subscriptions (
        user_id INTEGER,
        brand TEXT,
        PRIMARY KEY (user_id, brand)
    )
''')

# Таблица для отслеживания отправленных товаров
cursor.execute('''
    CREATE TABLE IF NOT EXISTS sent_items (
        item_url TEXT PRIMARY KEY,
        sent_at TIMESTAMP
    )
''')
conn.commit()

# ------------------ Helper Functions ------------------
def add_subscription(user_id: int, brand: str) -> bool:
    """Добавляет подписку на бренд для пользователя."""
    try:
        cursor.execute("INSERT INTO user_subscriptions (user_id, brand) VALUES (?, ?)", (user_id, brand.lower()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def remove_subscription(user_id: int, brand: str) -> bool:
    """Удаляет подписку на бренд для пользователя."""
    cursor.execute("DELETE FROM user_subscriptions WHERE user_id = ? AND brand = ?", (user_id, brand.lower()))
    conn.commit()
    return cursor.rowcount > 0

def get_user_brands(user_id: int) -> List[str]:
    """Возвращает список брендов, на которые подписан пользователь."""
    cursor.execute("SELECT brand FROM user_subscriptions WHERE user_id = ?", (user_id,))
    return [row[0] for row in cursor.fetchall()]

def get_all_subscriptions() -> Dict[int, Set[str]]:
    """Возвращает словарь {user_id: {brand1, brand2, ...}} для всех пользователей."""
    cursor.execute("SELECT user_id, brand FROM user_subscriptions")
    subscriptions = {}
    for user_id, brand in cursor.fetchall():
        if user_id not in subscriptions:
            subscriptions[user_id] = set()
        subscriptions[user_id].add(brand)
    return subscriptions

def mark_item_as_sent(item_url: str) -> None:
    """Помечает товар как отправленный, чтобы не дублировать уведомления."""
    cursor.execute("INSERT OR IGNORE INTO sent_items (item_url, sent_at) VALUES (?, ?)", (item_url, datetime.now()))
    conn.commit()

def is_item_sent(item_url: str) -> bool:
    """Проверяет, был ли товар уже отправлен."""
    cursor.execute("SELECT 1 FROM sent_items WHERE item_url = ?", (item_url,))
    return cursor.fetchone() is not None

def parse_yahoo_auctions(brand: str, limit: int = 10) -> List[Dict]:
    """
    Парсит Yahoo Auctions по заданному бренду.
    Возвращает список словарей с информацией о товарах.
    """
    params = {
        'p': brand,
        'auccat': CATEGORY_ID,
        'b': 1,  # Начинаем с первого товара
        'n': limit  # Количество товаров на странице
    }

    try:
        response = requests.get(YAHOO_SEARCH_URL, headers=HEADERS, params=params, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        items = []
        # Поиск всех элементов товара на странице
        product_elements = soup.select('.Product')
        
        for product in product_elements[:limit]:
            link_elem = product.select_one('.Product__titleLink')
            if not link_elem:
                continue
                
            url = link_elem.get('href')
            if not url:
                continue
                
            title = link_elem.get_text(strip=True)
            
            # Извлечение цены
            price_elem = product.select_one('.Product__priceValue')
            price = price_elem.get_text(strip=True) if price_elem else 'Цена не указана'
            
            items.append({
                'title': title,
                'price': price,
                'url': url
            })
        
        # Случайная задержка для имитации поведения человека
        time.sleep(random.uniform(1, 3))
        return items
        
    except Exception as e:
        logging.error(f"Ошибка при парсинге {brand}: {e}")
        return []

# ------------------ Telegram Bot Handlers ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    await update.message.reply_text(
        "👋 Привет! Я бот для отслеживания новых лотов на Yahoo Auctions.\n\n"
        "Доступные команды:\n"
        "/add_brand <бренд> - добавить бренд для отслеживания\n"
        "/remove_brand <бренд> - удалить бренд из отслеживания\n"
        "/my_brands - показать список отслеживаемых брендов\n"
        "/search_last <бренд> - найти последние 5 лотов по бренду\n\n"
        "Пример: /add_brand nike"
    )

async def add_brand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /add_brand."""
    if not context.args:
        await update.message.reply_text("Пожалуйста, укажите бренд. Пример: /add_brand nike")
        return
    
    brand = ' '.join(context.args).lower()
    user_id = update.effective_user.id
    
    if add_subscription(user_id, brand):
        await update.message.reply_text(f"✅ Бренд '{brand}' добавлен в список отслеживания.")
    else:
        await update.message.reply_text(f"⚠️ Бренд '{brand}' уже есть в вашем списке.")

async def remove_brand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /remove_brand."""
    if not context.args:
        await update.message.reply_text("Пожалуйста, укажите бренд. Пример: /remove_brand nike")
        return
    
    brand = ' '.join(context.args).lower()
    user_id = update.effective_user.id
    
    if remove_subscription(user_id, brand):
        await update.message.reply_text(f"🗑️ Бренд '{brand}' удален из списка отслеживания.")
    else:
        await update.message.reply_text(f"⚠️ Бренд '{brand}' не найден в вашем списке.")

async def my_brands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /my_brands."""
    user_id = update.effective_user.id
    brands = get_user_brands(user_id)
    
    if brands:
        brands_list = '\n'.join([f"• {brand}" for brand in brands])
        await update.message.reply_text(f"📋 Ваши отслеживаемые бренды:\n{brands_list}")
    else:
        await update.message.reply_text("📭 У вас пока нет отслеживаемых брендов. Добавьте их с помощью /add_brand.")

async def search_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /search_last."""
    if not context.args:
        await update.message.reply_text("Пожалуйста, укажите бренд. Пример: /search_last nike")
        return
    
    brand = ' '.join(context.args)
    await update.message.reply_text(f"🔍 Ищу последние лоты по запросу '{brand}'...")
    
    items = parse_yahoo_auctions(brand, limit=5)
    
    if not items:
        await update.message.reply_text(f"❌ Не найдено лотов по запросу '{brand}'. Попробуйте другой бренд.")
        return
    
    for item in items:
        message = (
            f"📦 *{item['title']}*\n"
            f"💰 {item['price']}\n"
            f"🔗 [Ссылка на лот]({item['url']})"
        )
        await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)

async def check_new_items(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Фоновая задача для проверки новых товаров по всем подпискам.
    Запускается каждые CHECK_INTERVAL_MINUTES минут.
    """
    subscriptions = get_all_subscriptions()
    
    if not subscriptions:
        return
    
    logging.info(f"Запущена проверка новых товаров для {len(subscriptions)} пользователей...")
    
    for user_id, brands in subscriptions.items():
        for brand in brands:
            items = parse_yahoo_auctions(brand, limit=5)
            new_items = [item for item in items if not is_item_sent(item['url'])]
            
            for item in new_items:
                # Отправляем уведомление пользователю
                message = (
                    f"🆕 *Новый лот по бренду '{brand}'!*\n\n"
                    f"📦 *{item['title']}*\n"
                    f"💰 {item['price']}\n"
                    f"🔗 [Ссылка на лот]({item['url']})"
                )
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode='Markdown',
                        disable_web_page_preview=True
                    )
                    mark_item_as_sent(item['url'])
                    logging.info(f"Отправлено уведомление пользователю {user_id} о товаре {item['url']}")
                except Exception as e:
                    logging.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")
            
            # Небольшая задержка между проверками разных брендов
            await asyncio.sleep(random.uniform(1, 3))

# ------------------ Main ------------------
def main() -> None:
    """Запуск бота."""
    # Настройка логирования
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Создание приложения
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Регистрация обработчиков команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add_brand", add_brand))
    app.add_handler(CommandHandler("remove_brand", remove_brand))
    app.add_handler(CommandHandler("my_brands", my_brands))
    app.add_handler(CommandHandler("search_last", search_last))
    
    # Настройка периодической проверки новых товаров
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(
            check_new_items,
            interval=CHECK_INTERVAL_MINUTES * 60,
            first=10
        )
        logging.info(f"Планировщик запущен: проверка каждые {CHECK_INTERVAL_MINUTES} минут")
    
    # Запуск бота
    logging.info("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
