import discord
import os
# --- Import from google.genai ---
import google.generativeai as genai # Use google.genai
from google.generativeai import types # Import types from google.genai
# --- END FIX ---
import database # Import database module
# utils import dihilangkan jika tidak dipakai langsung di sini, tapi bisa ditambahkan jika perlu
from discord.ext import commands
from discord import app_commands
import logging
from PIL import Image # Required for handling image inputs
import io # Required for handling image bytes
import asyncio # Required for async operations like sleep and typing
import re # Required for potential URL finding
# base64 import dihilangkan karena sepertinya tidak jadi dipakai dengan inline_data.data yang sudah bytes
# --- Import GoogleAPIError from google.api_core.exceptions ---
from google.api_core.exceptions import GoogleAPIError # Import GoogleAPIError
# --- END FIX ---

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

# --- Get API Key ---
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# --- Initialize Google AI Client and Models ---
_ai_client = None # The AI client instance

_flash_text_model_name = 'gemini-2.0-flash' # Gunakan nama model yang lebih umum jika 2.0 belum stabil/tersedia
_flash_image_gen_model_name = 'gemini-2.0-flash-preview-image-generation' # Atau model spesifik untuk image generation jika ada yang lebih baru dan terbukti berfungsi
# Catatan: Nama model 'gemini-2.0-flash' mungkin belum tersedia secara umum atau memerlukan API khusus.
# 'gemini-1.5-flash' lebih umum. Pastikan API key Anda mendukung model yang dipilih.
# Untuk image generation, model seperti 'gemini-pro-vision' bisa menganalisis gambar,
# tapi untuk *generasi* gambar, Anda mungkin perlu model khusus seperti 'imagen' (jika didukung library ini)
# atau periksa dokumentasi Gemini terbaru untuk nama model image generation yang tepat.
# Untuk sementara, kita asumsikan _flash_image_gen_model_name adalah nama model yang valid atau akan disesuaikan.

_flash_text_model = None # Model object for text/vision
_flash_image_gen_model = None # Model object for image generation


def initialize_gemini():
    """Initializes the Google AI client and gets GenerativeModel objects."""
    global _ai_client, _flash_text_model, _flash_image_gen_model

    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY environment variable not set. Skipping Gemini initialization. AI features will be unavailable.")
        return

    try:
        _ai_client = genai.Client(api_key=GOOGLE_API_KEY) # Inisialisasi client tetap sama
        _logger.info("Google AI client initialized.")

        # Get GenerativeModel objects using client.get_model()
        try:
            # Menggunakan _ai_client.get_model(model_name=...)
            _flash_text_model = _ai_client.get_model(model_name=_flash_text_model_name)
            _logger.info(f"Got generative model: {_flash_text_model_name}")
        except Exception as e:
            _logger.error(f"Failed to get generative model '{_flash_text_model_name}': {e}", exc_info=True)
            _flash_text_model = None

        # Cek apakah model image generation memang berbeda dan diperlukan
        # Jika sama dengan text model untuk multimodal, tidak perlu instance terpisah kecuali konfigurasinya beda.
        # Jika ini untuk GENERASI gambar murni (bukan analisis), pastikan nama modelnya tepat.
        # Jika _flash_image_gen_model_name sama dengan _flash_text_model_name, Anda bisa re-use objek modelnya
        # atau jika API call-nya berbeda, tetap buat objek terpisah.
        if _flash_image_gen_model_name == _flash_text_model_name and _flash_text_model is not None:
            _flash_image_gen_model = _flash_text_model # Re-use if same model and config for image tasks
            _logger.info(f"Re-using model '{_flash_image_gen_model_name}' for image generation tasks.")
        elif _flash_image_gen_model_name: # Hanya coba jika nama modelnya ada
            try:
                _flash_image_gen_model = _ai_client.get_model(model_name=_flash_image_gen_model_name)
                _logger.info(f"Got generative model: {_flash_image_gen_model_name}")
            except Exception as e:
                _logger.error(f"Failed to get generative model '{_flash_image_gen_model_name}': {e}", exc_info=True)
                _flash_image_gen_model = None
        else:
            _flash_image_gen_model = None # Jika nama model tidak diset

        if _flash_text_model or _flash_image_gen_model:
             _logger.info("At least one Gemini generative model object obtained successfully.")
        else:
             _logger.error("All Gemini generative model objects failed to obtain. AI features might be unavailable or limited.")

    except Exception as e:
        _logger.error(f"An unexpected error occurred during Google AI client initialization: {e}", exc_info=True)
        _ai_client = None
        _flash_text_model = None
        _flash_image_gen_model = None


