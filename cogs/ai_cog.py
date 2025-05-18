# cogs/ai_cog.py

import discord
import os
# --- Import dari google-genai (SESUAI DOKUMENTASI BARU) ---
from google import genai
from google.genai import types # Untuk membuat Part
# --- END FIX ---
import database
from discord.ext import commands
from discord import app_commands
import logging
from PIL import Image
import io
import asyncio # Masih diperlukan untuk typing, sleep, dll.
import re
# --- Import GoogleAPIError dari google.api_core.exceptions ---
from google.api_core.exceptions import GoogleAPIError
# --- END FIX ---

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

# --- Get API Key ---
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# --- Initialize Google AI Client ---
_ai_client = None # Klien google-genai

# Nama model (pastikan valid untuk API key Anda dan library google-genai)
# Periksa dokumentasi google-genai atau ai.google.dev untuk daftar model yang didukung oleh Gemini API (non-Vertex)
# Contoh umum: 'gemini-1.5-flash-latest' atau 'gemini-pro' untuk teks, 'gemini-pro-vision' untuk multimodal
# Untuk image generation, modelnya mungkin berbeda, misal 'imagen' jika didukung via API ini.
# Untuk sekarang, kita akan fokus pada text dan multimodal dengan model yang sama.
_text_vision_model_name = 'gemini-2.0-flash' # Ganti jika perlu
# Jika Anda memiliki model khusus untuk image generation, definisikan di sini.
# Jika tidak, Anda mungkin perlu menggunakan API lain atau model multimodal yang bisa menghasilkan gambar.
_image_generation_model_name = 'gemini-2.0-flash-preview-image-generation' # Asumsi model ini juga bisa generate gambar, atau sesuaikan

# Tidak ada lagi _flash_text_model dan _flash_image_gen_model sebagai objek global
# Kita akan menggunakan nama model langsung di panggilan API

def initialize_gemini_client():
    """Initializes the Google AI client."""
    global _ai_client

    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY environment variable not set. Skipping Gemini client initialization. AI features will be unavailable.")
        return False # Indikasi kegagalan

    try:
        _ai_client = genai.Client(api_key=GOOGLE_API_KEY)
        # Uji koneksi sederhana dengan listing models (opsional, tapi baik untuk verifikasi)
        try:
            models_list = list(_ai_client.models.list(page_size=1)) # Coba ambil 1 model
            if models_list:
                _logger.info(f"Google AI client initialized successfully. Found model: {models_list[0].name}")
                return True # Indikasi sukses
            else:
                _logger.warning("Google AI client initialized, but could not list any models. Check API key permissions or model availability.")
                return False # Indikasi potensi masalah
        except Exception as e_list:
            _logger.error(f"Google AI client initialized, but failed to list models: {e_list}", exc_info=True)
            # Jika listing model gagal, _ai_client mungkin tetap ada, tapi tidak bisa dipakai.
            # Anda bisa set _ai_client = None di sini jika ingin lebih strict.
            return False # Indikasi kegagalan

    except Exception as e:
        _logger.error(f"An unexpected error occurred during Google AI client initialization: {e}", exc_info=True)
        _ai_client = None
        return False # Indikasi kegagalan

