# Noelle_Bot/ai_services/ai_commands_cog.py

import discord
from discord.ext import commands
from discord import app_commands
import logging
import datetime

from . import gemini_client as gemini_services
from . import deep_search_service # Impor layanan baru kita
from utils import ai_utils 
from utils import web_utils

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


   # Di dalam kelas AICommandsCog

    # ... (kode lainnya tetap sama) ...

    # --- PERINTAH DEEP SEARCH YANG DISEMPURNAKAN ---
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
        """Menjalankan alur kerja deep research dan mengirimkan hasilnya dalam format baru."""
        
        if not gemini_services.is_text_service_enabled():
            return await interaction.response.send_message("Layanan AI Teks sedang tidak aktif.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=False, thinking=True)

        # 1. Panggil layanan inti untuk mendapatkan laporan terstruktur
        structured_report = await deep_search_service.run_deep_search(
            interaction=interaction,
            topic=topic,
            mode=mode.value,
            follow_up=pertanyaan_lanjutan
        )

        # Cek jika layanan mengembalikan pesan error
        if "Maaf," in structured_report or "Terjadi kesalahan" in structured_report:
            await interaction.edit_original_response(content=structured_report, view=None)
            return

        # 2. Proses dan pisahkan output terstruktur
        summary = "Ringkasan tidak ditemukan."
        full_report = structured_report # Fallback jika parsing gagal
        try:
            summary_start = structured_report.find("[SUMMARY_START]") + len("[SUMMARY_START]")
            summary_end = structured_report.find("[SUMMARY_END]")
            report_start = structured_report.find("[REPORT_START]") + len("[REPORT_START]")
            
            if summary_start != -1 and summary_end != -1 and report_start != -1:
                summary = structured_report[summary_start:summary_end].strip()
                full_report = structured_report[report_start:].strip()
            else:
                 _logger.warning("Gagal menemukan penanda di laporan AI. Menggunakan laporan penuh sebagai fallback.")

        except Exception as e:
            _logger.error(f"Error saat mem-parsing laporan AI: {e}")

        # 3. Unggah laporan lengkap ke layanan paste
        report_url = await web_utils.upload_to_paste_service(full_report)

        # 4. Siapkan embed dan view untuk ditampilkan di Discord
        embed = discord.Embed(
            title=f"Ringkasan Riset: {topic[:150]}",
            description=summary,
            color=discord.Color.dark_green()
        )
        embed.set_footer(text=f"Riset mendalam diminta oleh: {interaction.user.display_name}")

        view = discord.ui.View()
        if report_url:
            embed.add_field(name="Laporan Lengkap", value="Klik tombol di bawah untuk melihat laporan riset yang detail.", inline=False)
            button = discord.ui.Button(label="Buka Laporan Lengkap", style=discord.ButtonStyle.link, url=report_url, emoji="📄")
            view.add_item(button)
        else:
            embed.add_field(name="Laporan Lengkap Gagal Diunggah", value="Laporan lengkap akan dikirim sebagai file.", inline=False)
        
        # 5. Kirim hasil akhir
        await interaction.edit_original_response(content=f"✅ Riset mendalam untuk topik **\"{topic[:100]}\"** telah selesai.", embed=embed, view=view)

        # 6. Kirim file sebagai fallback jika URL gagal dibuat
        if not report_url:
            await ai_utils.send_long_text_as_file(interaction.channel, full_report, "laporan_lengkap.md", "Berikut adalah laporan lengkapnya:")

    # ... (error handler tetap sama) ...
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        pass


async def setup(bot: commands.Bot):
    if gemini_services.is_text_service_enabled() or gemini_services.is_image_service_enabled():
        await bot.add_cog(AICommandsCog(bot))
        _logger.info("AICommandsCog (Grup /ai) berhasil dimuat.")
    else:
        _logger.warning("AICommandsCog tidak dimuat karena semua layanan AI nonaktif.")