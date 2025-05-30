# Noelle_AI_Bot/ai_services/image_generator.py
import discord
from discord.ext import commands
from discord import app_commands
import google.genai as genai
from google.genai import types as genai_types
from google.api_core.exceptions import InvalidArgument, FailedPrecondition, GoogleAPIError
import asyncio
import io
import logging
import datetime # Untuk akses datetime di toggle_service

from . import gemini_client as gemini_services
from utils import ai_utils 

_logger = logging.getLogger(__name__)
# Ambil konstanta dari gemini_client.py
SESSION_TIMEOUT_MINUTES = 30 # Atau definisikan lagi jika perlu berbeda
MAX_CONTEXT_TOKENS = 120000

class ImageGeneratorCog(commands.Cog, name="AI Image Generator & Commands"): # Ubah nama Cog
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("ImageGeneratorCog instance dibuat.")

    async def _ensure_ai_channel(self, interaction: discord.Interaction) -> bool:
        # Menggunakan nama channel yang ditetapkan secara global
        designated_name = gemini_services.get_designated_ai_channel_name().lower()
        response_handler = interaction.response
        send_method_ephemeral = response_handler.send_message if not response_handler.is_done() else interaction.followup.send

        if not isinstance(interaction.channel, discord.TextChannel) or \
           interaction.channel.name.lower() != designated_name:
            await send_method_ephemeral(
                f"Perintah ini hanya dapat digunakan di channel bernama `{gemini_services.get_designated_ai_channel_name()}`.",
                ephemeral=True
            )
            return False
        return True

    ai_commands_group = app_commands.Group(name="ai", description="Perintah terkait manajemen fitur AI Noelle.")

    @ai_commands_group.command(name="clear_context", description="Membersihkan histori percakapan di channel AI ini.")
    async def ai_clear_context_cmd(self, interaction: discord.Interaction):
        if not gemini_services.is_ai_service_enabled():
            await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True); return
        if not await self._ensure_ai_channel(interaction): return

        message_handler_cog = self.bot.get_cog("AI Message Handler")
        if message_handler_cog and hasattr(message_handler_cog, '_clear_session_data'):
            message_handler_cog._clear_session_data(interaction.channel_id)
            await interaction.response.send_message("✨ Konteks percakapan di channel ini telah dibersihkan.", ephemeral=False)
            _logger.info(f"Konteks AI Channel {interaction.channel_id} dibersihkan oleh {interaction.user.name}.")
        else:
            await interaction.response.send_message("Gagal membersihkan sesi (handler tdk ditemukan).", ephemeral=True)

    @ai_commands_group.command(name="session_status", description="Menampilkan status sesi chat di channel AI ini.")
    async def ai_session_status_cmd(self, interaction: discord.Interaction):
        # ... (Logika command ini sama seperti sebelumnya, hanya _ensure_ai_channel yang berubah)
        if not gemini_services.is_ai_service_enabled(): await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True); return
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
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else: await interaction.response.send_message("Tidak ada sesi chat aktif di channel ini.", ephemeral=True)
        else: await interaction.response.send_message("Gagal mendapatkan status sesi (handler tdk ditemukan).", ephemeral=True)


    @ai_commands_group.command(name="toggle_service", description="Mengaktifkan/menonaktifkan layanan AI Noelle (Global).")
    @app_commands.choices(status=[app_commands.Choice(name="Aktifkan", value="on"), app_commands.Choice(name="Nonaktifkan", value="off")])
    @commands.has_permissions(manage_guild=True)
    async def ai_toggle_service_cmd(self, interaction: discord.Interaction, status: app_commands.Choice[str]):
        # Panggil fungsi toggle dari gemini_client.py
        # Untuk membersihkan sesi, kita perlu referensi ke dict sesi dari MessageHandlerCog
        message_handler_cog = self.bot.get_cog("AI Message Handler")
        if not message_handler_cog:
            await interaction.response.send_message("Error internal: Message handler tidak ditemukan.", ephemeral=True)
            return

        response_message = gemini_services.toggle_ai_service_status(
            status.value == "on"
        )
        # Jika layanan diaktifkan/dinonaktifkan, MessageHandlerCog harus membersihkan sesinya sendiri
        # berdasarkan status baru dari gemini_services.is_ai_service_enabled()
        # Atau, kita bisa panggil _clear_session_data di sini setelah status diubah
        if status.value == "off" or (status.value == "on" and gemini_services.is_ai_service_enabled()):
             for ch_id in list(message_handler_cog.active_chat_sessions.keys()):
                 message_handler_cog._clear_session_data(ch_id)
             if status.value == "off":
                 response_message += " Semua sesi chat aktif telah dihentikan."
             else:
                 response_message += " Semua sesi chat sebelumnya telah direset."

        await interaction.response.send_message(response_message, ephemeral=False if "berhasil" in response_message.lower() or "diaktifkan" in response_message.lower() or "dinonaktifkan" in response_message.lower() else True)

    @app_commands.command(name='generate_image', description='Membuat gambar dari teks di channel AI.')
    @app_commands.describe(prompt='Deskripsikan gambar yang ingin Anda buat.')
    @app_commands.guild_only()
    async def generate_image_command(self, interaction: discord.Interaction, prompt: str):
        # ... (Logika command ini sama seperti versi sebelumnya, pastikan _ensure_ai_channel dipanggil) ...
        # ... (dan pastikan _process_gemini_response dipanggil dengan benar untuk teks pendamping) ...
        if not gemini_services.is_ai_service_enabled():
            await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True); return
        
        client = gemini_services.get_gemini_client()
        if client is None:
            await interaction.response.send_message("Klien AI tidak terinisialisasi.", ephemeral=True); return

        if not await self._ensure_ai_channel(interaction): return

        if not prompt.strip():
            await interaction.response.send_message("Mohon berikan deskripsi gambar.", ephemeral=True); return
        
        if not interaction.response.is_done(): await interaction.response.defer(ephemeral=False)

        try:
            _logger.info(f"IMAGE_GEN: Memanggil model gambar Gemini dengan prompt: '{prompt}'.")
            config_obj = genai_types.GenerateContentConfig(response_modalities=[genai_types.Modality.TEXT, genai_types.Modality.IMAGE])
            api_response = await asyncio.to_thread(
                client.models.generate_content, model=gemini_services.GEMINI_IMAGE_GEN_MODEL_NAME, contents=prompt, config=config_obj)
            _logger.info("IMAGE_GEN: Menerima respons dari API gambar Gemini.")

            text_parts, img_bytes, mime_type = [], None, "image/png"
            if api_response.candidates:
                candidate = api_response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text: text_parts.append(part.text)
                        elif part.inline_data and part.inline_data.mime_type.startswith('image/'):
                            img_bytes, mime_type = part.inline_data.data, part.inline_data.mime_type
            final_text = "\n".join(text_parts).strip()

            if img_bytes:
                ext = mime_type.split('/')[-1] or 'png'; img_file = discord.File(io.BytesIO(img_bytes), filename=f"gemini_art.{ext}")
                title = "Gambar Dihasilkan ✨"; prompt_desc = f"**Prompt:** \"{discord.utils.escape_markdown(prompt[:1000])}{'...' if len(prompt)>1000 else ''}\""
                img_embed = discord.Embed(title=title, description=prompt_desc, color=discord.Color.random())
                img_embed.set_image(url=f"attachment://{img_file.filename}"); img_embed.set_footer(text=f"Oleh: {interaction.user.display_name}")
                await interaction.followup.send(embed=img_embed, file=img_file)
                _logger.info(f"IMAGE_GEN: Gambar terkirim untuk prompt: {prompt}")

                if final_text:
                    _logger.info("IMAGE_GEN: Mengirim teks pendamping gambar...")
                    # Panggil ai_utils untuk mengirim teks ini
                    await ai_utils.send_text_in_embeds(
                        target_channel=interaction.channel, # Kirim ke channel interaksi
                        response_text=final_text,
                        title_prefix="Info Tambahan Gambar",
                        footer_text=f"Untuk gambar dari: {interaction.user.display_name}",
                        reply_to_message=None, # Bukan reply
                        interaction_to_followup=None # Bukan followup lagi
                    )
            elif final_text: # Hanya teks
                _logger.warning(f"IMAGE_GEN: Hanya teks, tidak ada gambar. Prompt: '{prompt}'")
                await ai_utils.send_text_in_embeds(
                    target_channel=interaction.channel, # Kirim ke channel interaksi
                    response_text=final_text,
                    title_prefix="Respons AI (Tanpa Gambar)",
                    footer_text=f"Untuk prompt gambar dari: {interaction.user.display_name}",
                    reply_to_message=None, 
                    interaction_to_followup=interaction # Ini adalah respons utama, jadi bisa followup
                )
            else: # Tidak ada output
                if api_response.prompt_feedback and api_response.prompt_feedback.block_reason != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                    block_name = genai_types.BlockedReason(api_response.prompt_feedback.block_reason).name
                    await interaction.followup.send(f"Permintaan gambar diblokir ({block_name}).", ephemeral=True)
                else: await interaction.followup.send("Gagal hasilkan gambar (respons kosong).", ephemeral=True)
        except (InvalidArgument, FailedPrecondition) as e: await interaction.followup.send(f"Permintaan tidak dapat diproses: {e}", ephemeral=True)
        except GoogleAPIError as e: await interaction.followup.send(f"Error API AI: {e}", ephemeral=True)
        except Exception as e: await interaction.followup.send(f"Error tak terduga: {type(e).__name__} - {e}", ephemeral=True)


    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # ... (Error handler ini bisa disalin dari versi sebelumnya yang sudah baik) ...
        original_error = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else "Unknown AI Cmd"
        _logger.error(f"Error pd cmd AI '{command_name}' oleh {interaction.user.name}: {original_error}", exc_info=True)
        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        error_message = "Terjadi kesalahan internal saat memproses perintah AI Anda."
        if isinstance(original_error, app_commands.CheckFailure): error_message = f"Anda tidak memenuhi syarat: {original_error}"
        elif isinstance(original_error, InvalidArgument): error_message = f"Permintaan ke AI tidak valid/diblokir: {original_error}"
        elif isinstance(original_error, FailedPrecondition): error_message = f"Permintaan ke AI tidak dapat dipenuhi (filter?): {original_error}"
        elif isinstance(original_error, GoogleAPIError): error_message = f"Error layanan Google AI: {original_error}"
        elif isinstance(error, app_commands.CommandInvokeError) and isinstance(original_error, GoogleAPIError): error_message = f"Error layanan Google AI (invoke): {original_error}"
        elif isinstance(original_error, discord.errors.HTTPException): error_message = f"Error HTTP Discord: {original_error.status} - {original_error.text}"
        try: await send_method(error_message, ephemeral=True)
        except discord.errors.InteractionResponded:
             _logger.warning(f"Gagal kirim error (sudah direspons), coba ke channel utk cmd '{command_name}'.")
             try: await interaction.channel.send(f"{interaction.user.mention}, error: {error_message}")
             except Exception as ch_e: _logger.error(f"Gagal kirim error ke channel utk cmd '{command_name}': {ch_e}", exc_info=True)
        except Exception as e: _logger.error(f"Gagal kirim pesan error utk cmd '{command_name}': {e}", exc_info=True)

async def setup(bot: commands.Bot):
    client = gemini_services.get_gemini_client()
    if client is None or not gemini_services.is_ai_service_enabled():
        _logger.error("ImageGeneratorCog: Klien Gemini tidak siap atau layanan AI tidak aktif. Cog tidak akan dimuat.")
        return

    cog_instance = ImageGeneratorCog(bot)
    await bot.add_cog(cog_instance)
    _logger.info(f"{ImageGeneratorCog.__name__} Cog berhasil dimuat.")