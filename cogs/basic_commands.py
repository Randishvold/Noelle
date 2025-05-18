import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import database
import utils
import datetime

# Configure logging for basic commands (optional, but good practice)
import logging
_logger = logging.getLogger(__name__)
# If you want different logging levels per cog, you can configure it here
# _logger.setLevel(logging.DEBUG)


class BasicCommandsCog(commands.Cog):
    """Basic utility, moderation, info, role management, and config commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("BasicCommandsCog initialized.")


    # --- Custom Check Function ---
    # Note: Custom checks are called BEFORE the command function executes.
    # Raising app_commands.CheckFailure is the standard way to signal check failure.
    async def is_authorized_for_command(self, interaction: discord.Interaction, command_type: str):
        """Checks if the user has one of the configured roles for the command type."""
        if interaction.guild is None:
            # Commands requiring specific roles should ideally use @app_commands.guild_only()
            # or handle the None case gracefully. This check should ideally not be reached
            # for non-guild interactions if guild_only() is used.
            _logger.debug(f"is_authorized_for_command check called outside guild for user {interaction.user.id}.")
            return True # Or raise CheckFailure if command is intended for guilds only

        # Guild owner always bypasses role checks
        if interaction.user.id == interaction.guild.owner_id:
            _logger.debug(f"User {interaction.user.id} is guild owner, check passed.")
            return True

        config = database.get_server_config(interaction.guild_id)

        required_role_ids = []
        if command_type == 'mod':
            required_role_ids = config.get('mod_roles', [])
            _logger.debug(f"Checking mod roles: {required_role_ids}")
        elif command_type == 'role_manager':
            required_role_ids = config.get('role_manager_roles', [])
            _logger.debug(f"Checking role manager roles: {required_role_ids}")
        else:
             _logger.warning(f"Unknown command_type '{command_type}' passed to is_authorized_for_command.")
             # Should probably default to requiring admin or similar, but for now let check pass if type is unknown
             return True # Or raise an error/CheckFailure for misconfiguration?

        # If no roles are configured, anyone can use the command
        if not required_role_ids:
             _logger.debug(f"No roles configured for command_type '{command_type}', check passed.")
             return True

        user_role_ids = [role.id for role in interaction.user.roles]
        has_required_role = any(role_id in required_role_ids for role_id in user_role_ids)

        if has_required_role:
            _logger.debug(f"User {interaction.user.id} has required role, check passed.")
            return True
        else:
            _logger.debug(f"User {interaction.user.id} does NOT have required role, check failed.")
            # Raise CheckFailure with a specific message
            raise app_commands.CheckFailure(f"Anda harus memiliki salah satu peran yang dikonfigurasi ({command_type}) untuk menggunakan perintah ini.")


    async def _schedule_announcement_task(self, delay_seconds: float, target_channel: discord.TextChannel, embed_data: dict, invoker_user: discord.User, invoker_guild: discord.Guild, invoker_channel: discord.TextChannel):
        """Waits for a delay and sends the announcement embed."""
        _logger.info(f"Scheduling announcement task for {delay_seconds} seconds.")
        await asyncio.sleep(delay_seconds)

        _logger.info(f"Executing scheduled announcement task for channel {target_channel.id} in guild {target_channel.guild.id}.")

        try:
            # Use utils.create_processed_embed
            final_embed_object = utils.create_processed_embed(
                embed_data,
                user=invoker_user,
                member=invoker_user if invoker_guild else None, # Pass user as member if in guild context
                guild=invoker_guild,
                channel=invoker_channel # Pass the channel where command was invoked for channel vars
            )
        except Exception as e:
            _logger.error(f"Error creating final embed object in scheduled task: {e}")
            if invoker_channel: # Try to notify the invoker channel
                 try:
                     await invoker_channel.send(f"Gagal mengirim pengumuman terjadwal: Tidak dapat menyiapkan embed. Error: {e}")
                 except Exception as send_e:
                      _logger.error(f"Failed to send error message to invoker channel {invoker_channel.id}: {send_e}")
            return

        try:
            # Ensure the channel is still valid and bot has permissions before sending
            if target_channel is None:
                 _logger.warning(f"Scheduled announcement target channel is None. Task cancelled.")
                 return

            # Check bot's permissions in the target channel
            me = target_channel.guild.me # Bot's Member object in the guild
            perms = target_channel.permissions_for(me)
            if not perms.send_messages:
                 _logger.warning(f"Bot lacks send_messages permission in channel {target_channel.name} ({target_channel.id}) for scheduled announcement.")
                 # Optionally notify invoker if possible
                 if invoker_channel:
                      try:
                          await invoker_channel.send(f"Gagal mengirim pengumuman terjadwal ke {target_channel.mention}: Bot tidak memiliki izin `Send Messages`.")
                      except Exception as send_e:
                           _logger.error(f"Failed to send permission error message to invoker channel {invoker_channel.id}: {send_e}")
                 return


            await target_channel.send(embed=final_embed_object)
            _logger.info(f"Scheduled announcement sent to {target_channel.name} in {target_channel.guild.name} after {delay_seconds} seconds.")
        except discord.errors.NotFound:
             _logger.warning(f"Failed to send scheduled announcement: Target channel {target_channel.id} not found. Task cancelled.")
             if invoker_channel:
                 try:
                     await invoker_channel.send(f"Gagal mengirim pengumuman terjadwal: Channel target tidak ditemukan atau sudah dihapus.")
                 except Exception as send_e:
                      _logger.error(f"Failed to send channel not found message to invoker channel {invoker_channel.id}: {send_e}")
        except discord.errors.Forbidden:
            _logger.error(f"Failed to send scheduled announcement: Missing permissions in {target_channel.name} ({target_channel.id}) in guild {target_channel.guild.name} ({target_channel.guild.id}).")
            if invoker_channel:
                 try:
                      await invoker_channel.send(f"Gagal mengirim pengumuman terjadwal ke {target_channel.mention}: Bot tidak memiliki izin.")
                 except Exception as send_e:
                      _logger.error(f"Failed to send forbidden error message to invoker channel {invoker_channel.id}: {send_e}")
        except Exception as e:
            _logger.error(f"An error occurred while sending scheduled announcement: {e}")
            if invoker_channel:
                 try:
                      await invoker_channel.send(f"Gagal mengirim pengumuman terjadwal: Terjadi error saat pengiriman. Error: {e}")
                 except Exception as send_e:
                      _logger.error(f"Failed to send unexpected error message to invoker channel {invoker_channel.id}: {send_e}")


    # --- Basic Commands (Ping, Hello, Say, Variables) ---

    @app_commands.command(name="ping", description="Responds with Pong! and bot latency.")
    @app_commands.guild_only() # Restrict to guilds
    async def ping_slash(self, interaction: discord.Interaction):
        """Displays bot latency."""
        _logger.info(f"Received /ping from {interaction.user.id} in guild {interaction.guild_id}.")
        latency_ms = self.bot.latency * 1000
        await interaction.response.send_message(f"Pong! Latency: {latency_ms:.2f}ms")

    @app_commands.command(name="hello", description="Greets the user.")
    @app_commands.guild_only() # Restrict to guilds
    async def hello_slash(self, interaction: discord.Interaction):
        """Greets the user."""
        _logger.info(f"Received /hello from {interaction.user.id} in guild {interaction.guild_id}.")
        await interaction.response.send_message(f"Halo {interaction.user.mention}!")

    @app_commands.command(name="say", description="Sends raw text to a channel. Useful for triggering other bots.")
    @app_commands.describe(text="The exact text for the bot to send.")
    @app_commands.describe(channel="The channel to send the message in.")
    @commands.has_permissions(manage_messages=True) # Discord permission check
    @app_commands.guild_only() # Restrict to guilds
    async def say_slash(self, interaction: discord.Interaction, text: str, channel: discord.TextChannel):
        """Sends raw text to a channel."""
        _logger.info(f"Received /say from {interaction.user.id} in guild {interaction.guild_id} to channel {channel.id}.")

        # No need for guild_id check here thanks to @app_commands.guild_only()

        # You might want to replace variables in the text if you want that functionality
        # raw_text_to_send = utils.replace_variables(text, user=interaction.user, member=interaction.user, guild=interaction.guild, channel=channel)
        # For now, let's stick to raw text as per command description
        raw_text_to_send = text

        try:
            # Check bot's permissions in the target channel before sending
            me = channel.guild.me
            perms = channel.permissions_for(me)
            if not perms.send_messages:
                 await interaction.response.send_message(f"Saya tidak memiliki izin `Send Messages` di {channel.mention}.", ephemeral=True)
                 _logger.warning(f"Bot lacks send_messages permission in channel {channel.id} for /say command.")
                 return # Stop execution if permission is missing


            await channel.send(raw_text_to_send)
            await interaction.response.send_message(
                f"Mengirim pesan ke {channel.mention}."
                , ephemeral=True
            )
            _logger.info(f"Message sent to channel {channel.id} via /say.")
        except discord.errors.Forbidden:
            # Although we checked permissions above, this can still happen in rare race conditions
            await interaction.response.send_message(f"Saya tidak memiliki izin untuk mengirim pesan di {channel.mention}.", ephemeral=True)
            _logger.error(f"Forbidden error when sending message via /say to channel {channel.id}.")
        except Exception as e:
            _logger.error(f"An error occurred while sending message via /say: {e}")
            await interaction.response.send_message(f"Terjadi error saat mencoba mengirim pesan: {e}", ephemeral=True)

    @app_commands.command(name="variables", description="Lists available text variables and their usage.")
    @app_commands.guild_only() # Restrict to guilds
    async def variables_slash(self, interaction: discord.Interaction):
        """Lists available variables and their descriptions."""
        _logger.info(f"Received /variables from {interaction.user.id} in guild {interaction.guild_id}.")
        available_variables = utils.get_available_variables()

        if not available_variables:
            await interaction.response.send_message("Saat ini tidak ada variabel yang ditentukan.", ephemeral=True)
            return

        sorted_variables = sorted(available_variables.items())

        variable_list_text = "\n".join(
            f"`{{{name}}}` - {description}" for name, description in sorted_variables
        )

        embed = discord.Embed(
            title="Variabel yang Tersedia",
            description="Anda dapat menggunakan variabel ini di dalam custom embed atau dengan perintah seperti `/say` (jika diaktifkan).\n\n" + variable_list_text,
            color=discord.Color.purple()
        )
        embed.set_footer(text="Variabel diganti berdasarkan konteks (pengguna, server, channel).")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="pengumuman", description="Send an announcement with optional custom embed and timer.")
    @app_commands.describe(title="The title for the announcement.")
    @app_commands.describe(teks="The main text content for the announcement.")
    @app_commands.describe(channel="The channel to send the announcement in.")
    @app_commands.describe(embed="The name of the custom embed template to use (optional).")
    @app_commands.describe(timer="Countdown in minutes before sending (optional, min 1 minute).")
    @commands.has_permissions(manage_messages=True) # Discord permission check
    @app_commands.guild_only() # Restrict to guilds
    async def pengumuman_slash(self, interaction: discord.Interaction, title: str, teks: str, channel: discord.TextChannel, embed: str = None, timer: app_commands.Range[int, 1, None] = None):
        """Sends a custom announcement message with optional embed and timer."""
        _logger.info(f"Received /pengumuman from {interaction.user.id} in guild {interaction.guild_id} to channel {channel.id} with timer={timer} embed={embed}.")

        # No need for guild_id check here thanks to @app_commands.guild_only()

        embed_data = {} # Start with an empty dictionary

        if embed:
            loaded_embed_data = database.get_custom_embed(interaction.guild_id, embed)
            if loaded_embed_data is None:
                await interaction.response.send_message(f"Template embed kustom '{embed}' tidak ditemukan.", ephemeral=True)
                _logger.warning(f"Custom embed '{embed}' not found for guild {interaction.guild_id}.")
                return

            # Use the loaded data as the base
            embed_data = loaded_embed_data
            # Remove _id from the loaded data before using it
            if '_id' in embed_data:
                 del embed_data['_id']


        if not isinstance(embed_data, dict):
             _logger.warning(f"Loaded embed_data was not a dict for embed '{embed}'. Type: {type(embed_data)}. Proceeding with empty dict.")
             embed_data = {} # Fallback to empty dict if loaded data is corrupt


        # Override or add title and description from command arguments
        # Ensure title/teks are not empty strings before adding
        if title.strip():
            embed_data['title'] = title
        elif 'title' in embed_data: # If title is empty in command but existed in template, remove it
             del embed_data['title']

        if teks.strip():
            embed_data['description'] = teks
        elif 'description' in embed_data: # If teks is empty in command but existed in template, remove it
             del embed_data['description']

        # Ensure the bot has permissions in the target channel
        me = channel.guild.me
        perms = channel.permissions_for(me)
        if not perms.send_messages:
             await interaction.response.send_message(f"Saya tidak memiliki izin `Send Messages` di {channel.mention}.", ephemeral=True)
             _logger.warning(f"Bot lacks send_messages permission in channel {channel.id} for /pengumuman.")
             return # Stop execution if permission is missing


        if timer is not None and timer > 0:
            delay_seconds = timer * 60
            await interaction.response.send_message(f"Pengumuman dijadwalkan untuk dikirim ke {channel.mention} dalam {timer} menit!", ephemeral=True)
            self.bot.loop.create_task(
                self._schedule_announcement_task(
                    delay_seconds,
                    channel, # Target channel for sending
                    embed_data, # Data to build the embed
                    interaction.user, # User who invoked command (for variable replacement context)
                    interaction.guild, # Guild context
                    interaction.channel # Channel context
                )
            )
            _logger.info(f"Announcement task scheduled for {delay_seconds} seconds to channel {channel.id}.")

        else:
            try:
                # Use utils.create_processed_embed
                final_embed_object = utils.create_processed_embed(
                    embed_data,
                    user=interaction.user, # Pass user for variable replacement
                    member=interaction.user, # Pass user as member if in guild context
                    guild=interaction.guild, # Guild context
                    channel=interaction.channel # Channel context
                )
            except Exception as e:
                _logger.error(f"Error creating final embed object for immediate send: {e}")
                await interaction.response.send_message(f"Terjadi error saat menyiapkan embed untuk dikirim: {e}", ephemeral=True)
                return

            try:
                await channel.send(embed=final_embed_object)
                await interaction.response.send_message(f"Pengumuman dikirim ke {channel.mention}!", ephemeral=True)
                _logger.info(f"Announcement sent immediately to {channel.name} in {channel.guild.name}.")

            except discord.errors.Forbidden:
                 await interaction.response.send_message(f"Saya tidak memiliki izin untuk mengirim pesan di {channel.mention}.", ephemeral=True)
                 _logger.error(f"Forbidden error when sending immediate announcement to channel {channel.id}.")
            except Exception as e:
                _logger.error(f"An error occurred while sending the announcement immediately: {e}")
                await interaction.response.send_message(f"Terjadi error saat mengirim pengumuman: {e}", ephemeral=True)


    # --- Moderation Commands (Modified Responses and Added Check) ---

    @app_commands.command(name="kick", description="Kicks a member from the server.")
    @app_commands.describe(member="The member to kick.")
    @app_commands.describe(reason="The reason for kicking (optional).")
    @app_commands.guild_only() # Ensure command is in guild
    # Use the custom check instead of discord.py's has_permissions
    # @commands.has_permissions(kick_members=True)
    @app_commands.check(lambda i: BasicCommandsCog(i.client).is_authorized_for_command(i, 'mod')) # Apply custom check
    async def kick_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        """Kicks a member."""
        _logger.info(f"Received /kick from {interaction.user.id} on member {member.id} in guild {interaction.guild_id}.")

        # No need for interaction.guild is None check thanks to @app_commands.guild_only()

        if member.id == interaction.user.id:
             await interaction.response.send_message("Anda tidak bisa menendang diri sendiri.", ephemeral=True)
             return
        if member.id == interaction.guild.owner_id:
             await interaction.response.send_message("Anda tidak bisa menendang pemilik server.", ephemeral=True)
             return
        # Check if the bot has permission to kick the member (role hierarchy and actual permission)
        # We already have a check for bot's top role vs member's top role, but need to check bot's actual kick permission too
        me = interaction.guild.me # Bot's member object in the guild
        # Ensure the invoking user has higher role than the target member (unless they are owner)
        if interaction.user.top_role <= member.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Anda tidak bisa menendang anggota dengan peran yang sama atau lebih tinggi dari Anda.", ephemeral=True)
            return
        # Ensure the bot has higher role than the target member AND bot has kick permission
        if member.top_role >= me.top_role:
             await interaction.response.send_message("Saya tidak bisa menendang anggota ini karena peran tertingginya sama atau lebih tinggi dari peran saya.", ephemeral=True)
             return
        if not me.guild_permissions.kick_members:
            await interaction.response.send_message("Saya tidak memiliki izin `Kick Members`.", ephemeral=True)
            return


        try:
            await interaction.response.defer(ephemeral=False) # Defer response first
            await member.kick(reason=reason)

            embed = discord.Embed(
                title="Anggota Ditendang",
                description=f"{member.mention} telah ditendang dari server.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Ditendang Oleh", value=interaction.user.mention, inline=True)
            if reason:
                embed.add_field(name="Alasan", value=reason, inline=False)
            embed.set_footer(text=f"ID Anggota: {member.id}")

            await interaction.followup.send(embed=embed)
            _logger.info(f"Member {member.id} kicked successfully by {interaction.user.id}.")

        except discord.errors.Forbidden:
            # This can happen even after checks in complex permission scenarios
            _logger.error(f"Forbidden error when kicking member {member.id} by {interaction.user.id}.")
            await interaction.followup.send(f"Saya tidak memiliki izin untuk menendang {member.mention}.", ephemeral=True)
        except Exception as e:
            _logger.error(f"Error kicking member {member.id} by {interaction.user.id}: {e}")
            await interaction.followup.send(f"Terjadi error saat mencoba menendang {member.mention}.", ephemeral=True)


    @app_commands.command(name="ban", description="Bans a member from the server.")
    @app_commands.describe(member="The member to ban.")
    @app_commands.describe(reason="The reason for banning (optional).")
    @app_commands.guild_only() # Ensure command is in guild
    # Use the custom check instead of discord.py's has_permissions
    # @commands.has_permissions(ban_members=True)
    @app_commands.check(lambda i: BasicCommandsCog(i.client).is_authorized_for_command(i, 'mod')) # Apply custom check
    async def ban_slash(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        """Bans a member."""
        _logger.info(f"Received /ban from {interaction.user.id} on member {member.id} in guild {interaction.guild_id}.")

        # No need for interaction.guild is None check thanks to @app_commands.guild_only()

        if member.id == interaction.user.id:
             await interaction.response.send_message("Anda tidak bisa memblokir diri sendiri.", ephemeral=True)
             return
        if member.id == interaction.guild.owner_id:
             await interaction.response.send_message("Anda tidak bisa memblokir pemilik server.", ephemeral=True)
             return

        # Check if the bot has permission to ban the member (role hierarchy and actual permission)
        me = interaction.guild.me
        # Ensure the invoking user has higher role than the target member (unless they are owner)
        if interaction.user.top_role <= member.top_role and interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message("Anda tidak bisa memblokir anggota dengan peran yang sama atau lebih tinggi dari Anda.", ephemeral=True)
            return
        # Ensure the bot has higher role than the target member AND bot has ban permission
        if member.top_role >= me.top_role:
            await interaction.response.send_message("Saya tidak bisa memblokir anggota ini karena peran tertingginya sama atau lebih tinggi dari peran saya.", ephemeral=True)
            return
        if not me.guild_permissions.ban_members:
            await interaction.response.send_message("Saya tidak memiliki izin `Ban Members`.", ephemeral=True)
            return


        try:
            await interaction.response.defer(ephemeral=False) # Defer response first
            await member.ban(reason=reason)

            embed = discord.Embed(
                title="Anggota Diblokir",
                description=f"{member.mention} telah diblokir dari server.",
                color=discord.Color.red()
            )
            embed.add_field(name="Diblokir Oleh", value=interaction.user.mention, inline=True)
            if reason:
                embed.add_field(name="Alasan", value=reason, inline=False)
            embed.set_footer(text=f"ID Anggota: {member.id}")

            await interaction.followup.send(embed=embed)
            _logger.info(f"Member {member.id} banned successfully by {interaction.user.id}.")

        except discord.errors.Forbidden:
            _logger.error(f"Forbidden error when banning member {member.id} by {interaction.user.id}.")
            await interaction.followup.send(f"Saya tidak memiliki izin untuk memblokir {member.mention}.", ephemeral=True)
        except Exception as e:
            _logger.error(f"Error banning member {member.id} by {interaction.user.id}: {e}")
            await interaction.followup.send(f"Terjadi error saat mencoba memblokir {member.mention}.", ephemeral=True)

    # --- Info Commands ---

    @app_commands.command(name="serverinfo", description="Displays information about the server.")
    @app_commands.guild_only() # Restrict to guilds
    async def serverinfo_slash(self, interaction: discord.Interaction):
        """Displays server information."""
        _logger.info(f"Received /serverinfo from {interaction.user.id} in guild {interaction.guild_id}.")

        # No need for interaction.guild is None check thanks to @app_commands.guild_only()
        guild = interaction.guild

        embed = discord.Embed(
            title=f"Info Server: {guild.name}",
            color=discord.Color.blue()
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        # Fetch additional info if needed (requires relevant intents)
        # await guild.chunk() # Ensure all members/data are cached if needed

        embed.add_field(name="ID Server", value=guild.id, inline=True)
        embed.add_field(name="Pemilik", value=guild.owner.mention if guild.owner else "N/A", inline=True)
        embed.add_field(name="Dibuat Pada", value=utils.format_date(guild.created_at), inline=False)
        embed.add_field(name="Jumlah Anggota", value=guild.member_count, inline=True)
        embed.add_field(name="Jumlah Channel", value=len(guild.channels), inline=True)
        embed.add_field(name="Jumlah Peran", value=len(guild.roles), inline=True)
        embed.add_field(name="Tingkat Boost", value=f"{guild.premium_tier} (Boosts: {guild.premium_subscription_count})", inline=True)
        embed.add_field(name="Tingkat Verifikasi", value=str(guild.verification_level).split('.')[-1].capitalize(), inline=True)
        if guild.splash:
             embed.add_field(name="Splash Image", value="[Link]" + f"({guild.splash.url})", inline=True)
        if guild.banner:
             embed.add_field(name="Banner Image", value="[Link]" + f"({guild.banner.url})", inline=True)


        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="userinfo", description="Displays information about a user.")
    @app_commands.describe(member="The member to get info about (defaults to yourself).")
    @app_commands.guild_only() # Restrict to guilds
    async def userinfo_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        """Displays user information."""
        _logger.info(f"Received /userinfo from {interaction.user.id} about {member.id if member else 'self'} in guild {interaction.guild_id}.")

        # No need for interaction.guild is None check thanks to @app_commands.guild_only()
        target_member = member or interaction.user

        embed = discord.Embed(
            title=f"Info Pengguna: {target_member.display_name}",
            color=target_member.color if target_member.color != discord.Color.default() else discord.Color.blue()
        )
        # Use guild_avatar first if available, fallback to global avatar
        if target_member.guild_avatar:
             embed.set_thumbnail(url=target_member.guild_avatar.url)
        elif target_member.avatar:
             embed.set_thumbnail(url=target_member.avatar.url)


        # Handle discriminator '0'
        username = target_member.name
        if target_member.discriminator != '0':
             username += f"#{target_member.discriminator}"
        embed.add_field(name="Username", value=username, inline=True)

        embed.add_field(name="ID", value=target_member.id, inline=True)
        embed.add_field(name="Akun Dibuat", value=utils.format_date(target_member.created_at), inline=False)

        # Joined server date might be None for certain user types (e.g., Webhooks)
        joined_at_str = utils.format_date(target_member.joined_at) if target_member.joined_at else "N/A"
        embed.add_field(name="Bergabung Server", value=joined_at_str, inline=False)

        # List roles, excluding @everyone, sorted by position (highest first)
        roles = sorted([role for role in target_member.roles if role.name != '@everyone'], key=lambda r: r.position, reverse=True)
        role_mentions = [role.mention for role in roles]

        if role_mentions:
            # Truncate if role list is too long for embed field value (max 1024 characters)
            roles_value = ", ".join(role_mentions)
            if len(roles_value) > 1024:
                roles_value = roles_value[:1021] + "..." # Truncate and add ellipsis
            embed.add_field(name=f"Peran ({len(roles)})", value=roles_value, inline=False)
        else:
             embed.add_field(name="Peran (0)", value="Tidak ada", inline=False)

        # Ensure top_role is handled (it should always exist for a member)
        embed.add_field(name="Peran Tertinggi", value=target_member.top_role.mention, inline=True)

        # Check if the member is currently pending membership screening
        if hasattr(target_member, 'pending') and target_member.pending:
             embed.add_field(name="Tertunda", value="Ya", inline=True)

        # Optional: Add creation flags, status, etc. if needed and intents allow


        await interaction.response.send_message(embed=embed)

    # --- Role Management Commands (Modified Responses and Added Check) ---

    @app_commands.command(name="addrole", description="Gives a role to a member.")
    @app_commands.describe(member="The member to give the role to.")
    @app_commands.describe(role="The role to give.")
    @app_commands.guild_only() # Ensure command is in guild
    # Use the custom check instead of discord.py's has_permissions
    # @commands.has_permissions(manage_roles=True)
    @app_commands.check(lambda i: BasicCommandsCog(i.client).is_authorized_for_command(i, 'role_manager')) # Apply custom check
    async def addrole_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        """Gives a role to a member."""
        _logger.info(f"Received /addrole from {interaction.user.id} to member {member.id} with role {role.id} in guild {interaction.guild_id}.")

        # No need for interaction.guild is None check thanks to @app_commands.guild_only()

        if role == interaction.guild.default_role:
             await interaction.response.send_message("Tidak dapat menambahkan peran `@everyone` secara manual.", ephemeral=True)
             return

        # Check if the bot has permission to manage this role (role hierarchy and actual permission)
        me = interaction.guild.me
        if role >= me.top_role:
             await interaction.response.send_message("Saya tidak bisa memberikan peran ini karena sama atau lebih tinggi dari peran tertinggi saya.", ephemeral=True)
             return
        if not me.guild_permissions.manage_roles:
             await interaction.response.send_message("Saya tidak memiliki izin `Manage Roles`.", ephemeral=True)
             return
        # Check if the invoking user can manage this role (hierarchy)
        # This check is implicitly handled by the custom check if 'role_manager' requires a role lower than the target role
        # But explicitly checking if the user can manage the *target role* is also wise
        if interaction.user.top_role <= role and interaction.user.id != interaction.guild.owner_id:
             await interaction.response.send_message("Anda tidak bisa memberikan peran yang sama atau lebih tinggi dari peran tertinggi Anda.", ephemeral=True)
             return


        if role in member.roles:
            await interaction.response.send_message(f"{member.mention} sudah memiliki peran {role.mention}.", ephemeral=True)
            _logger.debug(f"Member {member.id} already has role {role.id}.")
            return

        try:
            await interaction.response.defer(ephemeral=False) # Defer response first
            await member.add_roles(role)

            embed = discord.Embed(
                title="Peran Diperbarui",
                description=f"Memberikan peran {role.mention} kepada {member.mention}.",
                color=discord.Color.green()
            )
            embed.add_field(name="Dilakukan Oleh", value=interaction.user.mention, inline=True)
            embed.set_footer(text=f"Member ID: {member.id} | Role ID: {role.id}")

            await interaction.followup.send(embed=embed)
            _logger.info(f"Role {role.id} added to member {member.id} by {interaction.user.id}.")

        except discord.errors.Forbidden:
            _logger.error(f"Forbidden error when adding role {role.id} to member {member.id} by {interaction.user.id}.")
            await interaction.followup.send(f"Saya tidak memiliki izin untuk memberikan peran {role.mention}.", ephemeral=True)
        except Exception as e:
            _logger.error(f"Error adding role {role.id} to member {member.id} by {interaction.user.id}: {e}")
            await interaction.followup.send(f"Terjadi error saat mencoba memberikan peran {role.mention}.", ephemeral=True)


    @app_commands.command(name="removerole", description="Removes a role from a member.")
    @app_commands.describe(member="The member to remove the role from.")
    @app_commands.describe(role="The role to remove.")
    @app_commands.guild_only() # Ensure command is in guild
    # Use the custom check instead of discord.py's has_permissions
    # @commands.has_permissions(manage_roles=True)
    @app_commands.check(lambda i: BasicCommandsCog(i.client).is_authorized_for_command(i, 'role_manager')) # Apply custom check
    async def removerole_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        """Removes a role from a member."""
        _logger.info(f"Received /removerole from {interaction.user.id} from member {member.id} with role {role.id} in guild {interaction.guild_id}.")

        # No need for interaction.guild is None check thanks to @app_commands.guild_only()

        if role == interaction.guild.default_role:
             await interaction.response.send_message("Tidak dapat menghapus peran `@everyone` secara manual.", ephemeral=True)
             return

        # Check if the bot has permission to manage this role (role hierarchy and actual permission)
        me = interaction.guild.me
        if role >= me.top_role:
             await interaction.response.send_message("Saya tidak bisa menghapus peran ini karena sama atau lebih tinggi dari peran tertinggi saya.", ephemeral=True)
             return
        if not me.guild_permissions.manage_roles:
             await interaction.response.send_message("Saya tidak memiliki izin `Manage Roles`.", ephemeral=True)
             return
        # Check if the invoking user can manage this role (hierarchy)
        if interaction.user.top_role <= role and interaction.user.id != interaction.guild.owner_id:
             await interaction.response.send_message("Anda tidak bisa menghapus peran yang sama atau lebih tinggi dari peran tertinggi Anda.", ephemeral=True)
             return

        if role not in member.roles:
            await interaction.response.send_message(f"{member.mention} tidak memiliki peran {role.mention}.", ephemeral=True)
            _logger.debug(f"Member {member.id} does not have role {role.id}.")
            return

        try:
            await interaction.response.defer(ephemeral=False) # Defer response first
            await member.remove_roles(role)

            embed = discord.Embed(
                title="Peran Diperbarui",
                description=f"Menghapus peran {role.mention} dari {member.mention}.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Dilakukan Oleh", value=interaction.user.mention, inline=True)
            embed.set_footer(text=f"Member ID: {member.id} | Role ID: {role.id}")


            await interaction.followup.send(embed=embed)
            _logger.info(f"Role {role.id} removed from member {member.id} by {interaction.user.id}.")

        except discord.errors.Forbidden:
            _logger.error(f"Forbidden error when removing role {role.id} from member {member.id} by {interaction.user.id}.")
            await interaction.followup.send(f"Saya tidak memiliki izin untuk menghapus peran {role.mention}.", ephemeral=True)
        except Exception as e:
            _logger.error(f"Error removing role {role.id} from member {member.id} by {interaction.user.id}: {e}")
            await interaction.followup.send(f"Terjadi error saat mencoba menghapus peran {role.mention}.", ephemeral=True)


    # --- Configuration Commands (NEW GROUP) ---

    config_group = app_commands.Group(name='config', description='Manage server bot configuration.')

    @config_group.command(name='mod_roles', description='Manage roles that can use moderation commands.')
    @app_commands.describe(action="Add or remove a role.", role="The role to add or remove.")
    @app_commands.choices(action=[
        app_commands.Choice(name='tambah', value='add'),
        app_commands.Choice(name='hapus', value='remove'),
    ])
    @commands.has_permissions(manage_guild=True) # Discord permission check
    @app_commands.guild_only() # Restrict to guilds
    async def config_mod_roles_slash(self, interaction: discord.Interaction, action: app_commands.Choice[str], role: discord.Role):
        """Adds or removes roles from the mod roles list."""
        _logger.info(f"Received /config mod_roles action={action.value} role={role.id} from {interaction.user.id} in guild {interaction.guild_id}.")

        # No need for interaction.guild_id check thanks to @app_commands.guild_only()

        config = database.get_server_config(interaction.guild_id)
        # Ensure mod_roles exists and is a list
        mod_role_ids = config.get('mod_roles', [])
        if not isinstance(mod_role_ids, list):
             _logger.warning(f"mod_roles in config for guild {interaction.guild_id} is not a list. Resetting to empty list.")
             mod_role_ids = [] # Reset if data is corrupt

        role_id = role.id
        role_mention = role.mention

        updated = False
        message = "Perintah tidak valid." # Default message

        if action.value == 'add':
            if role_id not in mod_role_ids:
                mod_role_ids.append(role_id)
                updated = True
                message = f"Menambahkan {role_mention} ke daftar peran moderasi."
                _logger.info(f"Added role {role.id} to mod roles for guild {interaction.guild_id}.")
            else:
                message = f"{role_mention} sudah ada di daftar peran moderasi."
                _logger.debug(f"Role {role.id} already in mod roles for guild {interaction.guild_id}.")
        elif action.value == 'remove':
            if role_id in mod_role_ids:
                mod_role_ids.remove(role_id)
                updated = True
                message = f"Menghapus {role_mention} dari daftar peran moderasi."
                _logger.info(f"Removed role {role.id} from mod roles for guild {interaction.guild_id}.")
            else:
                message = f"{role_mention} tidak ada di daftar peran moderasi."
                _logger.debug(f"Role {role.id} not in mod roles for guild {interaction.guild_id}.")


        if updated:
            database.update_server_config(interaction.guild_id, {'mod_roles': mod_role_ids})

        await interaction.response.send_message(message, ephemeral=True)


    @config_group.command(name='role_manager_roles', description='Manage roles that can use role management commands.')
    @app_commands.describe(action="Add or remove a role.", role="The role to add or remove.")
    @app_commands.choices(action=[
        app_commands.Choice(name='tambah', value='add'),
        app_commands.Choice(name='hapus', value='remove'),
    ])
    @commands.has_permissions(manage_guild=True) # Discord permission check
    @app_commands.guild_only() # Restrict to guilds
    async def config_role_manager_roles_slash(self, interaction: discord.Interaction, action: app_commands.Choice[str], role: discord.Role):
        """Adds or removes roles from the role manager roles list."""
        _logger.info(f"Received /config role_manager_roles action={action.value} role={role.id} from {interaction.user.id} in guild {interaction.guild_id}.")

        # No need for interaction.guild_id check thanks to @app_commands.guild_only()

        config = database.get_server_config(interaction.guild_id)
        # Ensure role_manager_roles exists and is a list
        role_manager_role_ids = config.get('role_manager_roles', [])
        if not isinstance(role_manager_role_ids, list):
            _logger.warning(f"role_manager_roles in config for guild {interaction.guild_id} is not a list. Resetting to empty list.")
            role_manager_role_ids = [] # Reset if data is corrupt


        role_id = role.id
        role_mention = role.mention

        updated = False
        message = "Perintah tidak valid." # Default message

        if action.value == 'add':
            if role_id not in role_manager_role_ids:
                role_manager_role_ids.append(role_id)
                updated = True
                message = f"Menambahkan {role_mention} ke daftar peran pengelola peran."
                _logger.info(f"Added role {role.id} to role manager roles for guild {interaction.guild_id}.")
            else:
                message = f"{role_mention} sudah ada di daftar peran pengelola peran."
                _logger.debug(f"Role {role.id} already in role manager roles for guild {interaction.guild_id}.")
        elif action.value == 'remove':
            if role_id in role_manager_role_ids:
                role_manager_role_ids.remove(role_id)
                updated = True
                message = f"Menghapus {role_mention} dari daftar peran pengelola peran."
                _logger.info(f"Removed role {role.id} from role manager roles for guild {interaction.guild_id}.")
            else:
                message = f"{role_mention} tidak ada di daftar peran pengelola peran."
                _logger.debug(f"Role {role.id} not in role manager roles for guild {interaction.guild_id}.")

        if updated:
            database.update_server_config(interaction.guild_id, {'role_manager_roles': role_manager_role_ids})

        await interaction.response.send_message(message, ephemeral=True)


    @config_group.command(name='ai_channel', description='Set or unset the designated AI interaction channel.')
    @app_commands.describe(channel="The channel to set as the AI channel (leave blank to unset).")
    @commands.has_permissions(manage_guild=True) # Discord permission check
    @app_commands.guild_only() # Restrict to guilds
    async def config_ai_channel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        """Sets the channel for AI interaction."""
        _logger.info(f"Received /config ai_channel channel={channel.id if channel else None} from {interaction.user.id} in guild {interaction.guild_id}.")

        # No need for interaction.guild_id check thanks to @app_commands.guild_only()

        config = database.get_server_config(interaction.guild_id)
        current_ai_channel_id = config.get('ai_channel_id')

        if channel:
            # Set the AI channel
            new_channel_id = channel.id
            if current_ai_channel_id == new_channel_id:
                 await interaction.response.send_message(
                     f"{channel.mention} sudah diatur sebagai channel AI.",
                     ephemeral=True
                 )
                 _logger.debug(f"Attempted to set AI channel to {channel.id} but it was already set.")
                 return

            database.update_server_config(interaction.guild_id, {'ai_channel_id': new_channel_id})
            await interaction.response.send_message(
                f"Berhasil mengatur {channel.mention} sebagai channel interaksi AI. Fitur AI sekarang akan merespons di channel ini.",
                ephemeral=True
            )
            _logger.info(f"Set AI channel for guild {interaction.guild_id} to {channel.id}.")
        else:
            # Unset the AI channel
            if current_ai_channel_id is None:
                 await interaction.response.send_message(
                     "Channel AI sudah tidak diatur.",
                     ephemeral=True
                 )
                 _logger.debug(f"Attempted to unset AI channel but it was already None.")
                 return

            database.update_server_config(interaction.guild_id, {'ai_channel_id': None})
            await interaction.response.send_message(
                "Berhasil membatalkan pengaturan channel interaksi AI. Fitur AI dinonaktifkan.",
                ephemeral=True
            )
            _logger.info(f"Unset AI channel for guild {interaction.guild_id}.")

    @config_group.command(name='show', description='Show the current server configuration.')
    @commands.has_permissions(manage_guild=True) # Discord permission check
    @app_commands.guild_only() # Restrict to guilds
    async def config_show_slash(self, interaction: discord.Interaction):
        """Shows the current server configuration."""
        _logger.info(f"Received /config show from {interaction.user.id} in guild {interaction.guild_id}.")

        # No need for interaction.guild_id check thanks to @app_commands.guild_only()

        config = database.get_server_config(interaction.guild_id)

        embed = discord.Embed(
            title=f"Konfigurasi Bot untuk {interaction.guild.name}",
            color=discord.Color.gold()
        )
        embed.add_field(name="ID Server", value=interaction.guild_id, inline=False)

        mod_role_mentions = []
        mod_role_ids = config.get('mod_roles', [])
        if isinstance(mod_role_ids, list): # Safely check if it's a list
             mod_role_mentions = [f"<@&{role_id}>" for role_id in mod_role_ids]

        embed.add_field(name="Peran Moderasi", value=", ".join(mod_role_mentions) if mod_role_mentions else "Tidak Dikonfigurasi", inline=False)

        role_manager_role_mentions = []
        role_manager_role_ids = config.get('role_manager_roles', [])
        if isinstance(role_manager_role_ids, list): # Safely check if it's a list
             role_manager_role_mentions = [f"<@&{role_id}>" for role_id in role_manager_role_ids]

        embed.add_field(name="Peran Pengelola Peran", value=", ".join(role_manager_role_mentions) if role_manager_role_mentions else "Tidak Dikonfigurasi", inline=False)

        ai_channel_id = config.get('ai_channel_id')
        ai_channel_mention = f"<#{ai_channel_id}>" if ai_channel_id else "Tidak Dikonfigurasi"
        embed.add_field(name="Channel AI", value=ai_channel_mention, inline=False)

        # Add other config fields here if you add more later

        await interaction.response.send_message(embed=embed, ephemeral=True)


    # --- Error Handler for basic commands ---
    # This handler catches errors specifically for commands defined in THIS cog.
    # --- FIX: Updated signature to accept standard interaction and error ---
    async def basic_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for basic commands."""
        _logger.error(f"Handling Basic command error for command {interaction.command.name if interaction.command else 'Unknown'} by user {interaction.user.id if interaction.user else 'Unknown'} in guild {interaction.guild_id if interaction.guild_id else 'DM'}.", exc_info=True) # Log handler start and traceback

        # Ensure we can send a message even if interaction response is done
        send_func = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message

        # Try to send the error message
        try:
            if isinstance(error, app_commands.MissingPermissions):
                 _logger.warning(f"MissingPermissions error: {error.missing_permissions}")
                 await send_func("Anda tidak memiliki izin untuk menggunakan perintah ini.", ephemeral=True)
            elif isinstance(error, app_commands.CheckFailure): # Catches custom CheckFailure specifically and @app_commands.guild_only()
                 _logger.warning(f"CheckFailure error: {error}")
                 await send_func(str(error), ephemeral=True) # Send the custom message from CheckFailure
            elif isinstance(error, app_commands.CommandInvokeError):
                 _logger.error(f"CommandInvokeError in basic command: {error.original}", exc_info=error.original)
                 await send_func(f"Terjadi error saat mengeksekusi perintah: {error.original}", ephemeral=True)
            elif isinstance(error, app_commands.TransformerError):
                 _logger.warning(f"TransformerError in basic command: {error.original}")
                 await send_func(f"Nilai tidak valid diberikan untuk argumen '{error.param_name}': {error.original}", ephemeral=True)
            else:
                _logger.error(f"An unexpected error occurred in basic command: {error}", exc_info=True)
                await send_func(f"Terjadi error tak terduga: {error}", ephemeral=True)

        except Exception as send_error_e:
            _logger.error(f"Failed to send error message in basic command error handler: {send_error_e}", exc_info=True)
            print(f"FATAL ERROR in Basic command handler for {interaction.command.name}: {error}. Also failed to send error message: {send_error_e}")
    # --- END FIX ---


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the BasicCommands cog and attaches error handlers."""
    cog_instance = BasicCommandsCog(bot)
    await bot.add_cog(cog_instance)
    _logger.info("BasicCommandsCog loaded.")

    # Attach error handlers after the cog instance is added to the bot
    # Access the methods via the cog_instance
    cog_instance.ping_slash.error(cog_instance.basic_command_error)
    cog_instance.hello_slash.error(cog_instance.basic_command_error)
    cog_instance.say_slash.error(cog_instance.basic_command_error)
    cog_instance.variables_slash.error(cog_instance.basic_command_error)
    cog_instance.pengumuman_slash.error(cog_instance.basic_command_error)
    cog_instance.kick_slash.error(cog_instance.basic_command_error)
    # --- FIX: Corrected typo and used instance method ---
    cog_instance.ban_slash.error(cog_instance.basic_command_error)
    # --- END FIX ---
    cog_instance.serverinfo_slash.error(cog_instance.basic_command_error)
    cog_instance.userinfo_slash.error(cog_instance.basic_command_error)
    cog_instance.addrole_slash.error(cog_instance.basic_command_error)
    cog_instance.removerole_slash.error(cog_instance.basic_command_error)
    # Attach error handlers for config commands (accessed via group then command name)
    # config_group is defined within the class, access via cog_instance
    cog_instance.config_mod_roles_slash.error(cog_instance.basic_command_error)
    cog_instance.config_role_manager_roles_slash.error(cog_instance.basic_command_error)
    cog_instance.config_ai_channel_slash.error(cog_instance.basic_command_error) # Attach error handler for the new command
    cog_instance.config_show_slash.error(cog_instance.basic_command_error)