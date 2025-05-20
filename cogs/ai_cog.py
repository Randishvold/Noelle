# cogs/ai_cog.py

import discord
import os
import google.genai as genai
from google.genai import types as genai_types
# HAPUS BARIS INI: from google.genai.chats import ChatSession 
# Kita akan menggunakan tipe genai.chats.Chat secara langsung
from google.api_core.exceptions import GoogleAPIError, InvalidArgument, FailedPrecondition
import database
from discord.ext import commands, tasks
from discord import app_commands
import logging
# from PIL import Image # Hanya jika Anda memproses gambar input secara langsung selain dari lampiran
import io
import asyncio
import datetime # Untuk timestamp sesi
# import re # Tidak digunakan lagi secara aktif di versi ini, kecuali jika _find_sensible_split_point memerlukannya

# ... (Konfigurasi logging, konstanta model, kunci API, inisialisasi klien tetap sama) ...
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
    global _gemini_client
    if GOOGLE_API_KEY is None:
        _logger.error("Variabel lingkungan GOOGLE_API_KEY tidak diatur. Fitur AI tidak akan tersedia.")
        return
    try:
        _gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
        _logger.info("Klien Google GenAI berhasil diinisialisasi.")
        # Verifikasi model opsional
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
        # Key: channel_id, Value: objek genai.chats.Chat
        self.active_chat_sessions: dict[int, genai.chats.Chat] = {} # PERUBAHAN TIPE ANOTASI
        self.chat_session_last_active: dict[int, datetime.datetime] = {}
        self.chat_token_counts: dict[int, int] = {} 
        
        self.session_cleanup_loop.start()
        _logger.info("AICog instance telah dibuat dan session cleanup loop dimulai.")

 
    def cog_unload(self):
        self.session_cleanup_loop.cancel() # Hentikan loop saat cog di-unload
        _logger.info("AICog di-unload dan session cleanup loop dihentikan.")

    # --- Helper untuk command AI channel ---
    async def _is_ai_channel(self, interaction: discord.Interaction) -> bool:
        """Pengecekan apakah interaksi terjadi di channel AI yang dikonfigurasi."""
        if not interaction.guild_id: return False # Bukan di server
        config = database.get_server_config(interaction.guild_id)
        ai_channel_id = config.get('ai_channel_id')
        return ai_channel_id is not None and interaction.channel_id == ai_channel_id

    async def _ensure_ai_channel(self, interaction: discord.Interaction) -> bool:
        """Memastikan command hanya bisa di AI channel, mengirim pesan jika tidak."""
        config = database.get_server_config(interaction.guild_id)
        ai_channel_id = config.get('ai_channel_id')

        if ai_channel_id is None:
            await interaction.response.send_message(
                "Channel AI belum diatur. Minta admin atur via `/config ai_channel`.",
                ephemeral=True
            )
            return False
        
        if interaction.channel_id != ai_channel_id:
            designated_channel = self.bot.get_channel(ai_channel_id)
            channel_mention = designated_channel.mention if designated_channel else f"channel AI (ID: {ai_channel_id})"
            await interaction.response.send_message(
                f"Perintah ini hanya dapat digunakan di {channel_mention}.",
                ephemeral=True
            )
            return False
        return True

    # --- Loop Pembersihan Sesi ---
    @tasks.loop(minutes=5) # Cek setiap 5 menit
    async def session_cleanup_loop(self):
        """Membersihkan sesi chat yang sudah timeout."""
        now = datetime.datetime.now(datetime.timezone.utc)
        timed_out_sessions_channel_ids = []
        for channel_id, last_active_time in list(self.chat_session_last_active.items()): # list() untuk copy
            if (now - last_active_time).total_seconds() > SESSION_TIMEOUT_MINUTES * 60:
                timed_out_sessions_channel_ids.append(channel_id)
        
        for channel_id in timed_out_sessions_channel_ids:
            if channel_id in self.active_chat_sessions:
                del self.active_chat_sessions[channel_id]
            if channel_id in self.chat_session_last_active:
                del self.chat_session_last_active[channel_id]
            if channel_id in self.chat_token_counts:
                del self.chat_token_counts[channel_id]
            _logger.info(f"Sesi chat untuk channel {channel_id} telah timeout dan dibersihkan.")
            # Opsional: kirim pesan ke channel bahwa sesi direset karena timeout
            # channel = self.bot.get_channel(channel_id)
            # if channel:
            #     try: await channel.send("Sesi chat dengan Noelle telah direset karena tidak aktif.")
            #     except Exception: pass

    @session_cleanup_loop.before_loop
    async def before_session_cleanup_loop(self):
        await self.bot.wait_until_ready() # Tunggu bot siap sebelum loop dimulai

    # ... (_send_long_text_as_file dan _find_sensible_split_point tetap sama) ...
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

    # ... (_send_text_in_embeds dan _process_and_send_text_response tetap sama seperti versi sebelumnya) ...
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
        response_text = "" # Ekstraksi teks dari respons API
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

        if not response_text.strip(): # Penanganan respons kosong/diblokir
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
            if context == "Info Tambahan Gambar" and is_interaction: # Teks pendamping gambar, kirim ke channel
                await self._send_text_in_embeds(target_ch, response_text, title_prefix, footer_txt, None, None)
            else:
                await self._send_text_in_embeds(target_ch, response_text, title_prefix, footer_txt, msg_to_reply, interaction_to_fup)
            _logger.info(f"({context}) Respons teks selesai diproses.")
        except Exception as e:
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
        
        # Hanya proses jika di AI channel atau dimention
        if not in_ai_channel and not is_mentioned:
            return

        # Logika untuk membersihkan mention dan mendapatkan konten utama
        text_content = message.content
        if is_mentioned:
            text_content = text_content.replace(bot_user.mention, '').strip()

        # Jika setelah membersihkan mention tidak ada teks dan tidak ada lampiran, dan ini adalah mention, maka sapa.
        # Atau jika di AI channel, pesan yang hanya mention (setelah mention dihilangkan jadi kosong) juga akan disapa.
        is_effectively_empty_after_mention_removal = not text_content and not message.attachments
        
        if is_mentioned and is_effectively_empty_after_mention_removal:
            await message.reply("Halo! Ada yang bisa saya bantu? (Sebut nama saya dengan pertanyaan Anda)")
            return

        # --- Logika Sesi Chat untuk AI Channel ---
        if in_ai_channel:
            context_log_prefix = f"AI Channel Session ({message.channel.id})"
            _logger.info(f"({context_log_prefix}) Pesan dari {message.author.name}")
            
            async with message.channel.typing():
                try:
                    # Dapatkan atau buat sesi chat
                    chat_session = self.active_chat_sessions.get(message.channel.id)
                    if chat_session is None:
                        # Periksa apakah model teks tersedia sebelum membuat sesi
                        try:
                            _gemini_client.models.get(model=GEMINI_TEXT_MODEL_NAME) # Cek cepat
                        except Exception:
                            _logger.error(f"({context_log_prefix}) Model teks '{GEMINI_TEXT_MODEL_NAME}' tidak dapat diakses. Tidak dapat memulai sesi chat.")
                            await message.reply(f"Maaf, model AI ({GEMINI_TEXT_MODEL_NAME}) tidak tersedia saat ini.")
                            return

                        chat_session = _gemini_client.chats.create(model=GEMINI_TEXT_MODEL_NAME)
                        self.active_chat_sessions[message.channel.id] = chat_session
                        self.chat_token_counts[message.channel.id] = 0 # Reset token count
                        _logger.info(f"({context_log_prefix}) Sesi chat baru dimulai.")
                    
                    # Update waktu aktivitas
                    self.chat_session_last_active[message.channel.id] = datetime.datetime.now(datetime.timezone.utc)

                    # Siapkan input untuk Gemini (bisa teks saja atau teks + gambar)
                    user_input_parts = []
                    if text_content: # Teks yang sudah dibersihkan dari mention
                        user_input_parts.append(text_content)
                    
                    image_attachments = [att for att in message.attachments if 'image' in att.content_type]
                    if image_attachments:
                        if len(image_attachments) > 4:
                            await message.reply("Mohon berikan maksimal 4 gambar."); return
                        for attachment in image_attachments:
                            try:
                                image_bytes = await attachment.read()
                                pil_image = Image.open(io.BytesIO(image_bytes))
                                user_input_parts.append(pil_image) # Tambahkan objek PIL Image
                            except Exception as img_e:
                                _logger.error(f"({context_log_prefix}) Gagal proses gambar lampiran: {img_e}", exc_info=True)
                                await message.channel.send(f"Gagal memproses gambar: {attachment.filename}")
                                # Jika hanya gambar ini dan gagal, dan tidak ada teks, jangan lanjutkan
                                if len(image_attachments) == 1 and not text_content: return
                    
                    if not user_input_parts: # Jika tidak ada input sama sekali (seharusnya sudah ditangani di atas)
                        _logger.debug(f"({context_log_prefix}) Tidak ada input yang valid untuk dikirim ke AI.")
                        return

                    # Kirim pesan ke sesi chat
                    # `send_message` di ChatSession menerima `contents`
                    api_response = await asyncio.to_thread(chat_session.send_message, contents=user_input_parts)
                    _logger.info(f"({context_log_prefix}) Menerima respons dari sesi chat Gemini.")
                    await self._process_and_send_text_response(message, api_response, context_log_prefix, is_interaction=False)

                    # Perbarui dan cek jumlah token
                    if chat_session.history: # Pastikan histori tidak kosong
                        try:
                            token_count_response = await asyncio.to_thread(
                                _gemini_client.models.count_tokens,
                                contents=chat_session.history # Hitung token dari seluruh histori sesi
                            )
                            current_tokens = token_count_response.total_tokens
                            self.chat_token_counts[message.channel.id] = current_tokens
                            _logger.info(f"({context_log_prefix}) Perkiraan token saat ini: {current_tokens}")

                            if current_tokens > MAX_CONTEXT_TOKENS:
                                _logger.warning(f"({context_log_prefix}) Konteks token ({current_tokens}) melebihi batas ({MAX_CONTEXT_TOKENS}). Mereset sesi.")
                                await message.channel.send(f"✨ Sesi percakapan telah mencapai batasnya dan akan direset untuk memulai yang baru! ✨")
                                # Buat sesi baru (clear context)
                                chat_session = _gemini_client.chats.create(model=GEMINI_TEXT_MODEL_NAME)
                                self.active_chat_sessions[message.channel.id] = chat_session
                                self.chat_token_counts[message.channel.id] = 0
                        except Exception as e:
                            _logger.error(f"({context_log_prefix}) Gagal menghitung token histori: {e}", exc_info=True)
                    
                except (InvalidArgument, FailedPrecondition) as e:
                    _logger.warning(f"({context_log_prefix}) Error API Google (safety/prompt): {e}")
                    await message.reply(f"Permintaan tidak dapat diproses: {e}")
                except GoogleAPIError as e: 
                    _logger.error(f"({context_log_prefix}) Error API Google: {e}", exc_info=True)
                    await message.reply(f"Error API AI: {e}")
                except Exception as e: 
                    _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True)
                    await message.reply("Error tak terduga.")
            return # Selesai untuk AI Channel

        # --- Logika Mention (di luar AI channel, atau jika hanya mention di AI channel) ---
        # Tetap stateless, tidak menggunakan sesi chat
        if is_mentioned: # text_content sudah dibersihkan dari mention di awal
            context_log_prefix = "Bot Mention"
            _logger.info(f"({context_log_prefix}) Memproses mention dari {message.author.name}...")
            async with message.channel.typing():
                try:
                    # Untuk mention, kita hanya proses teks. Gambar diabaikan.
                    if not text_content: # Jika hanya mention tanpa teks lain (sudah di-handle di atas sebenarnya)
                        await message.reply("Halo! Ada yang bisa saya bantu?"); return

                    api_response = await asyncio.to_thread(
                        _gemini_client.models.generate_content,
                        model=GEMINI_TEXT_MODEL_NAME,
                        contents=text_content # Kirim hanya teks
                    )
                    _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini.")
                    await self._process_and_send_text_response(message, api_response, context_log_prefix, is_interaction=False)
                except (InvalidArgument, FailedPrecondition) as e: _logger.warning(f"({context_log_prefix}) Error API (safety/prompt): {e}"); await message.reply(f"Permintaan tidak dapat diproses: {e}")
                except GoogleAPIError as e: _logger.error(f"({context_log_prefix}) Error API Google: {e}", exc_info=True); await message.reply(f"Error API AI: {e}")
                except Exception as e: _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True); await message.reply("Error tak terduga.")
            return

    # --- Grup Command AI ---
    ai_group = app_commands.Group(name="ai", description="Perintah terkait manajemen fitur AI Noelle.")

    @ai_group.command(name="clear_context", description="Membersihkan histori percakapan saat ini di channel AI ini.")
    async def ai_clear_context(self, interaction: discord.Interaction):
        global _ai_service_enabled
        if not _ai_service_enabled:
            await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True); return
        if not await self._ensure_ai_channel(interaction): return # Pastikan di AI channel

        channel_id = interaction.channel_id
        if channel_id in self.active_chat_sessions:
            del self.active_chat_sessions[channel_id]
            if channel_id in self.chat_session_last_active: del self.chat_session_last_active[channel_id]
            if channel_id in self.chat_token_counts: del self.chat_token_counts[channel_id]
            await interaction.response.send_message("✨ Konteks percakapan di channel ini telah dibersihkan. Sesi chat baru akan dimulai.", ephemeral=False)
            _logger.info(f"Konteks chat untuk channel {channel_id} dibersihkan oleh {interaction.user.name}.")
        else:
            await interaction.response.send_message("Tidak ada sesi chat aktif untuk dibersihkan di channel ini.", ephemeral=True)

    @ai_group.command(name="session_status", description="Menampilkan status sesi chat saat ini di channel AI ini.")
    async def ai_session_status(self, interaction: discord.Interaction):
        global _ai_service_enabled
        if not _ai_service_enabled:
            await interaction.response.send_message("Layanan AI sedang tidak aktif.", ephemeral=True); return
        if not await self._ensure_ai_channel(interaction): return

        channel_id = interaction.channel_id
        if channel_id in self.active_chat_sessions:
            last_active_dt = self.chat_session_last_active.get(channel_id)
            last_active_str = discord.utils.format_dt(last_active_dt, "R") if last_active_dt else "Tidak diketahui"
            
            token_count = self.chat_token_counts.get(channel_id, 0)
            if token_count == 0 and self.active_chat_sessions[channel_id].history: # Jika 0 tapi ada histori, hitung ulang
                try:
                    count_resp = await asyncio.to_thread(_gemini_client.models.count_tokens, contents=self.active_chat_sessions[channel_id].history)
                    token_count = count_resp.total_tokens
                    self.chat_token_counts[channel_id] = token_count
                except Exception as e:
                    _logger.error(f"Gagal menghitung token untuk status sesi di channel {channel_id}: {e}")
                    token_count = "Gagal menghitung"


            timeout_dt = last_active_dt + datetime.timedelta(minutes=SESSION_TIMEOUT_MINUTES) if last_active_dt else None
            timeout_str = discord.utils.format_dt(timeout_dt, "R") if timeout_dt else "N/A"

            embed = discord.Embed(title=f"Status Sesi AI - #{interaction.channel.name}", color=discord.Color.blue())
            embed.add_field(name="Status Sesi", value="Aktif", inline=False)
            embed.add_field(name="Aktivitas Terakhir", value=last_active_str, inline=True)
            embed.add_field(name="Perkiraan Token Konteks", value=f"{token_count} / {MAX_CONTEXT_TOKENS}", inline=True)
            embed.add_field(name="Timeout Sesi Berikutnya", value=timeout_str, inline=False)
            embed.set_footer(text="Konteks akan direset jika melebihi batas token atau timeout.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("Tidak ada sesi chat aktif di channel ini. Kirim pesan untuk memulai!", ephemeral=True)

    @ai_group.command(name="toggle_service", description="Mengaktifkan atau menonaktifkan layanan AI Noelle secara global.")
    @app_commands.choices(status=[
        app_commands.Choice(name="Aktifkan", value="on"),
        app_commands.Choice(name="Nonaktifkan", value="off"),
    ])
    @commands.has_permissions(manage_guild=True) # Hanya admin server
    async def ai_toggle_service(self, interaction: discord.Interaction, status: app_commands.Choice[str]):
        global _ai_service_enabled, _gemini_client
        
        new_status_bool = status.value == "on"

        if new_status_bool == _ai_service_enabled:
            await interaction.response.send_message(f"Layanan AI sudah dalam status **{'aktif' if _ai_service_enabled else 'nonaktif'}**.", ephemeral=True)
            return

        _ai_service_enabled = new_status_bool
        
        if _ai_service_enabled:
            if _gemini_client is None: # Jika client belum ada (misal karena API key baru ditambahkan)
                initialize_gemini_client() # Coba inisialisasi lagi
            
            if _gemini_client:
                # Bersihkan semua sesi aktif saat layanan diaktifkan kembali
                self.active_chat_sessions.clear()
                self.chat_session_last_active.clear()
                self.chat_token_counts.clear()
                _logger.info("Layanan AI diaktifkan. Semua sesi chat aktif telah dibersihkan.")
                await interaction.response.send_message("✅ Layanan AI Noelle telah **diaktifkan** secara global. Semua sesi chat sebelumnya telah direset.", ephemeral=False)
            else:
                _ai_service_enabled = False # Gagal aktifkan jika client tidak bisa dibuat
                _logger.error("Gagal mengaktifkan layanan AI karena klien Gemini tidak dapat diinisialisasi.")
                await interaction.response.send_message("⚠️ Gagal mengaktifkan layanan AI. Pastikan GOOGLE_API_KEY sudah benar dan coba lagi.", ephemeral=True)
        else:
            # Saat menonaktifkan, kita juga membersihkan sesi
            self.active_chat_sessions.clear()
            self.chat_session_last_active.clear()
            self.chat_token_counts.clear()
            _logger.info("Layanan AI dinonaktifkan. Semua sesi chat aktif telah dibersihkan.")
            await interaction.response.send_message("🛑 Layanan AI Noelle telah **dinonaktifkan** secara global. Semua sesi chat telah dihentikan.", ephemeral=False)


    # ... (generate_image_slash tetap sama, termasuk validasi AI channel) ...
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

        if not await self._ensure_ai_channel(interaction): return # Validasi AI Channel

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

    # ... (cog_app_command_error tetap sama) ...
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
    global _ai_service_enabled # Pastikan variabel global bisa diakses
    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY tidak ada. AICog tidak dimuat.")
        _ai_service_enabled = False # Nonaktifkan layanan jika kunci tidak ada
        return
    if _gemini_client is None: # Jika inisialisasi gagal
        _logger.error("Klien Gemini gagal inisialisasi. AICog tidak dimuat.")
        _ai_service_enabled = False # Nonaktifkan layanan
        return
    
    # Jika semua baik, layanan AI diaktifkan (jika sebelumnya nonaktif karena error startup)
    _ai_service_enabled = True 
    cog_instance = AICog(bot)
    # Daftarkan grup command ke tree bot
    # bot.tree.add_command(cog_instance.ai_group) 
    await bot.add_cog(cog_instance)
    _logger.info("AICog berhasil dimuat dan grup command 'ai' ditambahkan.")