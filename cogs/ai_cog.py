# cogs/ai_cog.py

import discord
import os
import google.genai as genai
from google.genai import types as genai_types
# genai.chats.Chat akan digunakan untuk anotasi tipe
from google.api_core.exceptions import GoogleAPIError, InvalidArgument, FailedPrecondition
import database
from discord.ext import commands, tasks
from discord import app_commands
import logging
from PIL import Image 
import io
import asyncio
import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

GEMINI_TEXT_MODEL_NAME = "models/gemini-2.0-flash"
GEMINI_IMAGE_GEN_MODEL_NAME = "models/gemini-2.0-flash-preview-image-generation"
MAX_CONTEXT_TOKENS = 120000 
SESSION_TIMEOUT_MINUTES = 30 

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
_gemini_client: genai.Client | None = None
_ai_service_enabled = True 

def initialize_gemini_client():
    # ... (fungsi ini tetap sama) ...
    global _gemini_client
    if GOOGLE_API_KEY is None:
        _logger.error("Variabel lingkungan GOOGLE_API_KEY tidak diatur. Fitur AI tidak akan tersedia.")
        return
    try:
        _gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
        _logger.info("Klien Google GenAI berhasil diinisialisasi.")
        try: _gemini_client.models.get(model=GEMINI_TEXT_MODEL_NAME); _logger.info(f"Model '{GEMINI_TEXT_MODEL_NAME}' OK.")
        except Exception as e: _logger.warning(f"Gagal cek model '{GEMINI_TEXT_MODEL_NAME}': {e}")
        try: _gemini_client.models.get(model=GEMINI_IMAGE_GEN_MODEL_NAME); _logger.info(f"Model '{GEMINI_IMAGE_GEN_MODEL_NAME}' OK.")
        except Exception as e: _logger.warning(f"Gagal cek model '{GEMINI_IMAGE_GEN_MODEL_NAME}': {e}")
    except Exception as e:
        _logger.error(f"Error inisialisasi klien Google GenAI: {e}", exc_info=True)
        _gemini_client = None

initialize_gemini_client()

