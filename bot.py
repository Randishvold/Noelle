import discord
import os
from discord.ext import commands
from dotenv import load_dotenv
from discord import app_commands

# Load environment variables from .env file if it exists (for local testing)
load_dotenv()

# Access the token from environment variables
TOKEN = os.getenv('DISCORD_TOKEN') # Ensure this matches the variable name in Railway

# Define Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
# intents.presences = True # Optional intent

# Create a bot instance
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Bot Events ---

@bot.event
async def on_ready():
    """Event triggered when the bot is ready and connected."""
    print(f'{bot.user} is connected to Discord!')
    print(f'Connected to {len(bot.guilds)} guilds.')

    # Sync Slash Commands
    try:
        # Sync globally for Railway deployment
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
        # For testing in a specific guild locally:
        # YOUR_TESTING_GUILD_ID = 123456789012345678 # Replace with your guild ID
        # synced = await bot.tree.sync(guild=discord.Object(id=YOUR_TESTING_GUILD_ID))
        # print(f"Synced {len(synced)} command(s) to test guild.")

    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # Optional: Change bot status
    await bot.change_presence(activity=discord.Game(name="managing the server!"))


@bot.event
async def on_member_join(member):
    """Event triggered when a new member joins the guild."""
    guild = member.guild
    channel = guild.system_channel # Or get a specific channel by ID

    if channel is not None:
        embed = discord.Embed(
            title=f"Welcome to {guild.name}!",
            description=f"Hello {member.mention}, welcome aboard!",
            color=discord.Color.green()
        )
        if member.avatar:
             embed.set_thumbnail(url=member.avatar.url)

        await channel.send(embed=embed)


# --- Slash Commands ---

@bot.tree.command(name="ping", description="Responds with Pong! and bot latency.")
async def ping_slash(interaction: discord.Interaction):
    """Displays bot latency."""
    latency_ms = bot.latency * 1000
    await interaction.response.send_message(f"Pong! Latency: {latency_ms:.2f}ms")

@bot.tree.command(name="hello", description="Greets the user.")
async def hello_slash(interaction: discord.Interaction):
    """Greets the user."""
    await interaction.response.send_message(f"Hello {interaction.user.mention}!")

@bot.tree.command(name="echo", description="Makes the bot repeat your message.")
@app_commands.describe(text="The message for the bot to repeat.")
async def echo_slash(interaction: discord.Interaction, text: str):
    """Repeats the user's message."""
    await interaction.response.send_message(f"You said: {text}")

@bot.tree.command(name="shutdown", description="Shuts down the bot (admin only).")
@commands.has_permissions(administrator=True)
async def shutdown_slash(interaction: discord.Interaction):
    """Shuts down the bot."""
    await interaction.response.send_message("Goodbye! Shutting down.")
    await bot.close()

@shutdown_slash.error
async def shutdown_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Error handler for the shutdown command."""
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"An error occurred: {error}", ephemeral=True)


# --- Run Bot ---

if __name__ == "__main__":
    if TOKEN is None:
        print("ERROR: Environment variable 'DISCORD_TOKEN' not found.")
        print("Make sure you have set the DISCORD_TOKEN variable:")
        print("- Locally: Create a .env file with DISCORD_TOKEN=YOUR_BOT_TOKEN")
        print("- On Railway: Add a variable with NAME='DISCORD_TOKEN' and VALUE='YOUR_BOT_TOKEN'.")
    else:
        print("Starting bot...")
        bot.run(TOKEN)