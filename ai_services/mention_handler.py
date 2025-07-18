# Noelle_Bot/ai_services/mention_handler.py
import discord
from discord.ext import commands
import google.genai as genai
from google.genai import types as genai_types
from google.api_core.exceptions import InvalidArgument, FailedPrecondition, GoogleAPIError, DeadlineExceeded
from google.genai.errors import ServerError 
import asyncio
import logging

from . import gemini_client as gemini_services
from utils import ai_utils 
from .message_handler import DEFAULT_SYSTEM_INSTRUCTION

_logger = logging.getLogger("noelle_bot.ai.mention_handler")

class MentionHandlerCog(commands.Cog, name="AI Mention Handler"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("MentionHandlerCog instance dibuat.")

    @commands.Cog.listener("on_message")
    async def ai_mention_listener(self, message: discord.Message):
        if not gemini_services.is_text_service_enabled() or \
           message.author.bot or message.guild is None or \
           gemini_services.get_gemini_client() is None: return
        bot_user = self.bot.user
        if not (bot_user and bot_user.mention in message.content): return 
        
        is_in_designated_ai_channel = message.channel.name.lower() == gemini_services.get_designated_ai_channel_name().lower()
        
        # --- LOGIKA DISEDERHANAKAN KEMBALI ---
        clean_content = message.content.replace(bot_user.mention, '').strip()

        # Jika di channel AI, dan ada teks, biarkan message_handler yang urus
        if is_in_designated_ai_channel and clean_content:
            return
            
        context_log_prefix = "Bot Mention"
        _logger.info(f"({context_log_prefix}) Memproses mention dari {message.author.name}.")
        
        async with message.channel.typing():
            try:
                if not clean_content and not message.attachments:
                    await message.reply("Halo! Ada yang bisa saya bantu?"); return
                
                client = gemini_services.get_gemini_client()
                
                google_search_tool = genai_types.Tool(google_search=genai_types.GoogleSearch())
                mention_config = genai_types.GenerateContentConfig(
                    system_instruction=DEFAULT_SYSTEM_INSTRUCTION,
                    tools=[google_search_tool]
                )
                
                # Tambahkan gambar jika ada
                user_input_parts = [clean_content] if clean_content else []
                if message.attachments:
                    for attachment in message.attachments:
                        if 'image' in attachment.content_type:
                             user_input_parts.append(Image.open(io.BytesIO(await attachment.read())))

                api_response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=gemini_services.GEMINI_TEXT_MODEL_NAME,
                    contents=user_input_parts,
                    config=mention_config
                )
                
                response_text_for_utils = api_response.text or ""
                api_candidate = api_response.candidates[0] if api_response.candidates else None
                
                if not response_text_for_utils.strip():
                    await message.reply("Maaf, saya tidak bisa memberikan respons saat ini.")
                    return

                await ai_utils.send_text_in_embeds(
                    target_channel=message.channel, response_text=response_text_for_utils,
                    footer_text=f"Untuk: {message.author.display_name}", api_candidate_obj=api_candidate,
                    reply_to_message=message, is_direct_ai_response=True
                )
            except Exception as e_general:
                _logger.error(f"({context_log_prefix}) Error tak terduga: {e_general}", exc_info=True)
                await message.reply(f"Error: {e_general}")

async def setup(bot: commands.Bot):
    if not gemini_services.is_text_service_enabled():
        _logger.error("MentionHandlerCog: Layanan Teks AI tidak siap. Cog tidak dimuat.")
        return

    await bot.add_cog(MentionHandlerCog(bot))
    _logger.info(f"{MentionHandlerCog.__name__} Cog berhasil dimuat.")