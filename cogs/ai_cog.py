# cogs/ai_cog.py

import discord
import os
import google.genai as genai
from google.genai import types as genai_types
from google.api_core.exceptions import GoogleAPIError, InvalidArgument, FailedPrecondition # Tambahkan InvalidArgument & FailedPrecondition
import database
from discord.ext import commands
from discord import app_commands
import logging
from PIL import Image
import io
import asyncio
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

GEMINI_TEXT_MODEL_NAME = "models/gemini-2.0-flash"
GEMINI_IMAGE_GEN_MODEL_NAME = "models/gemini-2.0-flash-preview-image-generation"

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

_gemini_client: genai.Client | None = None
# Kita tidak lagi menyimpan objek model individual karena generate_content dipanggil dari client.models
# _gemini_text_model: genai_types.Model | None = None
# _gemini_image_gen_model: genai_types.Model | None = None

def initialize_gemini_client(): # Ubah nama fungsi
    """
    Menginisialisasi klien Google AI.
    Model akan dirujuk berdasarkan namanya saat pemanggilan API.
    """
    global _gemini_client

    if GOOGLE_API_KEY is None:
        _logger.error("Variabel lingkungan GOOGLE_API_KEY tidak diatur. Fitur AI tidak akan tersedia.")
        return

    try:
        _gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
        _logger.info("Klien Google GenAI berhasil diinisialisasi.")
        # Verifikasi sederhana apakah model bisa diakses (opsional, tapi baik untuk debug awal)
        try:
            _gemini_client.models.get(model=GEMINI_TEXT_MODEL_NAME)
            _logger.info(f"Model '{GEMINI_TEXT_MODEL_NAME}' dapat diakses.")
        except Exception as e:
            _logger.warning(f"Tidak dapat memverifikasi akses ke model '{GEMINI_TEXT_MODEL_NAME}': {e}")
        try:
            _gemini_client.models.get(model=GEMINI_IMAGE_GEN_MODEL_NAME)
            _logger.info(f"Model '{GEMINI_IMAGE_GEN_MODEL_NAME}' dapat diakses.")
        except Exception as e:
            _logger.warning(f"Tidak dapat memverifikasi akses ke model '{GEMINI_IMAGE_GEN_MODEL_NAME}': {e}")

    except Exception as e:
        _logger.error(f"Terjadi error tak terduga saat inisialisasi klien Google GenAI: {e}", exc_info=True)
        _gemini_client = None

initialize_gemini_client()


