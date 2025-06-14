# Noelle_Bot/ai_services/ai_commands_cog.py

import discord
from discord.ext import commands
from discord import app_commands
import logging
import datetime

from . import gemini_client as gemini_services

_logger = logging.getLogger("noelle_bot.ai.commands_cog")

SESSION_TIMEOUT_MINUTES = 30 
MAX_CONTEXT_TOKENS = 120000

class AICommandsCog(commands.Cog, name="AI Commands"):
    """Cog ini menangani pendaftaran grup /ai dan subcommand manajemennya."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("AICommandsCog (Grup /ai) instance dibuat.")

    async def _ensure_ai_channel(self, interaction: discord.Interaction) -> bool:
        """Helper untuk memastikan command dijalankan di channel AI yang benar."""
        designated_name = gemini_services.get_designated_ai_channel_name().lower()
        
        # Periksa apakah sudah direspons, jika belum, gunakan response.send_message
        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message

        if not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name.lower() != designated_name:
            try:
                # defer dulu jika belum
                if not interaction.response.is_done():
                    await interaction.response.defer(ephemeral=True)
                await interaction.followup.send(f"Perintah ini hanya bisa digunakan di channel `{gemini_services.get_designated_ai_channel_name()}`.", ephemeral=True)
            except discord.errors.HTTPException as e:
                _logger.warning(f"Gagal mengirim pesan _ensure_ai_channel: {e}")
            return False
        return True

    ai_commands_group = app_commands.Group(name="ai", description="Perintah terkait manajemen fitur AI Noelle.")

    @ai_commands_group.command(name="clear_context", description="Membersihkan histori percakapan di channel AI ini.")
    async def ai_clear_context_cmd(self, interaction: discord.Interaction):
        if not gemini_services.is_text_service_enabled(): 
            return await interaction.response.send_message("Layanan AI Teks sedang tidak aktif.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        if not await self._ensure_ai_channel(interaction): return
        
        message_handler_cog = self.bot.get_cog("AI Message Handler")
        if message_handler_cog and hasattr(message_handler_cog, '_clear_session_data'):
            message_handler_cog._clear_session_data(interaction.channel_id)
            await interaction.followup.send("✨ Konteks percakapan di channel ini telah dibersihkan.", ephemeral=False)
        else: 
            await interaction.followup.send("Gagal membersihkan sesi (internal error: handler tidak ditemukan).", ephemeral=True)

    @ai_commands_group.command(name="session_status", description="Menampilkan status sesi chat di channel AI ini.")
    async def ai_session_status_cmd(self, interaction: discord.Interaction):
        if not gemini_services.is_text_service_enabled(): 
            return await interaction.response.send_message("Layanan AI Teks sedang tidak aktif.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        if not await self._ensure_ai_channel(interaction): return
        
        message_handler_cog = self.bot.get_cog("AI Message Handler")
        if message_handler_cog and hasattr(message_handler_cog, 'active_chat_sessions'):
            channel_id = interaction.channel_id
            if channel_id in message_handler_cog.active_chat_sessions:
                last_active_dt = message_handler_cog.chat_session_last_active.get(channel_id)
                last_active_str = discord.utils.format_dt(last_active_dt, "R") if last_active_dt else "Baru saja"
                token_count = message_handler_cog.chat_context_token_counts.get(channel_id, 0)
                timeout_dt = last_active_dt + datetime.timedelta(minutes=SESSION_TIMEOUT_MINUTES) if last_active_dt else None
                timeout_str = discord.utils.format_dt(timeout_dt, "R") if timeout_dt else "N/A"
                embed = discord.Embed(title=f"Status Sesi AI - #{interaction.channel.name}", color=discord.Color.blue())
                embed.add_field(name="Status Sesi", value="Aktif", inline=False)
                embed.add_field(name="Aktivitas Terakhir", value=last_active_str, inline=True)
                embed.add_field(name="Perkiraan Total Token", value=f"{token_count} / {MAX_CONTEXT_TOKENS}", inline=True)
                embed.add_field(name="Timeout Berikutnya", value=timeout_str, inline=False)
                await interaction.followup.send(embed=embed)
            else: 
                await interaction.followup.send("Tidak ada sesi chat aktif di channel ini.")
        else: 
            await interaction.followup.send("Gagal mendapatkan status sesi (internal error: handler tidak ditemukan).")

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # ... (error handler tidak berubah) ...
        pass

async def setup(bot: commands.Bot):
    if gemini_services.is_text_service_enabled() or gemini_services.is_image_service_enabled():
        await bot.add_cog(AICommandsCog(bot))
        _logger.info("AICommandsCog (Grup /ai) berhasil dimuat.")
    else:
        _logger.warning("AICommandsCog tidak dimuat karena semua layanan AI nonaktif.")