import os
import logging
import random
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, MessageHandler, filters
)

from scraper import search_with_offset
from database import (
    add_subscription, remove_subscription, list_subscriptions,
    get_all_subscriptions, is_item_sent, mark_item_sent
)
from utils import send_photo_with_caption, format_item_message

# ---------- Настройки ----------
TOKEN = os.environ.get("API_TOKEN")
if not TOKEN:
    raise ValueError("Токен не найден в переменных окружения")

# Состояния диалогов
WAITING_BRAND_NAME = 1
CHOOSING_MAIN_CAT = 2
CHOOSING_WOMEN_SUBCAT = 3
WAITING_BRAND_FOR_SEARCH = 4
CHOOSING_MAIN_CAT_FOR_SEARCH = 5
CHOOSING_WOMEN_SUBCAT_FOR_SEARCH = 6
SEARCH_ACTIVE = 7

# Категории
MAIN_CATEGORIES = {
    "👕 Футболки": "Tシャツ",
    "👕 Худи/Свитшоты": "パーカー",
    "🧥 Куртки/Пальто": "ジャケット",
    "👖 Штаны/Джинсы": "パンツ",
    "👟 Обувь": "靴",
    "💍 Аксессуары": "アクセサリー",
    "👗 Женское": "women",
    "📦 Всё подряд": "all"
}

