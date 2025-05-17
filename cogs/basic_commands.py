import discord
from discord.ext import commands
from discord import app_commands
from .. import utils # Import utils from parent directory

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

    @app_commands.command(name="say", description="Makes the bot say something with variable support.")
    @app_commands.describe(text="The text for the bot to say (supports variables).")
    @app_commands.describe(channel="The channel to send the message in (optional).") # Optional argument for channel
    async def say_slash(self, interaction: discord.Interaction, text: str, channel: discord.TextChannel = None):
        """Makes the bot say something with variables."""
        # Use interaction.channel if channel is None (default to current channel)
        target_channel = channel if channel is not None else interaction.channel

        if target_channel is None: # Should not happen in guild commands, but safety check
             await interaction.response.send_message("Could not determine a channel to send the message to.", ephemeral=True)
             return

        # Replace variables in the input text
        # Provide all available context from the interaction
        processed_text = utils.replace_variables(
            text,
            user=interaction.user,
            member=interaction.user, # User is also a member in a guild
            guild=interaction.guild,
            channel=interaction.channel # Context of the command invocation channel
            # Note: For the target_channel variable replacement, we pass interaction.channel
            # This means {channel.name} etc. will refer to the channel where the command was invoked,
            # not the target channel where the message is sent. Adjust replace_variables if needed
            # to specify which channel context to use for channel variables.
            # A simpler approach for now is to only use interaction.channel as the channel context.
        )

        try:
            await target_channel.send(processed_text)
            # Acknowledge the command interaction (important for slash commands)
            # Use followup.send because response.send_message is often used for the *actual* message
            # Or use response.send_message here and make the bot say the message via followup
            # Let's acknowledge ephemerally first.
            await interaction.response.send_message(f"Message sent to {target_channel.mention}!", ephemeral=True)

        except Exception as e:
            print(f"Error sending message via /say: {e}")
            await interaction.response.send_message(f"Failed to send message: {e}", ephemeral=True)


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the BasicCommands cog."""
    await bot.add_cog(BasicCommandsCog(bot))
    # No need to sync here, sync is done in on_ready in bot.py