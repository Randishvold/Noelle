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

# Variabel global untuk klien dan koleksi
_mongo_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None
_embeds_collection: AsyncIOMotorCollection | None = None
_configs_collection: AsyncIOMotorCollection | None = None

DEFAULT_SERVER_CONFIG = {
    'ai_channel_name': "ai-channel",
    'mod_roles': [],
}

async def connect_to_mongo() -> bool:
    """
    Menghubungkan ke MongoDB secara asinkron.
    Menginisialisasi klien, database, dan koleksi.
    Mengembalikan True jika berhasil, False jika gagal.
    """
    global _mongo_client, _db, _embeds_collection, _configs_collection
    if not MONGO_URI:
        _logger.error("MONGODB_URI tidak diatur. Fitur database tidak akan berfungsi.")
        return False
    
    if _mongo_client: # Jika sudah ada klien, tidak perlu konek lagi
        return True

    try:
        _logger.info("Mencoba koneksi ke MongoDB secara asinkron...")
        _mongo_client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Perintah ismaster adalah cara cepat untuk memverifikasi koneksi
        await _mongo_client.admin.command('ismaster') 
        _logger.info("Koneksi MongoDB (motor) berhasil!")
        
        _db = _mongo_client[DATABASE_NAME]
        _embeds_collection = _db[EMBEDS_COLLECTION_NAME]
        _configs_collection = _db[CONFIGS_COLLECTION_NAME]

        # Pastikan index ada (operasi non-blocking di background)
        await _embeds_collection.create_index([("guild_id", 1), ("embed_name", 1)], unique=True, background=True)
        _logger.info(f"Index unik dipastikan pada koleksi '{EMBEDS_COLLECTION_NAME}'.")
        await _configs_collection.create_index([("guild_id", 1)], unique=True, background=True)
        _logger.info(f"Index unik dipastikan pada koleksi '{CONFIGS_COLLECTION_NAME}'.")
        
        return True
    except ConnectionFailure as e:
        _logger.error(f"Koneksi MongoDB gagal: {e}")
    except PyMongoError as e:
        _logger.error(f"Error PyMongo/Motor saat koneksi: {e}")
    
    # Reset semua jika gagal
    _mongo_client = _db = _embeds_collection = _configs_collection = None
    return False

def get_db_status() -> bool:
    """Mengecek apakah klien database sudah terhubung."""
    return _mongo_client is not None

async def close_mongo_connection():
    """Menutup koneksi MongoDB."""
    global _mongo_client
    if _mongo_client:
        _mongo_client.close()
        _logger.info("Koneksi MongoDB (motor) ditutup.")
        _mongo_client = None

# --- Fungsi CRUD Asinkron untuk Embeds ---

async def save_custom_embed(guild_id: int, embed_name: str, embed_data: dict) -> bool:
    if not _embeds_collection:
        _logger.error("Embeds collection tidak tersedia untuk save_custom_embed.")
        return False
    try:
        doc_to_save = embed_data.copy()
        doc_to_save['guild_id'] = guild_id
        doc_to_save['embed_name'] = embed_name
        result = await _embeds_collection.replace_one({'guild_id': guild_id, 'embed_name': embed_name}, doc_to_save, upsert=True)
        return result.upserted_id is not None or result.modified_count > 0
    except PyMongoError as e:
        _logger.error(f"Error save_custom_embed: {e}")
        return False

async def get_custom_embed(guild_id: int, embed_name: str) -> dict | None:
    if not _embeds_collection:
        _logger.error("Embeds collection tidak tersedia untuk get_custom_embed.")
        return None
    try:
        return await _embeds_collection.find_one({'guild_id': guild_id, 'embed_name': embed_name})
    except PyMongoError as e:
        _logger.error(f"Error get_custom_embed: {e}")
        return None

async def get_all_custom_embed_names(guild_id: int) -> list[str]:
    if not _embeds_collection:
        _logger.error("Embeds collection tidak tersedia untuk get_all_custom_embed_names.")
        return []
    try:
        cursor = _embeds_collection.find({'guild_id': guild_id}, {'embed_name': 1, '_id': 0})
        return [doc['embed_name'] for doc in await cursor.to_list(length=100) if 'embed_name' in doc]
    except PyMongoError as e:
        _logger.error(f"Error get_all_custom_embed_names: {e}")
        return []

async def delete_custom_embed(guild_id: int, embed_name: str) -> bool:
    if not _embeds_collection:
        _logger.error("Embeds collection tidak tersedia untuk delete_custom_embed.")
        return False
    try:
        result = await _embeds_collection.delete_one({'guild_id': guild_id, 'embed_name': embed_name})
        return result.deleted_count > 0
    except PyMongoError as e:
        _logger.error(f"Error delete_custom_embed: {e}")
        return False

# --- Fungsi CRUD Asinkron untuk Server Configs ---

async def get_server_config(guild_id: int) -> dict:
    if not _configs_collection:
        _logger.warning("Configs collection tidak tersedia, mengembalikan config default.")
        return DEFAULT_SERVER_CONFIG.copy()
    try:
        config_doc = await _configs_collection.find_one({'guild_id': guild_id})
        if config_doc:
            merged_config = DEFAULT_SERVER_CONFIG.copy()
            merged_config.update(config_doc)
            if '_id' in merged_config: del merged_config['_id']
            return merged_config
        else:
            default_with_id = {'guild_id': guild_id, **DEFAULT_SERVER_CONFIG}
            await _configs_collection.insert_one(default_with_id)
            return DEFAULT_SERVER_CONFIG.copy()
    except PyMongoError as e:
        _logger.error(f"Error get_server_config: {e}")
    return DEFAULT_SERVER_CONFIG.copy()

async def update_server_config(guild_id: int, settings_to_update: dict) -> bool:
    if not _configs_collection:
        _logger.error("Configs collection tidak tersedia untuk update_server_config.")
        return False
    try:
        result = await _configs_collection.update_one({'guild_id': guild_id}, {'$set': settings_to_update}, upsert=True)
        return result.modified_count > 0 or result.upserted_id is not None
    except PyMongoError as e:
        _logger.error(f"Error update_server_config: {e}")
        return False