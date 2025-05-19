# cogs/ai_cog.py

import discord
import os
import google.genai as genai # Menggunakan google-genai SDK
from google.genai import types as genai_types # Alias untuk menghindari konflik nama
from google.api_core.exceptions import GoogleAPIError # Error umum Google API
import database
from discord.ext import commands
from discord import app_commands
import logging
from PIL import Image
import io
import asyncio
import re

# Konfigurasi logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

# --- Konstanta Model ---
GEMINI_TEXT_MODEL_NAME = "models/gemini-2.0-flash"  # Pastikan menyertakan prefix 'models/' jika diperlukan oleh SDK
GEMINI_IMAGE_GEN_MODEL_NAME = "models/gemini-2.0-flash-preview-image-generation" # Pastikan menyertakan prefix 'models/'

# --- Kunci API ---
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# --- Inisialisasi Klien dan Model Google AI ---
_gemini_client: genai.Client | None = None
_gemini_text_model: genai_types.Model | None = None # Seharusnya genai.models.Model, namun genai_types.Model juga ada
_gemini_image_gen_model: genai_types.Model | None = None # genai.models.Model

def initialize_gemini_models():
    """
    Menginisialisasi klien Google AI dan mengambil objek model Gemini.
    Fungsi ini akan dipanggil saat cog dimuat.
    """
    global _gemini_client, _gemini_text_model, _gemini_image_gen_model

    if GOOGLE_API_KEY is None:
        _logger.error("Variabel lingkungan GOOGLE_API_KEY tidak diatur. Fitur AI tidak akan tersedia.")
        return

    try:
        _gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
        _logger.info("Klien Google GenAI berhasil diinisialisasi.")

        # Dapatkan model untuk teks/multimodal umum
        try:
            # --- PERBAIKAN DI SINI ---
            _gemini_text_model = _gemini_client.models.get(model=GEMINI_TEXT_MODEL_NAME)
            # --- AKHIR PERBAIKAN ---
            _logger.info(f"Objek model berhasil didapatkan: {GEMINI_TEXT_MODEL_NAME}")
        except Exception as e:
            _logger.error(f"Gagal mendapatkan objek model '{GEMINI_TEXT_MODEL_NAME}': {e}", exc_info=True)
            _gemini_text_model = None

        # Dapatkan model untuk generasi gambar
        try:
            # --- PERBAIKAN DI SINI ---
            _gemini_image_gen_model = _gemini_client.models.get(model=GEMINI_IMAGE_GEN_MODEL_NAME)
            # --- AKHIR PERBAIKAN ---
            _logger.info(f"Objek model berhasil didapatkan: {GEMINI_IMAGE_GEN_MODEL_NAME}")
        except Exception as e:
            _logger.error(f"Gagal mendapatkan objek model '{GEMINI_IMAGE_GEN_MODEL_NAME}': {e}", exc_info=True)
            _gemini_image_gen_model = None

        if not _gemini_text_model and not _gemini_image_gen_model:
            _logger.error("Semua model Gemini gagal diinisialisasi. Fitur AI tidak akan tersedia.")
        elif not _gemini_text_model:
            _logger.warning(f"Model teks/multimodal ({GEMINI_TEXT_MODEL_NAME}) gagal diinisialisasi. Fitur terkait tidak akan berfungsi.")
        elif not _gemini_image_gen_model:
            _logger.warning(f"Model generasi gambar ({GEMINI_IMAGE_GEN_MODEL_NAME}) gagal diinisialisasi. Fitur terkait tidak akan berfungsi.")
        else:
            _logger.info("Setidaknya satu model Gemini berhasil diinisialisasi.")

    except Exception as e:
        _logger.error(f"Terjadi error tak terduga saat inisialisasi klien Google GenAI: {e}", exc_info=True)
        _gemini_client = None
        _gemini_text_model = None
        _gemini_image_gen_model = None

# Panggil inisialisasi saat modul ini diimpor
initialize_gemini_models()


