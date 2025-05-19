# cogs/ai_cog.py

import discord
import os
import google.genai as genai
from google.genai import types as genai_types
from google.api_core.exceptions import GoogleAPIError, InvalidArgument, FailedPrecondition
import database # Asumsi database.py ada dan berfungsi
from discord.ext import commands
from discord import app_commands
import logging
from PIL import Image # Hanya jika masih ada fitur yang membutuhkan ini secara langsung di cog
import io
import asyncio
# import re # Tidak digunakan lagi secara aktif di versi ini

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

GEMINI_TEXT_MODEL_NAME = "models/gemini-2.0-flash"
GEMINI_IMAGE_GEN_MODEL_NAME = "models/gemini-2.0-flash-preview-image-generation"

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

_gemini_client: genai.Client | None = None

def initialize_gemini_client():
    global _gemini_client
    if GOOGLE_API_KEY is None:
        _logger.error("Variabel lingkungan GOOGLE_API_KEY tidak diatur. Fitur AI tidak akan tersedia.")
        return
    try:
        _gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
        _logger.info("Klien Google GenAI berhasil diinisialisasi.")
        # Verifikasi akses model (opsional tapi baik)
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
        _logger.error(f"Error inisialisasi klien Google GenAI: {e}", exc_info=True)
        _gemini_client = None

initialize_gemini_client()

