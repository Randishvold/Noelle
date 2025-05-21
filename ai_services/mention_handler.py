# Noelle_AI_Bot/ai_services/mention_handler.py
import discord
from discord.ext import commands
import google.genai as genai
from google.genai import types as genai_types
from google.api_core.exceptions import InvalidArgument, FailedPrecondition, GoogleAPIError
import asyncio

from . import gemini_client as gemini_services
from utils import ai_utils
import database # Untuk cek AI channel ID jika perlu

_logger = logging.getLogger(__name__)

class MentionHandlerCog(commands.Cog, name="AI Mention Handler"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("MentionHandlerCog instance dibuat.")

    async def _process_gemini_response(self, message_or_interaction, response_obj: genai_types.GenerateContentResponse, context_prefix: str, is_interaction: bool = False):
        # Fungsi ini bisa di-copy dari MessageHandlerCog atau dipanggil dari ai_utils jika dibuat lebih generik
        # Untuk sementara, kita copy saja dulu
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
            # Untuk mention, kita mungkin tidak butuh penanganan khusus "Info Tambahan Gambar"
            await ai_utils.send_text_in_embeds(target_channel_for_messages, response_text, title, footer, msg_to_reply, interaction_to_fup)
            _logger.info(f"({context_prefix}) Respons teks selesai diproses via ai_utils.")
        except Exception as e:
            _logger.error(f"({context_prefix}) Error besar saat _process_gemini_response: {e}", exc_info=True)
            # ... (error handling akhir)
            err_msg = "Terjadi kesalahan signifikan saat menampilkan respons."
            try:
                if is_interaction:
                    if not message_or_interaction.response.is_done(): await message_or_interaction.response.send_message(err_msg, ephemeral=True)
                    else: await message_or_interaction.followup.send(err_msg, ephemeral=True)
                else: await message_or_interaction.reply(err_msg)
            except Exception: _logger.error(f"({context_prefix}) Gagal kirim error akhir.", exc_info=True)


    @commands.Cog.listener("on_message")
    async def ai_mention_listener(self, message: discord.Message):
        if not gemini_services.is_ai_service_enabled() or \
           message.author.bot or message.guild is None or \
           gemini_services.get_gemini_client() is None:
            return

        bot_user = self.bot.user
        if not (bot_user and bot_user.mention in message.content):
            return # Bot tidak dimention

        # Cek apakah ini di AI channel (jika ya, MessageHandlerCog yang urus, KECUALI jika hanya mention)
        guild_config = database.get_server_config(message.guild.id)
        ai_channel_id = guild_config.get('ai_channel_id')
        in_ai_channel = ai_channel_id is not None and message.channel.id == ai_channel_id

        text_content_cleaned = message.content.replace(bot_user.mention, '').strip()
        is_just_a_mention = not text_content_cleaned and not message.attachments

        if in_ai_channel and not is_just_a_mention:
            return # Biarkan MessageHandlerCog yang menangani pesan konten di AI channel

        # Jika sampai sini, berarti:
        # 1. Dimention di luar AI channel, ATAU
        # 2. Dimention di dalam AI channel TAPI hanya mention saja (is_just_a_mention == True)

        context_log_prefix = "Bot Mention"
        _logger.info(f"({context_log_prefix}) Memproses mention dari {message.author.name}.")
        
        async with message.channel.typing():
            try:
                if not text_content_cleaned: # Hanya mention, tidak ada teks tambahan
                    await message.reply("Halo! Ada yang bisa saya bantu? (Sebut nama saya dengan pertanyaan Anda)")
                    return

                client = gemini_services.get_gemini_client()
                # Mention adalah stateless, langsung panggil generate_content
                api_response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=gemini_services.GEMINI_TEXT_MODEL_NAME,
                    contents=text_content_cleaned # Hanya teks
                )
                _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini.")
                await self._process_gemini_response(message, api_response, context_log_prefix, is_interaction=False)
            
            except (InvalidArgument, FailedPrecondition) as e: _logger.warning(f"({context_log_prefix}) Error API (safety/prompt): {e}"); await message.reply(f"Permintaan tidak dapat diproses: {e}")
            except GoogleAPIError as e: _logger.error(f"({context_log_prefix}) Error API Google: {e}", exc_info=True); await message.reply(f"Error API AI: {e}")
            except Exception as e: _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True); await message.reply(f"Error tak terduga: {type(e).__name__} - {e}")