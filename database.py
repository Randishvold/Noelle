import os
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError
import urllib.parse
import sys

# --- MongoDB Connection ---

MONGO_URI = os.getenv('MONGODB_URI')

if not MONGO_URI:
    print("ERROR: MONGODB_URI environment variable not set.")
    print("Make sure you have added the MongoDB Add-on in Railway and linked it to your service, or set it manually for an external DB.")
    sys.exit(1)

DATABASE_NAME = 'my_discord_bot_db'
EMBEDS_COLLECTION_NAME = 'custom_embeds' # Name for embeds collection
CONFIGS_COLLECTION_NAME = 'server_configs' # Name for configs collection

_mongo_client = None
_db = None
_embeds_collection = None
_configs_collection = None # New global for configs collection

def connect_to_mongo():
    global _mongo_client, _db, _embeds_collection, _configs_collection
    try:
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        _mongo_client.admin.command('ismaster')
        print("MongoDB connection successful!")

        _db = _mongo_client[DATABASE_NAME]
        _embeds_collection = _db[EMBEDS_COLLECTION_NAME] # Assign to embed collection
        _configs_collection = _db[CONFIGS_COLLECTION_NAME] # Assign to configs collection


        # Ensure unique compound index on guild_id and embed_name for embeds
        try:
            _embeds_collection.create_index(
                [("guild_id", 1), ("embed_name", 1)],
                unique=True,
                background=True
            )
            print(f"Ensured unique index on {EMBEDS_COLLECTION_NAME} collection.")
        except OperationFailure as e:
            print(f"Could not create index on {EMBEDS_COLLECTION_NAME} (might already exist): {e}")

        # Ensure unique index on guild_id for server_configs
        try:
            _configs_collection.create_index(
                [("guild_id", 1)],
                unique=True,
                background=True
            )
            print(f"Ensured unique index on {CONFIGS_COLLECTION_NAME} collection.")
        except OperationFailure as e:
            print(f"Could not create index on {CONFIGS_COLLECTION_NAME} (might already exist): {e}")


    except ConnectionFailure as e:
        print(f"MongoDB connection failed: {e}")
        print("Please check your MONGODB_URI and network settings.")
        sys.exit(1)
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during connection: {e}")
        sys.exit(1)

connect_to_mongo()

# Helper to get collections
def get_embeds_collection():
     if _embeds_collection is None:
         connect_to_mongo()
         if _embeds_collection is None:
              raise ConnectionFailure("Failed to connect to MongoDB and get embeds collection.")
     return _embeds_collection

def get_configs_collection():
     if _configs_collection is None:
         connect_to_mongo()
         if _configs_collection is None:
              raise ConnectionFailure("Failed to connect to MongoDB and get configs collection.")
     return _configs_collection


# --- Embed Database Operations (Modified to use get_embeds_collection) ---

def save_custom_embed(guild_id: int, embed_name: str, embed_data: dict):
    """Saves or updates a custom embed in the database."""
    collection = get_embeds_collection() # Use embeds collection
    try:
        doc_to_save = embed_data.copy() if isinstance(embed_data, dict) else {}
        doc_to_save['guild_id'] = guild_id
        doc_to_save['embed_name'] = embed_name

        result = collection.replace_one(
            {'guild_id': guild_id, 'embed_name': embed_name},
            doc_to_save,
            upsert=True
        )
        return result.upserted_id or result.modified_count > 0

    except OperationFailure as e:
        print(f"MongoDB operation failed during save_custom_embed: {e}")
        if e.code == 11000:
             print(f"Specific E11000 duplicate key error detected for embed '{embed_name}' in guild {guild_id}.")
             if e.details and 'keyValue' in e.details:
                  print(f"Duplicate key value: {e.details['keyValue']}")
        return False
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during save_custom_embed: {e}")
        return False


def get_custom_embed(guild_id: int, embed_name: str):
    """Retrieves a custom embed from the database."""
    collection = get_embeds_collection() # Use embeds collection
    try:
        embed_doc = collection.find_one({'guild_id': guild_id, 'embed_name': embed_name})
        return embed_doc

    except OperationFailure as e:
        print(f"MongoDB operation failed during get_custom_embed: {e}")
        return None
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during get_custom_embed: {e}")
        return None


def get_all_custom_embed_names(guild_id: int):
    """Retrieves the names of all custom embeds for a guild."""
    collection = get_embeds_collection() # Use embeds collection
    try:
        cursor = collection.find({'guild_id': guild_id}, {'embed_name': 1, '_id': 0})
        names = [doc['embed_name'] for doc in cursor if 'embed_name' in doc]
        return names

    except OperationFailure as e:
        print(f"MongoDB operation failed during get_all_custom_embed_names: {e}")
        return []
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during get_all_custom_embed_names: {e}")
        return []


def delete_custom_embed(guild_id: int, embed_name: str):
    """Deletes a custom embed from the database."""
    collection = get_embeds_collection() # Use embeds collection
    try:
        result = collection.delete_one({'guild_id': guild_id, 'embed_name': embed_name})
        return result.deleted_count > 0

    except OperationFailure as e:
        print(f"MongoDB operation failed during delete_custom_embed: {e}")
        return False
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during delete_custom_embed: {e}")
        return False

# --- Server Config Database Operations (NEW) ---

# Default configuration for a new server
DEFAULT_SERVER_CONFIG = {
    'mod_roles': [], # List of role IDs that can use moderation commands (kick, ban, purge)
    'role_manager_roles': [], # List of role IDs that can use role management commands (addrole, removerole)
    # Add other default settings here later if needed
    'ai_channel_id': None,
}

def get_server_config(guild_id: int):
    """Retrieves the configuration for a server."""
    collection = get_configs_collection() # Use configs collection
    try:
        config_doc = collection.find_one({'guild_id': guild_id})
        # Return default config if not found, merging with default to ensure all keys exist
        if config_doc:
            # Merge stored config with default to ensure new default keys are present
            merged_config = DEFAULT_SERVER_CONFIG.copy()
            merged_config.update(config_doc)
            # Remove _id before returning
            if '_id' in merged_config:
                del merged_config['_id']
            return merged_config
        else:
            # Insert default config if not found, then return it
            collection.insert_one({'guild_id': guild_id, **DEFAULT_SERVER_CONFIG}) # Use ** to unpack default dict
            return DEFAULT_SERVER_CONFIG.copy() # Return a copy

    except OperationFailure as e:
        print(f"MongoDB operation failed during get_server_config: {e}")
        return DEFAULT_SERVER_CONFIG.copy() # Return default on error
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during get_server_config: {e}")
        return DEFAULT_SERVER_CONFIG.copy() # Return default on error


def update_server_config(guild_id: int, settings_to_update: dict):
    """Updates specific settings for a server configuration."""
    collection = get_configs_collection() # Use configs collection
    try:
        # Use update_one with $set to update only specified fields, upsert=True to insert if not found
        result = collection.update_one(
            {'guild_id': guild_id},
            {'$set': settings_to_update}, # Use $set to update only the keys in settings_to_update
            upsert=True
        )
        return result.modified_count > 0 or result.upserted_id is not None # Return True if modified or inserted

    except OperationFailure as e:
        print(f"MongoDB operation failed during update_server_config: {e}")
        return False
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during update_server_config: {e}")
        return False


# Function to close the connection (optional, connection pool manages)
def close_mongo_connection():
    """Closes the MongoDB client connection."""
    global _mongo_client
    if _mongo_client:
        _mongo_client.close()
        print("MongoDB connection closed.")
        _mongo_client = None