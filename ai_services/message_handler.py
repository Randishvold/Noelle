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
import logging # Pastikan logging diimpor

from . import gemini_client as gemini_services
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

    def _clear_session_data(self, channel_id: int): # Fungsi ini sekarang ada di sini
        if channel_id in self.active_chat_sessions: del self.active_chat_sessions[channel_id]
        if channel_id in self.chat_session_last_active: del self.chat_session_last_active[channel_id]
        if channel_id in self.chat_context_token_counts: del self.chat_context_token_counts[channel_id]
        _logger.info(f"MESSAGE_HANDLER: Data sesi untuk channel {channel_id} dibersihkan.")


    @tasks.loop(minutes=5)
    async def session_cleanup_loop(self):
        # ... (Loop ini tetap sama, menggunakan self._clear_session_data) ...
        now = datetime.datetime.now(datetime.timezone.utc)
        timed_out_ids = [ch_id for ch_id, la_time in list(self.chat_session_last_active.items()) 
                         if (now - la_time).total_seconds() > SESSION_TIMEOUT_MINUTES * 60]
        for channel_id in timed_out_ids:
            self._clear_session_data(channel_id)
            _logger.info(f"Sesi chat AI Channel untuk {channel_id} timeout & dibersihkan.")
            channel = self.bot.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel): # Pastikan channel valid dan bisa kirim pesan
                try: 
                    # Hanya kirim jika channel masih merupakan channel AI yang benar
                    if channel.name.lower() == gemini_services.get_designated_ai_channel_name().lower():
                        await channel.send("Sesi chat dengan Noelle telah direset karena tidak aktif.",delete_after=60)
                except Exception as e:
                    _logger.warning(f"Gagal mengirim notifikasi timeout sesi ke channel {channel_id}: {e}")


    @session_cleanup_loop.before_loop
    async def before_session_cleanup_loop(self):
        await self.bot.wait_until_ready()

    # _process_gemini_response pindah ke ai_utils.py dan dipanggil dari sana
    # atau tetap di sini jika tidak ingin ai_utils bergantung pada discord.Message/Interaction
    # Untuk saat ini, asumsikan _process_gemini_response ada di ai_utils (seperti sebelumnya)

    @commands.Cog.listener("on_message")
    async def ai_channel_message_listener(self, message: discord.Message):
        if not gemini_services.is_ai_service_enabled() or \
           message.author.bot or message.guild is None or \
           gemini_services.get_gemini_client() is None:
            return

        # --- MODIFIKASI: Cek nama channel ---
        if not (message.channel.name.lower() == gemini_services.get_designated_ai_channel_name().lower()):
            return # Bukan AI channel berdasarkan nama, abaikan untuk cog ini
        # ------------------------------------

        bot_user = self.bot.user
        if bot_user and bot_user.mention in message.content:
            cleaned_content = message.content.replace(bot_user.mention, '').strip()
            if not cleaned_content and not message.attachments:
                return # Hanya mention, biarkan MentionHandlerCog

        context_log_prefix = f"AI Channel Session ({message.channel.id} - {message.channel.name})"
        _logger.info(f"({context_log_prefix}) Pesan dari {message.author.name} di AI Channel.")
        
        async with message.channel.typing():
            try:
                client = gemini_services.get_gemini_client()
                chat_session = self.active_chat_sessions.get(message.channel.id)
                current_total_tokens = self.chat_context_token_counts.get(message.channel.id, 0)

                if chat_session is None:
                    try: client.models.get(model=gemini_services.GEMINI_TEXT_MODEL_NAME)
                    except Exception:
                        _logger.error(f"({context_log_prefix}) Model '{gemini_services.GEMINI_TEXT_MODEL_NAME}' gagal. Sesi tidak dimulai.")
                        await message.reply(f"Model AI ({gemini_services.GEMINI_TEXT_MODEL_NAME}) tidak tersedia."); return
                    
                    chat_session = client.chats.create(model=gemini_services.GEMINI_TEXT_MODEL_NAME, history=[])
                    self.active_chat_sessions[message.channel.id] = chat_session
                    self.chat_context_token_counts[message.channel.id] = 0 
                    current_total_tokens = 0
                    _logger.info(f"({context_log_prefix}) Sesi chat baru dimulai.")
                
                self.chat_session_last_active[message.channel.id] = datetime.datetime.now(datetime.timezone.utc)
                
                user_input_parts_for_api = []
                text_content_cleaned = message.content
                if bot_user and bot_user.mention in text_content_cleaned :
                    text_content_cleaned = text_content_cleaned.replace(bot_user.mention, "").strip()
                if text_content_cleaned: user_input_parts_for_api.append(text_content_cleaned)
                
                # ... (logika attachment gambar tetap sama) ...
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

                # ... (logika hitung token input dan output tetap sama, menggunakan gemini_services.GEMINI_TEXT_MODEL_NAME) ...
                parts_for_counting_input = [] # Hitung token input
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

                # Panggil fungsi dari ai_utils untuk mengirim respons
                await ai_utils.send_text_in_embeds(
                    target_channel=message.channel, 
                    response_text=api_response.text if hasattr(api_response, 'text') else "".join(p.text for c in api_response.candidates for p in c.content.parts if p.text), # Ambil teks respons
                    title_prefix=f"Respons Noelle ({context_log_prefix})", 
                    footer_text=f"Untuk: {message.author.display_name}",
                    reply_to_message=message # Reply ke pesan asli
                )
                
                if current_total_tokens > MAX_CONTEXT_TOKENS:
                    _logger.warning(f"({context_log_prefix}) Konteks token ({current_total_tokens}) > batas. Mereset sesi.")
                    await message.channel.send(f"✨ Sesi percakapan telah mencapai batasnya dan akan direset! ✨")
                    self._clear_session_data(message.channel.id)
            # ... (blok except tetap sama) ...
            except (InvalidArgument, FailedPrecondition) as e: _logger.warning(f"({context_log_prefix}) Error API (safety/prompt): {e}"); await message.reply(f"Permintaan tidak dapat diproses: {e}")
            except GoogleAPIError as e: _logger.error(f"({context_log_prefix}) Error API Google: {e}", exc_info=True); await message.reply(f"Error API AI: {e}")
            except Exception as e: _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True); await message.reply(f"Error tak terduga: {type(e).__name__} - {e}")

async def setup(bot: commands.Bot):
    # Pastikan klien Gemini sudah siap sebelum menambah cog ini
    # karena cog ini sangat bergantung pada klien.
    client = gemini_services.get_gemini_client()
    if client is None or not gemini_services.is_ai_service_enabled():
        _logger.error("MessageHandlerCog: Klien Gemini tidak siap atau layanan AI tidak aktif. Cog tidak akan dimuat.")
        # Bisa raise error agar load_extension gagal, atau biarkan bot jalan tanpa cog ini
        # raise commands.ExtensionFailed("MessageHandlerCog: Klien Gemini tidak siap.")
        return # Tidak jadi memuat cog jika klien tidak ada
        
    await bot.add_cog(MessageHandlerCog(bot))
    _logger.info(f"{MessageHandlerCog.__name__} (AI Channel Handler) Cog berhasil dimuat.")