# Noelle_Bot/ai_services/ai_management_cog.py

import discord
from discord.ext import commands
from discord import app_commands
import logging
import datetime

from . import gemini_client as gemini_services

_logger = logging.getLogger("noelle_bot.ai.manager")

# Konstanta dari cog lain, kita definisikan di sini agar tidak impor silang
SESSION_TIMEOUT_MINUTES = 30 
MAX_CONTEXT_TOKENS = 120000

class AIManagerCog(commands.Cog, name="AI Management"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("AIManagerCog instance dibuat.")

    async def _ensure_ai_channel(self, interaction: discord.Interaction) -> bool:
        """Memastikan perintah dijalankan di channel AI yang benar."""
        designated_name = gemini_services.get_designated_ai_channel_name().lower()
        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message

        if not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name.lower() != designated_name:
            await send_method(f"Perintah ini hanya bisa digunakan di channel `{gemini_services.get_designated_ai_channel_name()}`.", ephemeral=True)
            return False
        return True

    # Grup command /ai sekarang ada di sini
    ai_commands_group = app_commands.Group(name="ai", description="Perintah terkait manajemen fitur AI Noelle.")

    @ai_commands_group.command(name="clear_context", description="Membersihkan histori percakapan di channel AI ini.")
    async def ai_clear_context_cmd(self, interaction: discord.Interaction):
        # Perintah ini bergantung pada layanan teks
        if not gemini_services.is_text_service_enabled():
            return await interaction.response.send_message("Layanan Teks AI sedang tidak aktif.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        if not await self._ensure_ai_channel(interaction): return
        
        message_handler_cog = self.bot.get_cog("AI Message Handler")
        if message_handler_cog and hasattr(message_handler_cog, '_clear_session_data'):
            message_handler_cog._clear_session_data(interaction.channel_id)
            # Kirim pesan non-ephemeral agar semua orang di channel tahu
            await interaction.followup.send("✨ Konteks percakapan di channel ini telah dibersihkan.", ephemeral=False)
        else: 
            await interaction.followup.send("Gagal membersihkan sesi (internal error: handler tidak ditemukan).")

    @ai_commands_group.command(name="session_status", description="Menampilkan status sesi chat di channel AI ini.")
    async def ai_session_status_cmd(self, interaction: discord.Interaction):
        if not gemini_services.is_text_service_enabled():
            return await interaction.response.send_message("Layanan Teks AI sedang tidak aktif.", ephemeral=True)
        
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

    # Command toggle_service sudah tidak ada lagi karena status di-handle otomatis saat startup.
    # Kita bisa menambahkan command 'status' global sebagai gantinya.
    @ai_commands_group.command(name="status", description="Melihat status layanan AI Noelle secara global.")
    @commands.is_owner()
    async def ai_status_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(title="Status Layanan AI Noelle", color=discord.Color.gold())
        
        text_status = "✅ Aktif" if gemini_services.is_text_service_enabled() else "❌ Nonaktif"
        image_status = "✅ Aktif" if gemini_services.is_image_service_enabled() else "❌ Nonaktif"

        embed.add_field(name="Layanan Teks (Chat & Mention)", value=text_status, inline=False)
        embed.add_field(name="Layanan Gambar (Generator)", value=image_status, inline=False)
        
        embed.set_footer(text="Status ini ditentukan saat bot startup berdasarkan ketersediaan model.")
        
        await interaction.followup.send(embed=embed)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # Error handler yang disederhanakan untuk cog ini
        original_error = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else "Unknown AI Mgmt Cmd"
        
        if isinstance(original_error, commands.NotOwner):
            return await interaction.response.send_message("Hanya pemilik bot yang bisa menggunakan perintah ini.", ephemeral=True)

        _logger.error(f"Error pada cmd AI Mgt '{command_name}': {original_error}", exc_info=True)
        
        if interaction.is_expired(): return

        msg = "Terjadi kesalahan internal saat memproses perintah manajemen AI."
        
        try:
            send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
            await send_method(msg, ephemeral=True)
        except discord.errors.HTTPException:
            pass

async def setup(bot: commands.Bot):
    # Cog ini harus selalu dimuat karena merupakan command dasar AI
    await bot.add_cog(AIManagerCog(bot))
    _logger.info(f"{AIManagerCog.__name__} Cog berhasil dimuat.")