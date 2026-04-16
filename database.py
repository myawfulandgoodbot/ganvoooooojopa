import os
from pathlib import Path
from threading import Lock
from tinydb import TinyDB, Query

DB_PATH = Path(__file__).parent / "db.json"
QUERIES_TABLE = "queries"

_lock = Lock()
_db = TinyDB(str(DB_PATH))

def _get_queries_table():
    return _db.table(QUERIES_TABLE)

def _get_user_cache_table(chat_id: str):
    return _db.table(str(chat_id))

def add_query(chat_id: str, query: str):
    with _lock:
        table = _get_queries_table()
        q = Query()
        if table.search((q.chat_id == chat_id) & (q.query == query)):
            return
        table.insert({"chat_id": chat_id, "query": query})

def remove_query(chat_id: str, query: str):
    with _lock:
        table = _get_queries_table()
        q = Query()
        table.remove((q.chat_id == chat_id) & (q.query == query))

def list_queries(chat_id: str):
    with _lock:
        table = _get_queries_table()
        q = Query()
        docs = table.search(q.chat_id == chat_id)
        return [doc["query"] for doc in docs]

def get_all_queries():
    """Return list of (chat_id, query) for all users"""
    with _lock:
        table = _get_queries_table()
        return [(doc["chat_id"], doc["query"]) for doc in table.all()]

def is_item_sent(chat_id: str, item_id: str) -> bool:
    with _lock:
        cache = _get_user_cache_table(chat_id)
        return cache.contains(doc_id=item_id)  # используем item_id как doc_id

def mark_item_sent(chat_id: str, item_id: str, item_data: dict):
    with _lock:
        cache = _get_user_cache_table(chat_id)
        cache.upsert(item_data, doc_ids=[item_id])