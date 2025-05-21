# Noelle_AI_Bot/ai_services/message_handler.py
import discord
from discord.ext import commands, tasks
import google.genai as genai
from google.genai import types as genai_types
from google.api_core.exceptions import InvalidArgument, FailedPrecondition, GoogleAPIError
import datetime
import asyncio
from PIL import Image
import io

# Impor dari modul lain dalam paket ai_services
from . import gemini_client as gemini_services # Akses klien dan status layanan
# Impor dari database (jika digunakan)
import database # Asumsikan database.py ada di root proyek atau sys.path diatur
# Impor dari utils
from utils import ai_utils 

_logger = logging.getLogger(__name__)

MAX_CONTEXT_TOKENS = 120000 
SESSION_TIMEOUT_MINUTES = 30

class MessageHandlerCog(commands.Cog, name="AI Message Handler"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_chat_sessions: dict[int, genai.chats.Chat] = {} 
        self.chat_session_last_active: dict[int, datetime.datetime] = {}
        self.chat_context_token_counts: dict[int, int] = {} 
        self.session_cleanup_loop.start()
        _logger.info("MessageHandlerCog (AI Channel) instance dibuat.")

    def cog_unload(self):
        self.session_cleanup_loop.cancel()

    def _clear_session_data(self, channel_id: int):
        if channel_id in self.active_chat_sessions: del self.active_chat_sessions[channel_id]
        if channel_id in self.chat_session_last_active: del self.chat_session_last_active[channel_id]
        if channel_id in self.chat_context_token_counts: del self.chat_context_token_counts[channel_id]

    @tasks.loop(minutes=5)
    async def session_cleanup_loop(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        timed_out_ids = [ch_id for ch_id, la_time in list(self.chat_session_last_active.items()) 
                         if (now - la_time).total_seconds() > SESSION_TIMEOUT_MINUTES * 60]
        for channel_id in timed_out_ids:
            self._clear_session_data(channel_id)
            _logger.info(f"Sesi chat AI Channel untuk {channel_id} timeout & dibersihkan.")
            # channel = self.bot.get_channel(channel_id)
            # if channel:
            #     try: await channel.send("Sesi chat dengan Noelle telah direset karena tidak aktif.",delete_after=60)
            #     except Exception: pass


    @session_cleanup_loop.before_loop
    async def before_session_cleanup_loop(self):
        await self.bot.wait_until_ready()

    async def _process_gemini_response(self, message_or_interaction, response_obj: genai_types.GenerateContentResponse, context_prefix: str, is_interaction: bool = False):
        """Memproses dan mengirim respons teks Gemini menggunakan ai_utils."""
        # Fungsi ini mirip dengan _process_and_send_text_response Anda sebelumnya, tapi memanggil ai_utils
        response_text = ""
        if hasattr(response_obj, 'text') and response_obj.text: response_text = response_obj.text
        elif hasattr(response_obj, 'candidates') and response_obj.candidates:
            candidate = response_obj.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                response_text = "".join([p.text for p in candidate.content.parts if hasattr(p, 'text') and p.text])
            elif hasattr(candidate, 'text') and candidate.text: response_text = candidate.text
        
        title = f"Respons Noelle ({context_prefix})"
        footer = ""
        target_channel_for_messages: discord.abc.Messageable
        msg_to_reply: discord.Message | None = None
        interaction_to_fup: discord.Interaction | None = None
        initial_sender_func = None

        if is_interaction:
            interaction_to_fup = message_or_interaction; target_channel_for_messages = message_or_interaction.channel
            footer = f"Diminta oleh: {message_or_interaction.user.display_name}"
            initial_sender_func = interaction_to_fup.followup.send
        else: 
            msg_to_reply = message_or_interaction; target_channel_for_messages = message_or_interaction.channel
            footer = f"Untuk: {message_or_interaction.author.display_name}"
            initial_sender_func = msg_to_reply.reply

        if not response_text.strip():
            if hasattr(response_obj, 'prompt_feedback') and response_obj.prompt_feedback:
                block_reason_val = response_obj.prompt_feedback.block_reason
                if block_reason_val != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                    try: block_name = genai_types.BlockedReason(block_reason_val).name
                    except ValueError: block_name = f"UNKNOWN_{block_reason_val}"
                    _logger.warning(f"({context_prefix}) Prompt diblokir. Alasan: {block_name}.")
                    await initial_sender_func(f"Maaf, permintaan Anda diblokir ({block_name}).", ephemeral=is_interaction)
                    return
            _logger.warning(f"({context_prefix}) Gemini mengembalikan respons kosong.")
            await initial_sender_func("Maaf, saya tidak bisa memberikan respons saat ini.", ephemeral=is_interaction)
            return
        try:
            if context_prefix == "Info Tambahan Gambar" and is_interaction:
                await ai_utils.send_text_in_embeds(target_channel_for_messages, response_text, title, footer, None, None)
            else:
                await ai_utils.send_text_in_embeds(target_channel_for_messages, response_text, title, footer, msg_to_reply, interaction_to_fup)
            _logger.info(f"({context_prefix}) Respons teks selesai diproses via ai_utils.")
        except Exception as e:
            _logger.error(f"({context_prefix}) Error besar saat _process_gemini_response: {e}", exc_info=True)
            err_msg = "Terjadi kesalahan signifikan saat menampilkan respons."
            try:
                if is_interaction:
                    if not message_or_interaction.response.is_done(): await message_or_interaction.response.send_message(err_msg, ephemeral=True)
                    else: await message_or_interaction.followup.send(err_msg, ephemeral=True)
                else: await message_or_interaction.reply(err_msg)
            except Exception: _logger.error(f"({context_prefix}) Gagal kirim error akhir.", exc_info=True)


    @commands.Cog.listener("on_message")
    async def ai_channel_message_listener(self, message: discord.Message):
        if not gemini_services.is_ai_service_enabled() or \
           message.author.bot or message.guild is None or \
           gemini_services.get_gemini_client() is None:
            return

        # Cek apakah ini channel AI
        guild_config = database.get_server_config(message.guild.id)
        ai_channel_id = guild_config.get('ai_channel_id')
        if not (ai_channel_id and message.channel.id == ai_channel_id):
            return # Bukan AI channel, abaikan untuk cog ini

        # Cek apakah pesan hanya mention (akan ditangani oleh MentionHandlerCog)
        bot_user = self.bot.user
        if bot_user and bot_user.mention in message.content:
            cleaned_content = message.content.replace(bot_user.mention, '').strip()
            if not cleaned_content and not message.attachments:
                # Ini hanya mention, biarkan MentionHandlerCog yang menangani jika ada
                return 

        context_log_prefix = f"AI Channel Session ({message.channel.id})"
        _logger.info(f"({context_log_prefix}) Pesan dari {message.author.name} di AI Channel.")
        
        async with message.channel.typing():
            try:
                client = gemini_services.get_gemini_client() # Dapatkan klien dari modul gemini_services
                chat_session = self.active_chat_sessions.get(message.channel.id)
                current_total_tokens = self.chat_context_token_counts.get(message.channel.id, 0)

                if chat_session is None:
                    # Pastikan model teks tersedia
                    try: client.models.get(model=gemini_services.GEMINI_TEXT_MODEL_NAME)
                    except Exception:
                        _logger.error(f"({context_log_prefix}) Model '{gemini_services.GEMINI_TEXT_MODEL_NAME}' tidak diakses. Sesi tidak dimulai.")
                        await message.reply(f"Model AI ({gemini_services.GEMINI_TEXT_MODEL_NAME}) tidak tersedia."); return
                    
                    chat_session = client.chats.create(model=gemini_services.GEMINI_TEXT_MODEL_NAME, history=[])
                    self.active_chat_sessions[message.channel.id] = chat_session
                    self.chat_context_token_counts[message.channel.id] = 0 
                    current_total_tokens = 0
                    _logger.info(f"({context_log_prefix}) Sesi chat baru dimulai.")
                
                self.chat_session_last_active[message.channel.id] = datetime.datetime.now(datetime.timezone.utc)
                
                user_input_parts_for_api = []
                text_content_cleaned = message.content # Asumsi mention sudah dihandle/dihilangkan jika perlu di level ini
                if bot_user and bot_user.mention in text_content_cleaned : # Hapus mention jika masih ada
                    text_content_cleaned = text_content_cleaned.replace(bot_user.mention, "").strip()

                if text_content_cleaned: user_input_parts_for_api.append(text_content_cleaned)
                
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
                            if len(image_attachments) == 1 and not text_content_cleaned: return
                if not user_input_parts_for_api: _logger.debug(f"({context_log_prefix}) Tidak ada input valid."); return

                # Hitung token input
                parts_for_counting_input = []
                for item in user_input_parts_for_api:
                    if isinstance(item, str): parts_for_counting_input.append(genai_types.Part(text=item))
                    elif isinstance(item, Image.Image):
                        buffered = io.BytesIO(); img_format = item.format or "PNG"
                        try:
                            item.save(buffered, format=img_format); img_bytes = buffered.getvalue()
                            mime = Image.MIME.get(img_format) or f"image/{img_format.lower()}"
                            parts_for_counting_input.append(genai_types.Part(inline_data=genai_types.Blob(data=img_bytes, mime_type=mime)))
                        except Exception as e_pil: _logger.error(f"Gagal konversi PIL ke Part: {e_pil}")
                if parts_for_counting_input:
                    user_input_content_for_count = genai_types.Content(parts=parts_for_counting_input, role="user")
                    try:
                        count_resp = await asyncio.to_thread(client.models.count_tokens, model=gemini_services.GEMINI_TEXT_MODEL_NAME, contents=[user_input_content_for_count])
                        current_total_tokens += count_resp.total_tokens
                    except Exception as e: _logger.error(f"({context_log_prefix}) Gagal hitung token input: {e}", exc_info=True)

                api_response = await asyncio.to_thread(chat_session.send_message, message=user_input_parts_for_api)
                _logger.info(f"({context_log_prefix}) Menerima respons dari sesi chat Gemini.")

                if hasattr(api_response, 'candidates') and api_response.candidates and hasattr(api_response.candidates[0], 'content'):
                    model_response_content_for_count = api_response.candidates[0].content
                    try:
                        count_resp = await asyncio.to_thread(client.models.count_tokens, model=gemini_services.GEMINI_TEXT_MODEL_NAME, contents=[model_response_content_for_count])
                        current_total_tokens += count_resp.total_tokens
                    except Exception as e: _logger.error(f"({context_log_prefix}) Gagal hitung token output: {e}", exc_info=True)
                self.chat_context_token_counts[message.channel.id] = current_total_tokens
                _logger.info(f"({context_log_prefix}) Total token: {current_total_tokens}")

                await self._process_gemini_response(message, api_response, context_log_prefix, is_interaction=False)
                
                if current_total_tokens > MAX_CONTEXT_TOKENS:
                    _logger.warning(f"({context_log_prefix}) Konteks token ({current_total_tokens}) > batas. Mereset sesi.")
                    await message.channel.send(f"✨ Sesi percakapan telah mencapai batasnya dan akan direset! ✨")
                    self._clear_session_data(message.channel.id)
            except (InvalidArgument, FailedPrecondition) as e: _logger.warning(f"({context_log_prefix}) Error API (safety/prompt): {e}"); await message.reply(f"Permintaan tidak dapat diproses: {e}")
            except GoogleAPIError as e: _logger.error(f"({context_log_prefix}) Error API Google: {e}", exc_info=True); await message.reply(f"Error API AI: {e}")
            except Exception as e: _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True); await message.reply(f"Error tak terduga: {type(e).__name__} - {e}")