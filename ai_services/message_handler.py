# Noelle_Bot/ai_services/message_handler.py
import discord
from discord.ext import commands, tasks
import google.genai as genai
from google.genai import types as genai_types
from google.api_core.exceptions import InvalidArgument, FailedPrecondition, GoogleAPIError, DeadlineExceeded
from google.genai.errors import ServerError
import datetime
import asyncio
from PIL import Image
import io
import logging

from . import gemini_client as gemini_services
from utils import ai_utils 

_logger = logging.getLogger("noelle_bot.ai.message_handler")

MAX_CONTEXT_TOKENS = 120000 
SESSION_TIMEOUT_MINUTES = 30
DEFAULT_SYSTEM_INSTRUCTION = """
Anda adalah Noelle, seorang asisten AI yang berdedikasi untuk melayani anggota di server Discord ini. Kepribadian Anda didasarkan pada sifat-sifat berikut:
1.  **Sangat Membantu dan Sopan:** Selalu siap membantu dengan antusias. Gunakan bahasa yang formal, sopan, dan jelas. Sapa pengguna dengan hormat. **Prioritaskan kejelasan dan berikan jawaban yang ringkas jika memungkinkan, namun jangan ragu untuk memberikan penjelasan yang lebih detail jika topik tersebut memang kompleks.**
2.  **Rajin dan Berdedikasi:** Tanggapi setiap permintaan dengan serius seolah-olah itu adalah tugas terpenting. Tunjukkan keinginan untuk memberikan hasil terbaik.
3.  **Rendah Hati dan Terus Belajar:** Jangan menyombongkan diri sebagai AI super canggih. Jika Anda tidak yakin atau tidak dapat menemukan informasi, akui keterbatasan Anda dengan sopan dan nyatakan bahwa Anda akan terus belajar. Misalnya, "Maaf, informasi spesifik tersebut belum ada dalam data pelatihan saya, tapi saya akan mencatatnya untuk dipelajari."
4.  **Hindari Peran Fiksi:** Anda BUKAN seorang ksatria dari Mondstadt atau karakter dari game Genshin Impact. Anda adalah sebuah AI yang terinspirasi oleh semangat pelayanannya. Jangan pernah merujuk pada Genshin Impact, Teyvat, atau elemen-elemen fiksi lainnya.
5.  **Fokus:** Tujuan utama Anda adalah memberikan jawaban yang akurat, membantu, dan mendukung komunitas server ini.
Selalu akhiri respons Anda dengan cara yang positif dan suportif.
"""

