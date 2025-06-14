# Noelle_Bot/core/database.py

import os
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError
import logging

_logger = logging.getLogger("noelle_bot.database")

MONGO_URI = os.getenv('MONGODB_URI')
DATABASE_NAME = 'noelle_bot_db'
EMBEDS_COLLECTION_NAME = 'custom_embeds'
CONFIGS_COLLECTION_NAME = 'server_configs'

_mongo_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None
_embeds_collection: AsyncIOMotorCollection | None = None
_configs_collection: AsyncIOMotorCollection | None = None

DEFAULT_SERVER_CONFIG = {
    'ai_channel_name': "ai-channel",
    'mod_roles': [],
}

async def connect_to_mongo() -> bool:
    global _mongo_client, _db, _embeds_collection, _configs_collection
    if not MONGO_URI:
        _logger.error("MONGODB_URI tidak diatur. Fitur database tidak akan berfungsi.")
        return False
    
    if _mongo_client:
        return True

    try:
        _logger.info("Mencoba koneksi ke MongoDB secara asinkron...")
        _mongo_client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        await _mongo_client.admin.command('hello') # <--- DITAMBAHKAN (untuk verifikasi koneksi)
        _logger.info("Koneksi MongoDB (motor) berhasil!")
        
        _db = _mongo_client[DATABASE_NAME]
        _embeds_collection = _db[EMBEDS_COLLECTION_NAME]
        _configs_collection = _db[CONFIGS_COLLECTION_NAME]

        await _embeds_collection.create_index([("guild_id", 1), ("embed_name", 1)], unique=True, background=True) # <--- DITAMBAHKAN
        _logger.info(f"Index unik dipastikan pada koleksi '{EMBEDS_COLLECTION_NAME}'.")
        await _configs_collection.create_index([("guild_id", 1)], unique=True, background=True) # <--- DITAMBAHKAN
        _logger.info(f"Index unik dipastikan pada koleksi '{CONFIGS_COLLECTION_NAME}'.")
        
        return True
    except ConnectionFailure as e:
        _logger.error(f"Koneksi MongoDB gagal: {e}")
    except PyMongoError as e:
        _logger.error(f"Error PyMongo/Motor saat koneksi: {e}")
    
    _mongo_client = _db = _embeds_collection = _configs_collection = None
    return False

def get_db_status() -> bool:
    return _mongo_client is not None

async def close_mongo_connection():
    global _mongo_client
    if _mongo_client:
        _mongo_client.close()
        _logger.info("Koneksi MongoDB (motor) ditutup.")
        _mongo_client = None

# --- Fungsi CRUD Asinkron untuk Embeds ---

async def save_custom_embed(guild_id: int, embed_name: str, embed_data: dict) -> bool:
    if _embeds_collection is None:
        _logger.error("Embeds collection tidak tersedia untuk save_custom_embed.")
        return False
    try:
        doc_to_save = embed_data.copy()
        doc_to_save['guild_id'] = guild_id
        doc_to_save['embed_name'] = embed_name
        result = await _embeds_collection.replace_one({'guild_id': guild_id, 'embed_name': embed_name}, doc_to_save, upsert=True) # <--- DITAMBAHKAN
        return result.upserted_id is not None or result.modified_count > 0
    except PyMongoError as e:
        _logger.error(f"Error save_custom_embed: {e}")
        return False

async def get_custom_embed(guild_id: int, embed_name: str) -> dict | None:
    if _embeds_collection is None:
        _logger.error("Embeds collection tidak tersedia untuk get_custom_embed.")
        return None
    try:
        return await _embeds_collection.find_one({'guild_id': guild_id, 'embed_name': embed_name}) # <--- DITAMBAHKAN
    except PyMongoError as e:
        _logger.error(f"Error get_custom_embed: {e}")
        return None

async def get_all_custom_embed_names(guild_id: int) -> list[str]:
    if _embeds_collection is None:
        _logger.error("Embeds collection tidak tersedia untuk get_all_custom_embed_names.")
        return []
    try:
        cursor = _embeds_collection.find({'guild_id': guild_id}, {'embed_name': 1, '_id': 0})
        return [doc['embed_name'] for doc in await cursor.to_list(length=100) if 'embed_name' in doc] # <--- DITAMBAHKAN
    except PyMongoError as e:
        _logger.error(f"Error get_all_custom_embed_names: {e}")
        return []

async def delete_custom_embed(guild_id: int, embed_name: str) -> bool:
    if _embeds_collection is None:
        _logger.error("Embeds collection tidak tersedia untuk delete_custom_embed.")
        return False
    try:
        result = await _embeds_collection.delete_one({'guild_id': guild_id, 'embed_name': embed_name}) # <--- DITAMBAHKAN
        return result.deleted_count > 0
    except PyMongoError as e:
        _logger.error(f"Error delete_custom_embed: {e}")
        return False

# --- Fungsi CRUD Asinkron untuk Server Configs ---

async def get_server_config(guild_id: int) -> dict:
    if _configs_collection is None:
        _logger.warning("Configs collection tidak tersedia, mengembalikan config default.")
        return DEFAULT_SERVER_CONFIG.copy()
    try:
        config_doc = await _configs_collection.find_one({'guild_id': guild_id}) # <--- DITAMBAHKAN
        if config_doc:
            merged_config = DEFAULT_SERVER_CONFIG.copy()
            merged_config.update(config_doc)
            if '_id' in merged_config: del merged_config['_id']
            return merged_config
        else:
            default_with_id = {'guild_id': guild_id, **DEFAULT_SERVER_CONFIG}
            await _configs_collection.insert_one(default_with_id) # <--- DITAMBAHKAN
            return DEFAULT_SERVER_CONFIG.copy()
    except PyMongoError as e:
        _logger.error(f"Error get_server_config: {e}")
    return DEFAULT_SERVER_CONFIG.copy()

async def update_server_config(guild_id: int, settings_to_update: dict) -> bool:
    if _configs_collection is None:
        _logger.error("Configs collection tidak tersedia untuk update_server_config.")
        return False
    try:
        result = await _configs_collection.update_one({'guild_id': guild_id}, {'$set': settings_to_update}, upsert=True) # <--- DITAMBAHKAN
        return result.modified_count > 0 or result.upserted_id is not None
    except PyMongoError as e:
        _logger.error(f"Error update_server_config: {e}")
        return False