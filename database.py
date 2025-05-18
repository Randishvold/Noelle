import os
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError
import urllib.parse # To properly handle characters in connection string if needed
import sys # For exiting on critical error

# --- MongoDB Connection ---

# Get MongoDB connection string from environment variables
# Railway provides this as MONGODB_URI for the MongoDB Add-on
MONGO_URI = os.getenv('MONGODB_URI')

if not MONGO_URI:
    print("ERROR: MONGODB_URI environment variable not set.")
    print("Make sure you have added the MongoDB Add-on in Railway and linked it to your service.")
    sys.exit(1) # Exit if URI is not set - bot cannot function without DB

# MongoDB database and collection names
DATABASE_NAME = 'my_discord_bot_db' # Choose a name for your database
COLLECTION_NAME = 'custom_embeds' # Choose a name for your collection

# Use a global client instance to avoid creating a new connection for every operation
# Connections are managed by pymongo's connection pool
_mongo_client = None
_db = None
_collection = None

def connect_to_mongo():
    """Establishes connection to MongoDB and initializes globals."""
    global _mongo_client, _db, _collection
    try:
        # MongoClient handles connection pooling automatically
        # The URI includes credentials and host information
        # serverSelectionTimeoutMS sets a timeout for finding a server
        _mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)

        # The ismaster command is cheap and does not require auth.
        _mongo_client.admin.command('ismaster')
        print("MongoDB connection successful!")

        # Get the database and collection objects
        _db = _mongo_client[DATABASE_NAME]
        _collection = _db[COLLECTION_NAME]

        # Ensure unique compound index on guild_id and embed_name
        # This prevents duplicate embed names within the same guild
        try:
            _collection.create_index(
                [("guild_id", 1), ("embed_name", 1)],
                unique=True,
                background=True # Build index in background
            )
            print(f"Ensured unique index on {COLLECTION_NAME} collection.")
        except OperationFailure as e:
            print(f"Could not create index: {e}")
            # This might happen if the index already exists with different options, usually harmless.

    except ConnectionFailure as e:
        print(f"MongoDB connection failed: {e}")
        print("Please check your MONGODB_URI and network settings.")
        # Depending on severity, you might want to exit or retry
        sys.exit(1) # Exit on connection failure at startup
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during connection: {e}")
        sys.exit(1)

# Establish connection when the module is imported
connect_to_mongo()

# --- Database Operations ---

# Helper to ensure collection is accessible after connection
def get_collection():
    """Returns the MongoDB collection object, ensuring connection is made."""
    if _collection is None:
        print("Warning: MongoDB connection not established. Attempting to connect...")
        connect_to_mongo() # Try reconnecting
        if _collection is None:
            # If connection still fails, raise an error
            raise ConnectionFailure("Failed to connect to MongoDB.")
    return _collection


def save_custom_embed(guild_id: int, embed_name: str, embed_data: dict):
    """Saves or updates a custom embed in the database."""
    collection = get_collection()
    try:
        # Use replace_one with upsert=True to insert if not exists, or replace if exists
        result = collection.replace_one(
            {'guild_id': guild_id, 'embed_name': embed_name},
            embed_data, # pymongo handles converting dict to BSON
            upsert=True # Insert if document not found
        )
        # result.upserted_id will be the _id if a new document was inserted
        # result.modified_count will be 1 if an existing document was updated
        # print(f"Embed '{embed_name}' for guild {guild_id} saved/updated. Upserted ID: {result.upserted_id}, Modified Count: {result.modified_count}")
        return result.upserted_id or result.modified_count > 0 # Return True/False indication

    except OperationFailure as e:
        print(f"MongoDB operation failed during save_custom_embed: {e}")
        # Handle potential errors like unique index violation (less likely with replace_one)
        return False
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during save_custom_embed: {e}")
        return False


def get_custom_embed(guild_id: int, embed_name: str):
    """Retrieves a custom embed from the database."""
    collection = get_collection()
    try:
        # Find a single document matching the criteria
        embed_doc = collection.find_one({'guild_id': guild_id, 'embed_name': embed_name})
        # pymongo returns the document as a Python dictionary
        return embed_doc # Returns None if not found

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
        # Find all documents for the guild and project only the 'embed_name' field
        # We explicitly exclude the default _id field
        cursor = collection.find({'guild_id': guild_id}, {'embed_name': 1, '_id': 0})

        # Extract names from the cursor results
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
        # Delete a single document matching the criteria
        result = collection.delete_one({'guild_id': guild_id, 'embed_name': embed_name})

        return result.deleted_count > 0 # Return True if at least one document was deleted

    except OperationFailure as e:
        print(f"MongoDB operation failed during delete_custom_embed: {e}")
        return False
    except PyMongoError as e:
        print(f"An unexpected PyMongo error occurred during delete_custom_embed: {e}")
        return False

# Function to close the connection (optional, connection pool manages)
# but good practice if bot is gracefully shutting down
def close_mongo_connection():
    """Closes the MongoDB client connection."""
    global _mongo_client
    if _mongo_client:
        _mongo_client.close()
        print("MongoDB connection closed.")
        _mongo_client = None # Reset global

# Note: Pymongo's connection pool usually handles connections well without manual close,
# but you could add a bot event for shutdown if needed:
# @bot.event
# async def on_disconnect():
#     database.close_mongo_connection()
# @bot.event
# async def on_shutdown():
#     database.close_mongo_connection()