import discord
from discord.ext import commands
from discord import app_commands
import utils 

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
    @app_commands.describe(channel="The channel to send the message in (optional).")
    @commands.has_permissions(manage_messages=True) # Added permission check for /say
    async def say_slash(self, interaction: discord.Interaction, text: str, channel: discord.TextChannel = None):
        """Makes the bot say something with variables."""
        target_channel = channel if channel is not None else interaction.channel

        if target_channel is None:
             await interaction.response.send_message("Could not determine a channel to send the message to.", ephemeral=True)
             return

        processed_text = utils.replace_variables(
            text,
            user=interaction.user,
            member=interaction.user, # User is also a member in a guild
            guild=interaction.guild,
            channel=interaction.channel
        )

        try:
            await target_channel.send(processed_text)
            await interaction.response.send_message(f"Message sent to {target_channel.mention}!", ephemeral=True)

        except Exception as e:
            print(f"Error sending message via /say: {e}")
            await interaction.response.send_message(f"Failed to send message: {e}", ephemeral=True)

    @app_commands.command(name="variables", description="Lists available text variables and their usage.")
    async def variables_slash(self, interaction: discord.Interaction):
        """Lists available variables and their descriptions."""
        available_variables = utils.get_available_variables()

        if not available_variables:
            await interaction.response.send_message("No variables are currently defined.", ephemeral=True)
            return

        sorted_variables = sorted(available_variables.items())

        variable_list_text = "\n".join(
            f"`{{{name}}}` - {description}" for name, description in sorted_variables
        )

        embed = discord.Embed(
            title="Available Variables",
            description="You can use these variables inside custom embeds or with commands like `/say`.\n\n" + variable_list_text,
            color=discord.Color.purple()
        )
        embed.set_footer(text="Variables are replaced based on the context (user, server, channel).")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Error handler for /say and /variables
    async def basic_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for basic commands."""
        if isinstance(error, app_commands.MissingPermissions):
             await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        else:
            print(f"Error in basic command: {error}")
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

    say_slash.error(basic_command_error)
    variables_slash.error(basic_command_error)


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the BasicCommands cog."""
    await bot.add_cog(BasicCommandsCog(bot))