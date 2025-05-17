import discord
from discord.ext import commands
from discord import app_commands

class BasicCommandsCog(commands.Cog):
    """Basic utility commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Responds with Pong! and bot latency.")
    async def ping_slash(self, interaction: discord.Interaction):
        """Displays bot latency."""
        latency_ms = self.bot.latency * 1000
        await interaction.response.send_message(f"Pong! Latency: {latency_ms:.2f}ms")

    @app_commands.command(name="hello", description="Greets the user.")
    async def hello_slash(self, interaction: discord.Interaction):
        """Greets the user."""
        await interaction.response.send_message(f"Hello {interaction.user.mention}!")

# --- Setup function ---
# This is required by discord.py to load the cog
async def setup(bot: commands.Bot):
    """Sets up the BasicCommands cog."""
    await bot.add_cog(BasicCommandsCog(bot))
    # No need to sync here, sync is done in on_ready in bot.py