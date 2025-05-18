import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import database # Still needed for /pengumuman and potentially other future commands
import utils # Still needed for /pengumuman and /variables

class BasicCommandsCog(commands.Cog):
    """Basic utility commands, announcement command, and raw message sending."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _schedule_announcement_task(self, delay_seconds: float, target_channel: discord.TextChannel, embed_data: dict, invoker_user: discord.User, invoker_guild: discord.Guild, invoker_channel: discord.TextChannel):
        """Waits for a delay and sends the announcement embed."""
        await asyncio.sleep(delay_seconds)

        try:
            # Use utils.create_processed_embed (assuming it's moved to utils.py)
            final_embed_object = utils.create_processed_embed(
                embed_data,
                user=invoker_user,
                member=invoker_user if invoker_guild else None,
                guild=invoker_guild,
                channel=invoker_channel
            )
        except Exception as e:
            print(f"Error creating final embed object in scheduled task: {e}")
            if invoker_channel:
                 await invoker_channel.send(f"Failed to send scheduled announcement: Could not prepare embed. Error: {e}")
            return

        try:
            await target_channel.send(embed=final_embed_object)
            print(f"Scheduled announcement sent to {target_channel.name} in {target_channel.guild.name} after {delay_seconds} seconds.")
        except discord.errors.Forbidden:
            print(f"Failed to send scheduled announcement: Missing permissions in {target_channel.name} ({target_channel.id}) in guild {target_channel.guild.name} ({target_channel.guild.id}).")
        except Exception as e:
            print(f"An error occurred while sending scheduled announcement: {e}")
            if invoker_channel:
                 await invoker_channel.send(f"Failed to send scheduled announcement: An error occurred during sending. Error: {e}")

    @app_commands.command(name="ping", description="Responds with Pong! and bot latency.")
    async def ping_slash(self, interaction: discord.Interaction):
        """Displays bot latency."""
        latency_ms = self.bot.latency * 1000
        await interaction.response.send_message(f"Pong! Latency: {latency_ms:.2f}ms")

    @app_commands.command(name="hello", description="Greets the user.")
    async def hello_slash(self, interaction: discord.Interaction):
        """Greets the user."""
        await interaction.response.send_message(f"Hello {interaction.user.mention}!")

    # --- Modified Command: /say ---
    @app_commands.command(name="say", description="Sends raw text to a channel. Useful for triggering other bots.")
    @app_commands.describe(text="The exact text for the bot to send.")
    @app_commands.describe(channel="The channel to send the message in.") # Made channel required as it's the target for sending
    @commands.has_permissions(manage_messages=True) # Recommended permission to prevent spam
    async def say_slash(self, interaction: discord.Interaction, text: str, channel: discord.TextChannel):
        """Sends raw text to a channel."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # --- Removed variable processing ---
        # The text input will be sent exactly as provided by the user.
        raw_text_to_send = text

        # Optional: Check if Mimu Bot is in the guild (similar to old trigger_mimu)
        # mimu_user = self.bot.get_user(100036355262115840) # Mimu Bot's public user ID
        # if mimu_user and interaction.guild and interaction.guild.get_member(mimu_user.id) is None:
        #     # Decide how to handle: warn user, or proceed anyway?
        #     # Let's proceed anyway, the user might be triggering a different bot
        #     pass # No action needed if we just want to send the message

        try:
            # Send the raw text to the target channel
            await channel.send(raw_text_to_send)

            # Acknowledge the command interaction
            # Inform user that raw text was sent
            await interaction.response.send_message(
                f"Sent the message '{raw_text_to_send}' to {channel.mention}."
                f"\nIf this is a trigger for another bot (like Mimu), it should respond shortly."
                , ephemeral=True
            )
        except discord.errors.Forbidden:
            await interaction.response.send_message(f"I do not have permission to send messages in {channel.mention}.", ephemeral=True)
        except Exception as e:
            print(f"An error occurred while sending message via /say: {e}")
            await interaction.response.send_message(f"An error occurred while trying to send the message: {e}", ephemeral=True)

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

    @app_commands.command(name="pengumuman", description="Send an announcement with optional custom embed and timer.")
    @app_commands.describe(title="The title for the announcement.")
    @app_commands.describe(teks="The main text content for the announcement.")
    @app_commands.describe(channel="The channel to send the announcement in.")
    @app_commands.describe(embed="The name of the custom embed template to use (optional).")
    @app_commands.describe(timer="Countdown in minutes before sending (optional, min 1 minute).")
    @commands.has_permissions(manage_messages=True)
    async def pengumuman_slash(self, interaction: discord.Interaction, title: str, teks: str, channel: discord.TextChannel, embed: str = None, timer: app_commands.Range[int, 1, None] = None):
        """Sends a custom announcement message with optional embed and timer."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        embed_data = None

        if embed:
            loaded_embed_data = database.get_custom_embed(interaction.guild_id, embed)
            if loaded_embed_data is None:
                await interaction.response.send_message(f"Custom embed template '{embed}' not found.", ephemeral=True)
                return

            embed_data = loaded_embed_data
        else:
            embed_data = {}

        if not isinstance(embed_data, dict):
             print(f"Warning: embed_data was not a dict. Found type: {type(embed_data)}. Starting with empty dict.")
             embed_data = {}

        embed_data['title'] = title
        embed_data['description'] = teks

        if timer is not None and timer > 0:
            delay_seconds = timer * 60
            await interaction.response.send_message(f"Announcement scheduled to be sent to {channel.mention} in {timer} minutes!", ephemeral=True)
            self.bot.loop.create_task(
                self._schedule_announcement_task(
                    delay_seconds,
                    channel,
                    embed_data,
                    interaction.user,
                    interaction.guild,
                    interaction.channel
                )
            )
            print(f"Announcement task scheduled for {delay_seconds} seconds.")

        else:
            try:
                # Use utils.create_processed_embed (assuming it's moved to utils.py)
                final_embed_object = utils.create_processed_embed(
                    embed_data,
                    user=interaction.user,
                    member=interaction.user,
                    guild=interaction.guild,
                    channel=interaction.channel
                )
            except Exception as e:
                print(f"Error creating final embed object for immediate send: {e}")
                await interaction.response.send_message(f"An error occurred while preparing the embed for sending: {e}", ephemeral=True)
                return

            try:
                await channel.send(embed=final_embed_object)
                await interaction.response.send_message(f"Announcement sent to {channel.mention}!", ephemeral=True)
                print(f"Announcement sent immediately to {channel.name} in {channel.guild.name}.")

            except discord.errors.Forbidden:
                 await interaction.response.send_message(f"I do not have permission to send messages in {channel.mention}.", ephemeral=True)
            except Exception as e:
                print(f"An error occurred while sending the announcement immediately: {e}")
                await interaction.response.send_message(f"An error occurred while sending the announcement: {e}", ephemeral=True)


    # --- Error Handler for basic commands ---
    async def basic_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for basic commands."""
        if isinstance(error, app_commands.MissingPermissions):
             await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, app_commands.CommandInvokeError):
             print(f"CommandInvokeError in basic command: {error.original}")
             await interaction.response.send_message(f"An error occurred while executing the command: {error.original}", ephemeral=True)
        elif isinstance(error, app_commands.TransformerError) and isinstance(error.original, ValueError):
             await interaction.response.send_message(f"Invalid value provided for an argument: {error.original}", ephemeral=True)
        else:
            print(f"An unexpected error occurred in basic command: {error}")
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

    # Attach error handlers to the commands
    say_slash.error(basic_command_error) # Keep say_slash attached to the error handler
    variables_slash.error(basic_command_error)
    pengumuman_slash.error(basic_command_error)


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the BasicCommands cog."""
    await bot.add_cog(BasicCommandsCog(bot))