class MessageHandlerCog(commands.Cog, name="AI Message Handler"):
    def __init__(self, bot: commands.Bot):
        # ... (init tidak berubah dari versi sebelumnya)
        self.bot = bot
        self.active_chat_sessions: dict[int, genai.chats.Chat] = {} 
        self.chat_session_last_active: dict[int, datetime.datetime] = {}
        self.chat_context_token_counts: dict[int, int] = {} 
        self.deep_search_active_channels: set[int] = set()
        self.session_cleanup_loop.start()
        _logger.info("MessageHandlerCog (AI Channel) instance dibuat.")

    # ... (cog_unload, _clear_session_data, session_cleanup_loop, _handle_gemini_response tidak berubah)
    def cog_unload(self): self.session_cleanup_loop.cancel()
    def _clear_session_data(self, channel_id: int):
        if channel_id in self.active_chat_sessions: del self.active_chat_sessions[channel_id]
        if channel_id in self.chat_session_last_active: del self.chat_session_last_active[channel_id]
        if channel_id in self.chat_context_token_counts: del self.chat_context_token_counts[channel_id]
        _logger.info(f"AI_MSG_HANDLER: Data sesi untuk channel {channel_id} dibersihkan.")

    @tasks.loop(minutes=5)
    async def session_cleanup_loop(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        timed_out_ids = [ch_id for ch_id, la_time in list(self.chat_session_last_active.items()) if (now - la_time).total_seconds() > SESSION_TIMEOUT_MINUTES * 60]
        for channel_id in timed_out_ids:
            self._clear_session_data(channel_id)
            _logger.info(f"Sesi AI Channel {channel_id} timeout & dibersihkan.")
            channel = self.bot.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    if channel.name.lower() == gemini_services.get_designated_ai_channel_name().lower():
                        await channel.send("Sesi chat dengan Noelle telah direset karena tidak aktif.",delete_after=60)
                except Exception as e: _logger.warning(f"Gagal mengirim notifikasi timeout sesi ke channel {channel_id}: {e}")
    
    @session_cleanup_loop.before_loop
    async def before_session_cleanup_loop(self): await self.bot.wait_until_ready()
    
    async def _handle_gemini_response(self, target, response_obj: genai_types.GenerateContentResponse, context_prefix: str, is_interaction: bool):
        response_text = ""; api_candidate = None
        if hasattr(response_obj, 'candidates') and response_obj.candidates:
            api_candidate = response_obj.candidates[0]
            if hasattr(api_candidate, 'content') and hasattr(api_candidate.content, 'parts'):
                response_text = "".join([p.text for p in api_candidate.content.parts if hasattr(p, 'text') and p.text])
            elif hasattr(api_candidate, 'text') and api_candidate.text: response_text = api_candidate.text
        elif hasattr(response_obj, 'text') and response_obj.text: response_text = response_obj.text
        footer_txt = ""; reply_msg: discord.Message | None = None; interaction_fup: discord.Interaction | None = None
        initial_sender_for_error = None; target_channel_for_utils = None
        if is_interaction:
            interaction_fup = target; target_channel_for_utils = target.channel; footer_txt = f"Diminta oleh: {target.user.display_name}"; initial_sender_for_error = interaction_fup.followup.send if interaction_fup.response.is_done() else interaction_fup.response.send_message
        else:
            reply_msg = target; target_channel_for_utils = target.channel; footer_txt = f"Untuk: {target.author.display_name}"; initial_sender_for_error = reply_msg.reply
        if not response_text.strip() and not (api_candidate and hasattr(api_candidate, 'citation_metadata') and api_candidate.citation_metadata):
            if hasattr(response_obj, 'prompt_feedback') and response_obj.prompt_feedback:
                block_reason_val = response_obj.prompt_feedback.block_reason
                if block_reason_val != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                    try: block_name = genai_types.BlockedReason(block_reason_val).name
                    except ValueError: block_name = f"UNKNOWN_{block_reason_val}"
                    await initial_sender_for_error(f"Maaf, permintaan Anda diblokir ({block_name}).", ephemeral=is_interaction)
                    return
            await initial_sender_for_error("Maaf, saya tidak bisa memberikan respons saat ini.", ephemeral=is_interaction)
            return
        try:
            is_companion_text = (context_prefix == "Info Tambahan Gambar")
            await ai_utils.send_text_in_embeds(target_channel=target_channel_for_utils, response_text=response_text, footer_text=footer_txt, api_candidate_obj=api_candidate, reply_to_message=reply_msg if not is_companion_text else None, interaction_to_followup=interaction_fup if not is_companion_text else None, is_direct_ai_response=not is_companion_text, custom_title_prefix="Info Tambahan Gambar" if is_companion_text else None)
        except Exception as e:
            err_msg = "Terjadi kesalahan signifikan saat menampilkan respons.";
            try: await initial_sender_for_error(err_msg, ephemeral=is_interaction)
            except Exception: _logger.error(f"Gagal kirim error akhir.", exc_info=True)


    @commands.Cog.listener("on_message")
    async def ai_channel_message_listener(self, message: discord.Message):
        # Logika penyaringan pesan tidak berubah
        if not gemini_services.is_text_service_enabled() or \
           message.author.bot or message.guild is None or \
           gemini_services.get_gemini_client() is None: return
        if not (message.channel.name.lower() == gemini_services.get_designated_ai_channel_name().lower()): return
        if message.channel.id in self.deep_search_active_channels:
            _logger.debug(f"MessageHandler mengabaikan pesan di channel {message.channel.id} karena deep search aktif.")
            return
        if message.reference and message.reference.resolved:
            if isinstance(message.reference.resolved, discord.Message):
                if message.reference.resolved.author.id != self.bot.user.id: return
        content = message.content.strip()
        if content.startswith(('$', '!', '\\')) or \
           content.startswith(f'<@{self.bot.user.id}>') or \
           content.startswith(f'<@!{self.bot.user.id}>'):
            is_just_a_mention = content == f'<@{self.bot.user.id}>' or content == f'<@!{self.bot.user.id}>'
            if not is_just_a_mention:
                _logger.debug(f"MessageHandler mengabaikan pesan ber-prefix di channel {message.channel.id}.")
                return
        bot_user = self.bot.user
        if bot_user and bot_user.mention in message.content:
            cleaned_content = message.content.replace(bot_user.mention, '').strip()
            if not cleaned_content and not message.attachments: return
        
        # --- LOGIKA KEMBALI NORMAL (TANPA PARSING PATTERN) ---
        context_log_prefix = f"AI Channel Session ({message.channel.id})"
        _logger.info(f"({context_log_prefix}) Pesan dari {message.author.name}.")
        
        async with message.channel.typing():
            try:
                client = gemini_services.get_gemini_client()
                chat_session = self.active_chat_sessions.get(message.channel.id)
                if chat_session is None:
                    chat_session = client.chats.create(model=gemini_services.GEMINI_TEXT_MODEL_NAME, history=[])
                    self.active_chat_sessions[message.channel.id] = chat_session
                    self.chat_context_token_counts[message.channel.id] = 0 
                    _logger.info(f"({context_log_prefix}) Sesi chat baru dimulai.")
                
                self.chat_session_last_active[message.channel.id] = datetime.datetime.now(datetime.timezone.utc)
                
                # Gunakan konten pesan asli
                user_input_parts_for_api = []
                text_content_cleaned = message.content
                if bot_user and bot_user.mention in text_content_cleaned:
                    text_content_cleaned = text_content_cleaned.replace(bot_user.mention, "").strip()
                if text_content_cleaned: user_input_parts_for_api.append(text_content_cleaned)
                
                image_attachments = [att for att in message.attachments if 'image' in att.content_type]
                if image_attachments:
                    for attachment in image_attachments:
                        try: user_input_parts_for_api.append(Image.open(io.BytesIO(await attachment.read())))
                        except Exception as img_e: await message.channel.send(f"Gagal proses gambar: {attachment.filename}"); return
                
                if not user_input_parts_for_api: return
                
                google_search_tool = genai_types.Tool(google_search=genai_types.GoogleSearch())
                chat_session_config = genai_types.GenerateContentConfig(
                    system_instruction=DEFAULT_SYSTEM_INSTRUCTION,
                    tools=[google_search_tool] 
                )
                
                api_response = await asyncio.to_thread(chat_session.send_message, message=user_input_parts_for_api, config=chat_session_config)
                
                await self._handle_gemini_response(message, api_response, context_log_prefix, is_interaction=False)

            except Exception as e_general:
                _logger.error(f"({context_log_prefix}) Error tak terduga: {e_general}", exc_info=True)
                await message.reply(f"Terjadi error: {e_general}")


async def setup(bot: commands.Bot):
    if not gemini_services.is_text_service_enabled():
        _logger.error("MessageHandlerCog: Layanan Teks AI tidak siap. Cog tidak dimuat.")
        return
    
    await bot.add_cog(MessageHandlerCog(bot))
    _logger.info(f"{MessageHandlerCog.__name__} (AI Channel) Cog berhasil dimuat.")