class AICog(commands.Cog):
    """Cog untuk fitur interaksi AI menggunakan Gemini, termasuk sesi chat."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_chat_sessions: dict[int, genai.chats.Chat] = {} 
        self.chat_session_last_active: dict[int, datetime.datetime] = {}
        # --- MODIFIKASI: Hanya menyimpan jumlah token, bukan histori manual ---
        self.chat_context_token_counts: dict[int, int] = {} 
        # ------------------------------------------------------------------
        self.session_cleanup_loop.start()
        _logger.info("AICog instance telah dibuat dan session cleanup loop dimulai.")

    def cog_unload(self):
        self.session_cleanup_loop.cancel()
        _logger.info("AICog di-unload dan session cleanup loop dihentikan.")

    def _clear_session_data(self, channel_id: int):
        """Membersihkan semua data terkait sesi untuk channel_id tertentu."""
        if channel_id in self.active_chat_sessions: del self.active_chat_sessions[channel_id]
        if channel_id in self.chat_session_last_active: del self.chat_session_last_active[channel_id]
        # --- MODIFIKASI: Reset token count ---
        if channel_id in self.chat_context_token_counts: del self.chat_context_token_counts[channel_id]
        # -------------------------------------

    # ... (_is_ai_channel, _ensure_ai_channel, session_cleanup_loop, _send_long_text_as_file, _find_sensible_split_point, _send_text_in_embeds, _process_and_send_text_response tetap sama) ...
    async def _is_ai_channel(self, interaction: discord.Interaction) -> bool: # ... (tetap sama) ...
        if not interaction.guild_id: return False
        config = database.get_server_config(interaction.guild_id)
        ai_channel_id = config.get('ai_channel_id')
        return ai_channel_id is not None and interaction.channel_id == ai_channel_id

    async def _ensure_ai_channel(self, interaction: discord.Interaction) -> bool: # ... (tetap sama) ...
        config = database.get_server_config(interaction.guild_id)
        ai_channel_id = config.get('ai_channel_id')
        if ai_channel_id is None:
            await interaction.response.send_message("Channel AI belum diatur.", ephemeral=True); return False
        if interaction.channel_id != ai_channel_id:
            ch = self.bot.get_channel(ai_channel_id)
            await interaction.response.send_message(f"Cmd ini hanya di {ch.mention if ch else 'channel AI'}.", ephemeral=True); return False
        return True
        
    @tasks.loop(minutes=5)
    async def session_cleanup_loop(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        timed_out_ids = [ch_id for ch_id, la_time in list(self.chat_session_last_active.items()) 
                         if (now - la_time).total_seconds() > SESSION_TIMEOUT_MINUTES * 60]
        for channel_id in timed_out_ids:
            self._clear_session_data(channel_id) # Gunakan helper clear
            _logger.info(f"Sesi chat untuk channel {channel_id} timeout & dibersihkan.")

    @session_cleanup_loop.before_loop
    async def before_session_cleanup_loop(self): # ... (tetap sama) ...
        await self.bot.wait_until_ready()

    async def _send_long_text_as_file(self, target_channel: discord.abc.Messageable, text_content: str, filename: str = "response.txt", initial_message: str = "Respons terlalu panjang, dikirim sebagai file:"):
        try:
            file_data = io.BytesIO(text_content.encode('utf-8'))
            discord_file = discord.File(fp=file_data, filename=filename)
            await target_channel.send(content=initial_message, file=discord_file)
            _logger.info(f"Mengirim respons panjang sebagai file '{filename}' ke channel {target_channel.id}.")
        except Exception as e:
            _logger.error(f"Gagal mengirim teks sebagai file ke channel {target_channel.id}: {e}", exc_info=True)

    def _find_sensible_split_point(self, text: str, max_len: int) -> int:
        if len(text) <= max_len: return len(text)
        slice_to_check = text[:max_len]
        split_point_newline = slice_to_check.rfind('\n\n')
        if split_point_newline != -1: return split_point_newline + 2 
        sentence_enders = ['. ', '! ', '? ']
        best_split_point = -1
        for ender in sentence_enders:
            point = slice_to_check.rfind(ender)
            if point != -1 and point + len(ender) > best_split_point: best_split_point = point + len(ender)
        if best_split_point != -1: return best_split_point
        split_point_single_newline = slice_to_check.rfind('\n')
        if split_point_single_newline != -1: return split_point_single_newline + 1
        last_space = slice_to_check.rfind(' ')
        if last_space != -1: return last_space + 1
        return max_len

    async def _send_text_in_embeds(self, target_channel: discord.abc.Messageable, response_text: str, title_prefix: str, footer_text: str, reply_to_message: discord.Message | None = None, interaction_to_followup: discord.Interaction | None = None):
        EMBED_TITLE_LIMIT = 256; EMBED_DESC_LIMIT = 4096; EMBED_FIELD_VALUE_LIMIT = 1024
        MAX_FIELDS_PER_EMBED = 25; SAFE_CHAR_PER_EMBED = 5800 
        embeds_to_send = []; remaining_text = response_text.strip()
        for i in range(2):
            if not remaining_text: break
            current_embed_char_count = 0
            title = f"{title_prefix} (Bagian {i+1})" if i > 0 or (len(response_text) > SAFE_CHAR_PER_EMBED and i==0) else title_prefix
            embed = discord.Embed(title=title[:EMBED_TITLE_LIMIT], color=discord.Color.random())
            if footer_text: embed.set_footer(text=footer_text)
            current_embed_char_count += len(embed.title or "") + len(embed.footer.text or "")
            available_desc_space = min(EMBED_DESC_LIMIT, SAFE_CHAR_PER_EMBED - current_embed_char_count - 50)
            if available_desc_space > 0:
                desc_split_len = self._find_sensible_split_point(remaining_text, available_desc_space)
                if desc_split_len > 0:
                    embed.description = remaining_text[:desc_split_len]
                    remaining_text = remaining_text[desc_split_len:].lstrip()
                    current_embed_char_count += len(embed.description or "")
            field_count = 0
            while remaining_text and field_count < MAX_FIELDS_PER_EMBED and current_embed_char_count < SAFE_CHAR_PER_EMBED:
                field_name = "Lanjutan..."
                current_embed_char_count += len(field_name)
                available_field_space = min(EMBED_FIELD_VALUE_LIMIT, SAFE_CHAR_PER_EMBED - current_embed_char_count - 20)
                if available_field_space <= 20: break
                val_split_len = self._find_sensible_split_point(remaining_text, available_field_space)
                if val_split_len == 0 and remaining_text: val_split_len = min(len(remaining_text), available_field_space)
                field_value = remaining_text[:val_split_len]
                if not field_value.strip():
                    if not remaining_text.strip(): break
                    remaining_text = remaining_text[val_split_len:].lstrip(); continue
                embed.add_field(name=field_name, value=field_value, inline=False)
                remaining_text = remaining_text[val_split_len:].lstrip()
                current_embed_char_count += len(field_value); field_count += 1
            if embed.description or embed.fields: embeds_to_send.append(embed)
            elif not remaining_text: break
            else: _logger.info(f"Embed ke-{i+1} kosong, sisa akan jadi file."); break 
        for idx, emb in enumerate(embeds_to_send):
            try:
                if idx == 0: 
                    if interaction_to_followup: await interaction_to_followup.followup.send(embed=emb)
                    elif reply_to_message: await reply_to_message.reply(embed=emb)
                    else: await target_channel.send(embed=emb)
                else: await target_channel.send(embed=emb)
                _logger.info(f"Mengirim embed bagian {idx+1}."); await asyncio.sleep(0.3)
            except discord.errors.HTTPException as e:
                _logger.error(f"Gagal kirim embed {idx+1}: {e}", exc_info=True)
                failed_content = f"Title: {emb.title}\nDesc: {emb.description}\n" + "".join([f"\nFld ({f.name}):\n{f.value}\n" for f in emb.fields])
                await self._send_long_text_as_file(target_channel, failed_content, f"err_emb_{idx+1}.txt", "Gagal kirim embed, kontennya sbg file:")
                if idx == 0 and remaining_text.strip(): await self._send_long_text_as_file(target_channel, remaining_text, "sisa_respons.txt", "Sisa (gagal embed):"); remaining_text = "" 
                break 
        if remaining_text.strip(): await self._send_long_text_as_file(target_channel, remaining_text, "respons_lanjutan.txt", "Respons lanjutan (melebihi embed):")

    async def _process_and_send_text_response(self, message_or_interaction, response_obj: genai_types.GenerateContentResponse, context: str, is_interaction: bool = False):
        response_text = ""; # ... (Ekstraksi teks dari respons API tetap sama) ...
        if hasattr(response_obj, 'text') and response_obj.text: response_text = response_obj.text
        elif hasattr(response_obj, 'candidates') and response_obj.candidates:
            candidate = response_obj.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                response_text = "".join([p.text for p in candidate.content.parts if hasattr(p, 'text') and p.text])
            elif hasattr(candidate, 'text') and candidate.text: response_text = candidate.text
        
        title_prefix = f"Respons Noelle ({context})"; footer_txt = ""; target_ch: discord.abc.Messageable
        msg_to_reply: discord.Message | None = None; interaction_to_fup: discord.Interaction | None = None
        initial_sender = None

        if is_interaction:
            interaction_to_fup = message_or_interaction; target_ch = message_or_interaction.channel
            footer_txt = f"Diminta oleh: {message_or_interaction.user.display_name}"
            initial_sender = interaction_to_fup.followup.send
        else: 
            msg_to_reply = message_or_interaction; target_ch = message_or_interaction.channel
            footer_txt = f"Untuk: {message_or_interaction.author.display_name}"
            initial_sender = msg_to_reply.reply

        if not response_text.strip(): # ... (Penanganan respons kosong/diblokir tetap sama) ...
            if hasattr(response_obj, 'prompt_feedback') and response_obj.prompt_feedback:
                block_reason_val = response_obj.prompt_feedback.block_reason
                if block_reason_val != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                    try: block_name = genai_types.BlockedReason(block_reason_val).name
                    except ValueError: block_name = f"UNKNOWN_{block_reason_val}"
                    _logger.warning(f"({context}) Prompt diblokir. Alasan: {block_name}.")
                    await initial_sender(f"Maaf, permintaan Anda diblokir ({block_name}).", ephemeral=is_interaction)
                    return
            _logger.warning(f"({context}) Gemini mengembalikan respons kosong.")
            await initial_sender("Maaf, saya tidak bisa memberikan respons saat ini.", ephemeral=is_interaction)
            return
        try:
            if context == "Info Tambahan Gambar" and is_interaction:
                await self._send_text_in_embeds(target_ch, response_text, title_prefix, footer_txt, None, None)
            else:
                await self._send_text_in_embeds(target_ch, response_text, title_prefix, footer_txt, msg_to_reply, interaction_to_fup)
            _logger.info(f"({context}) Respons teks selesai diproses.")
        except Exception as e: # ... (Error handling akhir tetap sama) ...
            _logger.error(f"({context}) Error besar saat _process_and_send_text_response: {e}", exc_info=True)
            err_msg = "Terjadi kesalahan signifikan saat menampilkan respons."
            try:
                if is_interaction:
                    if not message_or_interaction.response.is_done(): await message_or_interaction.response.send_message(err_msg, ephemeral=True)
                    else: await message_or_interaction.followup.send(err_msg, ephemeral=True)
                else: await message_or_interaction.reply(err_msg)
            except Exception: _logger.error(f"({context}) Gagal kirim error akhir.", exc_info=True)


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        global _ai_service_enabled
        if not _ai_service_enabled or message.author.bot or message.guild is None or _gemini_client is None:
            return

        config = database.get_server_config(message.guild.id)
        ai_channel_id = config.get('ai_channel_id')
        bot_user = self.bot.user
        is_mentioned = bot_user and bot_user.mention in message.content
        in_ai_channel = ai_channel_id is not None and message.channel.id == ai_channel_id
        if not in_ai_channel and not is_mentioned: return

        text_content = message.content
        if is_mentioned: text_content = text_content.replace(bot_user.mention, '').strip()
        is_effectively_empty_after_mention_removal = not text_content and not message.attachments
        if is_mentioned and is_effectively_empty_after_mention_removal:
            await message.reply("Halo! Ada yang bisa saya bantu? (Sebut nama saya dengan pertanyaan Anda)"); return

        if in_ai_channel:
            context_log_prefix = f"AI Channel Session ({message.channel.id})"
            _logger.info(f"({context_log_prefix}) Pesan dari {message.author.name}")
            async with message.channel.typing():
                try:
                    chat_session = self.active_chat_sessions.get(message.channel.id)
                    current_total_tokens = self.chat_context_token_counts.get(message.channel.id, 0)

                    if chat_session is None:
                        try: _gemini_client.models.get(model=GEMINI_TEXT_MODEL_NAME)
                        except Exception:
                            _logger.error(f"({context_log_prefix}) Model '{GEMINI_TEXT_MODEL_NAME}' tidak diakses. Sesi tidak dimulai.")
                            await message.reply(f"Model AI ({GEMINI_TEXT_MODEL_NAME}) tidak tersedia."); return
                        
                        chat_session = _gemini_client.chats.create(model=GEMINI_TEXT_MODEL_NAME, history=[])
                        self.active_chat_sessions[message.channel.id] = chat_session
                        self.chat_context_token_counts[message.channel.id] = 0 
                        current_total_tokens = 0
                        _logger.info(f"({context_log_prefix}) Sesi chat baru dimulai.")
                    
                    self.chat_session_last_active[message.channel.id] = datetime.datetime.now(datetime.timezone.utc)
                    user_input_parts_for_api = []
                    if text_content: user_input_parts_for_api.append(text_content)
                    image_attachments = [att for att in message.attachments if 'image' in att.content_type]
                    if image_attachments:
                        if len(image_attachments) > 4: await message.reply("Maks. 4 gambar."); return
                        for attachment in image_attachments:
                            try:
                                image_bytes = await attachment.read(); pil_image = Image.open(io.BytesIO(image_bytes))
                                user_input_parts_for_api.append(pil_image)
                            except Exception as img_e:
                                _logger.error(f"({context_log_prefix}) Gagal proses gambar: {img_e}", exc_info=True)
                                await message.channel.send(f"Gagal proses gambar: {attachment.filename}")
                                if len(image_attachments) == 1 and not text_content: return
                    if not user_input_parts_for_api: _logger.debug(f"({context_log_prefix}) Tidak ada input valid."); return

                    # --- PERBAIKAN: Hitung token input pengguna ---
                    # Buat list of Parts untuk count_tokens
                    parts_for_counting_input = []
                    for item in user_input_parts_for_api:
                        if isinstance(item, str):
                            parts_for_counting_input.append(genai_types.Part(text=item))
                        elif isinstance(item, Image.Image): # PIL.Image
                            # Konversi PIL.Image ke Part dengan inline_data
                            buffered = io.BytesIO()
                            img_format = item.format if item.format else "PNG" # Default ke PNG jika format tidak diketahui
                            try:
                                item.save(buffered, format=img_format)
                                img_bytes = buffered.getvalue()
                                mime_type = Image.MIME.get(img_format) or f"image/{img_format.lower()}"
                                parts_for_counting_input.append(genai_types.Part(inline_data=genai_types.Blob(data=img_bytes, mime_type=mime_type)))
                            except Exception as e_pil_save:
                                _logger.error(f"({context_log_prefix}) Gagal konversi PIL Image ke Part untuk counting: {e_pil_save}")
                                # Jika gagal konversi, mungkin lewati part ini untuk counting atau beri nilai default
                    
                    if parts_for_counting_input:
                        user_input_content_for_count = genai_types.Content(parts=parts_for_counting_input, role="user")
                        try:
                            # --- PERBAIKAN: Tambahkan argumen 'model' ---
                            count_resp = await asyncio.to_thread(
                                _gemini_client.models.count_tokens, 
                                model=GEMINI_TEXT_MODEL_NAME, # Tambahkan nama model
                                contents=[user_input_content_for_count]
                            )
                            current_total_tokens += count_resp.total_tokens
                        except Exception as e:
                            _logger.error(f"({context_log_prefix}) Gagal hitung token input user: {e}", exc_info=True) # Tambah exc_info
                    # ------------------------------------------------

                    api_response = await asyncio.to_thread(chat_session.send_message, message=user_input_parts_for_api)
                    _logger.info(f"({context_log_prefix}) Menerima respons dari sesi chat Gemini.")

                    # --- PERBAIKAN: Hitung token output model ---
                    if hasattr(api_response, 'candidates') and api_response.candidates and \
                       hasattr(api_response.candidates[0], 'content'):
                        model_response_content_for_count = api_response.candidates[0].content
                        try:
                            # --- PERBAIKAN: Tambahkan argumen 'model' ---
                            count_resp = await asyncio.to_thread(
                                _gemini_client.models.count_tokens, 
                                model=GEMINI_TEXT_MODEL_NAME, # Tambahkan nama model
                                contents=[model_response_content_for_count]
                            )
                            current_total_tokens += count_resp.total_tokens
                        except Exception as e:
                            _logger.error(f"({context_log_prefix}) Gagal hitung token output model: {e}", exc_info=True) # Tambah exc_info
                    
                    self.chat_context_token_counts[message.channel.id] = current_total_tokens 
                    _logger.info(f"({context_log_prefix}) Perkiraan total token saat ini: {current_total_tokens}")
                    # -----------------------------------------------

                    await self._process_and_send_text_response(message, api_response, context_log_prefix, is_interaction=False)
                    
                    if current_total_tokens > MAX_CONTEXT_TOKENS:
                        _logger.warning(f"({context_log_prefix}) Konteks token ({current_total_tokens}) > batas ({MAX_CONTEXT_TOKENS}). Mereset sesi.")
                        await message.channel.send(f"✨ Sesi percakapan telah mencapai batasnya dan akan direset! ✨")
                        self._clear_session_data(message.channel.id)
                    
                except (InvalidArgument, FailedPrecondition) as e: _logger.warning(f"({context_log_prefix}) Error API (safety/prompt): {e}"); await message.reply(f"Permintaan tidak dapat diproses: {e}")
                except GoogleAPIError as e: _logger.error(f"({context_log_prefix}) Error API Google: {e}", exc_info=True); await message.reply(f"Error API AI: {e}")
                except Exception as e: _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True); await message.reply(f"Error tak terduga: {type(e).__name__} - {e}")
            return

        if is_mentioned: # ... (Logika mention stateless tetap sama) ...
            # ... (Tidak ada perubahan di sini karena tidak menggunakan sesi atau penghitungan token sesi) ...
            context_log_prefix = "Bot Mention" 
            _logger.info(f"({context_log_prefix}) Memproses mention dari {message.author.name}...")
            async with message.channel.typing():
                try:
                    if not text_content: await message.reply("Halo! Ada yang bisa saya bantu?"); return
                    api_response = await asyncio.to_thread(
                        _gemini_client.models.generate_content, model=GEMINI_TEXT_MODEL_NAME, contents=text_content)
                    _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini.")
                    await self._process_and_send_text_response(message, api_response, context_log_prefix, is_interaction=False)
                except (InvalidArgument, FailedPrecondition) as e: _logger.warning(f"({context_log_prefix}) Error API (safety/prompt): {e}"); await message.reply(f"Permintaan tidak dapat diproses: {e}")
                except GoogleAPIError as e: _logger.error(f"({context_log_prefix}) Error API Google: {e}", exc_info=True); await message.reply(f"Error API AI: {e}")
                except Exception as e: _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True); await message.reply(f"Error tak terduga: {type(e).__name__} - {e}")
            return


    ai_group = app_commands.Group(name="ai", description="Perintah terkait manajemen fitur AI Noelle.")

    @ai_group.command(name="clear_context", description="Membersihkan histori percakapan saat ini di channel AI ini.")
    async def ai_clear_context(self, interaction: discord.Interaction):
        global _ai_service_enabled
        if not _ai_service_enabled: await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True); return
        if not await self._ensure_ai_channel(interaction): return

        channel_id = interaction.channel_id
        if channel_id in self.active_chat_sessions: # Cukup cek salah satu
            self._clear_session_data(channel_id)
            await interaction.response.send_message("✨ Konteks percakapan di channel ini telah dibersihkan.", ephemeral=False)
            _logger.info(f"Konteks chat untuk channel {channel_id} dibersihkan oleh {interaction.user.name}.")
        else:
            await interaction.response.send_message("Tidak ada sesi chat aktif untuk dibersihkan di channel ini.", ephemeral=True)

    @ai_group.command(name="session_status", description="Menampilkan status sesi chat saat ini di channel AI ini.")
    async def ai_session_status(self, interaction: discord.Interaction):
        global _ai_service_enabled
        if not _ai_service_enabled: await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True); return
        if not await self._ensure_ai_channel(interaction): return

        channel_id = interaction.channel_id
        if channel_id in self.active_chat_sessions : 
            last_active_dt = self.chat_session_last_active.get(channel_id)
            last_active_str = discord.utils.format_dt(last_active_dt, "R") if last_active_dt else "Baru saja dimulai"
            
            token_count_display = self.chat_context_token_counts.get(channel_id, 0)
            
            # Jika token count 0 tapi sesi ada, coba hitung ulang dari histori internal (jika Chat object punya cara akses)
            # Namun, karena kita tidak punya akses langsung ke Chat.history, kita tidak bisa melakukan ini.
            # Jadi, jika token count 0, itu berarti sesi baru atau baru direset.

            timeout_dt = last_active_dt + datetime.timedelta(minutes=SESSION_TIMEOUT_MINUTES) if last_active_dt else None
            timeout_str = discord.utils.format_dt(timeout_dt, "R") if timeout_dt else "N/A"

            embed = discord.Embed(title=f"Status Sesi AI - #{interaction.channel.name}", color=discord.Color.blue())
            embed.add_field(name="Status Sesi", value="Aktif", inline=False)
            embed.add_field(name="Aktivitas Terakhir", value=last_active_str, inline=True)
            embed.add_field(name="Perkiraan Total Token Konteks", value=f"{token_count_display} / {MAX_CONTEXT_TOKENS}", inline=True)
            embed.add_field(name="Timeout Sesi Berikutnya", value=timeout_str, inline=False)
            embed.set_footer(text="Konteks akan direset jika melebihi batas token atau timeout.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada sesi chat aktif di channel ini.", ephemeral=True)

    # ... (ai_toggle_service, generate_image_slash, cog_app_command_error, setup tetap sama) ...
    @ai_group.command(name="toggle_service", description="Mengaktifkan atau menonaktifkan layanan AI Noelle secara global.")
    @app_commands.choices(status=[app_commands.Choice(name="Aktifkan", value="on"), app_commands.Choice(name="Nonaktifkan", value="off")])
    @commands.has_permissions(manage_guild=True) # Hanya admin server
    async def ai_toggle_service(self, interaction: discord.Interaction, status: app_commands.Choice[str]):
        global _ai_service_enabled, _gemini_client
        new_status_bool = status.value == "on"
        if new_status_bool == _ai_service_enabled:
            await interaction.response.send_message(f"Layanan AI sudah dalam status **{'aktif' if _ai_service_enabled else 'nonaktif'}**.", ephemeral=True); return
        _ai_service_enabled = new_status_bool
        if _ai_service_enabled:
            if _gemini_client is None: initialize_gemini_client()
            if _gemini_client:
                for ch_id in list(self.active_chat_sessions.keys()): self._clear_session_data(ch_id)
                _logger.info("Layanan AI diaktifkan. Semua sesi chat aktif telah dibersihkan.")
                await interaction.response.send_message("✅ Layanan AI Noelle telah **diaktifkan** global. Sesi sebelumnya direset.", ephemeral=False)
            else:
                _ai_service_enabled = False 
                _logger.error("Gagal aktifkan layanan AI karena klien Gemini tidak dapat diinisialisasi.")
                await interaction.response.send_message("⚠️ Gagal aktifkan layanan AI. Cek GOOGLE_API_KEY.", ephemeral=True)
        else:
            for ch_id in list(self.active_chat_sessions.keys()): self._clear_session_data(ch_id)
            _logger.info("Layanan AI dinonaktifkan. Semua sesi chat aktif telah dibersihkan.")
            await interaction.response.send_message("🛑 Layanan AI Noelle telah **dinonaktifkan** global. Sesi dihentikan.", ephemeral=False)

    @app_commands.command(name='generate_image', description='Membuat gambar berdasarkan deskripsi teks menggunakan AI.')
    @app_commands.describe(prompt='Deskripsikan gambar yang ingin Anda buat.')
    @app_commands.guild_only()
    async def generate_image_slash(self, interaction: discord.Interaction, prompt: str):
        global _ai_service_enabled
        if not _ai_service_enabled:
            await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True); return
        
        _logger.info(f"Menerima /generate_image dari {interaction.user.name} dengan prompt: '{prompt}'...")
        response_handler = interaction.response 
        send_method_ephemeral = response_handler.send_message if not response_handler.is_done() else interaction.followup.send

        if _gemini_client is None:
            _logger.warning("Klien Gemini tidak tersedia untuk /generate_image.")
            await send_method_ephemeral("Layanan AI tidak tersedia.", ephemeral=True)
            return

        if not await self._ensure_ai_channel(interaction): return

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

            generated_text_parts = []; generated_image_bytes = None; mime_type_image = "image/png" 
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
                        await interaction.followup.send(f"Maaf, permintaan gambar Anda diblokir ({block_reason_name}).", ephemeral=True); return
                _logger.warning(f"Gemini mengembalikan respons kosong untuk gambar. Prompt: '{prompt}'.")
                await interaction.followup.send("Gagal menghasilkan gambar. AI memberikan respons kosong atau tidak terduga.", ephemeral=True)
        except (InvalidArgument, FailedPrecondition) as e: _logger.warning(f"Error API (safety/prompt) /generate_image: {e}. Prompt: '{prompt}'"); await interaction.followup.send(f"Permintaan tidak dapat diproses: {e}", ephemeral=True)
        except GoogleAPIError as e: _logger.error(f"Error API Google /generate_image: {e}. Prompt: '{prompt}'", exc_info=True); await interaction.followup.send(f"Error API AI: {e}", ephemeral=True)
        except Exception as e: _logger.error(f"Error tak terduga /generate_image: {e}. Prompt: '{prompt}'", exc_info=True); await interaction.followup.send(f"Error tak terduga: {type(e).__name__} - {e}", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
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
    global _ai_service_enabled 
    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY tidak ada. AICog tidak dimuat.")
        _ai_service_enabled = False 
        return
    if _gemini_client is None: 
        _logger.error("Klien Gemini gagal inisialisasi. AICog tidak dimuat.")
        _ai_service_enabled = False 
        return
    _ai_service_enabled = True 
    cog_instance = AICog(bot)
    await bot.add_cog(cog_instance)
    _logger.info("AICog berhasil dimuat.")