# Noelle_Bot/core/database.py
import os
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError
import sys
import logging

_logger = logging.getLogger("noelle_bot.database")

# ... (MONGO_URI, DATABASE_NAME, dll. tetap sama) ...
MONGO_URI = os.getenv('MONGODB_URI')
DATABASE_NAME = 'noelle_bot_db'
EMBEDS_COLLECTION_NAME = 'custom_embeds'
CONFIGS_COLLECTION_NAME = 'server_configs'

_mongo_client = None
_db = None
_embeds_collection = None
_configs_collection = None

DEFAULT_SERVER_CONFIG = {
    'ai_channel_name': "ai-channel",
    'mod_roles': [],
}

def connect_to_mongo():
    # ... (fungsi connect_to_mongo tetap sama, pastikan mengembalikan True/False) ...
    global _mongo_client, _db, _embeds_collection, _configs_collection
    if not MONGO_URI:
        _logger.error("MONGODB_URI tidak diatur. Fitur database tidak akan berfungsi.")
        return False 
    try:
        if _mongo_client is None: 
            _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            _mongo_client.admin.command('ismaster') 
            _logger.info("Koneksi MongoDB berhasil!")
            _db = _mongo_client[DATABASE_NAME]
            _embeds_collection = _db[EMBEDS_COLLECTION_NAME]
            _configs_collection = _db[CONFIGS_COLLECTION_NAME]
            try:
                _embeds_collection.create_index([("guild_id", 1), ("embed_name", 1)], unique=True, background=True)
                _logger.info(f"Index unik dipastikan pada koleksi '{EMBEDS_COLLECTION_NAME}'.")
            except OperationFailure as e:
                _logger.warning(f"Tidak dapat membuat index di '{EMBEDS_COLLECTION_NAME}' (mungkin sudah ada): {e}")
            try:
                _configs_collection.create_index([("guild_id", 1)], unique=True, background=True)
                _logger.info(f"Index unik dipastikan pada koleksi '{CONFIGS_COLLECTION_NAME}'.")
            except OperationFailure as e:
                _logger.warning(f"Tidak dapat membuat index di '{CONFIGS_COLLECTION_NAME}' (mungkin sudah ada): {e}")
        return True
    except ConnectionFailure as e: _logger.error(f"Koneksi MongoDB gagal: {e}")
    except PyMongoError as e: _logger.error(f"Error PyMongo saat koneksi: {e}")
    _mongo_client = _db = _embeds_collection = _configs_collection = None
    return False


def get_embeds_collection():
     global _embeds_collection # Pastikan menggunakan global jika ingin memodifikasi variabel global
     if _embeds_collection is None: # --- PERBAIKAN DI SINI ---
         if not connect_to_mongo(): return None
     return _embeds_collection

def get_configs_collection():
     global _configs_collection # Pastikan menggunakan global
     if _configs_collection is None: # --- PERBAIKAN DI SINI ---
         if not connect_to_mongo(): return None
     return _configs_collection

# --- Fungsi CRUD untuk Embeds ---
def save_custom_embed(guild_id: int, embed_name: str, embed_data: dict):
    collection = get_embeds_collection()
    if collection is None: # --- PERBAIKAN DI SINI ---
        _logger.error("Embeds collection tidak tersedia untuk save_custom_embed.")
        return False
    try:
        # ... (sisa fungsi sama)
        doc_to_save = embed_data.copy(); doc_to_save['guild_id'] = guild_id; doc_to_save['embed_name'] = embed_name
        result = collection.replace_one({'guild_id': guild_id, 'embed_name': embed_name}, doc_to_save, upsert=True)
        return result.upserted_id or result.modified_count > 0
    except PyMongoError as e: _logger.error(f"Error save_custom_embed: {e}"); return False

def get_custom_embed(guild_id: int, embed_name: str):
    collection = get_embeds_collection()
    if collection is None: # --- PERBAIKAN DI SINI ---
        _logger.error("Embeds collection tidak tersedia untuk get_custom_embed.")
        return None
    try: 
        # ... (sisa fungsi sama)
        return collection.find_one({'guild_id': guild_id, 'embed_name': embed_name})
    except PyMongoError as e: _logger.error(f"Error get_custom_embed: {e}"); return None

def get_all_custom_embed_names(guild_id: int):
    collection = get_embeds_collection()
    if collection is None: # --- PERBAIKAN DI SINI ---
        _logger.error("Embeds collection tidak tersedia untuk get_all_custom_embed_names.")
        return [] # Kembalikan list kosong jika koleksi tidak ada
    try:
        # ... (sisa fungsi sama)
        cursor = collection.find({'guild_id': guild_id}, {'embed_name': 1, '_id': 0})
        return [doc['embed_name'] for doc in cursor if 'embed_name' in doc]
    except PyMongoError as e: _logger.error(f"Error get_all_custom_embed_names: {e}"); return []

def delete_custom_embed(guild_id: int, embed_name: str):
    collection = get_embeds_collection()
    if collection is None: # --- PERBAIKAN DI SINI ---
        _logger.error("Embeds collection tidak tersedia untuk delete_custom_embed.")
        return False
    try:
        # ... (sisa fungsi sama)
        result = collection.delete_one({'guild_id': guild_id, 'embed_name': embed_name})
        return result.deleted_count > 0
    except PyMongoError as e: _logger.error(f"Error delete_custom_embed: {e}"); return False

# --- Fungsi CRUD untuk Server Configs ---
def get_server_config(guild_id: int) -> dict:
    collection = get_configs_collection()
    if collection is None: # --- PERBAIKAN DI SINI ---
        _logger.warning("Configs collection tidak tersedia, mengembalikan config default.")
        return DEFAULT_SERVER_CONFIG.copy()
    try:
        # ... (sisa fungsi sama)
        config_doc = collection.find_one({'guild_id': guild_id})
        if config_doc:
            merged_config = DEFAULT_SERVER_CONFIG.copy()
            merged_config.update(config_doc)
            if '_id' in merged_config: del merged_config['_id']
            return merged_config
        else:
            default_with_id = {'guild_id': guild_id, **DEFAULT_SERVER_CONFIG}
            collection.insert_one(default_with_id)
            return DEFAULT_SERVER_CONFIG.copy()
    except PyMongoError as e: _logger.error(f"Error get_server_config: {e}")
    return DEFAULT_SERVER_CONFIG.copy()

def update_server_config(guild_id: int, settings_to_update: dict) -> bool:
    collection = get_configs_collection()
    if collection is None: # --- PERBAIKAN DI SINI ---
        _logger.error("Configs collection tidak tersedia untuk update_server_config.")
        return False
    try:
        # ... (sisa fungsi sama)
        result = collection.update_one({'guild_id': guild_id}, {'$set': settings_to_update}, upsert=True)
        return result.modified_count > 0 or result.upserted_id is not None
    except PyMongoError as e: _logger.error(f"Error update_server_config: {e}"); return False

def close_mongo_connection(): # ... (sama seperti sebelumnya)
    global _mongo_client
    if _mongo_client:
        _mongo_client.close()
        _logger.info("Koneksi MongoDB ditutup.")
        _mongo_client = None