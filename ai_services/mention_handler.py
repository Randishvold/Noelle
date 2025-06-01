# Noelle_AI_Bot/ai_services/mention_handler.py
import discord
from discord.ext import commands
import google.genai as genai
from google.genai import types as genai_types
from google.api_core.exceptions import InvalidArgument, FailedPrecondition, GoogleAPIError
import asyncio
import logging

from . import gemini_client as gemini_services
from utils import ai_utils 
# Tidak perlu database.py lagi untuk cog ini

_logger = logging.getLogger(__name__) # Gunakan nama modul untuk logger

# System instruction default dari message_handler
DEFAULT_SYSTEM_INSTRUCTION = "Berikan respons yang relatif singkat dan padat jika memungkinkan, idealnya muat dalam deskripsi embed Discord (sekitar 4000 karakter). Namun, jika informasi yang detail memang diperlukan, jangan ragu untuk memberikan respons yang lebih panjang."

class MentionHandlerCog(commands.Cog, name="AI Mention Handler"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("MentionHandlerCog instance dibuat.")

    # Hapus _process_gemini_response dari sini, akan menggunakan yang ada di MessageHandlerCog atau ai_utils.send_text_in_embeds langsung

    @commands.Cog.listener("on_message")
    async def ai_mention_listener(self, message: discord.Message):
        if not gemini_services.is_ai_service_enabled() or \
           message.author.bot or message.guild is None or \
           gemini_services.get_gemini_client() is None:
            return

        bot_user = self.bot.user
        if not (bot_user and bot_user.mention in message.content):
            return 

        is_in_designated_ai_channel = message.channel.name.lower() == gemini_services.get_designated_ai_channel_name().lower()
        text_content_cleaned = message.content.replace(bot_user.mention, '').strip()
        is_just_a_mention = not text_content_cleaned and not message.attachments
        if is_in_designated_ai_channel and not is_just_a_mention:
            return 

        context_log_prefix = "Bot Mention"
        _logger.info(f"({context_log_prefix}) Memproses mention dari {message.author.name}.")
        
        async with message.channel.typing():
            try:
                if not text_content_cleaned: 
                    await message.reply("Halo! Ada yang bisa saya bantu?"); return

                client = gemini_services.get_gemini_client()
                # --- SYSTEM INSTRUCTION UNTUK MENTION ---
                mention_config = genai_types.GenerateContentConfig(
                    system_instruction=DEFAULT_SYSTEM_INSTRUCTION
                )
                # --------------------------------------
                api_response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=gemini_services.GEMINI_TEXT_MODEL_NAME,
                    contents=text_content_cleaned, # Hanya teks untuk mention
                    config=mention_config # Terapkan config
                )
                _logger.info(f"({context_log_prefix}) Menerima respons dari Gemini.")
                
                response_text_for_utils = ""
                if hasattr(api_response, 'text') and api_response.text: response_text_for_utils = api_response.text
                elif hasattr(api_response, 'candidates') and api_response.candidates:
                    candidate = api_response.candidates[0]
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                        response_text_for_utils = "".join([p.text for p in candidate.content.parts if hasattr(p, 'text') and p.text])
                    elif hasattr(candidate, 'text') and candidate.text: response_text_for_utils = candidate.text
                
                if not response_text_for_utils.strip():
                    if hasattr(api_response, 'prompt_feedback') and api_response.prompt_feedback and \
                       api_response.prompt_feedback.block_reason != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                        block_name = genai_types.BlockedReason(api_response.prompt_feedback.block_reason).name
                        await message.reply(f"Maaf, permintaan Anda diblokir ({block_name}).")
                    else: await message.reply("Maaf, saya tidak bisa memberikan respons saat ini.")
                    return

                await ai_utils.send_text_in_embeds(
                    target_channel=message.channel,
                    response_text=response_text_for_utils,
                    footer_text=f"Untuk: {message.author.display_name}",
                    reply_to_message=message,
                    is_direct_ai_response=True 
                )
            
            except (InvalidArgument, FailedPrecondition) as e: _logger.warning(f"({context_log_prefix}) Error API (safety/prompt): {e}"); await message.reply(f"Permintaan tidak dapat diproses: {e}")
            except GoogleAPIError as e: _logger.error(f"({context_log_prefix}) Error API Google: {e}", exc_info=True); await message.reply(f"Error API AI: {e}")
            except Exception as e: _logger.error(f"({context_log_prefix}) Error tak terduga: {e}", exc_info=True); await message.reply(f"Error tak terduga: {type(e).__name__} - {e}")

async def setup(bot: commands.Bot):
    client = gemini_services.get_gemini_client()
    if client is None or not gemini_services.is_ai_service_enabled():
        _logger.error("MentionHandlerCog: Klien Gemini tidak siap. Cog tidak dimuat.")
        return
    await bot.add_cog(MentionHandlerCog(bot))
    _logger.info(f"{MentionHandlerCog.__name__} Cog berhasil dimuat.")