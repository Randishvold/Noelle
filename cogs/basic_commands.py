import discord
from discord.ext import commands
from discord import app_commands
# Import database module to load embeds
import database
import utils # Import utils from parent directory

class BasicCommandsCog(commands.Cog):
    """Basic utility commands and announcement command."""

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
    @commands.has_permissions(manage_messages=True)
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

    # --- New Command: /pengumuman ---
    @app_commands.command(name="pengumuman", description="Send an announcement with optional custom embed.")
    @app_commands.describe(title="The title for the announcement.")
    @app_commands.describe(teks="The main text content for the announcement.")
    @app_commands.describe(channel="The channel to send the announcement in.")
    @app_commands.describe(embed="The name of the custom embed template to use (optional).")
    # Timer is optional and not implemented yet
    # @app_commands.describe(timer="Countdown in minutes before sending (optional, not yet implemented).")
    @commands.has_permissions(manage_messages=True) # Requires permission to manage messages
    async def pengumuman_slash(self, interaction: discord.Interaction, title: str, teks: str, channel: discord.TextChannel, embed: str = None): # timer: int = None
        """Sends a custom announcement message."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        embed_data = None # Start with no embed data

        if embed: # If an embed name is provided
            # Load embed data from the database
            loaded_embed_data = database.get_custom_embed(interaction.guild_id, embed)

            if loaded_embed_data is None:
                # Inform the user if the embed template was not found
                await interaction.response.send_message(f"Custom embed template '{embed}' not found.", ephemeral=True)
                return # Stop execution if embed not found

            embed_data = loaded_embed_data # Use the loaded data as base

        else: # If no embed name is provided, create a simple embed structure
            embed_data = {} # Start with an empty dictionary

        # --- Inject (Override) title and description from command input ---
        # Ensure the data is treated as a dictionary
        if not isinstance(embed_data, dict):
             print(f"Warning: embed_data was not a dict. Found type: {type(embed_data)}. Starting with empty dict.")
             embed_data = {} # Fallback to empty dict if loaded data was invalid

        # Override title and description with user input.
        # These inputs can also contain variables themselves (e.g., {user.name})
        embed_data['title'] = title
        embed_data['description'] = teks

        # --- Create the final discord.Embed object with variables processed ---
        # Use the create_processed_embed helper function from embed_cog
        # Note: create_processed_embed is defined in embed_cog. We need to access it.
        # Option 1: Move create_processed_embed to utils.py (Recommended for utility functions)
        # Option 2: Access it via bot.get_cog('EmbedCog').create_processed_embed (More complex)
        # Let's move create_processed_embed to utils.py for better modularity.
        # (Assume create_processed_embed is now in utils.py - requires updating utils.py)
        try:
            # Pass the modified embed_data to the helper function
            # Pass context from the interaction
            final_embed_object = utils.create_processed_embed(
                embed_data,
                user=interaction.user,
                member=interaction.user, # interaction.user is also a member in a guild
                guild=interaction.guild,
                channel=interaction.channel # Context of the command invocation channel
            )

        except Exception as e:
            print(f"Error creating final embed object in /pengumuman: {e}")
            await interaction.response.send_message(f"An error occurred while preparing the embed: {e}", ephemeral=True)
            return # Stop if embed creation fails


        # --- Send the embed to the target channel ---
        try:
            # Discord permissions check will handle if bot cannot send to channel
            await channel.send(embed=final_embed_object)

            # Acknowledge the command interaction
            # Use followup.send because interaction.response has already been used if embed was not found
            # Or simply send an ephemeral success message. Ephemeral is cleaner.
            await interaction.response.send_message(f"Announcement sent to {channel.mention}!", ephemeral=True)

        except discord.errors.Forbidden:
             await interaction.response.send_message(f"I do not have permission to send messages in {channel.mention}.", ephemeral=True)
        except Exception as e:
            print(f"Error sending announcement embed: {e}")
            await interaction.response.send_message(f"An error occurred while sending the announcement: {e}", ephemeral=True)


    # --- Error Handler for basic commands (add pengumuman to it) ---
    # Assuming you have a general error handler or add one like this:
    async def basic_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for basic commands."""
        if isinstance(error, app_commands.MissingPermissions):
             await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, app_commands.CommandInvokeError):
             # Log the original exception from CommandInvokeError
             print(f"CommandInvokeError in basic command: {error.original}")
             await interaction.response.send_message(f"An error occurred while executing the command: {error.original}", ephemeral=True)
        else:
            print(f"An unexpected error occurred in basic command: {error}")
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

    # Attach error handlers to the commands
    say_slash.error(basic_command_error)
    variables_slash.error(basic_command_error)
    # --- Attach error handler to the new command ---
    pengumuman_slash.error(basic_command_error)


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the BasicCommands cog."""
    await bot.add_cog(BasicCommandsCog(bot))
    # No need to sync here, sync is done in on_ready in bot.py