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
COLLECTION_NAME = 'custom_embeds'

_mongo_client = None
_db = None
_collection = None

def connect_to_mongo():
    global _mongo_client, _db, _collection
    try:
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        _mongo_client.admin.command('ismaster')
        print("MongoDB connection successful!")
        _db = _mongo_client[DATABASE_NAME]
        _collection = _db[COLLECTION_NAME]

        try:
            # Ensure unique compound index on guild_id and embed_name
            # This prevents duplicate embed names within the same guild
            # Note: MongoDB treats missing fields as null for indexing purposes.
            # Our save logic below explicitly adds these fields to the document.
            _collection.create_index(
                [("guild_id", 1), ("embed_name", 1)],
                unique=True,
                background=True
            )
            print(f"Ensured unique index on {COLLECTION_NAME} collection.")
        except OperationFailure as e:
            print(f"Could not create index (might already exist): {e}")

    except ConnectionFailure as e:
        print(f"MongoDB connection failed: {e}")
        print("Please check your MONGODB_URI and network settings.")
        sys.exit(1)
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during connection: {e}")
        sys.exit(1)

connect_to_mongo()

def get_collection():
    if _collection is None:
        print("Warning: MongoDB connection not established. Attempting to connect...")
        connect_to_mongo()
        if _collection is None:
            raise ConnectionFailure("Failed to connect to MongoDB.")
    return _collection


def save_custom_embed(guild_id: int, embed_name: str, embed_data: dict):
    """Saves or updates a custom embed in the database."""
    collection = get_collection()
    try:
        # --- FIX: Ensure guild_id and embed_name are in the document data being saved ---
        # This prevents implicit null values for the index on insert if these keys are missing from embed_data
        # Make a copy to avoid modifying the original embed_data dictionary if it's used elsewhere
        doc_to_save = embed_data.copy() if isinstance(embed_data, dict) else {} # Start with a copy or empty dict
        doc_to_save['guild_id'] = guild_id
        doc_to_save['embed_name'] = embed_name

        # print(f"Attempting to save document: {doc_to_save}") # Optional: for debugging the data being sent

        result = collection.replace_one(
            # Filter still uses the correct parameters to find the document
            {'guild_id': guild_id, 'embed_name': embed_name},
            doc_to_save, # Save the document with guild_id and embed_name explicitly included
            upsert=True # Insert if document not found
        )
        # print(f"Save result: Upserted ID: {result.upserted_id}, Modified Count: {result.modified_count}, Matched Count: {result.matched_count}") # Optional: log result

        return result.upserted_id or result.modified_count > 0

    except OperationFailure as e:
        print(f"MongoDB operation failed during save_custom_embed: {e}")
        # Check if it's the specific duplicate key error we're seeing
        if e.code == 11000:
             print("Specific E11000 duplicate key error detected. This likely means a document with guild_id=null and embed_name=null still exists or was created unexpectedly.")
             # You might want to log the specific key causing the duplication from e.details
             if e.details and 'keyValue' in e.details:
                  print(f"Duplicate key value: {e.details['keyValue']}")

        return False
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during save_custom_embed: {e}")
        return False


def get_custom_embed(guild_id: int, embed_name: str):
    """Retrieves a custom embed from the database."""
    collection = get_collection()
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
    collection = get_collection()
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
    collection = get_collection()
    try:
        result = collection.delete_one({'guild_id': guild_id, 'embed_name': embed_name})
        return result.deleted_count > 0

    except OperationFailure as e:
        print(f"MongoDB operation failed during delete_custom_embed: {e}")
        return False
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during delete_custom_embed: {e}")
        return False

def close_mongo_connection():
    global _mongo_client
    if _mongo_client:
        _mongo_client.close()
        print("MongoDB connection closed.")
        _mongo_client = None