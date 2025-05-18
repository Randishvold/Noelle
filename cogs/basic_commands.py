import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import database
import utils
import datetime

class BasicCommandsCog(commands.Cog):
    """Basic utility, moderation, and info commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
    @commands.has_permissions(manage_messages=True)
    async def say_slash(self, interaction: discord.Interaction, text: str, channel: discord.TextChannel):
        """Sends raw text to a channel."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        raw_text_to_send = text

        try:
            await channel.send(raw_text_to_send)
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


    # --- Moderation Commands ---

    @app_commands.command(name="kick", description="Kicks a member from the server.")
    @app_commands.describe(member="The member to kick.")
    @app_commands.describe(reason="The reason for kicking (optional).")
    @commands.has_permissions(kick_members=True) # Requires Kick Members permission
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        """Kicks a member."""
        # Ensure command is used in a guild
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # Prevent kicking self or server owner
        if member.id == interaction.user.id:
             await interaction.response.send_message("You cannot kick yourself.", ephemeral=True)
             return
        if member.id == interaction.guild.owner_id:
             await interaction.response.send_message("You cannot kick the server owner.", ephemeral=True)
             return

        # Prevent bot from kicking members higher in hierarchy
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message("I cannot kick this member as their highest role is equal to or higher than mine.", ephemeral=True)
            return

        try:
            await interaction.response.defer(ephemeral=True)
            await member.kick(reason=reason)
            await interaction.followup.send(f'{member.mention} has been kicked.' + (f' Reason: {reason}' if reason else ''))
        except discord.errors.Forbidden:
            await interaction.followup.send(f"I do not have permission to kick {member.mention}.", ephemeral=True)
        except Exception as e:
            print(f"Error kicking member: {e}")
            await interaction.followup.send(f"An error occurred while trying to kick {member.mention}.", ephemeral=True)


    @app_commands.command(name="ban", description="Bans a member from the server.")
    @app_commands.describe(member="The member to ban.")
    @app_commands.describe(reason="The reason for banning (optional).")
    @commands.has_permissions(ban_members=True) # Requires Ban Members permission
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
            await interaction.response.defer(ephemeral=True)
            await member.ban(reason=reason)
            await interaction.followup.send(f'{member.mention} has been banned.' + (f' Reason: {reason}' if reason else ''))
        except discord.errors.Forbidden:
            await interaction.followup.send(f"I do not have permission to ban {member.mention}.", ephemeral=True)
        except Exception as e:
            print(f"Error banning member: {e}")
            await interaction.followup.send(f"An error occurred while trying to ban {member.mention}.", ephemeral=True)

    # Note: Mute/Timeout is more complex, requiring role setup or using Discord's native timeout

    # --- Info Commands ---

    @app_commands.command(name="serverinfo", description="Displays information about the server.")
    async def serverinfo_slash(self, interaction: discord.Interaction):
        """Displays server information."""
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        guild = interaction.guild

        embed = discord.Embed(
            title=f"Server Info: {guild.name}",
            color=discord.Color.blue()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="Server ID", value=guild.id, inline=True)
        embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "N/A", inline=True)
        embed.add_field(name="Created On", value=utils.format_date(guild.created_at), inline=False)
        embed.add_field(name="Member Count", value=guild.member_count, inline=True)
        embed.add_field(name="Channel Count", value=len(guild.channels), inline=True)
        embed.add_field(name="Role Count", value=len(guild.roles), inline=True)
        embed.add_field(name="Boost Level", value=f"{guild.premium_tier} (Boosts: {guild.premium_subscription_count})", inline=True)
        embed.add_field(name="Verification Level", value=str(guild.verification_level).split('.')[-1].capitalize(), inline=True)

        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="userinfo", description="Displays information about a user.")
    @app_commands.describe(member="The member to get info about (defaults to yourself).")
    async def userinfo_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        """Displays user information."""
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        target_member = member or interaction.user

        embed = discord.Embed(
            title=f"User Info: {target_member.display_name}",
            color=target_member.color if target_member.color != discord.Color.default() else discord.Color.blue()
        )
        if target_member.avatar:
            embed.set_thumbnail(url=target_member.avatar.url)
        if target_member.guild_avatar:
             embed.set_image(url=target_member.guild_avatar.url)

        embed.add_field(name="Username", value=f"{target_member.name}#{target_member.discriminator}" if target_member.discriminator != '0' else target_member.name, inline=True)
        embed.add_field(name="ID", value=target_member.id, inline=True)
        embed.add_field(name="Account Created", value=utils.format_date(target_member.created_at), inline=False)
        embed.add_field(name="Joined Server", value=utils.format_date(target_member.joined_at), inline=False)

        roles = [role.mention for role in target_member.roles if role.name != '@everyone']
        if roles:
            embed.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles), inline=False)
        else:
             embed.add_field(name="Roles (0)", value="None", inline=False)

        embed.add_field(name="Highest Role", value=target_member.top_role.mention, inline=True)
        if target_member.pending:
             embed.add_field(name="Pending", value="Yes", inline=True)


        await interaction.response.send_message(embed=embed)

    # --- Role Management Commands ---

    @app_commands.command(name="addrole", description="Gives a role to a member.")
    @app_commands.describe(member="The member to give the role to.")
    @app_commands.describe(role="The role to give.")
    @commands.has_permissions(manage_roles=True) # Requires Manage Roles permission
    async def addrole_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        """Gives a role to a member."""
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # FIX: Change role.is_everyone to role == interaction.guild.default_role
        if role == interaction.guild.default_role:
             await interaction.response.send_message("Cannot manually add the @everyone role.", ephemeral=True)
             return

        # Prevent bot giving roles higher than its own highest role
        if role >= interaction.guild.me.top_role:
             await interaction.response.send_message("I cannot give this role as it is equal to or higher than my highest role.", ephemeral=True)
             return

        # Prevent user giving roles higher than their own highest role (Optional)
        # if role >= interaction.user.top_role:
        #     await interaction.response.send_message("You cannot give a role higher than your own highest role.", ephemeral=True)
        #     return

        # Check if member already has the role
        if role in member.roles:
            await interaction.response.send_message(f"{member.mention} already has the role {role.mention}.", ephemeral=True)
            return

        try:
            await interaction.response.defer(ephemeral=True)
            await member.add_roles(role)
            await interaction.followup.send(f"Gave the role {role.mention} to {member.mention}.")
        except discord.errors.Forbidden:
            await interaction.followup.send(f"I do not have permission to give the role {role.mention}.", ephemeral=True)
        except Exception as e:
            print(f"Error adding role: {e}")
            await interaction.followup.send(f"An error occurred while trying to give the role {role.mention}.", ephemeral=True)


    @app_commands.command(name="removerole", description="Removes a role from a member.")
    @app_commands.describe(member="The member to remove the role from.")
    @app_commands.describe(role="The role to remove.")
    @commands.has_permissions(manage_roles=True) # Requires Manage Roles permission
    async def removerole_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        """Removes a role from a member."""
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # FIX: Change role.is_everyone to role == interaction.guild.default_role
        if role == interaction.guild.default_role:
             await interaction.response.send_message("Cannot manually remove the @everyone role.", ephemeral=True)
             return

        # Prevent bot removing roles higher than its own highest role
        if role >= interaction.guild.me.top_role:
             await interaction.response.send_message("I cannot remove this role as it is equal to or higher than my highest role.", ephemeral=True)
             return

        # Prevent user removing roles higher than their own highest role (Optional)
        # if role >= interaction.user.top_role:
        #     await interaction.response.send_message("You cannot remove a role higher than your own highest role.", ephemeral=True)
        #     return

        # Check if member has the role
        if role not in member.roles:
            await interaction.response.send_message(f"{member.mention} does not have the role {role.mention}.", ephemeral=True)
            return

        try:
            await interaction.response.defer(ephemeral=True)
            await member.remove_roles(role)
            await interaction.followup.send(f"Removed the role {role.mention} from {member.mention}.")
        except discord.errors.Forbidden:
            await interaction.followup.send(f"I do not have permission to remove the role {role.mention}.", ephemeral=True)
        except Exception as e:
            print(f"Error removing role: {e}")
            await interaction.followup.send(f"An error occurred while trying to remove the role {role.mention}.", ephemeral=True)


    # --- Error Handler for basic commands ---
    async def basic_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for basic commands."""
        if isinstance(error, app_commands.MissingPermissions):
             if interaction.response.is_done():
                 await interaction.followup.send("You don't have permission to use this command.", ephemeral=True)
             else:
                 await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
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


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the BasicCommands cog."""
    await bot.add_cog(BasicCommandsCog(bot))