# cogs/ai_cog.py

import discord
import os
import google.genai as genai
from google.genai import types as genai_types
from google.api_core.exceptions import GoogleAPIError, InvalidArgument, FailedPrecondition
import database
from discord.ext import commands
from discord import app_commands
import logging
from PIL import Image # Diperlukan jika Anda memproses gambar input
import io
import asyncio
import re # Untuk mencari pemisah kalimat/paragraf
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

load_dotenv()
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

    async def _send_long_text_as_file(self, target_channel: discord.abc.Messageable, text_content: str, filename: str = "response.txt", initial_message: str = "Respons terlalu panjang, dikirim sebagai file:"):
        """Mengirim teks panjang sebagai file ke channel yang ditentukan."""
        try:
            file_data = io.BytesIO(text_content.encode('utf-8'))
            discord_file = discord.File(fp=file_data, filename=filename)
            await target_channel.send(content=initial_message, file=discord_file)
            _logger.info(f"Mengirim respons panjang sebagai file '{filename}' ke channel {target_channel.id}.")
        except Exception as e:
            _logger.error(f"Gagal mengirim teks sebagai file ke channel {target_channel.id}: {e}", exc_info=True)
            # Hindari mengirim pesan error lagi jika ini adalah fallback terakhir

    def _find_sensible_split_point(self, text: str, max_len: int) -> int:
        """Mencari titik potong yang "masuk akal" dalam batas max_len."""
        if len(text) <= max_len:
            return len(text)

        slice_to_check = text[:max_len]
        
        split_point_newline = slice_to_check.rfind('\n\n')
        if split_point_newline != -1:
            return split_point_newline + 2 

        sentence_enders = ['. ', '! ', '? ']
        best_split_point = -1
        for ender in sentence_enders:
            point = slice_to_check.rfind(ender)
            if point != -1 and point + len(ender) > best_split_point:
                best_split_point = point + len(ender)
        if best_split_point != -1:
            return best_split_point

        split_point_single_newline = slice_to_check.rfind('\n')
        if split_point_single_newline != -1:
            return split_point_single_newline + 1

        last_space = slice_to_check.rfind(' ')
        if last_space != -1:
            return last_space + 1
            
        return max_len

    async def _send_text_in_embeds(self, 
                                 target_channel: discord.abc.Messageable,
                                 response_text: str, 
                                 title_prefix: str, 
                                 footer_text: str,
                                 reply_to_message: discord.Message | None = None,
                                 interaction_to_followup: discord.Interaction | None = None):
        """Mengirim teks dalam maksimal 2 embed. Sisa dikirim sebagai file."""
        EMBED_TITLE_LIMIT = 256
        EMBED_DESC_LIMIT = 4096
        EMBED_FIELD_VALUE_LIMIT = 1024
        MAX_FIELDS_PER_EMBED = 25
        SAFE_CHAR_PER_EMBED = 5800 

        embeds_to_send = []
        remaining_text = response_text.strip() # Pastikan tidak ada spasi di awal/akhir

        for i in range(2): # Maksimal 2 embed
            if not remaining_text: # Jika sudah tidak ada teks lagi
                break

            current_embed_char_count = 0
            title = f"{title_prefix} (Bagian {i+1})" if i > 0 or (len(response_text) > SAFE_CHAR_PER_EMBED and i==0) else title_prefix
            embed = discord.Embed(title=title[:EMBED_TITLE_LIMIT], color=discord.Color.random()) # Batasi panjang judul
            if footer_text:
                embed.set_footer(text=footer_text)
            
            current_embed_char_count += len(embed.title or "") + len(embed.footer.text or "")

            # Isi deskripsi embed
            # Budget untuk deskripsi: EMBED_DESC_LIMIT ATAU sisa budget di SAFE_CHAR_PER_EMBED
            available_desc_space = min(EMBED_DESC_LIMIT, SAFE_CHAR_PER_EMBED - current_embed_char_count - 50) # -50 buffer
            if available_desc_space > 0:
                desc_split_len = self._find_sensible_split_point(remaining_text, available_desc_space)
                if desc_split_len > 0:
                    embed.description = remaining_text[:desc_split_len]
                    remaining_text = remaining_text[desc_split_len:].lstrip()
                    current_embed_char_count += len(embed.description or "")
            
            # Isi fields
            field_count = 0
            while remaining_text and field_count < MAX_FIELDS_PER_EMBED and current_embed_char_count < SAFE_CHAR_PER_EMBED:
                field_name = "Lanjutan..."
                current_embed_char_count += len(field_name)

                available_field_space = min(EMBED_FIELD_VALUE_LIMIT, SAFE_CHAR_PER_EMBED - current_embed_char_count - 20) # -20 buffer
                if available_field_space <= 20: break # Jangan buat field terlalu kecil

                val_split_len = self._find_sensible_split_point(remaining_text, available_field_space)
                if val_split_len == 0 and remaining_text: # Jika tidak bisa split tapi masih ada teks, ambil paksa
                    val_split_len = min(len(remaining_text), available_field_space)
                
                field_value = remaining_text[:val_split_len]
                if not field_value.strip(): # Jangan tambah field kosong
                    if not remaining_text.strip(): break # Keluar jika memang tidak ada teks lagi
                    remaining_text = remaining_text[val_split_len:].lstrip() # Lewati jika hanya spasi
                    continue

                embed.add_field(name=field_name, value=field_value, inline=False)
                remaining_text = remaining_text[val_split_len:].lstrip()
                current_embed_char_count += len(field_value)
                field_count += 1
            
            if embed.description or embed.fields: # Hanya tambahkan embed jika ada konten
                embeds_to_send.append(embed)
            elif not remaining_text: # Jika embed kosong dan tidak ada sisa teks, selesai
                break
            else: # Embed kosong tapi masih ada sisa teks, kemungkinan budget habis, kirim sisanya sebagai file
                _logger.info(f"Embed ke-{i+1} akan kosong tapi masih ada sisa teks, sisa akan dikirim sebagai file.")
                break 


        # Kirim embed yang sudah dibuat
        for idx, emb in enumerate(embeds_to_send):
            try:
                if idx == 0: 
                    if interaction_to_followup:
                        await interaction_to_followup.followup.send(embed=emb)
                    elif reply_to_message:
                        await reply_to_message.reply(embed=emb)
                    else: 
                        await target_channel.send(embed=emb)
                else: 
                    await target_channel.send(embed=emb)
                _logger.info(f"Mengirim embed bagian {idx+1}.")
                await asyncio.sleep(0.3)
            except discord.errors.HTTPException as e:
                _logger.error(f"Gagal mengirim embed bagian {idx+1}: {e}", exc_info=True)
                failed_embed_content = f"Title: {emb.title}\nDescription: {emb.description}\n"
                for field in emb.fields: failed_embed_content += f"\nField ({field.name}):\n{field.value}\n"
                await self._send_long_text_as_file(target_channel, failed_embed_content, f"error_embed_part_{idx+1}.txt", "Gagal mengirim embed, kontennya sbg file:")
                if idx == 0 and remaining_text.strip():
                    await self._send_long_text_as_file(target_channel, remaining_text, "sisa_respons.txt", "Sisa respons (setelah kegagalan embed):")
                    remaining_text = "" 
                break 

        if remaining_text.strip():
            _logger.info("Teks masih tersisa setelah maksimal embed, mengirim sisanya sebagai file.")
            await self._send_long_text_as_file(target_channel, remaining_text, "respons_lanjutan.txt", "Respons lanjutan (melebihi kapasitas embed):")

    async def _process_and_send_text_response(self, message_or_interaction, response: genai_types.GenerateContentResponse, context: str, is_interaction: bool = False):
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
        
        title_prefix = f"Respons Noelle ({context})"
        footer_txt = ""
        target_channel_for_messages: discord.abc.Messageable
        message_to_reply: discord.Message | None = None
        interaction_to_followup: discord.Interaction | None = None
        initial_sender_func = None # Fungsi untuk mengirim pesan/respons pertama

        if is_interaction:
            interaction_to_followup = message_or_interaction
            target_channel_for_messages = message_or_interaction.channel
            footer_txt = f"Diminta oleh: {message_or_interaction.user.display_name}"
            initial_sender_func = interaction_to_followup.followup.send # Untuk pesan pertama dari interaksi
        else: 
            message_to_reply = message_or_interaction
            target_channel_for_messages = message_or_interaction.channel
            footer_txt = f"Untuk: {message_or_interaction.author.display_name}"
            initial_sender_func = message_to_reply.reply # Untuk pesan pertama dari message

        if not response_text.strip():
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                block_reason_value = response.prompt_feedback.block_reason
                if block_reason_value != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                    try: block_reason_name = genai_types.BlockedReason(block_reason_value).name
                    except ValueError: block_reason_name = f"UNKNOWN_{block_reason_value}"
                    _logger.warning(f"({context}) Prompt diblokir. Alasan: {block_reason_name}.")
                    await initial_sender_func(f"Maaf, permintaan Anda diblokir ({block_reason_name}).", ephemeral=is_interaction)
                    return
            _logger.warning(f"({context}) Gemini mengembalikan respons kosong.")
            await initial_sender_func("Maaf, saya tidak bisa memberikan respons saat ini.", ephemeral=is_interaction)
            return

        try:
            # Penanganan khusus untuk teks pendamping gambar agar tidak followup lagi
            if context == "Info Tambahan Gambar" and is_interaction:
                await self._send_text_in_embeds(
                    target_channel=target_channel_for_messages,
                    response_text=response_text,
                    title_prefix=title_prefix,
                    footer_text=footer_txt,
                    reply_to_message=None, 
                    interaction_to_followup=None # Kirim sebagai pesan baru
                )
            else:
                await self._send_text_in_embeds(
                    target_channel=target_channel_for_messages,
                    response_text=response_text,
                    title_prefix=title_prefix,
                    footer_text=footer_txt,
                    reply_to_message=message_to_reply,
                    interaction_to_followup=interaction_to_followup
                )
            _logger.info(f"({context}) Respons teks selesai diproses (embed/file).")
        except Exception as e:
            _logger.error(f"({context}) Error besar saat _process_and_send_text_response: {e}", exc_info=True)
            error_msg_content = "Terjadi kesalahan signifikan saat menampilkan respons."
            try: # Usahakan kirim error ke pengguna
                if is_interaction:
                    if not message_or_interaction.response.is_done():
                        await message_or_interaction.response.send_message(error_msg_content, ephemeral=True)
                    else:
                        await message_or_interaction.followup.send(error_msg_content, ephemeral=True)
                else:
                    await message_or_interaction.reply(error_msg_content)
            except Exception:
                _logger.error(f"({context}) Gagal mengirim pesan error akhir ke pengguna.", exc_info=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None: return
        if _gemini_client is None: return

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
                            await message.reply("Mohon berikan maksimal 4 gambar."); return
                        for attachment in image_attachments:
                            try:
                                image_bytes = await attachment.read()
                                pil_image = Image.open(io.BytesIO(image_bytes))
                                content_parts.append(pil_image)
                            except Exception as img_e:
                                _logger.error(f"({context_log_prefix}) Gagal proses gambar {attachment.filename}: {img_e}", exc_info=True)
                                await message.channel.send(f"Peringatan: Gagal proses gambar '{attachment.filename}'.")
                                if len(image_attachments) == 1 and not cleaned_content_for_mention_check: return
                    
                    text_content = message.content
                    if bot_user and bot_user.mention in text_content:
                        text_content = text_content.replace(bot_user.mention, '').strip()
                    if text_content: content_parts.append(text_content)

                    if not content_parts:
                        if is_mentioned and not text_content and not image_attachments:
                             await message.reply("Halo! Ada yang bisa saya bantu?")
                        return
                    
                    api_response = await asyncio.to_thread(
                        _gemini_client.models.generate_content,
                        model=GEMINI_TEXT_MODEL_NAME, contents=content_parts)
                    _logger.info(f"({context_log_prefix}) Menerima respons Gemini.")
                    await self._process_and_send_text_response(message, api_response, context_log_prefix, is_interaction=False)
                except (InvalidArgument, FailedPrecondition) as e:
                    _logger.warning(f"({context_log_prefix}) Error API (safety/prompt): {e}")
                    await message.reply(f"Permintaan tidak dapat diproses: {e}")
                except GoogleAPIError as e: _logger.error(f"({context_log_prefix}) Error API Google: {e}", exc_info=True); await message.reply(f"Error API AI: {e}")
                except Exception as e: _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True); await message.reply("Error tak terduga.")
            return

        if is_mentioned and (not in_ai_channel or just_a_mention):
            context_log_prefix = "Bot Mention"
            _logger.info(f"({context_log_prefix}) Memproses mention dari {message.author.name}...")
            async with message.channel.typing():
                try:
                    text_content_for_mention = message.content.replace(bot_user.mention, '', 1).strip()
                    if not text_content_for_mention: await message.reply("Halo! Ada yang bisa saya bantu?"); return
                    api_response = await asyncio.to_thread(
                        _gemini_client.models.generate_content,
                        model=GEMINI_TEXT_MODEL_NAME, contents=text_content_for_mention)
                    _logger.info(f"({context_log_prefix}) Menerima respons Gemini.")
                    await self._process_and_send_text_response(message, api_response, context_log_prefix, is_interaction=False)
                except (InvalidArgument, FailedPrecondition) as e: _logger.warning(f"({context_log_prefix}) Error API (safety/prompt): {e}"); await message.reply(f"Permintaan tidak dapat diproses: {e}")
                except GoogleAPIError as e: _logger.error(f"({context_log_prefix}) Error API Google: {e}", exc_info=True); await message.reply(f"Error API AI: {e}")
                except Exception as e: _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True); await message.reply("Error tak terduga.")
            return

    @app_commands.command(name='generate_image', description='Membuat gambar berdasarkan deskripsi teks menggunakan AI.')
    @app_commands.describe(prompt='Deskripsikan gambar yang ingin Anda buat.')
    @app_commands.guild_only()
    async def generate_image_slash(self, interaction: discord.Interaction, prompt: str):
        _logger.info(f"Menerima /generate_image dari {interaction.user.name} dengan prompt: '{prompt}'...")
        response_handler = interaction.response # Simpan untuk cek is_done
        send_method_ephemeral = response_handler.send_message if not response_handler.is_done() else interaction.followup.send

        if _gemini_client is None:
            _logger.warning("Klien Gemini tidak tersedia untuk /generate_image.")
            await send_method_ephemeral("Layanan AI tidak tersedia.", ephemeral=True)
            return

        config = database.get_server_config(interaction.guild_id)
        ai_channel_id = config.get('ai_channel_id')

        if ai_channel_id is None:
            await send_method_ephemeral("Channel AI belum diatur. Atur via `/config ai_channel`.", ephemeral=True)
            _logger.warning(f"/generate_image: channel AI belum diatur di guild {interaction.guild.name}.")
            return
        
        if interaction.channel_id != ai_channel_id:
            designated_channel = self.bot.get_channel(ai_channel_id)
            channel_mention = designated_channel.mention if designated_channel else f"channel AI (ID: {ai_channel_id})"
            await send_method_ephemeral(f"Perintah ini hanya dapat digunakan di {channel_mention}.", ephemeral=True)
            _logger.warning(f"/generate_image: digunakan di channel salah, bukan di {channel_mention}.")
            return

        if not prompt.strip():
            await send_method_ephemeral("Mohon berikan deskripsi gambar.", ephemeral=True)
            return
        
        if not response_handler.is_done():
            await response_handler.defer(ephemeral=False)

        try:
            _logger.info(f"Memanggil model gambar Gemini dengan prompt: '{prompt}'.")
            generation_config_object = genai_types.GenerateContentConfig(
                response_modalities=[genai_types.Modality.TEXT, genai_types.Modality.IMAGE]
            )
            api_response = await asyncio.to_thread(
                _gemini_client.models.generate_content,
                model=GEMINI_IMAGE_GEN_MODEL_NAME, contents=prompt, config=generation_config_object)
            _logger.info("Menerima respons dari API gambar Gemini.")

            generated_text_parts = []
            generated_image_bytes = None
            mime_type_image = "image/png" 

            if hasattr(api_response, 'candidates') and api_response.candidates:
                candidate = api_response.candidates[0]
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    for part in candidate.content.parts:
                        if hasattr(part, 'text') and part.text: generated_text_parts.append(part.text)
                        elif hasattr(part, 'inline_data') and part.inline_data and hasattr(part.inline_data, 'mime_type') and part.inline_data.mime_type.startswith('image/'):
                            generated_image_bytes = part.inline_data.data
                            mime_type_image = part.inline_data.mime_type
                            _logger.info(f"Menerima inline_data gambar (MIME: {mime_type_image}).")
            
            final_text_response = "\n".join(generated_text_parts).strip()

            if generated_image_bytes:
                extension = mime_type_image.split('/')[-1] if '/' in mime_type_image else 'png'
                filename = f"gemini_image.{extension}"
                image_file = discord.File(io.BytesIO(generated_image_bytes), filename=filename)
                embed_title = "Gambar Dihasilkan oleh Noelle ✨"
                prompt_display = f"**Prompt:** \"{discord.utils.escape_markdown(prompt[:1000])}{'...' if len(prompt) > 1000 else ''}\""
                image_embed = discord.Embed(title=embed_title, description=prompt_display, color=discord.Color.random())
                image_embed.set_image(url=f"attachment://{filename}")
                image_embed.set_footer(text=f"Diminta oleh: {interaction.user.display_name}")
                await interaction.followup.send(embed=image_embed, file=image_file)
                _logger.info(f"Gambar berhasil dikirim untuk prompt: {prompt}")

                if final_text_response:
                    _logger.info("Mengirim teks pendamping untuk gambar...")
                    dummy_text_part = genai_types.Part(text=final_text_response)
                    dummy_content = genai_types.Content(parts=[dummy_text_part], role="model")
                    dummy_candidate = genai_types.Candidate(content=dummy_content, finish_reason=genai_types.FinishReason.STOP, index=0)
                    dummy_response_for_text = genai_types.GenerateContentResponse(candidates=[dummy_candidate])
                    await self._process_and_send_text_response(interaction, dummy_response_for_text, "Info Tambahan Gambar", is_interaction=True)
            elif final_text_response: 
                _logger.warning(f"Gemini menghasilkan teks tapi tidak ada gambar. Prompt: '{prompt}'")
                dummy_text_part = genai_types.Part(text=final_text_response)
                dummy_content = genai_types.Content(parts=[dummy_text_part], role="model")
                dummy_candidate = genai_types.Candidate(content=dummy_content, finish_reason=genai_types.FinishReason.STOP, index=0)
                dummy_response_for_text = genai_types.GenerateContentResponse(candidates=[dummy_candidate])
                await self._process_and_send_text_response(interaction, dummy_response_for_text, "Image Gen Text-Only", is_interaction=True)
            else:
                if hasattr(api_response, 'prompt_feedback') and api_response.prompt_feedback:
                    block_reason_value = api_response.prompt_feedback.block_reason
                    if block_reason_value != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                        try: block_reason_name = genai_types.BlockedReason(block_reason_value).name
                        except ValueError: block_reason_name = f"UNKNOWN_REASON_{block_reason_value}"
                        _logger.warning(f"Prompt gambar diblokir. Alasan: {block_reason_name}. Prompt: '{prompt}'.")
                        await interaction.followup.send(f"Maaf, permintaan gambar Anda diblokir ({block_reason_name}).", ephemeral=True)
                        return
                _logger.warning(f"Gemini mengembalikan respons kosong untuk gambar. Prompt: '{prompt}'.")
                await interaction.followup.send("Gagal menghasilkan gambar. AI memberikan respons kosong atau tidak terduga.", ephemeral=True)
        except (InvalidArgument, FailedPrecondition) as e:
            _logger.warning(f"Error API Google (safety/prompt) /generate_image: {e}. Prompt: '{prompt}'")
            await interaction.followup.send(f"Permintaan tidak dapat diproses: {e}", ephemeral=True)
        except GoogleAPIError as e:
            _logger.error(f"Error API Google /generate_image: {e}. Prompt: '{prompt}'", exc_info=True)
            await interaction.followup.send(f"Error API AI: {e}", ephemeral=True)
        except Exception as e:
            _logger.error(f"Error tak terduga /generate_image: {e}. Prompt: '{prompt}'", exc_info=True)
            await interaction.followup.send(f"Error tak terduga: {type(e).__name__} - {e}", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original_error = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else "Unknown AI Cmd"
        _logger.error(f"Error pd cmd AI '{command_name}' oleh {interaction.user.name}: {original_error}", exc_info=True)
        
        send_method = None
        if interaction.response.is_done():
            send_method = interaction.followup.send
        else:
            send_method = interaction.response.send_message
            
        error_message = "Terjadi kesalahan internal saat memproses perintah AI Anda."

        if isinstance(original_error, app_commands.CheckFailure):
            error_message = f"Anda tidak memenuhi syarat untuk menggunakan perintah ini: {original_error}"
        elif isinstance(original_error, InvalidArgument): 
            error_message = f"Permintaan Anda ke AI tidak valid atau diblokir: {original_error}"
        elif isinstance(original_error, FailedPrecondition): 
             error_message = f"Permintaan Anda ke AI tidak dapat dipenuhi (kemungkinan filter): {original_error}"
        elif isinstance(original_error, GoogleAPIError):
            error_message = f"Error pada layanan Google AI: {original_error}"
        elif isinstance(error, app_commands.CommandInvokeError) and isinstance(original_error, GoogleAPIError):
             error_message = f"Error pada layanan Google AI (invoke): {original_error}"
        elif isinstance(original_error, discord.errors.HTTPException):
            error_message = f"Error HTTP Discord: {original_error.status} - {original_error.text}"
        
        try:
            await send_method(error_message, ephemeral=True)
        except discord.errors.InteractionResponded:
             _logger.warning(f"Gagal kirim error via followup/response (sudah direspons), mencoba kirim ke channel utk cmd '{command_name}'.")
             try: await interaction.channel.send(f"{interaction.user.mention}, terjadi error: {error_message}")
             except Exception as ch_send_e: _logger.error(f"Gagal kirim error ke channel utk cmd '{command_name}': {ch_send_e}", exc_info=True)
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