class AICog(commands.Cog):
    """Cog untuk fitur interaksi AI menggunakan Gemini dari Google GenAI."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("AICog instance telah dibuat.")

    async def _send_long_text_as_file(self, target: discord.abc.Messageable, text_content: str, filename: str = "response.txt", initial_message: str = "Respons terlalu panjang, dikirim sebagai file:"):
        """Mengirim teks panjang sebagai file."""
        try:
            file_data = io.BytesIO(text_content.encode('utf-8'))
            discord_file = discord.File(fp=file_data, filename=filename)
            await target.send(content=initial_message, file=discord_file)
            _logger.info(f"Mengirim respons panjang sebagai file '{filename}'.")
        except Exception as e:
            _logger.error(f"Gagal mengirim teks sebagai file: {e}", exc_info=True)
            await target.send("Gagal mengirim respons sebagai file. Silakan coba lagi nanti.")


    async def _process_and_send_text_response(self, message_or_interaction, response: genai_types.GenerateContentResponse, context: str, is_interaction: bool = False):
        """
        Memproses respons teks dari Gemini dan mengirimkannya sebagai embed atau file.
        """
        response_text = ""
        # Ekstraksi teks dari respons API
        if hasattr(response, 'text') and response.text:
            response_text = response.text
        elif hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                text_parts_list = [part.text for part in candidate.content.parts if hasattr(part, 'text') and part.text]
                response_text = "".join(text_parts_list)
            elif hasattr(candidate, 'text') and candidate.text:
                response_text = candidate.text

        # Tentukan fungsi pengiriman berdasarkan tipe (pesan atau interaksi)
        target_to_send: discord.abc.Messageable
        initial_send_func = None
        followup_send_func = None

        if is_interaction:
            target_to_send = interaction.channel # Untuk send_long_text_as_file atau followup
            initial_send_func = message_or_interaction.followup.send
            followup_send_func = message_or_interaction.channel.send # Untuk potongan tambahan embed jika ada
        else: # Ini adalah message
            target_to_send = message_or_interaction.channel
            initial_send_func = message_or_interaction.reply
            followup_send_func = message_or_interaction.reply

        if not response_text.strip():
            # Penanganan jika respons kosong atau diblokir
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                block_reason_value = response.prompt_feedback.block_reason
                if block_reason_value != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                    try:
                        block_reason_name = genai_types.BlockedReason(block_reason_value).name
                    except ValueError:
                        block_reason_name = f"UNKNOWN_REASON_VALUE_{block_reason_value}"
                    _logger.warning(f"({context}) Prompt diblokir. Alasan: {block_reason_name}.")
                    await initial_send_func(f"Maaf, permintaan Anda diblokir oleh filter keamanan AI ({block_reason_name}).", ephemeral=is_interaction)
                    return
            _logger.warning(f"({context}) Gemini mengembalikan respons kosong.")
            await initial_send_func("Maaf, saya tidak bisa memberikan respons saat ini.", ephemeral=is_interaction)
            return

        # Batas karakter untuk embed
        EMBED_TITLE_LIMIT = 256
        EMBED_DESC_LIMIT = 4096
        EMBED_FIELD_NAME_LIMIT = 256 # Tidak digunakan untuk nama field, tapi baik untuk diketahui
        EMBED_FIELD_VALUE_LIMIT = 1024
        MAX_FIELDS = 25
        TOTAL_EMBED_CHAR_LIMIT = 6000 # Batas total karakter praktis
        
        # Coba kirim sebagai embed dulu
        try:
            if len(response_text) <= EMBED_DESC_LIMIT: # Muat dalam deskripsi tunggal
                embed = discord.Embed(
                    title=f"Respons dari Noelle ({context})",
                    description=response_text,
                    color=discord.Color.random()
                )
                if is_interaction:
                    embed.set_footer(text=f"Diminta oleh: {message_or_interaction.user.display_name}")
                else: # message
                    embed.set_footer(text=f"Untuk: {message_or_interaction.author.display_name}")
                await initial_send_func(embed=embed)
                _logger.info(f"({context}) Respons teks dikirim sebagai embed tunggal.")
            
            # Jika lebih panjang dari deskripsi, coba bagi ke fields (logika sederhana)
            elif len(response_text) <= TOTAL_EMBED_CHAR_LIMIT - EMBED_TITLE_LIMIT - 100: # Beri ruang untuk judul & footer
                embed = discord.Embed(
                    title=f"Respons dari Noelle ({context})",
                    color=discord.Color.random()
                )
                if is_interaction:
                    embed.set_footer(text=f"Diminta oleh: {message_or_interaction.user.display_name}")
                else: # message
                    embed.set_footer(text=f"Untuk: {message_or_interaction.author.display_name}")

                remaining_text = response_text
                field_count = 0
                
                # Bagian pertama di deskripsi jika muat
                if len(remaining_text) > EMBED_DESC_LIMIT:
                    embed.description = remaining_text[:EMBED_DESC_LIMIT-3] + "..."
                    remaining_text = remaining_text[EMBED_DESC_LIMIT-3:]
                else:
                    embed.description = remaining_text
                    remaining_text = ""

                # Sisa teks dibagi ke fields
                while remaining_text and field_count < MAX_FIELDS:
                    chunk = remaining_text[:EMBED_FIELD_VALUE_LIMIT]
                    embed.add_field(name=f"Lanjutan ({field_count + 1})" if field_count > 0 or embed.description else "Respons", value=chunk, inline=False)
                    remaining_text = remaining_text[len(chunk):]
                    field_count += 1
                
                await initial_send_func(embed=embed)
                _logger.info(f"({context}) Respons teks dikirim sebagai embed dengan beberapa field.")

                # Jika masih ada sisa teks setelah embed pertama dengan field penuh
                if remaining_text:
                    _logger.info(f"({context}) Teks masih tersisa setelah embed pertama, mengirim sebagai file.")
                    await self._send_long_text_as_file(target_to_send, remaining_text, filename=f"lanjutan_respons_{context.lower().replace(' ', '_')}.txt", initial_message="Lanjutan respons karena terlalu panjang untuk embed:")
            
            else: # Terlalu panjang bahkan untuk dibagi ke fields, kirim sebagai file
                _logger.info(f"({context}) Respons teks terlalu panjang ({len(response_text)} chars), mengirim sebagai file.")
                await self._send_long_text_as_file(target_to_send, response_text, filename=f"respons_{context.lower().replace(' ', '_')}.txt")

        except discord.errors.HTTPException as e:
            _logger.error(f"({context}) Gagal mengirim embed/file: {e}", exc_info=True)
            # Fallback ke pengiriman teks biasa jika embed gagal dan teks tidak terlalu ekstrim
            if len(response_text) < 1990 : # Batas aman untuk pesan teks biasa
                await initial_send_func(f"Gagal mengirim respons dalam format embed. Berikut teksnya:\n\n{response_text[:1950]}{'...' if len(response_text)>1950 else ''}", ephemeral=is_interaction)
            else: # Jika embed gagal dan teksnya juga panjang, fallback ke file
                await self._send_long_text_as_file(target_to_send, response_text, filename=f"respons_error_{context.lower().replace(' ', '_')}.txt", initial_message="Gagal mengirim respons dalam format embed. Berikut respons sebagai file:")
        except Exception as e:
            _logger.error(f"({context}) Error tak terduga saat memproses/mengirim respons teks: {e}", exc_info=True)
            await initial_send_func("Terjadi error saat menampilkan respons dari AI.", ephemeral=is_interaction)


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if _gemini_client is None:
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
                    
                    api_response = await asyncio.to_thread(
                        _gemini_client.models.generate_content,
                        model=GEMINI_TEXT_MODEL_NAME,
                        contents=content_parts
                    )
                    _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini.")
                    # Menggunakan is_interaction=False
                    await self._process_and_send_text_response(message, api_response, context_log_prefix, is_interaction=False)

                except (InvalidArgument, FailedPrecondition) as specific_api_e:
                    _logger.warning(f"({context_log_prefix}) Error API Google (safety/prompt): {specific_api_e}")
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

                    api_response = await asyncio.to_thread(
                        _gemini_client.models.generate_content,
                        model=GEMINI_TEXT_MODEL_NAME,
                        contents=text_content_for_mention
                    )
                    _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini.")
                    # Menggunakan is_interaction=False
                    await self._process_and_send_text_response(message, api_response, context_log_prefix, is_interaction=False)
                
                except (InvalidArgument, FailedPrecondition) as specific_api_e:
                    _logger.warning(f"({context_log_prefix}) Error API Google (safety/prompt): {specific_api_e}")
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

        # --- VALIDASI CHANNEL AI ---
        config = database.get_server_config(interaction.guild_id)
        ai_channel_id = config.get('ai_channel_id')

        if ai_channel_id is None:
            await interaction.response.send_message(
                "Channel AI belum diatur di server ini. Silakan minta admin untuk mengatur menggunakan `/config ai_channel`.",
                ephemeral=True
            )
            _logger.warning(f"/generate_image digunakan oleh {interaction.user.name} tapi channel AI belum diatur di guild {interaction.guild.name}.")
            return
        
        if interaction.channel_id != ai_channel_id:
            designated_channel = self.bot.get_channel(ai_channel_id)
            channel_mention = designated_channel.mention if designated_channel else f"channel AI yang telah ditentukan (ID: {ai_channel_id})"
            await interaction.response.send_message(
                f"Perintah ini hanya dapat digunakan di {channel_mention}.",
                ephemeral=True
            )
            _logger.warning(f"/generate_image digunakan oleh {interaction.user.name} di channel {interaction.channel.name}, bukan di channel AI ({ai_channel_id}).")
            return
        # --- AKHIR VALIDASI CHANNEL AI ---

        if not prompt.strip():
            await interaction.response.send_message("Mohon berikan deskripsi gambar.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=False) # Defer di sini, sebelum try-except utama

        try:
            _logger.info(f"Memanggil model gambar Gemini dengan prompt: '{prompt}'.")
            
            generation_config_object = genai_types.GenerateContentConfig(
                response_modalities=[genai_types.Modality.TEXT, genai_types.Modality.IMAGE]
            )

            api_response = await asyncio.to_thread(
                _gemini_client.models.generate_content,
                model=GEMINI_IMAGE_GEN_MODEL_NAME,
                contents=prompt,
                config=generation_config_object
            )
            _logger.info("Menerima respons dari API gambar Gemini.")

            generated_text_parts = []
            generated_image_bytes = None
            mime_type_image = "image/png" 

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
            
            final_text_response = "\n".join(generated_text_parts).strip()

            if generated_image_bytes:
                extension = mime_type_image.split('/')[-1] if '/' in mime_type_image else 'png'
                filename = f"gemini_image.{extension}"
                image_file = discord.File(io.BytesIO(generated_image_bytes), filename=filename)
                
                # Teks pendamping akan dimasukkan ke deskripsi embed. Jika terlalu panjang, _process_and_send_text_response akan menanganinya.
                # Untuk kasus ini, kita buat embed sederhana dulu, teks pendamping bisa dikirim terpisah jika panjang.
                embed_title = "Gambar Dihasilkan oleh Noelle ✨"
                prompt_display = f"**Prompt:** \"{discord.utils.escape_markdown(prompt[:1000])}{'...' if len(prompt) > 1000 else ''}\""
                
                image_embed = discord.Embed(title=embed_title, description=prompt_display, color=discord.Color.random())
                image_embed.set_image(url=f"attachment://{filename}")
                image_embed.set_footer(text=f"Diminta oleh: {interaction.user.display_name}")
                
                await interaction.followup.send(embed=image_embed, file=image_file)
                _logger.info(f"Gambar berhasil dikirim untuk prompt: {prompt}")

                # Kirim teks pendamping secara terpisah jika ada, menggunakan logika embed/file
                if final_text_response:
                    _logger.info("Mengirim teks pendamping untuk gambar...")
                    # Buat objek "dummy" response hanya untuk teks agar bisa dipakai _process_and_send_text_response
                    # Ini agak hacky, idealnya _process_and_send_text_response bisa menerima teks langsung
                    dummy_text_part = genai_types.Part(text=final_text_response)
                    dummy_content = genai_types.Content(parts=[dummy_text_part], role="model")
                    dummy_candidate = genai_types.Candidate(content=dummy_content, finish_reason=genai_types.FinishReason.STOP, index=0) # finish_reason dan index dummy
                    dummy_response_for_text = genai_types.GenerateContentResponse(candidates=[dummy_candidate])

                    # Gunakan interaction.channel.send untuk teks pendamping agar tidak mengganggu followup gambar
                    # Atau, kita bisa buat fungsi send_text_response_to_channel yang lebih generik
                    class DummyMessageable: # Objek dummy untuk message.reply atau interaction.followup.send
                        def __init__(self, channel, original_interaction):
                            self.channel = channel
                            self.original_interaction = original_interaction
                            self.author = original_interaction.user # Mirip author message
                            self.guild = original_interaction.guild # Mirip guild message

                        async def reply(self, *args, **kwargs): # Mirip message.reply
                            return await self.channel.send(*args, **kwargs)

                        async def send(self, *args, **kwargs): # Mirip channel.send
                             return await self.channel.send(*args, **kwargs)
                    
                    # Kita akan mengirim teks pendamping sebagai pesan baru di channel
                    await self._process_and_send_text_response(
                        DummyMessageable(interaction.channel, interaction), 
                        dummy_response_for_text, 
                        "Image Gen Companion Text", 
                        is_interaction=False # Perlakukan sebagai pesan baru, bukan followup dari interaksi utama
                    )


            elif final_text_response: # Hanya teks, tidak ada gambar
                _logger.warning(f"Gemini menghasilkan teks tapi tidak ada data gambar. Prompt: '{prompt}'")
                # Kirim menggunakan logika embed/file
                dummy_text_part = genai_types.Part(text=final_text_response)
                dummy_content = genai_types.Content(parts=[dummy_text_part], role="model")
                dummy_candidate = genai_types.Candidate(content=dummy_content, finish_reason=genai_types.FinishReason.STOP, index=0)
                dummy_response_for_text = genai_types.GenerateContentResponse(candidates=[dummy_candidate])
                await self._process_and_send_text_response(interaction, dummy_response_for_text, "Image Gen Text-Only", is_interaction=True)
            else:
                if hasattr(api_response, 'prompt_feedback') and api_response.prompt_feedback:
                    block_reason_value = api_response.prompt_feedback.block_reason
                    if block_reason_value != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                        try:
                            block_reason_name = genai_types.BlockedReason(block_reason_value).name
                        except ValueError:
                             block_reason_name = f"UNKNOWN_REASON_VALUE_{block_reason_value}"
                        _logger.warning(f"Prompt gambar diblokir. Alasan: {block_reason_name}. Prompt: '{prompt}'.")
                        await interaction.followup.send(f"Maaf, permintaan gambar Anda diblokir ({block_reason_name}).", ephemeral=True)
                        return
                _logger.warning(f"Gemini mengembalikan respons kosong untuk gambar. Prompt: '{prompt}'.")
                await interaction.followup.send("Gagal menghasilkan gambar. AI memberikan respons kosong atau tidak terduga.", ephemeral=True)

        except (InvalidArgument, FailedPrecondition) as specific_api_e:
            _logger.warning(f"Error API Google (safety/prompt) saat generate gambar: {specific_api_e}. Prompt: '{prompt}'")
            await interaction.followup.send(f"Permintaan Anda tidak dapat diproses oleh AI: {specific_api_e}", ephemeral=True)
        except GoogleAPIError as api_e:
            _logger.error(f"Error API Google saat generate gambar: {api_e}. Prompt: '{prompt}'", exc_info=True)
            await interaction.followup.send(f"Terjadi error pada API AI: {api_e}", ephemeral=True)
        except Exception as e:
            _logger.error(f"Error tak terduga saat generate gambar: {e}. Prompt: '{prompt}'", exc_info=True)
            await interaction.followup.send(f"Terjadi error tak terduga saat membuat gambar: {type(e).__name__} - {e}", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        # (Error handler ini sebagian besar tetap sama, pastikan pesan errornya jelas)
        original_error = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else "Unknown AI Cmd"
        _logger.error(f"Error pd cmd AI '{command_name}' oleh {interaction.user.name}: {original_error}", exc_info=True)
        
        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        error_message = "Terjadi kesalahan internal saat memproses perintah AI Anda."

        if isinstance(original_error, app_commands.CheckFailure):
            error_message = f"Anda tidak memenuhi syarat untuk menggunakan perintah ini: {original_error}"
        elif isinstance(original_error, InvalidArgument): # Lebih spesifik untuk input tidak valid atau diblokir
            error_message = f"Permintaan Anda ke AI tidak valid atau diblokir karena alasan keamanan: {original_error}"
        elif isinstance(original_error, FailedPrecondition): # Seringkali karena safety filter juga
             error_message = f"Permintaan Anda ke AI tidak dapat dipenuhi (kemungkinan terkait filter keamanan): {original_error}"
        elif isinstance(original_error, GoogleAPIError):
            error_message = f"Terjadi error pada layanan Google AI: {original_error}"
        elif isinstance(error, app_commands.CommandInvokeError) and isinstance(original_error, GoogleAPIError):
             error_message = f"Terjadi error pada layanan Google AI (invoke): {original_error.original}"
        elif isinstance(original_error, discord.errors.HTTPException):
            error_message = f"Terjadi error HTTP saat berkomunikasi dengan Discord: {original_error.status} - {original_error.text}"
        
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