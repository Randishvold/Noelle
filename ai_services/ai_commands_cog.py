# Noelle_Bot/ai_services/ai_commands_cog.py

import discord
from discord.ext import commands
from discord import app_commands
import logging
import datetime

from . import gemini_client as gemini_services
from . import deep_search_service # Impor layanan baru kita
from utils import ai_utils 

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
        
        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message

        if not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name.lower() != designated_name:
            try:
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
        # ... (kode clear_context tetap sama) ...
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
        # ... (kode session_status tetap sama) ...
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


    # --- PERINTAH BARU: DEEP SEARCH ---
    @ai_commands_group.command(name="deep_search", description="Lakukan riset mendalam tentang sebuah topik menggunakan beberapa agen AI.")
    @app_commands.describe(
        topic="Topik yang ingin Anda teliti secara mendalam.",
        mode="Pilih mode riset: Cepat (sedikit kueri) atau Komprehensif (lebih banyak kueri).",
        pertanyaan_lanjutan="(Opsional) Pertanyaan spesifik untuk dijawab dalam laporan akhir."
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="Cepat (sekitar 3-4 sub-topik)", value="fast"),
        app_commands.Choice(name="Komprehensif (sekitar 5-7 sub-topik)", value="comprehensive"),
    ])
    async def ai_deep_search_cmd(self, interaction: discord.Interaction, topic: str, mode: app_commands.Choice[str], pertanyaan_lanjutan: str = None):
        """Menjalankan alur kerja deep research dan mengirimkan hasilnya."""
        
        # Cek apakah layanan utama AI aktif
        if not gemini_services.is_text_service_enabled():
            return await interaction.response.send_message("Layanan AI Teks sedang tidak aktif. Fitur ini tidak dapat digunakan.", ephemeral=True)
        
        # Defer respons karena proses ini akan lama. ephemeral=False agar status bisa dilihat semua orang.
        await interaction.response.defer(ephemeral=False, thinking=True)

        # Memanggil layanan inti untuk melakukan seluruh pekerjaan
        final_report = await deep_search_service.run_deep_search(
            interaction=interaction,
            topic=topic,
            mode=mode.value,
            follow_up=pertanyaan_lanjutan
        )

        # Edit pesan status awal menjadi pesan konfirmasi selesai
        await interaction.edit_original_response(content=f"✅ Riset mendalam untuk topik **\"{topic[:100]}\"** telah selesai. Laporan lengkap di bawah ini:", view=None)

        # Gunakan utilitas yang ada untuk mengirim teks panjang dalam beberapa embed
        await ai_utils.send_text_in_embeds(
            target_channel=interaction.channel,
            response_text=final_report,
            footer_text=f"Riset mendalam diminta oleh: {interaction.user.display_name}",
            api_candidate_obj=None, # Tidak ada candidate object tunggal untuk laporan akhir
            is_direct_ai_response=False, # Ini adalah laporan, bukan respons langsung
            custom_title_prefix=f"Laporan Riset: {topic[:150]}"
        )

    # ... (error handler tetap sama) ...
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        pass


async def setup(bot: commands.Bot):
    if gemini_services.is_text_service_enabled() or gemini_services.is_image_service_enabled():
        await bot.add_cog(AICommandsCog(bot))
        _logger.info("AICommandsCog (Grup /ai) berhasil dimuat.")
    else:
        _logger.warning("AICommandsCog tidak dimuat karena semua layanan AI nonaktif.")