WOMEN_SUBCATEGORIES = {
    "👗 Платья": "ワンピース",
    "📏 Юбки": "スカート",
    "👠 Каблуки/Туфли": "ハイヒール",
    "🔙 Назад": "back"
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Нижнее меню ----------
MAIN_MENU_BUTTONS = [
    [KeyboardButton("➕ Добавить бренд")],
    [KeyboardButton("📋 Мои бренды")],
    [KeyboardButton("🗑️ Удалить бренд")],
    [KeyboardButton("🔍 Поиск лотов")],
]
MAIN_MENU_MARKUP = ReplyKeyboardMarkup(MAIN_MENU_BUTTONS, resize_keyboard=True)

def get_search_query(brand: str, category_code: str) -> str:
    if category_code and category_code != "all":
        return f"{brand} {category_code}"
    return brand

def get_category_display(category_code: str) -> str:
    if not category_code:
        return "все категории"
    for name, code in MAIN_CATEGORIES.items():
        if code == category_code:
            return name
    for name, code in WOMEN_SUBCATEGORIES.items():
        if code == category_code:
            return name
    return category_code

# ---------- Старт и главное меню ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Привет! Я бот для отслеживания лотов на Yahoo Auctions.\n\n"
        "Используйте кнопки ниже для управления.",
        reply_markup=MAIN_MENU_MARKUP
    )
    return ConversationHandler.END

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок нижнего меню."""
    text = update.message.text
    if text == "➕ Добавить бренд":
        await update.message.reply_text(
            "✏️ Напишите название бренда (например, nike).\n\n"
            "Или нажмите /cancel, чтобы отменить.",
            reply_markup=MAIN_MENU_MARKUP
        )
        return WAITING_BRAND_NAME
    elif text == "📋 Мои бренды":
        chat_id = str(update.effective_chat.id)
        subs = list_subscriptions(chat_id)
        if not subs:
            msg = "📭 У вас нет отслеживаемых брендов."
        else:
            lines = [f"• {brand} – *{get_category_display(cat)}*" for brand, cat in subs]
            msg = "📋 Ваши подписки:\n" + "\n".join(lines)
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=MAIN_MENU_MARKUP)
        return ConversationHandler.END
    elif text == "🗑️ Удалить бренд":
        chat_id = str(update.effective_chat.id)
        subs = list_subscriptions(chat_id)
        if not subs:
            await update.message.reply_text("📭 У вас нет активных подписок.", reply_markup=MAIN_MENU_MARKUP)
            return ConversationHandler.END
        keyboard = []
        for brand, cat_code in subs:
            display = f"{brand} [{get_category_display(cat_code)}]"
            keyboard.append([InlineKeyboardButton(display, callback_data=f"del_{brand}_{cat_code}")])
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_del")])
        await update.message.reply_text(
            "Выберите подписку для удаления:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return None  # остаёмся в ожидании callback
    elif text == "🔍 Поиск лотов":
        await update.message.reply_text(
            "✏️ Напишите название бренда для поиска (например, nike).\n\n"
            "Или нажмите /cancel, чтобы отменить.",
            reply_markup=MAIN_MENU_MARKUP
        )
        return WAITING_BRAND_FOR_SEARCH
    else:
        await update.message.reply_text("Неизвестная команда. Используйте кнопки меню.", reply_markup=MAIN_MENU_MARKUP)
        return ConversationHandler.END

# ---------- Добавление бренда ----------
async def receive_brand_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brand = update.message.text.strip().lower()
    if not brand:
        await update.message.reply_text("Пожалуйста, напишите бренд текстом.", reply_markup=MAIN_MENU_MARKUP)
        return WAITING_BRAND_NAME
    context.user_data["temp_brand"] = brand
    keyboard = [[InlineKeyboardButton(name, callback_data=code)] for name, code in MAIN_CATEGORIES.items()]
    await update.message.reply_text(
        f"Бренд: *{brand}*\nТеперь выберите категорию:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING_MAIN_CAT

async def add_main_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    if choice == "women":
        keyboard = [[InlineKeyboardButton(name, callback_data=code)] for name, code in WOMEN_SUBCATEGORIES.items()]
        await query.edit_message_text("Выберите женскую категорию:", reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSING_WOMEN_SUBCAT
    else:
        return await save_subscription(update, context, choice)

async def add_women_subcategory_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    if choice == "back":
        brand = context.user_data.get("temp_brand")
        keyboard = [[InlineKeyboardButton(name, callback_data=code)] for name, code in MAIN_CATEGORIES.items()]
        await query.edit_message_text(
            f"Бренд: *{brand}*\nВыберите категорию:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSING_MAIN_CAT
    else:
        return await save_subscription(update, context, choice)

async def save_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE, category_code: str):
    query = update.callback_query
    brand = context.user_data.get("temp_brand")
    chat_id = str(update.effective_chat.id)
    if not brand:
        await query.edit_message_text("❌ Ошибка. Попробуйте снова через главное меню.")
        await query.message.reply_text("Главное меню:", reply_markup=MAIN_MENU_MARKUP)
        return ConversationHandler.END
    if category_code == "all":
        category_code = ""
    success = add_subscription(chat_id, brand, category_code)
    cat_display = get_category_display(category_code)
    if success:
        await query.edit_message_text(
            f"✅ Подписка добавлена:\nБренд: *{brand}*\nКатегория: *{cat_display}*",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(f"⚠️ Подписка на {brand} с такой категорией уже существует.")
    context.user_data.pop("temp_brand", None)
    await query.message.reply_text("Главное меню:", reply_markup=MAIN_MENU_MARKUP)
    return ConversationHandler.END

# ---------- Удаление бренда (callback) ----------
async def remove_brand_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "cancel_del":
        await query.edit_message_text("❌ Удаление отменено.")
        await query.message.reply_text("Главное меню:", reply_markup=MAIN_MENU_MARKUP)
        return ConversationHandler.END
    elif data.startswith("del_"):
        parts = data.split("_", 2)
        if len(parts) == 3:
            _, brand, cat_code = parts
            chat_id = str(update.effective_chat.id)
            remove_subscription(chat_id, brand, cat_code)
            await query.edit_message_text(f"🗑️ Подписка на {brand} (категория: {get_category_display(cat_code)}) удалена.")
            await query.message.reply_text("Главное меню:", reply_markup=MAIN_MENU_MARKUP)
            return ConversationHandler.END
    return ConversationHandler.END

# ---------- Поиск лотов ----------
async def receive_brand_for_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brand = update.message.text.strip().lower()
    if not brand:
        await update.message.reply_text("Пожалуйста, напишите бренд текстом.", reply_markup=MAIN_MENU_MARKUP)
        return WAITING_BRAND_FOR_SEARCH
    context.user_data["temp_search_brand"] = brand
    keyboard = [[InlineKeyboardButton(name, callback_data=code)] for name, code in MAIN_CATEGORIES.items()]
    await update.message.reply_text(
        f"Бренд: *{brand}*\nВыберите категорию для поиска:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING_MAIN_CAT_FOR_SEARCH

async def search_main_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    if choice == "women":
        keyboard = [[InlineKeyboardButton(name, callback_data=code)] for name, code in WOMEN_SUBCATEGORIES.items()]
        await query.edit_message_text("Выберите женскую категорию:", reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSING_WOMEN_SUBCAT_FOR_SEARCH
    else:
        return await start_search(update, context, choice, offset=0)

async def search_women_subcategory_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    if choice == "back":
        brand = context.user_data.get("temp_search_brand")
        keyboard = [[InlineKeyboardButton(name, callback_data=code)] for name, code in MAIN_CATEGORIES.items()]
        await query.edit_message_text(
            f"Бренд: *{brand}*\nВыберите категорию для поиска:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSING_MAIN_CAT_FOR_SEARCH
    else:
        return await start_search(update, context, choice, offset=0)

async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE, category_code: str, offset: int):
    query = update.callback_query
    brand = context.user_data.get("temp_search_brand")
    chat_id = str(update.effective_chat.id)
    if not brand:
        await query.edit_message_text("❌ Ошибка. Попробуйте снова через главное меню.")
        await query.message.reply_text("Главное меню:", reply_markup=MAIN_MENU_MARKUP)
        return ConversationHandler.END

    if category_code == "all":
        category_code = ""
    search_query = get_search_query(brand, category_code)

    context.user_data["search_params"] = {
        "brand": brand,
        "category_code": category_code,
        "search_query": search_query
    }

    cat_display = get_category_display(category_code)
    await query.edit_message_text(f"🔍 Ищу лоты: *{search_query}* (категория: {cat_display})", parse_mode="Markdown")

    try:
        results = search_with_offset(search_query, limit=5, offset=offset)
        if not results:
            await query.message.reply_text(f"❌ Ничего не найдено по '{search_query}'.")
            keyboard = [
                [InlineKeyboardButton("🔄 Другая категория", callback_data="change_category")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
            ]
            await query.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))
            return SEARCH_ACTIVE

        for item in results:
            caption = format_item_message(item)  # включает цену, дату
            # Добавляем инлайн-кнопку "Открыть объявление"
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Открыть объявление", url=item["url"])]])
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Открыть объявление", url=item["url"])]])
            await send_photo_with_caption(context.bot, chat_id, item["img"], caption, reply_markup=keyboard)
            await asyncio.sleep(0.5)

        if len(results) == 5:
            keyboard = [
                [InlineKeyboardButton("📦 Ещё 5", callback_data=f"more_{offset+5}")],
                [InlineKeyboardButton("🔄 Другая категория", callback_data="change_category")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
            ]
            await query.message.reply_text(
                "Показаны первые 5. Нажмите «Ещё», чтобы загрузить следующие.\n"
                "Или выберите другую категорию или главное меню.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SEARCH_ACTIVE
        else:
            keyboard = [
                [InlineKeyboardButton("🔄 Другая категория", callback_data="change_category")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
            ]
            await query.message.reply_text(
                "✅ Поиск завершён. Больше лотов нет.\n"
                "Можете выбрать другую категорию или вернуться в главное меню.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data.pop("search_params", None)
            return SEARCH_ACTIVE
    except Exception as e:
        logger.exception("Ошибка при поиске")
        await query.message.reply_text(f"❌ Ошибка: {e}")
        context.user_data.pop("search_params", None)
        return ConversationHandler.END

async def more_results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("more_"):
        new_offset = int(data.split("_")[1])
        params = context.user_data.get("search_params")
        if not params:
            await query.edit_message_text("❌ Сессия поиска истекла. Начните заново через главное меню.")
            return ConversationHandler.END

        brand = params["brand"]
        category_code = params["category_code"]
        search_query = params["search_query"]
        chat_id = str(update.effective_chat.id)

        try:
            results = search_with_offset(search_query, limit=5, offset=new_offset)
            if not results:
                await query.edit_message_text("❌ Больше ничего не найдено.")
                keyboard = [
                    [InlineKeyboardButton("🔄 Другая категория", callback_data="change_category")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
                ]
                await query.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))
                context.user_data.pop("search_params", None)
                return SEARCH_ACTIVE

            await query.message.delete()
            for item in results:
                caption = format_item_message(item)
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Открыть объявление", url=item["url"])]])
                await send_photo_with_caption(context.bot, chat_id, item["img"], caption)
                await context.bot.send_message(chat_id=chat_id, text="🔗 Ссылка на лот:", reply_markup=keyboard)
                await asyncio.sleep(0.5)

            if len(results) == 5:
                keyboard = [
                    [InlineKeyboardButton("📦 Ещё 5", callback_data=f"more_{new_offset+5}")],
                    [InlineKeyboardButton("🔄 Другая категория", callback_data="change_category")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
                ]
                await query.message.reply_text(
                    "Показаны следующие 5. Нажмите «Ещё», чтобы продолжить.\n"
                    "Или выберите другую категорию или главное меню.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return SEARCH_ACTIVE
            else:
                keyboard = [
                    [InlineKeyboardButton("🔄 Другая категория", callback_data="change_category")],
                    [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
                ]
                await query.message.reply_text(
                    "✅ Больше лотов нет.\n"
                    "Можете выбрать другую категорию или вернуться в главное меню.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                context.user_data.pop("search_params", None)
                return SEARCH_ACTIVE
        except Exception as e:
            logger.exception("Ошибка при пагинации")
            await query.message.reply_text(f"❌ Ошибка: {e}")
            context.user_data.pop("search_params", None)
            return ConversationHandler.END

# ---------- Навигация внутри поиска ----------
async def change_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    params = context.user_data.get("search_params")
    if not params:
        await query.edit_message_text("❌ Не удалось определить бренд. Начните заново через главное меню.")
        await query.message.reply_text("Главное меню:", reply_markup=MAIN_MENU_MARKUP)
        return ConversationHandler.END

    brand = params["brand"]
    context.user_data["temp_search_brand"] = brand
    keyboard = [[InlineKeyboardButton(name, callback_data=code)] for name, code in MAIN_CATEGORIES.items()]
    await query.edit_message_text(
        f"Бренд: *{brand}*\nВыберите новую категорию для поиска:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING_MAIN_CAT_FOR_SEARCH

async def to_main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("🏠 Возвращаемся в главное меню...")
    await query.message.reply_text("Главное меню:", reply_markup=MAIN_MENU_MARKUP)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("✅ Действие отменено.", reply_markup=MAIN_MENU_MARKUP)
    return ConversationHandler.END

# ---------- Фоновая проверка ----------
async def periodic_check(context: ContextTypes.DEFAULT_TYPE):
    all_subs = get_all_subscriptions()
    if not all_subs:
        return
    logger.info(f"Плановая проверка для {len(all_subs)} подписок...")
    for chat_id, brand, category_code in all_subs:
        query_str = get_search_query(brand, category_code)
        try:
            results = search_with_offset(query_str, limit=10, offset=0)
            for item in results:
                if not is_item_sent(chat_id, item["item_id"]):
                    caption = format_item_message(item)
                    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Открыть объявление", url=item["url"])]])
                    await context.bot.send_message(chat_id=chat_id, text=f"🆕 Новый лот по запросу '{query_str}':")
                    await send_photo_with_caption(context.bot, chat_id, item["img"], caption)
                    await context.bot.send_message(chat_id=chat_id, text="🔗 Ссылка на лот:", reply_markup=keyboard)
                    mark_item_sent(chat_id, item["item_id"], item)
                    await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Ошибка при проверке {brand}/{category_code}: {e}")

async def post_init(app: Application):
    interval = random.randint(10, 120) * 60
    app.job_queue.run_repeating(periodic_check, interval=interval, first=10)
    logger.info(f"Планировщик запущен, интервал {interval//60} минут")

# ---------- Запуск ----------
def main():
    app = Application.builder().token(TOKEN).build()

    # Диалог добавления бренда
    add_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Добавить бренд$"), main_menu_handler)],
        states={
            WAITING_BRAND_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_brand_name),
                CommandHandler("cancel", cancel)
            ],
            CHOOSING_MAIN_CAT: [CallbackQueryHandler(add_main_category_chosen)],
            CHOOSING_WOMEN_SUBCAT: [CallbackQueryHandler(add_women_subcategory_chosen)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # Диалог поиска
    search_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 Поиск лотов$"), main_menu_handler)],
        states={
            WAITING_BRAND_FOR_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_brand_for_search),
                CommandHandler("cancel", cancel)
            ],
            CHOOSING_MAIN_CAT_FOR_SEARCH: [CallbackQueryHandler(search_main_category_chosen)],
            CHOOSING_WOMEN_SUBCAT_FOR_SEARCH: [CallbackQueryHandler(search_women_subcategory_chosen)],
            SEARCH_ACTIVE: [
                CallbackQueryHandler(more_results_callback, pattern="^more_"),
                CallbackQueryHandler(change_category_callback, pattern="^change_category$"),
                CallbackQueryHandler(to_main_menu_callback, pattern="^to_main_menu$")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # Обработчики кнопок нижнего меню (кроме добавления и поиска, они уже в диалогах)
    app.add_handler(MessageHandler(filters.Regex("^(📋 Мои бренды|🗑️ Удалить бренд)$"), main_menu_handler))
    # Обработчик удаления бренда (callback)
    app.add_handler(CallbackQueryHandler(remove_brand_callback, pattern="^(del_|cancel_del)"))
    # Обработчик команды /start
    app.add_handler(CommandHandler("start", start))
    # Общий cancel для любого состояния
    app.add_handler(CommandHandler("cancel", cancel))

    app.add_handler(add_conv)
    app.add_handler(search_conv)

    app.post_init = post_init
    app.run_polling()

if __name__ == "__main__":
    main()