class AICog(commands.Cog):
    """Cog untuk fitur interaksi AI menggunakan Gemini dari Google GenAI."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Klien sudah global, tidak perlu disimpan di self jika tidak ada modifikasi per instance cog
        _logger.info("AICog instance telah dibuat.")

    async def _process_and_send_text_response(self, message_or_interaction, response: genai_types.GenerateContentResponse, context: str, is_interaction: bool = False):
        """
        Memproses respons teks dari Gemini dan mengirimkannya.
        Bisa mengirim sebagai balasan pesan atau followup interaksi.
        """
        response_text = ""
        if hasattr(response, 'text') and response.text:
            response_text = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                text_parts_list = [part.text for part in candidate.content.parts if hasattr(part, 'text') and part.text]
                response_text = "".join(text_parts_list)
            elif hasattr(candidate, 'text') and candidate.text:
                response_text = candidate.text

        send_func = message_or_interaction.followup.send if is_interaction else message_or_interaction.reply

        if not response_text.strip():
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                block_reason_value = response.prompt_feedback.block_reason
                if block_reason_value != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                    try:
                        block_reason_name = genai_types.BlockedReason(block_reason_value).name
                    except ValueError:
                        block_reason_name = f"UNKNOWN_REASON_VALUE_{block_reason_value}"
                    _logger.warning(f"({context}) Prompt diblokir. Alasan: {block_reason_name}. Feedback: {response.prompt_feedback}")
                    await send_func(f"Maaf, permintaan Anda diblokir oleh filter keamanan AI ({block_reason_name}).")
                    return
            _logger.warning(f"({context}) Gemini mengembalikan respons kosong. Full response: {response}")
            await send_func("Maaf, saya tidak bisa memberikan respons saat ini.")
            return

        max_length = 1990
        if len(response_text) > max_length:
            _logger.info(f"({context}) Respons teks terlalu panjang ({len(response_text)} chars), membaginya.")
            chunks = [response_text[i:i + max_length] for i in range(0, len(response_text), max_length)]
            for i, chunk in enumerate(chunks):
                header = f"(Bagian {i + 1}/{len(chunks)}):\n" if len(chunks) > 1 else ""
                try:
                    if is_interaction and i == 0: # Untuk interaksi, pesan pertama bisa langsung
                         await message_or_interaction.followup.send(header + chunk)
                    elif is_interaction: # Pesan lanjutan untuk interaksi
                         await message_or_interaction.channel.send(header + chunk)
                    else: # Untuk pesan biasa
                        await message_or_interaction.reply(header + chunk)
                except discord.errors.HTTPException as e:
                    _logger.error(f"({context}) Gagal mengirim potongan pesan: {e}", exc_info=True)
                    target_channel = message_or_interaction.channel if hasattr(message_or_interaction, 'channel') else message_or_interaction
                    await target_channel.send(f"Gagal mengirim bagian {i+1} respons: {e}")
                await asyncio.sleep(0.5)
        else:
            await send_func(response_text)
        _logger.info(f"({context}) Respons teks berhasil dikirim.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        if _gemini_client is None: # Cek klien global
            return

        config = database.get_server_config(message.guild.id)
        ai_channel_id = config.get('ai_channel_id')
        bot_user = self.bot.user
        is_mentioned = bot_user and bot_user.mention in message.content
        in_ai_channel = ai_channel_id is not None and message.channel.id == ai_channel_id
        cleaned_content_for_mention_check = message.content.replace(bot_user.mention, '').strip()
        just_a_mention = is_mentioned and not cleaned_content_for_mention_check and not message.attachments
        context_log_prefix = ""

        if in_ai_channel and not just_a_mention:
            context_log_prefix = "AI Channel"
            _logger.info(f"({context_log_prefix}) Memproses pesan dari {message.author.name}...")
            async with message.channel.typing():
                try:
                    content_parts = []
                    # (Logika proses attachment gambar tetap sama)
                    image_attachments = [att for att in message.attachments if 'image' in att.content_type]
                    if image_attachments:
                        if len(image_attachments) > 4:
                            await message.reply("Mohon berikan maksimal 4 gambar.")
                            return
                        for attachment in image_attachments:
                            try:
                                image_bytes = await attachment.read()
                                pil_image = Image.open(io.BytesIO(image_bytes))
                                content_parts.append(pil_image)
                            except Exception as img_e:
                                _logger.error(f"({context_log_prefix}) Gagal proses gambar {attachment.filename}: {img_e}", exc_info=True)
                                await message.channel.send(f"Peringatan: Gagal proses gambar '{attachment.filename}'.")
                                if len(image_attachments) == 1 and not message.content.strip().replace(bot_user.mention if bot_user else "", '', 1).strip():
                                    return
                    
                    text_content = message.content
                    if bot_user and bot_user.mention in text_content:
                        text_content = text_content.replace(bot_user.mention, '').strip()
                    if text_content:
                        content_parts.append(text_content)

                    if not content_parts:
                        if is_mentioned and not text_content and not image_attachments:
                             await message.reply("Halo! Ada yang bisa saya bantu?")
                        return
                    
                    # --- PERBAIKAN PEMANGGILAN API ---
                    api_response = await asyncio.to_thread(
                        _gemini_client.models.generate_content, # Panggil dari client.models
                        model=GEMINI_TEXT_MODEL_NAME,          # Sebutkan nama model
                        contents=content_parts
                    )
                    # --- AKHIR PERBAIKAN ---
                    _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini.")
                    await self._process_and_send_text_response(message, api_response, context_log_prefix)

                except (InvalidArgument, FailedPrecondition) as specific_api_e: # Tangani error spesifik jika relevan
                    _logger.warning(f"({context_log_prefix}) Error API spesifik Google (kemungkinan terkait safety/prompt): {specific_api_e}")
                    await message.reply(f"Permintaan Anda tidak dapat diproses oleh AI: {specific_api_e}")
                except GoogleAPIError as api_e:
                    _logger.error(f"({context_log_prefix}) Error API Google: {api_e}", exc_info=True)
                    await message.reply(f"Terjadi error pada API AI: {api_e}")
                except Exception as e:
                    _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True)
                    await message.reply("Terjadi error tak terduga.")
            return

        if is_mentioned and (not in_ai_channel or just_a_mention):
            context_log_prefix = "Bot Mention"
            _logger.info(f"({context_log_prefix}) Memproses mention dari {message.author.name}...")
            async with message.channel.typing():
                try:
                    text_content_for_mention = message.content.replace(bot_user.mention, '', 1).strip()
                    if not text_content_for_mention:
                        await message.reply("Halo! Ada yang bisa saya bantu?")
                        return

                    # --- PERBAIKAN PEMANGGILAN API ---
                    api_response = await asyncio.to_thread(
                        _gemini_client.models.generate_content, # Panggil dari client.models
                        model=GEMINI_TEXT_MODEL_NAME,          # Sebutkan nama model
                        contents=text_content_for_mention
                    )
                    # --- AKHIR PERBAIKAN ---
                    _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini.")
                    await self._process_and_send_text_response(message, api_response, context_log_prefix)
                
                except (InvalidArgument, FailedPrecondition) as specific_api_e:
                    _logger.warning(f"({context_log_prefix}) Error API spesifik Google (kemungkinan terkait safety/prompt): {specific_api_e}")
                    await message.reply(f"Permintaan Anda tidak dapat diproses oleh AI: {specific_api_e}")
                except GoogleAPIError as api_e:
                    _logger.error(f"({context_log_prefix}) Error API Google: {api_e}", exc_info=True)
                    await message.reply(f"Terjadi error pada API AI: {api_e}")
                except Exception as e:
                    _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True)
                    await message.reply("Terjadi error tak terduga.")
            return

    @app_commands.command(name='generate_image', description='Membuat gambar berdasarkan deskripsi teks menggunakan AI.')
    @app_commands.describe(prompt='Deskripsikan gambar yang ingin Anda buat.')
    @app_commands.guild_only()
    async def generate_image_slash(self, interaction: discord.Interaction, prompt: str):
        _logger.info(f"Menerima /generate_image dari {interaction.user.name} dengan prompt: '{prompt}'...")

        if _gemini_client is None:
            _logger.warning("Klien Gemini tidak tersedia untuk /generate_image.")
            await interaction.response.send_message("Layanan AI tidak tersedia.", ephemeral=True)
            return

        if not prompt.strip():
            await interaction.response.send_message("Mohon berikan deskripsi gambar.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=False)

        try:
            _logger.info(f"Memanggil model gambar Gemini dengan prompt: '{prompt}'.")
            
            # --- PERBAIKAN NAMA VARIABEL DAN ARGUMEN ---
            # Buat objek GenerationConfig
            generation_config_object = genai_types.GenerateContentConfig(
                response_modalities=[genai_types.Modality.TEXT, genai_types.Modality.IMAGE]
            )

            # Panggil API dengan argumen 'config' yang benar
            api_response = await asyncio.to_thread(
                _gemini_client.models.generate_content,
                model=GEMINI_IMAGE_GEN_MODEL_NAME,
                contents=prompt, # Untuk text-to-image, 'contents' adalah prompt string
                config=generation_config_object # Argumen yang benar adalah 'config'
            )
            # --- AKHIR PERBAIKAN ---
            _logger.info("Menerima respons dari API gambar Gemini.")

            generated_text_parts = []
            generated_image_bytes = None
            mime_type_image = "image/png" # Default

            if hasattr(api_response, 'candidates') and api_response.candidates:
                candidate = api_response.candidates[0]
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            generated_text_parts.append(part.text)
                        elif hasattr(part, 'inline_data') and part.inline_data and hasattr(part.inline_data, 'mime_type') and part.inline_data.mime_type.startswith('image/'):
                            generated_image_bytes = part.inline_data.data
                            mime_type_image = part.inline_data.mime_type
                            _logger.info(f"Menerima inline_data gambar (MIME: {mime_type_image}).")
                            # Ambil gambar pertama yang valid
                            # break # Jika hanya ingin satu gambar, bisa di-break di sini
            
            final_text_response = "\n".join(generated_text_parts).strip()

            if generated_image_bytes:
                extension = mime_type_image.split('/')[-1] if '/' in mime_type_image else 'png'
                filename = f"gemini_image.{extension}"
                image_file = discord.File(io.BytesIO(generated_image_bytes), filename=filename)
                
                embed_desc = f"**Prompt:** \"{discord.utils.escape_markdown(prompt[:1000])}{'...' if len(prompt) > 1000 else ''}\""
                if final_text_response:
                    # Batasi panjang teks pendamping di embed agar tidak terlalu panjang
                    embed_desc += f"\n\n**AI:** {final_text_response[:1000]}{'...' if len(final_text_response) > 1000 else ''}"
                
                embed = discord.Embed(title="Gambar Dihasilkan oleh Gemini ✨", description=embed_desc, color=discord.Color.random())
                embed.set_image(url=f"attachment://{filename}")
                embed.set_footer(text=f"Diminta oleh: {interaction.user.display_name}")
                
                await interaction.followup.send(embed=embed, file=image_file)
                _logger.info(f"Gambar dan teks pendamping (jika ada) berhasil dikirim untuk prompt: {prompt}")
            elif final_text_response:
                _logger.warning(f"Gemini menghasilkan teks tetapi tidak ada data gambar. Prompt: '{prompt}'")
                await interaction.followup.send(f"AI merespons (tanpa gambar):\n\n{final_text_response}")
            else:
                if hasattr(api_response, 'prompt_feedback') and api_response.prompt_feedback:
                    block_reason_value = api_response.prompt_feedback.block_reason
                    if block_reason_value != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                        try:
                            block_reason_name = genai_types.BlockedReason(block_reason_value).name
                        except ValueError:
                             block_reason_name = f"UNKNOWN_REASON_VALUE_{block_reason_value}"
                        _logger.warning(f"Prompt gambar diblokir. Alasan: {block_reason_name}. Prompt: '{prompt}'. Feedback: {api_response.prompt_feedback}")
                        await interaction.followup.send(f"Maaf, permintaan gambar Anda diblokir ({block_reason_name}).")
                        return
                _logger.warning(f"Gemini mengembalikan respons kosong untuk gambar. Prompt: '{prompt}'. Resp: {api_response}")
                await interaction.followup.send("Gagal menghasilkan gambar. AI memberikan respons yang tidak terduga atau kosong.")

        except (InvalidArgument, FailedPrecondition) as specific_api_e:
            _logger.warning(f"Error API spesifik Google (kemungkinan terkait safety/prompt) saat generate gambar: {specific_api_e}. Prompt: '{prompt}'")
            await interaction.followup.send(f"Permintaan Anda tidak dapat diproses oleh AI: {specific_api_e}", ephemeral=True)
        except GoogleAPIError as api_e:
            _logger.error(f"Error API Google saat generate gambar: {api_e}. Prompt: '{prompt}'", exc_info=True)
            await interaction.followup.send(f"Terjadi error pada API AI: {api_e}", ephemeral=True)
        except Exception as e:
            _logger.error(f"Error tak terduga saat generate gambar: {e}. Prompt: '{prompt}'", exc_info=True)
            await interaction.followup.send(f"Terjadi error tak terduga saat membuat gambar: {type(e).__name__} - {e}", ephemeral=True) # Tampilkan tipe error juga

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original_error = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else "Unknown AI Cmd"
        _logger.error(f"Error pd cmd AI '{command_name}' oleh {interaction.user.name}: {original_error}", exc_info=True)
        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        error_message = "Terjadi kesalahan internal saat memproses perintah AI."

        if isinstance(original_error, app_commands.CheckFailure):
            error_message = f"Anda tidak memenuhi syarat: {original_error}"
        # Hapus pengecekan BlockedPromptError/StopCandidateError di sini
        elif isinstance(original_error, (InvalidArgument, FailedPrecondition)):
             error_message = f"Permintaan Anda tidak valid atau diblokir oleh AI: {original_error}"
        elif isinstance(original_error, GoogleAPIError):
            error_message = f"Error pada layanan Google AI: {original_error}"
        elif isinstance(error, app_commands.CommandInvokeError) and isinstance(original_error, GoogleAPIError):
             error_message = f"Error pada layanan Google AI (invoke): {original_error.original}"
        elif isinstance(original_error, discord.errors.HTTPException):
            error_message = f"Error HTTP Discord: {original_error.status} - {original_error.text}"
        
        try:
            await send_method(error_message, ephemeral=True)
        except Exception as e:
            _logger.error(f"Gagal kirim pesan error utk cmd '{command_name}': {e}", exc_info=True)

async def setup(bot: commands.Bot):
    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY tidak ada. AICog tidak dimuat.")
        return
    if _gemini_client is None:
        _logger.error("Klien Gemini gagal inisialisasi. AICog tidak dimuat.")
        return
    
    cog_instance = AICog(bot)
    await bot.add_cog(cog_instance)
    _logger.info("AICog berhasil dimuat.")