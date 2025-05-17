import discord
import os
from discord.ext import commands
from dotenv import load_dotenv
import asyncio # Needed for async file operations

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
    cogs_dir = os.path.join(os.path.dirname(__file__), 'cogs')
    for filename in os.listdir(cogs_dir):
        if filename.endswith('.py') and filename != '__init__.py':
            cog_name = f'cogs.{filename[:-3]}' # Format as package.module (e.g., cogs.embed_cog)
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

    # Load cogs *before* syncing commands
    await load_cogs()

    # Sync Slash Commands after all cogs are loaded
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # Optional: Change bot status
    await bot.change_presence(activity=discord.Game(name="listening for commands!"))


# --- Run Bot ---

if __name__ == "__main__":
    if TOKEN is None:
        print("ERROR: Environment variable 'DISCORD_TOKEN' not found.")
        print("Make sure you have set the DISCORD_TOKEN variable:")
        print("- Locally: Create a .env file in the project folder with: DISCORD_TOKEN=YOUR_BOT_TOKEN")
        print("- On Railway: Go to the Railway dashboard, select your bot service, open the 'Variables' tab, and add a variable with NAME='DISCORD_TOKEN' and VALUE='YOUR_BOT_TOKEN'.")
    else:
        print("Starting bot...")
        # bot.run is synchronous, so load_cogs needs to be awaited
        # However, on_ready is called by bot.run automatically after connecting.
        # So, load_cogs is called inside on_ready.
        try:
            bot.run(TOKEN)
        except Exception as e:
            print(f"Bot failed to run: {e}")