# HAPUS ATAU KOMENTARI BARIS INI:
# initialize_gemini() # Panggilan di level modul tidak diperlukan lagi


class AICog(commands.Cog):
    """Cog for AI interaction features using on_message listener and slash commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Store the initialized models
        self.flash_text_model = _flash_text_model
        self.flash_image_gen_model = _flash_image_gen_model
        _logger.info("AICog instance created.")

    # ... (sisa kode AICog tetap sama, pastikan method generate_image_slash menggunakan self.flash_image_gen_model) ...
    # Pastikan di dalam generate_image_slash:
    # model = self.flash_image_gen_model (sudah benar)
    # Dan pastikan model tersebut adalah model yang mendukung image generation.

    # ... (sisa kode Cog, termasuk on_message dan generate_image_slash) ...

    # --- Image Generation Command ---
    @app_commands.command(name='generate_image', description='Generates an image based on a text prompt using AI.')
    @app_commands.describe(prompt='Describe the image you want to generate.')
    @app_commands.guild_only()
    async def generate_image_slash(self, interaction: discord.Interaction, prompt: str):
        _logger.info(f"Received /generate_image command from {interaction.user.id} with prompt: '{prompt}' in guild {interaction.guild_id}.")

        config = database.get_server_config(interaction.guild_id)
        ai_channel_id = config.get('ai_channel_id')

        if ai_channel_id is None or interaction.channel_id != ai_channel_id:
            ai_channel = self.bot.get_channel(ai_channel_id) if ai_channel_id else None
            channel_mention = ai_channel.mention if ai_channel else '`/config ai_channel` untuk mengaturnya'
            await interaction.response.send_message(
                f"Command ini hanya bisa digunakan di channel AI yang sudah ditentukan. Silakan gunakan {channel_mention}.",
                ephemeral=True
            )
            _logger.warning(f"/generate_image used outside AI channel {ai_channel_id} by user {interaction.user.id} in channel {interaction.channel_id}.")
            return

        # Gunakan model yang sudah diinisialisasi di __init__
        model_to_use = self.flash_image_gen_model # atau self.flash_text_model jika itu juga bisa generate gambar
        
        if model_to_use is None:
            _logger.warning(f"Skipping generate_image in guild {interaction.guild.id}: Image generation model not available.")
            await interaction.response.send_message("Layanan AI untuk generate gambar tidak tersedia. Model AI untuk generate gambar gagal diinisialisasi atau tidak tersedia.", ephemeral=True)
            return

        if not hasattr(model_to_use, 'generate_content'):
            _logger.error(f"Model object for image generation ('{model_to_use.model_name if hasattr(model_to_use, 'model_name') else 'Unknown Model'}') has no 'generate_content' method.")
            await interaction.response.send_message("Terjadi error internal: Model AI gambar tidak dapat memproses permintaan.", ephemeral=True)
            return

        if not prompt.strip():
            await interaction.response.send_message("Mohon berikan deskripsi untuk gambar yang ingin Anda buat.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)

        try:
            _logger.info(f"Calling image generation model for prompt: '{prompt}'.")
            
            # Penting: Untuk image generation murni, beberapa model mungkin mengharapkan prompt khusus
            # atau konfigurasi berbeda. 'gemini-1.5-flash' adalah model multimodal.
            # Jika Anda ingin *membuat* gambar dari teks, pastikan modelnya mendukung itu.
            # Contoh ini mengasumsikan model yang dipilih bisa generate gambar dari teks.
            response = await asyncio.to_thread(
                model_to_use.generate_content,
                prompt, # Input adalah prompt teks
                # generation_config dan safety_settings mungkin diperlukan atau bisa disesuaikan
                # generation_config=types.GenerationConfig(candidate_count=1), # Contoh
                # safety_settings=[...] # Contoh
            )
            _logger.info(f"Received response from Gemini API for image generation.")

            # --- Parsing respons untuk gambar ---
            # Ekspektasi: respons akan berisi data gambar jika berhasil.
            # Struktur respons untuk image generation bisa berbeda dari text generation.
            # Periksa dokumentasi model spesifik yang Anda gunakan.
            # Umumnya, bagian gambar ada di response.parts atau response.candidates[0].content.parts
            # yang memiliki mime_type 'image/png' atau 'image/jpeg'.

            image_parts = []
            if hasattr(response, 'parts'): # Jika respons langsung memiliki parts
                image_parts = [part for part in response.parts if part.mime_type and part.mime_type.startswith("image/")]
            elif hasattr(response, 'candidates') and response.candidates:
                 candidate = response.candidates[0]
                 if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                     image_parts = [part for part in candidate.content.parts if hasattr(part, 'mime_type') and part.mime_type.startswith("image/")]
            
            if not image_parts:
                _logger.warning(f"Image generation did not return any image parts. Response: {response}")
                # Cek apakah ada teks error atau feedback dari model
                response_text = ""
                if hasattr(response, 'text'): response_text = response.text
                elif hasattr(response, 'candidates') and response.candidates and hasattr(response.candidates[0], 'text'):
                    response_text = response.candidates[0].text

                if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason != types.content.BlockReason.BLOCK_REASON_UNSPECIFIED:
                    block_reason = types.content.BlockReason(response.prompt_feedback.block_reason).name
                    _logger.warning(f"Generate Image prompt blocked by Gemini safety filter. Reason: {block_reason}.")
                    await interaction.followup.send(f"Maaf, permintaan generate gambar ini diblokir oleh filter keamanan AI ({block_reason}).")
                else:
                    fallback_message = "Gagal menghasilkan gambar. AI tidak memberikan output gambar."
                    if response_text: fallback_message += f" Pesan dari AI: {response_text}"
                    await interaction.followup.send(fallback_message)
                return

            # Kirim gambar pertama yang ditemukan
            # Anda bisa loop jika model bisa menghasilkan multiple images
            first_image_part = image_parts[0]
            image_bytes = first_image_part.data # inline_data.data adalah bytes
            
            # Tentukan ekstensi file dari mime_type
            mime_type = first_image_part.mime_type
            extension = mime_type.split('/')[-1] if '/' in mime_type else 'png'
            file_name = f"generated_image.{extension}"

            discord_file = discord.File(io.BytesIO(image_bytes), filename=file_name)
            
            embed = discord.Embed(title="Gambar Dihasilkan!", color=discord.Color.blue())
            embed.set_image(url=f"attachment://{file_name}") # Referensi ke file yang diattach
            prompt_text_footer = prompt[:100] + ('...' if len(prompt) > 100 else '')
            embed.set_footer(text=f"Prompt: \"{prompt_text_footer}\"")
            
            await interaction.followup.send(embed=embed, file=discord_file)
            _logger.info(f"Sent generated image for prompt: '{prompt}'")

        except types.BlockedPromptException as e:
            _logger.warning(f"Generate Image prompt blocked by Gemini API: {e}")
            await interaction.followup.send("Maaf, permintaan generate gambar ini melanggar kebijakan penggunaan AI dan tidak bisa diproses.")
        except types.StopCandidateException as e:
            _logger.warning(f"Gemini response stopped prematurely during image generation: {e}")
            await interaction.followup.send("Maaf, proses generate gambar terhenti di tengah jalan.")
        except GoogleAPIError as e:
            _logger.error(f"Gemini API Error during generate_image: {e}", exc_info=True)
            await interaction.followup.send(f"Terjadi error pada API AI saat generate gambar: {e}")
        except Exception as e:
            _logger.error(f"An unexpected error occurred during image generation: {e}", exc_info=True)
            await interaction.followup.send(f"Terjadi error tak terduga saat mencoba generate gambar: {e}")
    
    # ... (ai_command_error tetap sama) ...

async def setup(bot: commands.Bot):
    """Sets up the AICog."""
    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY environment variable not found. AICog will not be loaded.")
        return

    initialize_gemini() # Panggil sekali di sini

    if _flash_text_model is None and _flash_image_gen_model is None: # Periksa model yang sudah diinisialisasi
        _logger.error("All Gemini models failed to initialize. AICog will not be loaded or AI features will be unavailable.")
        # Jika Anda ingin cog tetap load tapi fitur AI mati, jangan return di sini.
        # Jika ingin cog tidak load sama sekali jika model gagal, maka return di sini.
        # Untuk kasus ini, kita biarkan cog load, tapi command akan gagal jika modelnya None.
        # return # Opsional: jika ingin cog tidak load sama sekali jika model gagal

    cog_instance = AICog(bot)
    await bot.add_cog(cog_instance)
    _logger.info("AICog loaded.") # Ini akan tetap tercetak jika return di atas dikomentari

    cog_instance.generate_image_slash.error(cog_instance.ai_command_error)
    # Tidak ada error handler khusus untuk on_message, error ditangani di dalam on_message