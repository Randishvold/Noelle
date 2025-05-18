import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import database
import utils
import datetime

class BasicCommandsCog(commands.Cog):
    """Basic utility, moderation, info, role management, and config commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --- Custom Check Function ---
    # This check will replace commands.has_permissions for specific commands
    async def is_authorized_for_command(self, interaction: discord.Interaction, command_type: str):
        """Checks if the user has one of the configured roles for the command type."""
        if interaction.guild is None:
            # Commands requiring guild context are handled by the command itself
            # This check is mainly for role-based authorization within a guild
            return True # Or False, depending on how strict you want for non-guild

        # Server owner can always bypass role restrictions
        if interaction.user.id == interaction.guild.owner_id:
            return True

        # Get server configuration
        config = database.get_server_config(interaction.guild_id)

        # Determine which role list to check based on command_type
        required_role_ids = []
        if command_type == 'mod':
            required_role_ids = config.get('mod_roles', []) # Get mod roles from config
        elif command_type == 'role_manager':
            required_role_ids = config.get('role_manager_roles', []) # Get role manager roles from config
        # Add other command types here if needed

        # If no roles are configured, allow anyone with basic command permission (optional)
        # Or enforce that roles *must* be configured to use these commands.
        # Let's enforce roles must be configured for these commands.
        if not required_role_ids:
             # No roles configured for this command type
             # User needs standard Discord permission or be owner
             # For simplicity, we'll rely on this check, so if list is empty, only owner can bypass
             pass # Proceed to check roles below

        # Check if the user has any of the required roles
        user_role_ids = [role.id for role in interaction.user.roles]
        # Check if there's any overlap between user's role IDs and required role IDs
        has_required_role = any(role_id in required_role_ids for role_id in user_role_ids)

        # You might still want to keep a base Discord permission check
        # alongside the role check for extra security, but let's remove
        # commands.has_permissions for now as requested.

        if has_required_role:
            return True
        else:
            # Check failed - raise CheckFailure with a custom message
            # This message will be caught by the error handler
            # Use a specific exception type if needed for more granular error handling
            raise app_commands.CheckFailure(f"You must have one of the configured roles to use this command ({command_type}).")


    async def _schedule_announcement_task(self, delay_seconds: float, target_channel: discord.TextChannel, embed_data: dict, invoker_user: discord.User, invoker_guild: discord.Guild, invoker_channel: discord.TextChannel):
        """Waits for a delay and sends the announcement embed."""
        await asyncio.sleep(delay_seconds)

        try:
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

    # --- Basic Commands (Ping, Hello, Say, Variables) ---
    # (These remain the same, they don't use the custom role check)

    @app_commands.command(name="ping", description="Responds with Pong! and bot latency.")
    async def ping_slash(self, interaction: discord.Interaction):
        """Displays bot latency."""
        latency_ms = self.bot.latency * 1000
        await interaction.response.send_message(f"Pong! Latency: {latency_ms:.2f}ms")

    @app_commands.command(name="hello", description="Greets the user.")
    async def hello_slash(self, interaction: discord.Interaction):
        """Greets the user."""
        await interaction.response.send_message(f"Hello {interaction.user.mention}!")

    @app_commands.command(name="say", description="Sends raw text to a channel. Useful for triggering other bots.")
    @app_commands.describe(text="The exact text for the bot to send.")
    @app_commands.describe(channel="The channel to send the message in.")
    @commands.has_permissions(manage_messages=True) # Keep Discord permission check for this command
    async def say_slash(self, interaction: discord.Interaction, text: str, channel: discord.TextChannel):
        """Sends raw text to a channel."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        raw_text_to_send = text

        try:
            await channel.send(raw_text_to_send)
            await interaction.response.send_message(
                f"Sent the message to {channel.mention}." # Simplified confirmation
                , ephemeral=True # Keep confirmation ephemeral
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
    @commands.has_permissions(manage_messages=True) # Keep Discord permission check for this command
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


    # --- Moderation Commands (Modified Responses and Added Check) ---

    @app_commands.command(name="kick", description="Kicks a member from the server.")
    @app_commands.describe(member="The member to kick.")
    @app_commands.describe(reason="The reason for kicking (optional).")
    # Remove commands.has_permissions - Rely on custom check
    @app_commands.check(lambda i: i.guild is not None) # Ensure command is in guild
    @app_commands.check(lambda i: BasicCommandsCog(i.client).is_authorized_for_command(i, 'mod')) # Apply custom check
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        """Kicks a member."""
        # Guild check already done by app_commands.check, but leave here for clarity or if check is removed
        # if interaction.guild is None: ...

        if member.id == interaction.user.id:
             await interaction.response.send_message("You cannot kick yourself.", ephemeral=True)
             return
        if member.id == interaction.guild.owner_id:
             await interaction.response.send_message("You cannot kick the server owner.", ephemeral=True)
             return

        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("I cannot kick this member as their highest role is equal to or higher than mine.", ephemeral=True)
            return

        try:
            # Defer the response publicly
            await interaction.response.defer(ephemeral=False)
            await member.kick(reason=reason)

            # Send public embed confirmation
            embed = discord.Embed(
                title="Member Kicked",
                description=f"{member.mention} has been kicked from the server.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Kicked By", value=interaction.user.mention, inline=True)
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)

            await interaction.followup.send(embed=embed)

        except discord.errors.Forbidden:
            await interaction.followup.send(f"I do not have permission to kick {member.mention}.", ephemeral=True) # Keep permission error ephemeral
        except Exception as e:
            print(f"Error kicking member: {e}")
            await interaction.followup.send(f"An error occurred while trying to kick {member.mention}.", ephemeral=True) # Keep other errors ephemeral


    @app_commands.command(name="ban", description="Bans a member from the server.")
    @app_commands.describe(member="The member to ban.")
    @app_commands.describe(reason="The reason for banning (optional).")
    # Remove commands.has_permissions - Rely on custom check
    @app_commands.check(lambda i: i.guild is not None) # Ensure command is in guild
    @app_commands.check(lambda i: BasicCommandsCog(i.client).is_authorized_for_command(i, 'mod')) # Apply custom check
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        """Bans a member."""
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if member.id == interaction.user.id:
             await interaction.response.send_message("You cannot ban yourself.", ephemeral=True)
             return
        if member.id == interaction.guild.owner_id:
             await interaction.response.send_message("You cannot ban the server owner.", ephemeral=True)
             return

        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("I cannot ban this member as their highest role is equal to or higher than mine.", ephemeral=True)
            return

        try:
            await interaction.response.defer(ephemeral=False)
            await member.ban(reason=reason)

            # Send public embed confirmation
            embed = discord.Embed(
                title="Member Banned",
                description=f"{member.mention} has been banned from the server.",
                color=discord.Color.red()
            )
            embed.add_field(name="Banned By", value=interaction.user.mention, inline=True)
            if reason:
                embed.add_field(name="Reason", value=reason, inline=False)

            await interaction.followup.send(embed=embed)

        except discord.errors.Forbidden:
            await interaction.followup.send(f"I do not have permission to ban {member.mention}.", ephemeral=True)
        except Exception as e:
            print(f"Error banning member: {e}")
            await interaction.followup.send(f"An error occurred while trying to ban {member.mention}.", ephemeral=True)

    # --- Info Commands (Already public, add embeds where applicable) ---
    # serverinfo_slash and userinfo_slash already use embeds, they are fine.


    # --- Role Management Commands (Modified Responses and Added Check) ---

    @app_commands.command(name="addrole", description="Gives a role to a member.")
    @app_commands.describe(member="The member to give the role to.")
    @app_commands.describe(role="The role to give.")
    # Remove commands.has_permissions - Rely on custom check
    @app_commands.check(lambda i: i.guild is not None) # Ensure command is in guild
    @app_commands.check(lambda i: BasicCommandsCog(i.client).is_authorized_for_command(i, 'role_manager')) # Apply custom check
    async def addrole_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        """Gives a role to a member."""
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if role == interaction.guild.default_role:
             await interaction.response.send_message("Cannot manually add the @everyone role.", ephemeral=True)
             return

        if role >= interaction.guild.me.top_role:
             await interaction.response.send_message("I cannot give this role as it is equal to or higher than my highest role.", ephemeral=True)
             return

        # User permission check via custom check now handles user role hierarchy too implicitly
        # as the check will fail if user doesn't have the configured mod/role_manager roles.
        # A separate check for user vs target role hierarchy is still good practice if desired.
        # if role >= interaction.user.top_role: ... # User's role must be higher than the role being managed

        if role in member.roles:
            await interaction.response.send_message(f"{member.mention} already has the role {role.mention}.", ephemeral=True)
            return

        try:
            await interaction.response.defer(ephemeral=False)
            await member.add_roles(role)

            # Send public embed confirmation
            embed = discord.Embed(
                title="Role Updated",
                description=f"Gave the role {role.mention} to {member.mention}.",
                color=discord.Color.green()
            )
            embed.add_field(name="Action By", value=interaction.user.mention, inline=True)

            await interaction.followup.send(embed=embed)

        except discord.errors.Forbidden:
            await interaction.followup.send(f"I do not have permission to give the role {role.mention}.", ephemeral=True)
        except Exception as e:
            print(f"Error adding role: {e}")
            await interaction.followup.send(f"An error occurred while trying to give the role {role.mention}.", ephemeral=True)


    @app_commands.command(name="removerole", description="Removes a role from a member.")
    @app_commands.describe(member="The member to remove the role from.")
    @app_commands.describe(role="The role to remove.")
    # Remove commands.has_permissions - Rely on custom check
    @app_commands.check(lambda i: i.guild is not None) # Ensure command is in guild
    @app_commands.check(lambda i: BasicCommandsCog(i.client).is_authorized_for_command(i, 'role_manager')) # Apply custom check
    async def removerole_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        """Removes a role from a member."""
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        if role == interaction.guild.default_role:
             await interaction.response.send_message("Cannot manually remove the @everyone role.", ephemeral=True)
             return

        if role >= interaction.guild.me.top_role:
             await interaction.response.send_message("I cannot remove this role as it is equal to or higher than my highest role.", ephemeral=True)
             return

        # User permission check via custom check now handles user role hierarchy too implicitly

        if role not in member.roles:
            await interaction.response.send_message(f"{member.mention} does not have the role {role.mention}.", ephemeral=True)
            return

        try:
            await interaction.response.defer(ephemeral=False)
            await member.remove_roles(role)

            # Send public embed confirmation
            embed = discord.Embed(
                title="Role Updated",
                description=f"Removed the role {role.mention} from {member.mention}.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Action By", value=interaction.user.mention, inline=True)

            await interaction.followup.send(embed=embed)

        except discord.errors.Forbidden:
            await interaction.followup.send(f"I do not have permission to remove the role {role.mention}.", ephemeral=True)
        except Exception as e:
            print(f"Error removing role: {e}")
            await interaction.followup.send(f"An error occurred while trying to remove the role {role.mention}.", ephemeral=True)


    # --- Configuration Commands (NEW GROUP) ---

    # Create a command group named 'config'
    config_group = app_commands.Group(name='config', description='Manage server bot configuration.')

    # Add the group to the bot's command tree (done implicitly when cog is added, but explicit is possible)
    # bot.tree.add_command(config_group) # No need to add here if defined as part of the Cog

    # Only server owner or users with Manage Guild permission can use config commands
    @config_group.command(name='mod_roles', description='Manage roles that can use moderation commands.')
    @app_commands.describe(action="Add or remove a role.", role="The role to add or remove.")
    @app_commands.choices(action=[
        app_commands.Choice(name='add', value='add'),
        app_commands.Choice(name='remove', value='remove'),
    ])
    @commands.has_permissions(manage_guild=True) # Requires Manage Guild permission for config changes
    async def config_mod_roles_slash(self, interaction: discord.Interaction, action: app_commands.Choice[str], role: discord.Role):
        """Adds or removes roles from the mod roles list."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # Get current config
        config = database.get_server_config(interaction.guild_id)
        mod_role_ids = config.get('mod_roles', []) # Ensure it's a list, default to empty

        role_id = role.id
        role_mention = role.mention

        updated = False
        if action.value == 'add':
            if role_id not in mod_role_ids:
                mod_role_ids.append(role_id)
                updated = True
                message = f"Added {role_mention} to the moderation roles list."
            else:
                message = f"{role_mention} is already in the moderation roles list."
        elif action.value == 'remove':
            if role_id in mod_role_ids:
                mod_role_ids.remove(role_id)
                updated = True
                message = f"Removed {role_mention} from the moderation roles list."
            else:
                message = f"{role_mention} is not in the moderation roles list."
        else:
             message = "Invalid action specified." # Should not happen with choices

        if updated:
            # Update the config in the database
            database.update_server_config(interaction.guild_id, {'mod_roles': mod_role_ids})

        await interaction.response.send_message(message, ephemeral=True) # Keep config changes ephemeral


    @config_group.command(name='role_manager_roles', description='Manage roles that can use role management commands.')
    @app_commands.describe(action="Add or remove a role.", role="The role to add or remove.")
    @app_commands.choices(action=[
        app_commands.Choice(name='add', value='add'),
        app_commands.Choice(name='remove', value='remove'),
    ])
    @commands.has_permissions(manage_guild=True) # Requires Manage Guild permission
    async def config_role_manager_roles_slash(self, interaction: discord.Interaction, action: app_commands.Choice[str], role: discord.Role):
        """Adds or removes roles from the role manager roles list."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        config = database.get_server_config(interaction.guild_id)
        role_manager_role_ids = config.get('role_manager_roles', []) # Ensure it's a list

        role_id = role.id
        role_mention = role.mention

        updated = False
        if action.value == 'add':
            if role_id not in role_manager_role_ids:
                role_manager_role_ids.append(role_id)
                updated = True
                message = f"Added {role_mention} to the role manager roles list."
            else:
                message = f"{role_mention} is already in the role manager roles list."
        elif action.value == 'remove':
            if role_id in role_manager_role_ids:
                role_manager_role_ids.remove(role_id)
                updated = True
                message = f"Removed {role_mention} from the role manager roles list."
            else:
                message = f"{role_mention} is not in the role manager roles list."
        else:
             message = "Invalid action specified." # Should not happen with choices

        if updated:
            database.update_server_config(interaction.guild_id, {'role_manager_roles': role_manager_role_ids})

        await interaction.response.send_message(message, ephemeral=True) # Keep config changes ephemeral


    @config_group.command(name='show', description='Show the current server configuration.')
    @commands.has_permissions(manage_guild=True) # Requires Manage Guild permission
    async def config_show_slash(self, interaction: discord.Interaction):
        """Shows the current server configuration."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        config = database.get_server_config(interaction.guild_id)

        embed = discord.Embed(
            title=f"Bot Configuration for {interaction.guild.name}",
            color=discord.Color.gold()
        )
        embed.add_field(name="Server ID", value=interaction.guild_id, inline=False)

        # Display Mod Roles
        mod_role_mentions = [f"<@&{role_id}>" for role_id in config.get('mod_roles', [])]
        embed.add_field(name="Moderation Roles", value=", ".join(mod_role_mentions) if mod_role_mentions else "None Configured", inline=False)

        # Display Role Manager Roles
        role_manager_role_mentions = [f"<@&{role_id}>" for role_id in config.get('role_manager_roles', [])]
        embed.add_field(name="Role Manager Roles", value=", ".join(role_manager_role_mentions) if role_manager_role_mentions else "None Configured", inline=False)

        # Add other config fields here later

        await interaction.response.send_message(embed=embed, ephemeral=True) # Keep config show ephemeral


    # --- Error Handler for basic commands (add config commands to it) ---
    async def basic_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for basic commands."""
        if isinstance(error, app_commands.MissingPermissions):
             if interaction.response.is_done():
                 await interaction.followup.send("You don't have permission to use this command.", ephemeral=True)
             else:
                 await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        # Handle the custom check failure
        elif isinstance(error, app_commands.CheckFailure) and "configured roles" in str(error): # Check for the specific message from our custom check
             if interaction.response.is_done():
                 await interaction.followup.send(str(error), ephemeral=True) # Send custom check error message
             else:
                 await interaction.response.send_message(str(error), ephemeral=True) # Send custom check error message
        elif isinstance(error, app_commands.CommandInvokeError):
             print(f"CommandInvokeError in basic command: {error.original}")
             if interaction.response.is_done():
                 await interaction.followup.send(f"An error occurred while executing the command: {error.original}", ephemeral=True)
             else:
                 await interaction.response.send_message(f"An error occurred while executing the command: {error.original}", ephemeral=True)
        elif isinstance(error, app_commands.TransformerError) and isinstance(error.original, ValueError):
             if interaction.response.is_done():
                 await interaction.followup.send(f"Invalid value provided for an argument: {error.original}", ephemeral=True)
             else:
                 await interaction.response.send_message(f"Invalid value provided for an argument: {error.original}", ephemeral=True)
        else:
            print(f"An unexpected error occurred in basic command: {error}")
            if interaction.response.is_done():
                await interaction.followup.send(f"An unexpected error occurred: {error}", ephemeral=True)
            else:
                 await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)


    # Attach error handlers to the commands
    ping_slash.error(basic_command_error)
    hello_slash.error(basic_command_error)
    say_slash.error(basic_command_error)
    variables_slash.error(basic_command_error)
    pengumuman_slash.error(basic_command_error)
    kick_slash.error(basic_command_error)
    ban_slash.error(basic_command_error)
    serverinfo_slash.error(basic_command_error)
    userinfo_slash.error(basic_command_error)
    addrole_slash.error(basic_command_error)
    removerole_slash.error(basic_command_error)
    # --- Attach error handlers for config commands ---
    config_mod_roles_slash.error(basic_command_error)
    config_role_manager_roles_slash.error(basic_command_error)
    config_show_slash.error(basic_command_error)


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the BasicCommands cog."""
    await bot.add_cog(BasicCommandsCog(bot))