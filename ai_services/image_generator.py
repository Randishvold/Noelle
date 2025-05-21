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

from . import gemini_client as gemini_services
import database # Untuk cek AI channel dan config
from utils import ai_utils # Untuk mengirim teks pendamping

_logger = logging.getLogger(__name__)

class ImageGeneratorCog(commands.Cog, name="AI Image Generator"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Referensi ke MessageHandlerCog untuk akses _clear_session_data jika diperlukan
        # Ini bisa menjadi circular dependency jika MessageHandlerCog juga impor ImageGeneratorCog
        # Cara yang lebih baik adalah meletakkan _clear_session_data di gemini_client.py atau modul utilitas sesi.
        # Untuk sekarang, kita anggap toggle_service di gemini_client.py sudah cukup.
        _logger.info("ImageGeneratorCog instance dibuat.")

    async def _ensure_ai_channel(self, interaction: discord.Interaction) -> bool:
        # Duplikasi sementara, idealnya ini ada di utils atau diwariskan
        # atau MessageHandlerCog bisa diakses dari sini untuk panggil metodenya
        # (Tapi lebih baik independen jika memungkinkan)
        if not interaction.guild_id: return False
        config = database.get_server_config(interaction.guild_id)
        ai_channel_id = config.get('ai_channel_id')
        response_handler = interaction.response
        send_method_ephemeral = response_handler.send_message if not response_handler.is_done() else interaction.followup.send

        if ai_channel_id is None:
            await send_method_ephemeral("Channel AI belum diatur. Atur via `/config ai_channel`.", ephemeral=True)
            return False
        if interaction.channel_id != ai_channel_id:
            designated_channel = self.bot.get_channel(ai_channel_id)
            channel_mention = designated_channel.mention if designated_channel else f"channel AI ({ai_channel_id})"
            await send_method_ephemeral(f"Perintah ini hanya dapat digunakan di {channel_mention}.", ephemeral=True)
            return False
        return True

    # --- Grup Command AI ---
    # Kita definisikan grup di sini agar command-nya bisa menjadi bagian dari grup ini
    # Namun, grupnya sendiri akan ditambahkan ke tree bot sekali saja (di main.py atau saat load cog pertama yg punya grup itu)
    # Untuk struktur yang lebih rapi, semua command /ai bisa ada di satu cog ini.
    
    ai_commands_group = app_commands.Group(name="ai", description="Perintah terkait manajemen fitur AI Noelle.")

    @ai_commands_group.command(name="clear_context", description="Membersihkan histori percakapan di channel AI ini.")
    async def ai_clear_context_cmd(self, interaction: discord.Interaction):
        if not gemini_services.is_ai_service_enabled():
            await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True); return
        if not await self._ensure_ai_channel(interaction): return

        # Akses MessageHandlerCog untuk membersihkan sesi
        message_handler_cog = self.bot.get_cog("AI Message Handler") # Nama cog dari MessageHandlerCog
        if message_handler_cog and hasattr(message_handler_cog, '_clear_session_data'):
            message_handler_cog._clear_session_data(interaction.channel_id)
            await interaction.response.send_message("✨ Konteks percakapan di channel ini telah dibersihkan.", ephemeral=False)
            _logger.info(f"Konteks AI Channel {interaction.channel_id} dibersihkan oleh {interaction.user.name}.")
        else:
            await interaction.response.send_message("Gagal membersihkan sesi (handler tidak ditemukan).", ephemeral=True)
            _logger.error("Tidak dapat menemukan MessageHandlerCog untuk clear_context.")


    @ai_commands_group.command(name="session_status", description="Menampilkan status sesi chat di channel AI ini.")
    async def ai_session_status_cmd(self, interaction: discord.Interaction):
        if not gemini_services.is_ai_service_enabled():
            await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True); return
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
        message_handler_cog = self.bot.get_cog("AI Message Handler") # Untuk akses data sesi
        if not message_handler_cog:
             await interaction.response.send_message("Error: Komponen message handler tidak ditemukan.",ephemeral=True)
             return

        response_message = gemini_services.toggle_ai_service(
            status.value == "on",
            message_handler_cog.active_chat_sessions, # Pass referensi dict
            message_handler_cog.chat_session_last_active,
            message_handler_cog.chat_context_token_counts
        )
        await interaction.response.send_message(response_message, ephemeral=False if "berhasil" in response_message.lower() else True)


    @app_commands.command(name='generate_image', description='Membuat gambar dari teks di AI Channel.')
    @app_commands.describe(prompt='Deskripsikan gambar yang ingin Anda buat.')
    @app_commands.guild_only() # Pastikan hanya di guild
    async def generate_image_command(self, interaction: discord.Interaction, prompt: str):
        if not gemini_services.is_ai_service_enabled():
            await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True); return
        
        client = gemini_services.get_gemini_client()
        if client is None:
            await interaction.response.send_message("Klien AI tidak terinisialisasi.", ephemeral=True); return

        if not await self._ensure_ai_channel(interaction): return # Validasi AI Channel

        if not prompt.strip():
            await interaction.response.send_message("Mohon berikan deskripsi gambar.", ephemeral=True); return
        
        if not interaction.response.is_done(): await interaction.response.defer(ephemeral=False)

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
            if api_response.candidates:
                candidate = api_response.candidates[0]
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.text: text_parts.append(part.text)
                        elif part.inline_data and part.inline_data.mime_type.startswith('image/'):
                            img_bytes, mime_type = part.inline_data.data, part.inline_data.mime_type
                            _logger.info(f"IMAGE_GEN: Diterima inline_data gambar (MIME: {mime_type}).")
            
            final_text = "\n".join(text_parts).strip()

            if img_bytes:
                ext = mime_type.split('/')[-1] or 'png'
                img_file = discord.File(io.BytesIO(img_bytes), filename=f"gemini_art.{ext}")
                title = "Gambar Dihasilkan oleh Noelle ✨"
                prompt_desc = f"**Prompt:** \"{discord.utils.escape_markdown(prompt[:1000])}{'...' if len(prompt)>1000 else ''}\""
                img_embed = discord.Embed(title=title, description=prompt_desc, color=discord.Color.random())
                img_embed.set_image(url=f"attachment://{img_file.filename}")
                img_embed.set_footer(text=f"Diminta oleh: {interaction.user.display_name}")
                await interaction.followup.send(embed=img_embed, file=img_file)
                _logger.info(f"IMAGE_GEN: Gambar terkirim untuk prompt: {prompt}")

                if final_text: # Kirim teks pendamping jika ada
                    _logger.info("IMAGE_GEN: Mengirim teks pendamping gambar...")
                    # Gunakan _process_gemini_response dari MessageHandlerCog (atau ai_utils)
                    # Ini agak rumit jika cog dipisah, idealnya _process_gemini_response ada di ai_utils
                    message_handler_cog = self.bot.get_cog("AI Message Handler")
                    if message_handler_cog:
                        # Buat dummy response object untuk teks
                        dummy_text_part = genai_types.Part(text=final_text)
                        dummy_content = genai_types.Content(parts=[dummy_text_part], role="model")
                        dummy_candidate = genai_types.Candidate(content=dummy_content, finish_reason=genai_types.FinishReason.STOP, index=0)
                        dummy_response_for_text = genai_types.GenerateContentResponse(candidates=[dummy_candidate])
                        await message_handler_cog._process_gemini_response(interaction, dummy_response_for_text, "Info Tambahan Gambar", is_interaction=True)
                    else: # Fallback jika MessageHandlerCog tidak ditemukan
                        await interaction.channel.send(f"**Info Tambahan:**\n{final_text[:1900]}")

            elif final_text:
                _logger.warning(f"IMAGE_GEN: Hanya teks, tidak ada gambar. Prompt: '{prompt}'")
                message_handler_cog = self.bot.get_cog("AI Message Handler")
                if message_handler_cog:
                    dummy_text_part = genai_types.Part(text=final_text) # ... (buat dummy response seperti di atas)
                    dummy_content = genai_types.Content(parts=[dummy_text_part], role="model")
                    dummy_candidate = genai_types.Candidate(content=dummy_content, finish_reason=genai_types.FinishReason.STOP, index=0)
                    dummy_response_for_text = genai_types.GenerateContentResponse(candidates=[dummy_candidate])
                    await message_handler_cog._process_gemini_response(interaction, dummy_response_for_text, "Image Gen Text-Only", is_interaction=True)
                else:
                    await interaction.followup.send(f"AI merespons (tanpa gambar):\n{final_text[:1900]}", ephemeral=True)
            else: # Tidak ada gambar maupun teks
                # ... (penanganan prompt_feedback seperti sebelumnya) ...
                if api_response.prompt_feedback and api_response.prompt_feedback.block_reason != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                    block_name = genai_types.BlockedReason(api_response.prompt_feedback.block_reason).name
                    await interaction.followup.send(f"Permintaan gambar diblokir ({block_name}).", ephemeral=True)
                else:
                    await interaction.followup.send("Gagal hasilkan gambar (respons kosong).", ephemeral=True)
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