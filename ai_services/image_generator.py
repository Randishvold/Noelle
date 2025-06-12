# Noelle_Bot/ai_services/image_generator.py
import discord
from discord.ext import commands
from discord import app_commands
import google.genai as genai
from google.genai import types as genai_types
from google.api_core import exceptions as google_exceptions
import asyncio
import io
import logging
import datetime 

from . import gemini_client as gemini_services
from utils import ai_utils 

_logger = logging.getLogger("noelle_bot.ai.image_generator")

SESSION_TIMEOUT_MINUTES = 30 
MAX_CONTEXT_TOKENS = 120000

class ImageGeneratorCog(commands.Cog, name="AI Image Generator & Commands"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("ImageGeneratorCog instance dibuat.")

    async def _ensure_ai_channel(self, interaction: discord.Interaction) -> bool:
        designated_name = gemini_services.get_designated_ai_channel_name().lower()
        
        # Penentuan metode respons yang aman
        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message

        if not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name.lower() != designated_name:
            try:
                # Coba kirim respons ephemeral
                await send_method(f"Perintah ini hanya bisa digunakan di channel `{gemini_services.get_designated_ai_channel_name()}`.", ephemeral=True)
            except discord.errors.InteractionResponded:
                # Jika sudah direspons (misalnya oleh defer), coba kirim pesan biasa
                await interaction.channel.send(f"{interaction.user.mention}, perintah ini hanya untuk channel `{gemini_services.get_designated_ai_channel_name()}`.", delete_after=10)
            except Exception as e:
                _logger.error(f"Gagal mengirim pesan _ensure_ai_channel: {e}")
            return False
        return True

    ai_commands_group = app_commands.Group(name="ai", description="Perintah terkait manajemen fitur AI Noelle.")

    @ai_commands_group.command(name="clear_context", description="Membersihkan histori percakapan di channel AI ini.")
    async def ai_clear_context_cmd(self, interaction: discord.Interaction):
        # Check cepat, bisa langsung direspons
        if not gemini_services.is_ai_service_enabled(): 
            return await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True)
        
        # Defer karena check ini mungkin akan butuh waktu
        await interaction.response.defer(ephemeral=True)
        if not await self._ensure_ai_channel(interaction): return
        
        message_handler_cog = self.bot.get_cog("AI Message Handler")
        if message_handler_cog and hasattr(message_handler_cog, '_clear_session_data'):
            message_handler_cog._clear_session_data(interaction.channel_id)
            await interaction.followup.send("✨ Konteks percakapan di channel ini telah dibersihkan.", ephemeral=False)
        else: 
            await interaction.followup.send("Gagal membersihkan sesi (internal error: handler tidak ditemukan).")

    @ai_commands_group.command(name="session_status", description="Menampilkan status sesi chat di channel AI ini.")
    async def ai_session_status_cmd(self, interaction: discord.Interaction):
        if not gemini_services.is_ai_service_enabled(): 
            return await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True)
        
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

    @ai_commands_group.command(name="toggle_service", description="Mengaktifkan/menonaktifkan layanan AI Noelle (Global).")
    @app_commands.choices(status=[app_commands.Choice(name="Aktifkan", value="on"), app_commands.Choice(name="Nonaktifkan", value="off")])
    @commands.has_permissions(manage_guild=True)
    async def ai_toggle_service_cmd(self, interaction: discord.Interaction, status: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        response_message = gemini_services.toggle_ai_service_status(status.value == "on")
        
        if status.value == "off" or (status.value == "on" and gemini_services.is_ai_service_enabled()):
            message_handler_cog = self.bot.get_cog("AI Message Handler")
            if message_handler_cog and hasattr(message_handler_cog, '_clear_session_data'):
                for ch_id in list(message_handler_cog.active_chat_sessions.keys()): 
                    message_handler_cog._clear_session_data(ch_id)
                if status.value == "off": response_message += " Semua sesi chat aktif telah dihentikan."
                else: response_message += " Semua sesi chat sebelumnya telah direset."
            else: 
                _logger.warning("Tidak dapat menemukan MessageHandlerCog untuk membersihkan sesi saat toggle service.")
        
        await interaction.followup.send(response_message)

    @app_commands.command(name='generate_image', description='Membuat gambar dari teks di channel AI.')
    @app_commands.describe(prompt='Deskripsikan gambar yang ingin Anda buat.')
    @app_commands.guild_only()
    async def generate_image_command(self, interaction: discord.Interaction, prompt: str):
        # --- PERBAIKAN: Pindahkan semua check cepat ke atas SEBELUM defer ---
        if not gemini_services.is_ai_service_enabled():
            return await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True)
        
        client = gemini_services.get_gemini_client()
        if client is None:
            return await interaction.response.send_message("Klien AI tidak terinisialisasi.", ephemeral=True)

        # Check ini bisa merespons, jadi letakkan sebelum defer
        if not await self._ensure_ai_channel(interaction):
            return

        if not prompt.strip():
            return await interaction.response.send_message("Mohon berikan deskripsi gambar.", ephemeral=True)
        
        # --- PERBAIKAN: Defer di sini SETELAH semua check cepat selesai ---
        await interaction.response.defer(ephemeral=False)

        try:
            _logger.info(f"IMAGE_GEN: Memanggil model gambar Gemini dengan prompt: '{prompt}'.")
            
            config_obj = genai_types.GenerateContentConfig(
                response_modalities=[genai_types.Modality.TEXT, genai_types.Modality.IMAGE]
            )
            api_response = await asyncio.to_thread(
                client.models.generate_content,
                model=gemini_services.GEMINI_IMAGE_GEN_MODEL_NAME, contents=prompt, config=config_obj
            )
            _logger.info("IMAGE_GEN: Menerima respons dari API gambar Gemini.")

            text_parts, img_bytes, mime_type = [], None, "image/png"
            api_candidate = None
            if api_response.candidates:
                api_candidate = api_response.candidates[0]
                if api_candidate.content and api_candidate.content.parts:
                    for part in api_candidate.content.parts:
                        if part.text: text_parts.append(part.text)
                        elif part.inline_data and part.inline_data.mime_type.startswith('image/'):
                            img_bytes, mime_type = part.inline_data.data, part.inline_data.mime_type
            final_text_companion = "\n".join(text_parts).strip()

            if img_bytes:
                ext = mime_type.split('/')[-1] if '/' in mime_type else 'png'
                img_file = discord.File(io.BytesIO(img_bytes), filename=f"gemini_art.{ext}")
                title_embed_img = "Gambar Dihasilkan oleh Noelle ✨"
                description_content = f"**Prompt:** \"{discord.utils.escape_markdown(prompt[:1500])}{'...' if len(prompt)>1500 else ''}\""
                sisa_teks_pendamping = ""

                if final_text_companion:
                    combined_desc_len = len(description_content) + len("\n\n**Noelle:**\n") + len(final_text_companion)
                    if combined_desc_len <= ai_utils.EMBED_DESC_LIMIT:
                        description_content += f"\n\n**Noelle:**\n{final_text_companion}"
                    else:
                        available_space = ai_utils.EMBED_DESC_LIMIT - (len(description_content) + len("\n\n**Noelle:**\n") + 10)
                        if available_space > 20:
                            split_at = ai_utils.find_sensible_split_point(final_text_companion, available_space)
                            description_content += f"\n\n**Noelle:**\n{final_text_companion[:split_at]}..."
                            sisa_teks_pendamping = final_text_companion[split_at:].strip()
                        else: sisa_teks_pendamping = final_text_companion
                
                img_embed = discord.Embed(title=title_embed_img, description=description_content, color=discord.Color.random())
                img_embed.set_image(url=f"attachment://{img_file.filename}")
                img_embed.set_footer(text=f"Diminta oleh: {interaction.user.display_name}")
                
                if api_candidate and hasattr(api_candidate, 'citation_metadata') and api_candidate.citation_metadata and hasattr(api_candidate.citation_metadata, 'citations') and api_candidate.citation_metadata.citations:
                    citations_list_img = []
                    for idx_c, citation_img in enumerate(api_candidate.citation_metadata.citations[:2]):
                        title_c = getattr(citation_img, 'title', None)
                        uri_c = getattr(citation_img, 'uri', None)
                        if uri_c:
                            display_c = title_c if title_c else (uri_c.split('/')[-1][:40] if '/' in uri_c else uri_c[:25])
                            citations_list_img.append(f"[{display_c.strip()[:40]}]({uri_c})")
                    if citations_list_img:
                        img_embed.add_field(name="Sumber Info Tambahan:", value="▫️ " + "\n▫️ ".join(citations_list_img), inline=False)

                await interaction.followup.send(embed=img_embed, file=img_file)

                if sisa_teks_pendamping:
                    await ai_utils.send_text_in_embeds(
                        target_channel=interaction.channel,
                        response_text=sisa_teks_pendamping,
                        footer_text=f"Lanjutan untuk gambar dari: {interaction.user.display_name}",
                        api_candidate_obj=None,
                        is_direct_ai_response=False, 
                        custom_title_prefix="Info Tambahan Gambar"
                    )
            elif final_text_companion:
                await ai_utils.send_text_in_embeds(
                    target_channel=interaction.channel, response_text=final_text_companion,
                    footer_text=f"Untuk prompt gambar dari: {interaction.user.display_name}",
                    api_candidate_obj=api_candidate,
                    interaction_to_followup=interaction, 
                    is_direct_ai_response=True, custom_title_prefix=None
                )
            else:
                block_reason = getattr(api_response.prompt_feedback, 'block_reason', None)
                if block_reason and block_reason != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                    block_name = genai_types.BlockedReason(block_reason).name
                    await interaction.followup.send(f"Permintaan gambar diblokir ({block_name}).", ephemeral=True)
                else:
                    await interaction.followup.send("Gagal menghasilkan gambar (respons kosong dari API).", ephemeral=True)
        
        except Exception as e:
            _logger.error(f"Error tak terduga dalam /generate_image: {e}", exc_info=True)
            if not interaction.is_expired():
                try:
                    await interaction.followup.send("Terjadi kesalahan internal saat membuat gambar.", ephemeral=True)
                except discord.errors.HTTPException:
                    pass

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original_error = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else "Unknown AI Cmd"
        
        # Hindari logging "Interaction has already been acknowledged" karena ini sering terjadi dan bukan error kritis
        if isinstance(original_error, discord.errors.HTTPException) and original_error.code == 40060:
            _logger.warning(f"Gagal merespons interaksi untuk '{command_name}' (sudah diakui/kedaluwarsa).")
            return

        _logger.error(f"Error pada cmd AI '{command_name}' oleh {interaction.user.name}: {original_error}", exc_info=True)
        
        # Jangan coba kirim respons jika interaksi sudah tidak valid
        if interaction.is_expired():
            return

        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        error_message = "Terjadi kesalahan internal saat memproses perintah AI Anda."
        
        # Pemetaan error yang lebih baik
        if isinstance(original_error, app_commands.MissingPermissions): error_message = f"Anda tidak punya izin: {original_error.missing_permissions[0]}"
        elif isinstance(original_error, app_commands.CheckFailure): error_message = f"Anda tidak memenuhi syarat untuk menggunakan perintah ini."
        elif isinstance(original_error, (google_exceptions.InvalidArgument, google_exceptions.FailedPrecondition)): error_message = f"Permintaan ke AI tidak valid atau diblokir oleh filter keamanan."
        elif isinstance(original_error, (google_exceptions.ServerError, google_exceptions.DeadlineExceeded, google_exceptions.ServiceUnavailable)): error_message = "Server AI sedang sibuk atau timeout. Coba lagi nanti."
        elif isinstance(original_error, google_exceptions.GoogleAPIError): error_message = f"Terjadi error pada layanan Google AI."
        
        try:
            await send_method(error_message, ephemeral=True)
        except discord.errors.HTTPException:
            _logger.warning(f"Gagal kirim pesan error (mungkin interaksi sudah kedaluwarsa).")

async def setup(bot: commands.Bot):
    client = gemini_services.get_gemini_client()
    if client is None or not gemini_services.is_ai_service_enabled():
        _logger.error("ImageGeneratorCog: Klien Gemini tidak siap. Cog tidak dimuat.")
        return
    await bot.add_cog(ImageGeneratorCog(bot))
    _logger.info(f"{ImageGeneratorCog.__name__} Cog berhasil dimuat.")