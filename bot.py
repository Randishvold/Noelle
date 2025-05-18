import discord
import os
import sys
from discord.ext import commands
from dotenv import load_dotenv
import asyncio

# --- Add the project root directory to sys.path ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# -------------------------------------------------

# Load environment variables from .env file if it exists (for local testing)
load_dotenv()

# Access the token from environment variables
TOKEN = os.getenv('DISCORD_TOKEN')

# Define Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
# intents.presences = True

# Create a bot instance
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Cog Loading ---

async def load_cogs():
    """Loads all cogs from the 'cogs' directory."""
    cogs_dir = os.path.join(PROJECT_ROOT, 'cogs')
    for filename in os.listdir(cogs_dir):
        if filename.endswith('.py') and filename != '__init__.py':
            cog_name = f'cogs.{filename[:-3]}'
            try:
                await bot.load_extension(cog_name)
                print(f'Loaded cog: {cog_name}')
            except Exception as e:
                print(f'Failed to load cog {cog_name}: {e}')

# --- Bot Events ---

@bot.event
async def on_ready():
    """Event triggered when the bot is ready and connected."""
    print(f'{bot.user} is connected to Discord!')
    print(f'Connected to {len(bot.guilds)} guilds.')

    await load_cogs()

    # Sync Slash Commands after all cogs are loaded
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
        # --- Tambahkan logging detail command yang disinkronkan ---
        if synced:
            print("Synced commands:")
            for command in synced:
                print(f"- {command.name} (ID: {command.id})") # Print command name and ID
        # -------------------------------------------------------
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    await bot.change_presence(activity=discord.Game(name="listening for commands!"))


# --- Run Bot ---

if __name__ == "__main__":
    if TOKEN is None:
        print("ERROR: Environment variable 'DISCORD_TOKEN' not found.")
        print("Make sure you have set the DISCORD_TOKEN variable.")
    else:
        print("Starting bot...")
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"Bot failed to run: {e}")