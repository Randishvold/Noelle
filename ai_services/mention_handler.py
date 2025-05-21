# Noelle_AI_Bot/ai_services/mention_handler.py
import discord
from discord.ext import commands
# ... (impor lain yang relevan seperti google.genai, types, exceptions)
import google.genai as genai # Perlu diimpor untuk type hinting
from google.genai import types as genai_types
from google.api_core.exceptions import InvalidArgument, FailedPrecondition, GoogleAPIError
import asyncio
import logging

from . import gemini_client as gemini_services
from utils import ai_utils 
# Tidak perlu database.py lagi untuk cog ini jika hanya cek nama channel dari gemini_services

_logger = logging.getLogger(__name__)

class MentionHandlerCog(commands.Cog, name="AI Mention Handler"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("MentionHandlerCog instance dibuat.")

    # Tidak perlu _process_gemini_response di sini jika sudah ada di ai_utils
    # dan ai_utils.send_text_in_embeds dipanggil langsung

    @commands.Cog.listener("on_message")
    async def ai_mention_listener(self, message: discord.Message):
        if not gemini_services.is_ai_service_enabled() or \
           message.author.bot or message.guild is None or \
           gemini_services.get_gemini_client() is None:
            return

        bot_user = self.bot.user
        if not (bot_user and bot_user.mention in message.content):
            return 

        # --- MODIFIKASI: Cek apakah ini di AI channel ---
        # Jika di AI channel, dan BUKAN hanya mention, maka MessageHandlerCog yang urus
        is_in_designated_ai_channel = message.channel.name.lower() == gemini_services.get_designated_ai_channel_name().lower()
        
        text_content_cleaned = message.content.replace(bot_user.mention, '').strip()
        is_just_a_mention = not text_content_cleaned and not message.attachments

        if is_in_designated_ai_channel and not is_just_a_mention:
            return # Biarkan MessageHandlerCog
        # -------------------------------------------------

        context_log_prefix = "Bot Mention"
        _logger.info(f"({context_log_prefix}) Memproses mention dari {message.author.name}.")
        
        async with message.channel.typing():
            try:
                if not text_content_cleaned: 
                    await message.reply("Halo! Ada yang bisa saya bantu? (Sebut nama saya dengan pertanyaan Anda)")
                    return

                client = gemini_services.get_gemini_client()
                api_response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=gemini_services.GEMINI_TEXT_MODEL_NAME,
                    contents=text_content_cleaned
                )
                _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini.")
                
                # Ekstrak teks respons untuk dikirim ke ai_utils
                response_text_for_utils = ""
                if hasattr(api_response, 'text') and api_response.text: response_text_for_utils = api_response.text
                elif hasattr(api_response, 'candidates') and api_response.candidates:
                    candidate = api_response.candidates[0]
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                        response_text_for_utils = "".join([p.text for p in candidate.content.parts if hasattr(p, 'text') and p.text])
                    elif hasattr(candidate, 'text') and candidate.text: response_text_for_utils = candidate.text
                
                if not response_text_for_utils.strip(): # Penanganan jika kosong
                    # (Sama seperti di _process_gemini_response sebelumnya)
                    if hasattr(api_response, 'prompt_feedback') and api_response.prompt_feedback and \
                       api_response.prompt_feedback.block_reason != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                        block_name = genai_types.BlockedReason(api_response.prompt_feedback.block_reason).name
                        await message.reply(f"Maaf, permintaan Anda diblokir ({block_name}).")
                    else:
                        await message.reply("Maaf, saya tidak bisa memberikan respons saat ini.")
                    return

                await ai_utils.send_text_in_embeds(
                    target_channel=message.channel,
                    response_text=response_text_for_utils,
                    title_prefix=f"Respons Noelle ({context_log_prefix})",
                    footer_text=f"Untuk: {message.author.display_name}",
                    reply_to_message=message
                )
            
            except (InvalidArgument, FailedPrecondition) as e: _logger.warning(f"({context_log_prefix}) Error API (safety/prompt): {e}"); await message.reply(f"Permintaan tidak dapat diproses: {e}")
            except GoogleAPIError as e: _logger.error(f"({context_log_prefix}) Error API Google: {e}", exc_info=True); await message.reply(f"Error API AI: {e}")
            except Exception as e: _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True); await message.reply(f"Error tak terduga: {type(e).__name__} - {e}")