class AICog(commands.Cog):
    """Cog for AI interaction features using on_message listener and slash commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ai_client = _ai_client # Simpan instance klien
        self.text_vision_model_name = _text_vision_model_name
        self.image_generation_model_name = _image_generation_model_name
        _logger.info("AICog instance created.")
        if not self.ai_client:
            _logger.warning("AICog initialized, but AI client is not available. AI features will be disabled.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None or not self.ai_client:
            return

        config = database.get_server_config(message.guild.id)
        ai_channel_id = config.get('ai_channel_id')
        bot_user = self.bot.user
        is_mentioned = bot_user and bot_user.mention in message.content

        process_in_ai_channel = ai_channel_id is not None and message.channel.id == ai_channel_id
        process_as_mention = is_mentioned and (not process_in_ai_channel or message.content.strip() == bot_user.mention)

        if not (process_in_ai_channel or process_as_mention):
            return

        _logger.info(f"Processing AI message from {message.author.id} in guild {message.guild.name} ({message.guild.id}). Mention: {process_as_mention}, AI Channel: {process_in_ai_channel}")

        async with message.channel.typing():
            try:
                content_parts = []
                text_content_for_api = message.content.strip()

                if process_as_mention and bot_user: # Hapus mention jika ini adalah skenario mention
                    text_content_for_api = text_content_for_api.replace(bot_user.mention, '', 1).strip()
                elif process_in_ai_channel and bot_user and text_content_for_api.startswith(bot_user.mention): # Hapus mention jika di AI channel dan diawali mention
                    text_content_for_api = text_content_for_api.replace(bot_user.mention, '', 1).strip()


                # Proses attachment gambar (HANYA jika ini di AI channel, bukan untuk mention biasa)
                # Atau jika Anda ingin mention juga bisa memproses gambar.
                if process_in_ai_channel: # Anda bisa ubah kondisi ini
                    image_attachments = [att for att in message.attachments if 'image' in att.content_type]
                    if image_attachments:
                        if len(image_attachments) > 4:
                            await message.reply("Mohon berikan maksimal 4 gambar pada satu waktu.")
                            return
                        for attachment in image_attachments:
                            try:
                                image_bytes = await attachment.read()
                                pil_image = Image.open(io.BytesIO(image_bytes))
                                # Sesuai dokumentasi google-genai, PIL.Image bisa langsung dimasukkan ke list contents
                                content_parts.append(pil_image)
                                _logger.info(f"Added image attachment {attachment.filename} to content parts.")
                            except Exception as img_e:
                                _logger.error(f"Failed to process image attachment {attachment.filename}: {img_e}", exc_info=True)
                                await message.channel.send(f"Peringatan: Tidak dapat memproses gambar '{attachment.filename}'.")
                                if len(image_attachments) == 1 and not text_content_for_api:
                                    await message.reply("Tidak dapat memproses gambar yang Anda kirim.")
                                    return

                # Tambahkan teks jika ada
                if text_content_for_api:
                    content_parts.append(text_content_for_api)

                if not content_parts:
                    if process_as_mention: # Jika mention tapi tidak ada konten lain
                         await message.reply("Halo! Ada yang bisa saya bantu? (Anda menyebut saya tapi tidak ada teks yang bisa diproses).")
                    _logger.debug("Message had no processable content. Ignoring.")
                    return

                # Panggil API menggunakan client.aio.models.generate_content
                response = await self.ai_client.aio.models.generate_content(
                    model=f'models/{self.text_vision_model_name}', # Nama model harus diawali 'models/'
                    contents=content_parts,
                    # generation_config=... (opsional)
                    # safety_settings=... (opsional)
                )
                _logger.info(f"Received response from Gemini for on_message.")

                response_text = ""
                # Parsing respons dari google-genai
                if hasattr(response, 'text') and response.text: # Cara paling umum
                    response_text = response.text
                elif hasattr(response, 'parts'): # Jika ada parts individual
                    response_text = "".join(str(part.text) for part in response.parts if hasattr(part, 'text'))
                elif hasattr(response, 'candidates') and response.candidates: # Fallback jika ada candidates
                     candidate = response.candidates[0]
                     if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                         response_text = "".join(str(part.text) for part in candidate.content.parts if hasattr(part, 'text'))


                if not response_text.strip():
                    block_reason_msg = ""
                    if hasattr(response, 'prompt_feedback') and response.prompt_feedback and \
                       response.prompt_feedback.block_reason != types.generation.BlockReason.BLOCK_REASON_UNSPECIFIED:
                        block_reason = types.generation.BlockReason(response.prompt_feedback.block_reason).name
                        block_reason_msg = f" diblokir oleh filter keamanan AI ({block_reason})."
                        _logger.warning(f"on_message prompt blocked. Reason: {block_reason}. Feedback: {response.prompt_feedback}")

                    await message.reply(f"Maaf, saya tidak bisa memberikan respons saat ini{block_reason_msg}")
                    return

                # Kirim respons (dengan chunking jika perlu)
                limit = 1500 if process_as_mention else 1990 # Batas lebih pendek untuk mention
                if len(response_text) > limit:
                    _logger.info(f"Splitting long text response (limit {limit}).")
                    chunks = [response_text[i:i+limit] for i in range(0, len(response_text), limit)]
                    for i, chunk in enumerate(chunks):
                        header = f"(Bagian {i+1}/{len(chunks)}):\n" if len(chunks) > 1 else ""
                        await message.reply(header + chunk)
                        await asyncio.sleep(0.5)
                else:
                    await message.reply(response_text)

            except types.BlockedPromptError as e: # Error spesifik google-genai
                _logger.warning(f"on_message prompt blocked by Gemini API: {e}")
                await message.reply("Maaf, permintaan ini melanggar kebijakan penggunaan AI dan tidak bisa diproses.")
            # StopCandidateException mungkin tidak ada di google-genai, periksa API-nya.
            # except types.StopCandidateException as e:
            #     _logger.warning(f"Gemini response stopped prematurely: {e}")
            #     await message.reply("Maaf, respons AI terhenti di tengah jalan.")
            except GoogleAPIError as e:
                _logger.error(f"Gemini API Error during on_message: {e}", exc_info=True)
                await message.reply(f"Terjadi error pada API AI: {e.message if hasattr(e, 'message') else e}")
            except Exception as e:
                _logger.error(f"An unexpected error occurred during AI processing (on_message): {e}", exc_info=True)
                await message.reply(f"Terjadi error tak terduga saat memproses permintaan AI.")

    @app_commands.command(name='generate_image', description='Generates an image based on a text prompt using AI.')
    @app_commands.describe(prompt='Describe the image you want to generate.')
    @app_commands.guild_only()
    async def generate_image_slash(self, interaction: discord.Interaction, prompt: str):
        _logger.info(f"Received /generate_image command from {interaction.user.id} with prompt: '{prompt}' in guild {interaction.guild_id}.")

        if not self.ai_client:
            await interaction.response.send_message("Layanan AI tidak tersedia saat ini (klien AI gagal inisialisasi).", ephemeral=True)
            return

        config = database.get_server_config(interaction.guild_id)
        ai_channel_id = config.get('ai_channel_id')

        if ai_channel_id is None or interaction.channel_id != ai_channel_id:
            ai_channel = self.bot.get_channel(ai_channel_id) if ai_channel_id else None
            channel_mention = ai_channel.mention if ai_channel else '`/config ai_channel` untuk mengaturnya'
            await interaction.response.send_message(
                f"Command ini hanya bisa digunakan di channel AI yang sudah ditentukan. Silakan gunakan {channel_mention}.",
                ephemeral=True
            )
            return

        if not prompt.strip():
            await interaction.response.send_message("Mohon berikan deskripsi untuk gambar yang ingin Anda buat.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)

        try:
            _logger.info(f"Calling image generation model '{self.image_generation_model_name}' for prompt: '{prompt}'.")
            # Pastikan model yang digunakan di sini benar-benar untuk image generation.
            # `google-genai` mungkin memiliki method berbeda untuk image generation murni, e.g. `client.models.generate_image(...)`
            # atau modelnya harus spesifik (seperti 'imagen').
            # Jika `generate_content` bisa menghasilkan gambar, pastikan format `contents` dan parsingnya benar.
            # Untuk contoh ini, kita asumsikan `generate_content` dari model yang dipilih bisa mengembalikan gambar.

            # PENTING: Cek dokumentasi `google-genai` untuk cara generate gambar yang TEPAT.
            # Jika `generate_content` digunakan, output gambar biasanya berupa `Part` dengan `mime_type` gambar.
            response = await self.ai_client.aio.models.generate_content(
                model=f'models/{self.image_generation_model_name}', # Pastikan nama model ini benar
                contents=[prompt], # Prompt teks
                # Mungkin perlu generation_config khusus untuk gambar
                # generation_config=types.GenerationConfig(candidate_count=1, response_mime_type="image/png") # CONTOH, periksa dokumentasi!
            )
            _logger.info(f"Received response from Gemini API for image generation.")

            image_parts = []
            if hasattr(response, 'parts'):
                image_parts = [part for part in response.parts if hasattr(part, 'mime_type') and part.mime_type.startswith("image/")]
            elif hasattr(response, 'candidates') and response.candidates:
                 candidate = response.candidates[0]
                 if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                     image_parts = [part for part in candidate.content.parts if hasattr(part, 'mime_type') and part.mime_type.startswith("image/")]

            if not image_parts:
                _logger.warning(f"Image generation did not return any image parts. Response: {response}")
                response_text = response.text if hasattr(response, 'text') else "Tidak ada detail tambahan."

                block_reason_msg = ""
                if hasattr(response, 'prompt_feedback') and response.prompt_feedback and \
                   response.prompt_feedback.block_reason != types.generation.BlockReason.BLOCK_REASON_UNSPECIFIED:
                    block_reason = types.generation.BlockReason(response.prompt_feedback.block_reason).name
                    block_reason_msg = f" (Alasan: {block_reason})"
                    _logger.warning(f"Image generation prompt blocked. Reason: {block_reason}. Feedback: {response.prompt_feedback}")

                await interaction.followup.send(f"Gagal menghasilkan gambar{block_reason_msg}. Pesan dari AI: {response_text}")
                return

            first_image_part = image_parts[0]
            if not hasattr(first_image_part, 'data') or not first_image_part.data:
                _logger.error(f"Image part found but no data attribute or data is empty. Part: {first_image_part}")
                await interaction.followup.send("Gagal menghasilkan gambar: data gambar tidak ditemukan dalam respons.")
                return

            image_bytes = first_image_part.data
            mime_type = first_image_part.mime_type
            extension = mime_type.split('/')[-1] if '/' in mime_type else 'png'
            file_name = f"generated_image.{extension}"

            discord_file = discord.File(io.BytesIO(image_bytes), filename=file_name)
            embed = discord.Embed(title="Gambar Dihasilkan!", color=discord.Color.blue())
            embed.set_image(url=f"attachment://{file_name}")
            prompt_text_footer = prompt[:100] + ('...' if len(prompt) > 100 else '')
            embed.set_footer(text=f"Prompt: \"{prompt_text_footer}\"")

            await interaction.followup.send(embed=embed, file=discord_file)
            _logger.info(f"Sent generated image for prompt: '{prompt}'")

        except types.BlockedPromptError as e:
            _logger.warning(f"Generate Image prompt blocked by Gemini API: {e}")
            await interaction.followup.send("Maaf, permintaan generate gambar ini melanggar kebijakan penggunaan AI dan tidak bisa diproses.")
        except GoogleAPIError as e:
            _logger.error(f"Gemini API Error during generate_image: {e}", exc_info=True)
            await interaction.followup.send(f"Terjadi error pada API AI saat generate gambar: {e.message if hasattr(e, 'message') else e}")
        except Exception as e:
            _logger.error(f"An unexpected error occurred during image generation: {e}", exc_info=True)
            await interaction.followup.send(f"Terjadi error tak terduga saat mencoba generate gambar: {e}")

    async def ai_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        _logger.error(f"Handling AI command error for command {interaction.command.name if interaction.command else 'Unknown'}", exc_info=error)
        send_func = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        error_message = f"Terjadi error tak terduga: {error}"

        if isinstance(error, app_commands.CheckFailure):
            error_message = str(error)
        elif isinstance(error, app_commands.CommandInvokeError):
            original_error = error.original
            if isinstance(original_error, GoogleAPIError):
                error_message = f"Terjadi error pada API AI: {original_error.message if hasattr(original_error, 'message') else original_error}"
            elif isinstance(original_error, types.BlockedPromptError): # Error spesifik google-genai
                 error_message = "Permintaan Anda diblokir oleh kebijakan penggunaan AI."
            else:
                error_message = f"Terjadi error saat mengeksekusi command AI: {original_error}"
        try:
            await send_func(error_message, ephemeral=True)
        except Exception as send_error_e:
            _logger.error(f"Failed to send error message in AI command error handler: {send_error_e}", exc_info=True)

async def setup(bot: commands.Bot):
    """Sets up the AICog."""
    if not initialize_gemini_client(): # Panggil dan periksa hasilnya
        _logger.error("AICog will not be loaded due to Gemini client initialization failure.")
        return # Jangan load cog jika klien gagal inisialisasi

    cog_instance = AICog(bot)
    await bot.add_cog(cog_instance)
    _logger.info("AICog loaded successfully.")

    # Pasang error handler setelah cog ditambahkan
    if hasattr(cog_instance, 'generate_image_slash'):
        cog_instance.generate_image_slash.error(cog_instance.ai_command_error)