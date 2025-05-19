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
import re # Untuk parsing URL fallback (meskipun kurang utama untuk Gemini image gen)

# Konfigurasi logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

# --- Konstanta Model ---
# Nama model sesuai permintaan pengguna dan praktik umum
GEMINI_TEXT_MODEL_NAME = "gemini-2.0-flash"
GEMINI_IMAGE_GEN_MODEL_NAME = "gemini-2.0-flash-preview-image-generation"

# --- Kunci API ---
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# --- Inisialisasi Klien dan Model Google AI ---
_gemini_client: genai.Client | None = None
_gemini_text_model: genai_types.Model | None = None
_gemini_image_gen_model: genai_types.Model | None = None

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
            _gemini_text_model = _gemini_client.models.get(GEMINI_TEXT_MODEL_NAME)
            _logger.info(f"Objek model berhasil didapatkan: {GEMINI_TEXT_MODEL_NAME}")
        except Exception as e:
            _logger.error(f"Gagal mendapatkan objek model '{GEMINI_TEXT_MODEL_NAME}': {e}", exc_info=True)
            _gemini_text_model = None

        # Dapatkan model untuk generasi gambar
        try:
            _gemini_image_gen_model = _gemini_client.models.get(GEMINI_IMAGE_GEN_MODEL_NAME)
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
        if hasattr(response, 'text') and response.text: # Cara termudah mendapatkan teks jika model langsung memberikannya
            response_text = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                response_text = "".join(part.text for part in candidate.content.parts if hasattr(part, 'text') and part.text)

        if not response_text.strip():
            # Cek feedback jika respons kosong karena diblokir
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                if response.prompt_feedback.block_reason != genai_types.HarmBlockThreshold.HARM_BLOCK_THRESHOLD_UNSPECIFIED: # Menggunakan konstanta enum yang benar
                    block_reason_name = genai_types.BlockedReason(response.prompt_feedback.block_reason).name
                    _logger.warning(f"({context}) Prompt diblokir oleh filter keamanan Gemini. Alasan: {block_reason_name}. Feedback: {response.prompt_feedback}")
                    await message.reply(f"Maaf, permintaan Anda diblokir oleh filter keamanan AI ({block_reason_name}).")
                    return
            _logger.warning(f"({context}) Gemini mengembalikan respons kosong. Full response: {response}")
            await message.reply("Maaf, saya tidak bisa memberikan respons saat ini.")
            return

        # Kirim respons dalam potongan jika terlalu panjang
        max_length = 1990 # Sisakan ruang untuk header/footer
        if len(response_text) > max_length:
            _logger.info(f"({context}) Respons teks terlalu panjang, membaginya menjadi beberapa pesan.")
            chunks = [response_text[i:i + max_length] for i in range(0, len(response_text), max_length)]
            for i, chunk in enumerate(chunks):
                header = f"(Bagian {i + 1}/{len(chunks)}):\n" if len(chunks) > 1 else ""
                try:
                    await message.reply(header + chunk)
                except discord.errors.HTTPException as e:
                    _logger.error(f"({context}) Gagal mengirim potongan pesan: {e}")
                    await message.channel.send(f"Gagal mengirim bagian {i+1} respons: {e}") # Kirim ke channel jika reply gagal
                await asyncio.sleep(0.5) # Jeda antar pesan
        else:
            await message.reply(response_text)
        _logger.info(f"({context}) Respons teks berhasil dikirim.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Memproses pesan untuk interaksi AI di channel khusus atau saat bot dimention."""
        if message.author.bot or message.guild is None:
            return

        if self.text_model is None: # Model teks adalah prasyarat untuk on_message
            # _logger.debug("Model teks Gemini tidak tersedia, on_message dilewati.") # Bisa di-uncomment untuk debugging
            return

        config = database.get_server_config(message.guild.id)
        ai_channel_id = config.get('ai_channel_id')
        bot_user = self.bot.user
        is_mentioned = bot_user and bot_user.mention in message.content

        in_ai_channel = ai_channel_id is not None and message.channel.id == ai_channel_id
        just_a_mention = is_mentioned and message.content.strip() == bot_user.mention

        context_log_prefix = "" # Untuk logging yang lebih baik

        # Skenario 1: Pesan di channel AI (dan bukan hanya mention)
        if in_ai_channel and not just_a_mention:
            context_log_prefix = "AI Channel"
            _logger.info(f"({context_log_prefix}) Memproses pesan dari {message.author.name} di guild {message.guild.name}, channel {message.channel.name}.")
            
            async with message.channel.typing():
                try:
                    content_parts = []
                    # Proses lampiran gambar
                    image_attachments = [att for att in message.attachments if 'image' in att.content_type]
                    if image_attachments:
                        if len(image_attachments) > 4:
                            await message.reply("Mohon berikan maksimal 4 gambar dalam satu waktu.")
                            return
                        for attachment in image_attachments:
                            try:
                                image_bytes = await attachment.read()
                                pil_image = Image.open(io.BytesIO(image_bytes))
                                content_parts.append(pil_image) # Tambahkan objek PIL Image
                                _logger.info(f"({context_log_prefix}) Menambahkan lampiran gambar: {attachment.filename}")
                            except Exception as img_e:
                                _logger.error(f"({context_log_prefix}) Gagal memproses lampiran gambar {attachment.filename}: {img_e}", exc_info=True)
                                await message.channel.send(f"Peringatan: Tidak dapat memproses gambar '{attachment.filename}'.")
                                if len(image_attachments) == 1 and not message.content.strip().replace(bot_user.mention, '', 1).strip():
                                    await message.reply("Tidak dapat memproses gambar yang Anda kirim.")
                                    return
                    
                    # Proses konten teks (hapus mention jika ada)
                    text_content = message.content
                    if is_mentioned: # Hapus mention jika ada di mana saja dalam teks untuk AI channel
                        text_content = text_content.replace(bot_user.mention, '').strip()
                    
                    if text_content:
                        content_parts.append(text_content)

                    if not content_parts:
                        _logger.debug(f"({context_log_prefix}) Pesan tidak memiliki konten yang dapat diproses (setelah filter).")
                        # Bisa ditambahkan respons "Halo, ada yang bisa dibantu?" jika hanya mention tanpa teks lain
                        if is_mentioned and not text_content and not image_attachments:
                             await message.reply("Halo! Ada yang bisa saya bantu?")
                        return

                    # Panggil API Gemini
                    api_response = await asyncio.to_thread(
                        self.text_model.generate_content,
                        contents=content_parts # Kirim list of parts (text dan/atau PIL.Image)
                    )
                    _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini.")
                    await self._process_and_send_text_response(message, api_response, context_log_prefix)

                except (genai_types.BlockedPromptError, genai_types.StopCandidateError) as model_e: # Menggunakan error dari google.genai.types
                    _logger.warning(f"({context_log_prefix}) Error model Gemini: {model_e}")
                    await message.reply(f"Maaf, terjadi masalah dengan model AI: {model_e}")
                except GoogleAPIError as api_e:
                    _logger.error(f"({context_log_prefix}) Error API Google: {api_e}", exc_info=True)
                    await message.reply(f"Terjadi error pada API AI: {api_e}")
                except Exception as e:
                    _logger.error(f"({context_log_prefix}) Error tak terduga saat memproses permintaan AI: {e}", exc_info=True)
                    await message.reply("Terjadi error tak terduga saat memproses permintaan AI.")
            return # Selesai memproses untuk AI channel

        # Skenario 2: Bot dimention (di luar channel AI, atau hanya mention di channel AI)
        if is_mentioned and (not in_ai_channel or just_a_mention):
            context_log_prefix = "Bot Mention"
            _logger.info(f"({context_log_prefix}) Memproses mention dari {message.author.name} di guild {message.guild.name}, channel {message.channel.name}.")

            async with message.channel.typing():
                try:
                    text_content = message.content.replace(bot_user.mention, '', 1).strip()
                    if not text_content: # Hanya mention, tidak ada teks tambahan
                        await message.reply("Halo! Ada yang bisa saya bantu? (Sebut nama saya dengan pertanyaan Anda)")
                        return

                    # Panggil API Gemini (hanya teks untuk mention sederhana)
                    api_response = await asyncio.to_thread(
                        self.text_model.generate_content,
                        contents=text_content # Hanya kirim teks
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
            return # Selesai memproses mention

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

        # Validasi channel (opsional, bisa dihilangkan jika ingin bisa di semua channel)
        config = database.get_server_config(interaction.guild_id)
        ai_channel_id = config.get('ai_channel_id')
        if ai_channel_id and interaction.channel_id != ai_channel_id:
            ai_channel = self.bot.get_channel(ai_channel_id)
            channel_mention = ai_channel.mention if ai_channel else f"channel AI yang ditentukan (ID: {ai_channel_id})"
            await interaction.response.send_message(
                f"Command ini sebaiknya digunakan di {channel_mention} untuk menjaga kerapian, namun saya akan tetap proses di sini.",
                ephemeral=True
            )
            # Tidak return, tetap proses tapi beri peringatan
        
        await interaction.response.defer(ephemeral=False)

        try:
            _logger.info(f"Memanggil model generasi gambar Gemini dengan prompt: '{prompt}'.")
            
            # Konfigurasi untuk meminta output gambar dan teks
            generation_config = genai_types.GenerationConfig(
                response_modalities=[genai_types.Modality.TEXT, genai_types.Modality.IMAGE] # Sesuai dokumentasi
            )

            api_response = await asyncio.to_thread(
                self.image_gen_model.generate_content,
                contents=prompt, # Untuk text-to-image, contents adalah prompt teks
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
                        elif hasattr(part, 'inline_data') and part.inline_data.mime_type.startswith('image/'):
                            generated_image_bytes = part.inline_data.data
                            _logger.info(f"Menerima inline_data gambar dari Gemini (MIME: {part.inline_data.mime_type}).")
                            # Asumsi hanya satu gambar yang relevan, ambil yang pertama
                            # Jika ingin menangani multiple image output, perlu loop/list di sini
                elif hasattr(candidate,'text') and candidate.text : # fallback jika struktur agak berbeda
                     generated_text_parts.append(candidate.text)

            final_text_response = "\n".join(generated_text_parts).strip()

            # Kirim respons
            if generated_image_bytes:
                image_file = discord.File(io.BytesIO(generated_image_bytes), filename="generated_image.png") # Ekstensi bisa disesuaikan dari mime_type jika perlu
                embed = discord.Embed(
                    title="Gambar Dihasilkan!",
                    description=f"Prompt: \"{discord.utils.escape_markdown(prompt[:1000])}{'...' if len(prompt) > 1000 else ''}\"",
                    color=discord.Color.blue()
                )
                if final_text_response:
                    embed.add_field(name="Deskripsi Tambahan dari AI:", value=final_text_response[:1020] + ('...' if len(final_text_response) > 1020 else ''), inline=False)
                
                embed.set_image(url=f"attachment://{image_file.filename}")
                await interaction.followup.send(embed=embed, file=image_file)
                _logger.info("Gambar dan teks pendamping (jika ada) berhasil dikirim.")
            elif final_text_response: # Hanya teks, tidak ada gambar
                _logger.warning("Gemini menghasilkan teks tetapi tidak ada data gambar.")
                await interaction.followup.send(f"Berikut respons dari AI untuk prompt Anda (tidak ada gambar dihasilkan):\n\n{final_text_response}")
            else: # Tidak ada teks maupun gambar
                # Cek feedback jika respons kosong karena diblokir
                if hasattr(api_response, 'prompt_feedback') and api_response.prompt_feedback:
                    if api_response.prompt_feedback.block_reason != genai_types.HarmBlockThreshold.HARM_BLOCK_THRESHOLD_UNSPECIFIED:
                        block_reason_name = genai_types.BlockedReason(api_response.prompt_feedback.block_reason).name
                        _logger.warning(f"Prompt generasi gambar diblokir oleh filter keamanan Gemini. Alasan: {block_reason_name}. Feedback: {api_response.prompt_feedback}")
                        await interaction.followup.send(f"Maaf, permintaan generasi gambar Anda diblokir oleh filter keamanan AI ({block_reason_name}).")
                        return
                _logger.warning(f"Gemini mengembalikan respons kosong untuk generasi gambar. Full response: {api_response}")
                await interaction.followup.send("Maaf, gagal menghasilkan gambar atau teks. AI memberikan respons kosong.")

        except (genai_types.BlockedPromptError, genai_types.StopCandidateError) as model_e:
            _logger.warning(f"Error model Gemini saat generate gambar: {model_e}")
            await interaction.followup.send(f"Maaf, terjadi masalah dengan model AI: {model_e}", ephemeral=True)
        except GoogleAPIError as api_e:
            _logger.error(f"Error API Google saat generate gambar: {api_e}", exc_info=True)
            await interaction.followup.send(f"Terjadi error pada API AI saat membuat gambar: {api_e}", ephemeral=True)
        except Exception as e:
            _logger.error(f"Error tak terduga saat generate gambar: {e}", exc_info=True)
            await interaction.followup.send("Terjadi error tak terduga saat mencoba membuat gambar.", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler untuk slash commands di dalam AICog."""
        original_error = getattr(error, 'original', error)
        _logger.error(
            f"Error pada AI command '{interaction.command.name if interaction.command else 'N/A'}' oleh {interaction.user.name}: {original_error}",
            exc_info=True
        )

        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message

        if isinstance(original_error, app_commands.CheckFailure):
            await send_method(f"Anda tidak memenuhi syarat untuk menggunakan perintah ini: {original_error}", ephemeral=True)
        elif isinstance(original_error, (genai_types.BlockedPromptError, genai_types.StopCandidateError)):
            await send_method(f"Permintaan Anda ke AI diblokir atau dihentikan: {original_error}", ephemeral=True)
        elif isinstance(original_error, GoogleAPIError):
            await send_method(f"Terjadi error pada API Google: {original_error}", ephemeral=True)
        elif isinstance(original_error, app_commands.CommandInvokeError) and isinstance(original_error.original, GoogleAPIError): # Nested GoogleAPIError
            await send_method(f"Terjadi error pada API Google (invoke): {original_error.original}", ephemeral=True)
        else:
            await send_method(f"Terjadi error tak terduga saat menjalankan perintah AI: {original_error}", ephemeral=True)

async def setup(bot: commands.Bot):
    """Setup function untuk memuat AICog."""
    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY tidak ditemukan. AICog tidak akan dimuat.")
        return

    # Inisialisasi model sudah dipanggil di atas saat modul diimpor.
    # Cek apakah model berhasil diinisialisasi.
    if _gemini_text_model is None and _gemini_image_gen_model is None:
        _logger.error("Tidak ada model Gemini yang berhasil diinisialisasi. AICog tidak akan dimuat.")
        return
    
    cog_instance = AICog(bot)
    await bot.add_cog(cog_instance)
    _logger.info("AICog berhasil dimuat.")
    
    # Error handler untuk cog ini (jika ada command lain yang ditambahkan di cog ini)
    # Untuk sekarang, generate_image_slash adalah satu-satunya command, jadi errornya bisa langsung
    # ditangani di cog_app_command_error atau diikat secara spesifik jika perlu.
    # Jika ada banyak command, cog_app_command_error lebih umum.
    # cog_instance.generate_image_slash.error(cog_instance.cog_app_command_error) # Bisa juga begini