class AICog(commands.Cog):
    """Cog untuk fitur interaksi AI menggunakan Gemini dari Google GenAI."""

    def __init__(self, bot: commands.Bot):
        """Inisialisasi AICog."""
        self.bot = bot
        self.text_model = _gemini_text_model
        self.image_gen_model = _gemini_image_gen_model
        _logger.info("AICog instance telah dibuat.")

    async def _process_and_send_text_response(self, message: discord.Message, response: genai_types.GenerateContentResponse, context: str):
        """
        Memproses respons teks dari Gemini dan mengirimkannya ke channel.
        Konteks digunakan untuk logging.
        """
        response_text = ""
        # Coba akses response.text secara langsung dulu, ini sering ada di respons sederhana
        if hasattr(response, 'text') and response.text:
            response_text = response.text
        # Jika tidak ada, iterasi candidates dan parts
        elif hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                # Gabungkan semua bagian teks
                text_parts_list = [part.text for part in candidate.content.parts if hasattr(part, 'text') and part.text]
                response_text = "".join(text_parts_list)
            # Fallback jika struktur sedikit berbeda tapi ada candidate.text
            elif hasattr(candidate, 'text') and candidate.text:
                response_text = candidate.text

        if not response_text.strip():
            # Cek feedback jika respons kosong karena diblokir
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                # Akses block_reason melalui prompt_feedback
                block_reason_value = response.prompt_feedback.block_reason
                # Bandingkan dengan nilai enum BlockReason. HarmBlockThreshold adalah untuk setting.
                if block_reason_value != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED: # Menggunakan enum yang benar dari types
                    try:
                        block_reason_name = genai_types.BlockedReason(block_reason_value).name
                    except ValueError:
                        block_reason_name = f"UNKNOWN_REASON_VALUE_{block_reason_value}"
                    _logger.warning(f"({context}) Prompt diblokir oleh filter keamanan Gemini. Alasan: {block_reason_name}. Feedback: {response.prompt_feedback}")
                    await message.reply(f"Maaf, permintaan Anda diblokir oleh filter keamanan AI ({block_reason_name}).")
                    return
            _logger.warning(f"({context}) Gemini mengembalikan respons kosong. Full response: {response}")
            await message.reply("Maaf, saya tidak bisa memberikan respons saat ini.")
            return

        # Kirim respons dalam potongan jika terlalu panjang
        max_length = 1990
        if len(response_text) > max_length:
            _logger.info(f"({context}) Respons teks terlalu panjang ({len(response_text)} chars), membaginya menjadi beberapa pesan.")
            chunks = [response_text[i:i + max_length] for i in range(0, len(response_text), max_length)]
            for i, chunk in enumerate(chunks):
                header = f"(Bagian {i + 1}/{len(chunks)}):\n" if len(chunks) > 1 else ""
                try:
                    await message.reply(header + chunk)
                except discord.errors.HTTPException as e:
                    _logger.error(f"({context}) Gagal mengirim potongan pesan: {e}", exc_info=True)
                    try:
                        await message.channel.send(f"Gagal mengirim bagian {i+1} respons: {e}")
                    except Exception as send_err:
                        _logger.error(f"({context}) Gagal mengirim pesan error ke channel: {send_err}", exc_info=True)
                except Exception as e:
                    _logger.error(f"({context}) Error tak terduga saat mengirim potongan pesan: {e}", exc_info=True)
                await asyncio.sleep(0.5)
        else:
            await message.reply(response_text)
        _logger.info(f"({context}) Respons teks berhasil dikirim.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Memproses pesan untuk interaksi AI di channel khusus atau saat bot dimention."""
        if message.author.bot or message.guild is None:
            return

        if self.text_model is None:
            return

        config = database.get_server_config(message.guild.id)
        ai_channel_id = config.get('ai_channel_id')
        bot_user = self.bot.user
        is_mentioned = bot_user and bot_user.mention in message.content

        in_ai_channel = ai_channel_id is not None and message.channel.id == ai_channel_id
        # Cek apakah pesan HANYA mention bot, tanpa teks atau lampiran lain yang relevan
        cleaned_content_for_mention_check = message.content.replace(bot_user.mention, '').strip()
        just_a_mention = is_mentioned and not cleaned_content_for_mention_check and not message.attachments


        context_log_prefix = ""

        # Skenario 1: Pesan di channel AI (dan bukan hanya mention)
        if in_ai_channel and not just_a_mention:
            context_log_prefix = "AI Channel"
            _logger.info(f"({context_log_prefix}) Memproses pesan dari {message.author.name} di guild {message.guild.name}, channel {message.channel.name}.")
            
            async with message.channel.typing():
                try:
                    content_parts = []
                    image_attachments = [att for att in message.attachments if 'image' in att.content_type]
                    if image_attachments:
                        if len(image_attachments) > 4: # Batas wajar untuk API
                            await message.reply("Mohon berikan maksimal 4 gambar dalam satu waktu.")
                            return
                        for attachment in image_attachments:
                            try:
                                image_bytes = await attachment.read()
                                pil_image = Image.open(io.BytesIO(image_bytes))
                                content_parts.append(pil_image)
                                _logger.info(f"({context_log_prefix}) Menambahkan lampiran gambar: {attachment.filename}")
                            except Exception as img_e:
                                _logger.error(f"({context_log_prefix}) Gagal memproses lampiran gambar {attachment.filename}: {img_e}", exc_info=True)
                                await message.channel.send(f"Peringatan: Tidak dapat memproses gambar '{attachment.filename}'.")
                                # Jika hanya gambar ini dan gagal, jangan lanjutkan jika tidak ada teks
                                if len(image_attachments) == 1 and not message.content.strip().replace(bot_user.mention if bot_user else "", '', 1).strip():
                                    await message.reply("Tidak dapat memproses gambar yang Anda kirim.")
                                    return
                    
                    text_content = message.content
                    if bot_user and bot_user.mention in text_content: # Hapus mention jika ada di mana saja
                        text_content = text_content.replace(bot_user.mention, '').strip()
                    
                    if text_content:
                        content_parts.append(text_content)

                    if not content_parts:
                        _logger.debug(f"({context_log_prefix}) Pesan tidak memiliki konten yang dapat diproses.")
                        # Jika pesan awalnya ada mention tapi setelah dihapus jadi kosong
                        if is_mentioned and not text_content and not image_attachments:
                             await message.reply("Halo! Ada yang bisa saya bantu?")
                        return

                    api_response = await asyncio.to_thread(
                        self.text_model.generate_content,
                        contents=content_parts
                    )
                    _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini.")
                    await self._process_and_send_text_response(message, api_response, context_log_prefix)

                except (genai_types.BlockedPromptError, genai_types.StopCandidateError) as model_e: # Sesuaikan dengan nama error yang benar
                    _logger.warning(f"({context_log_prefix}) Error model Gemini: {model_e}")
                    await message.reply(f"Maaf, terjadi masalah dengan model AI: {model_e}")
                except GoogleAPIError as api_e:
                    _logger.error(f"({context_log_prefix}) Error API Google: {api_e}", exc_info=True)
                    await message.reply(f"Terjadi error pada API AI: {api_e}")
                except Exception as e:
                    _logger.error(f"({context_log_prefix}) Error tak terduga saat memproses permintaan AI: {e}", exc_info=True)
                    await message.reply("Terjadi error tak terduga saat memproses permintaan AI.")
            return

        # Skenario 2: Bot dimention (di luar channel AI, atau hanya mention di channel AI)
        if is_mentioned and (not in_ai_channel or just_a_mention):
            context_log_prefix = "Bot Mention"
            _logger.info(f"({context_log_prefix}) Memproses mention dari {message.author.name} di guild {message.guild.name}, channel {message.channel.name}.")

            async with message.channel.typing():
                try:
                    text_content_for_mention = message.content.replace(bot_user.mention, '', 1).strip()
                    if not text_content_for_mention:
                        await message.reply("Halo! Ada yang bisa saya bantu? (Sebut nama saya dengan pertanyaan Anda)")
                        return

                    api_response = await asyncio.to_thread(
                        self.text_model.generate_content,
                        contents=text_content_for_mention # Hanya teks
                    )
                    _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini untuk mention.")
                    await self._process_and_send_text_response(message, api_response, context_log_prefix)
                
                except (genai_types.BlockedPromptError, genai_types.StopCandidateError) as model_e:
                    _logger.warning(f"({context_log_prefix}) Error model Gemini: {model_e}")
                    await message.reply(f"Maaf, terjadi masalah dengan model AI: {model_e}")
                except GoogleAPIError as api_e:
                    _logger.error(f"({context_log_prefix}) Error API Google: {api_e}", exc_info=True)
                    await message.reply(f"Terjadi error pada API AI: {api_e}")
                except Exception as e:
                    _logger.error(f"({context_log_prefix}) Error tak terduga saat memproses mention: {e}", exc_info=True)
                    await message.reply("Terjadi error tak terduga saat memproses permintaan AI.")
            return

    @app_commands.command(name='generate_image', description='Membuat gambar berdasarkan deskripsi teks menggunakan AI.')
    @app_commands.describe(prompt='Deskripsikan gambar yang ingin Anda buat.')
    @app_commands.guild_only()
    async def generate_image_slash(self, interaction: discord.Interaction, prompt: str):
        """Generates an image based on a text prompt using the Gemini image generation model."""
        _logger.info(f"Menerima command /generate_image dari {interaction.user.name} dengan prompt: '{prompt}' di guild {interaction.guild.name}.")

        if self.image_gen_model is None:
            _logger.warning(f"Command /generate_image dilewati di guild {interaction.guild.name}: Model generasi gambar tidak tersedia.")
            await interaction.response.send_message("Layanan AI untuk generasi gambar tidak tersedia saat ini.", ephemeral=True)
            return

        if not prompt.strip():
            await interaction.response.send_message("Mohon berikan deskripsi untuk gambar yang ingin Anda buat.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=False)

        try:
            _logger.info(f"Memanggil model generasi gambar Gemini dengan prompt: '{prompt}'.")
            
            generation_config = genai_types.GenerateContentConfig(
                response_modalities=[genai_types.Modality.TEXT, genai_types.Modality.IMAGE] # TEXT dan IMAGE
            )

            # Untuk text-to-image, 'contents' adalah prompt string
            api_response = await asyncio.to_thread(
                self.image_gen_model.generate_content,
                contents=prompt, 
                generation_config=generation_config
            )
            _logger.info("Menerima respons dari API generasi gambar Gemini.")

            generated_text_parts = []
            generated_image_bytes = None
            
            if hasattr(api_response, 'candidates') and api_response.candidates:
                candidate = api_response.candidates[0]
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text:
                            generated_text_parts.append(part.text)
                        elif hasattr(part, 'inline_data') and part.inline_data and hasattr(part.inline_data, 'mime_type') and part.inline_data.mime_type.startswith('image/'):
                            generated_image_bytes = part.inline_data.data # ini adalah bytes
                            _logger.info(f"Menerima inline_data gambar dari Gemini (MIME: {part.inline_data.mime_type}).")
                            # Ambil gambar pertama yang valid
                            break # Asumsi kita hanya butuh satu gambar utama dari prompt ini
            
            final_text_response = "\n".join(generated_text_parts).strip()

            if generated_image_bytes:
                # Tentukan ekstensi file dari mime_type jika memungkinkan
                mime_type = "image/png" # default
                if hasattr(api_response.candidates[0].content.parts[0], 'inline_data') and \
                   hasattr(api_response.candidates[0].content.parts[0].inline_data, 'mime_type'):
                    # Cari part gambar untuk mendapatkan mime_type yang benar
                    for part in api_response.candidates[0].content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data and part.inline_data.mime_type.startswith('image/'):
                            mime_type = part.inline_data.mime_type
                            break
                
                extension = mime_type.split('/')[-1] if '/' in mime_type else 'png'
                filename = f"generated_image.{extension}"

                image_file = discord.File(io.BytesIO(generated_image_bytes), filename=filename)
                
                embed_description = f"**Prompt:** \"{discord.utils.escape_markdown(prompt[:1000])}{'...' if len(prompt) > 1000 else ''}\""
                if final_text_response:
                    embed_description += f"\n\n**Deskripsi Tambahan dari AI:**\n{final_text_response[:1020]}{'...' if len(final_text_response) > 1020 else ''}"

                embed = discord.Embed(
                    title="Gambar Berhasil Dihasilkan!",
                    description=embed_description,
                    color=discord.Color.random() # Warna acak untuk embed
                )
                embed.set_image(url=f"attachment://{filename}")
                embed.set_footer(text=f"Diminta oleh: {interaction.user.display_name}")
                
                await interaction.followup.send(embed=embed, file=image_file)
                _logger.info(f"Gambar dan teks pendamping (jika ada) berhasil dikirim untuk prompt: {prompt}")
            elif final_text_response:
                _logger.warning(f"Gemini menghasilkan teks tetapi tidak ada data gambar untuk prompt: {prompt}")
                await interaction.followup.send(f"Berikut respons dari AI untuk prompt Anda (tidak ada gambar dihasilkan):\n\n{final_text_response}")
            else:
                # Cek prompt_feedback jika tidak ada output sama sekali
                if hasattr(api_response, 'prompt_feedback') and api_response.prompt_feedback:
                    block_reason_value = api_response.prompt_feedback.block_reason
                    if block_reason_value != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                        try:
                            block_reason_name = genai_types.BlockedReason(block_reason_value).name
                        except ValueError:
                            block_reason_name = f"UNKNOWN_REASON_VALUE_{block_reason_value}"
                        _logger.warning(f"Prompt generasi gambar diblokir. Alasan: {block_reason_name}. Prompt: '{prompt}'. Feedback: {api_response.prompt_feedback}")
                        await interaction.followup.send(f"Maaf, permintaan generasi gambar Anda diblokir oleh filter keamanan AI ({block_reason_name}).")
                        return
                _logger.warning(f"Gemini mengembalikan respons kosong untuk generasi gambar. Prompt: '{prompt}'. Full response: {api_response}")
                await interaction.followup.send("Maaf, gagal menghasilkan gambar atau teks. AI memberikan respons yang tidak terduga atau kosong.")

        except (genai_types.BlockedPromptError, genai_types.StopCandidateError) as model_e: # Sesuaikan nama error
            _logger.warning(f"Error model Gemini saat generate gambar: {model_e}. Prompt: '{prompt}'")
            await interaction.followup.send(f"Maaf, terjadi masalah dengan model AI: {model_e}", ephemeral=True)
        except GoogleAPIError as api_e:
            _logger.error(f"Error API Google saat generate gambar: {api_e}. Prompt: '{prompt}'", exc_info=True)
            await interaction.followup.send(f"Terjadi error pada API AI saat membuat gambar: {api_e}", ephemeral=True)
        except Exception as e:
            _logger.error(f"Error tak terduga saat generate gambar: {e}. Prompt: '{prompt}'", exc_info=True)
            await interaction.followup.send("Terjadi error tak terduga saat mencoba membuat gambar.", ephemeral=True)


    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler umum untuk slash commands di dalam AICog."""
        original_error = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else "Unknown AI Command"
        
        _logger.error(
            f"Error pada command AI '{command_name}' oleh {interaction.user.name} ({interaction.user.id}): {original_error}",
            exc_info=True # Selalu sertakan traceback untuk error yang ditangani di sini
        )

        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        error_message = "Terjadi kesalahan internal saat memproses perintah AI Anda." # Pesan default

        if isinstance(original_error, app_commands.CheckFailure):
            error_message = f"Anda tidak memenuhi syarat untuk menggunakan perintah ini: {original_error}"
        elif isinstance(original_error, genai_types.BlockedPromptError):
            error_message = f"Permintaan Anda ke AI diblokir karena melanggar kebijakan konten: {original_error}"
        elif isinstance(original_error, genai_types.StopCandidateError):
             error_message = f"Pembuatan respons AI dihentikan lebih awal: {original_error}"
        elif isinstance(original_error, GoogleAPIError):
            error_message = f"Terjadi error pada layanan Google AI: {original_error}"
        elif isinstance(original_error, app_commands.CommandInvokeError) and isinstance(original_error.original, GoogleAPIError):
            error_message = f"Terjadi error pada layanan Google AI (invoke): {original_error.original}"
        elif isinstance(original_error, discord.errors.HTTPException):
            error_message = f"Terjadi error HTTP saat berkomunikasi dengan Discord: {original_error.status} - {original_error.text}"
        
        try:
            await send_method(error_message, ephemeral=True)
        except Exception as e:
            _logger.error(f"Gagal mengirim pesan error untuk command '{command_name}': {e}", exc_info=True)


async def setup(bot: commands.Bot):
    """Setup function untuk memuat AICog."""
    if GOOGLE_API_KEY is None:
        _logger.error("Variabel lingkungan GOOGLE_API_KEY tidak ditemukan. AICog tidak akan dimuat.")
        return

    if not _gemini_client: # Jika klien gagal diinisialisasi
        _logger.error("Klien Google GenAI gagal diinisialisasi. AICog tidak akan dimuat.")
        return
        
    if _gemini_text_model is None and _gemini_image_gen_model is None:
        _logger.error("Tidak ada model Gemini yang berhasil diinisialisasi. AICog tidak akan dimuat.")
        return
    
    cog_instance = AICog(bot)
    await bot.add_cog(cog_instance)
    _logger.info("AICog berhasil dimuat.")