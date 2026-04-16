import requests
import logging
from telegram import Bot

logger = logging.getLogger(__name__)

async def send_photo_with_caption(bot: Bot, chat_id: str, photo_url: str, caption: str):
    """Отправить фото с подписью, если фото недоступно – отправить только текст."""
    try:
        resp = requests.get(photo_url, timeout=10)
        resp.raise_for_status()
        await bot.send_photo(chat_id=chat_id, photo=resp.content, caption=caption, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Не удалось отправить фото {photo_url}: {e}")
        await bot.send_message(chat_id=chat_id, text=caption, parse_mode="Markdown", disable_web_page_preview=True)

def format_item_message(item: dict) -> str:
    """Форматирует сообщение о товаре."""
    return (
        f"[{item['title']}]({item['url']})\n"
        f"💰 *{item['start_price']}円*\n"
        f"🕒 Опубликовано: {item['post_ts']}"  # можно преобразовать в дату, но для простоты оставим timestamp
    )