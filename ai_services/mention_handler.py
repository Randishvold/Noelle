# Noelle_Bot/ai_services/mention_handler.py
import discord
from discord.ext import commands
import google.genai as genai
from google.genai import types as genai_types
# --- PERBAIKAN IMPOR ERROR ---
from google.api_core.exceptions import InvalidArgument, FailedPrecondition, GoogleAPIError, DeadlineExceeded # Pindahkan DeadlineExceeded ke sini
from google.genai.errors import ServerError # ServerError tetap dari google.genai.errors
# -----------------------------
import asyncio
import logging

# ... sisa kode mention_handler.py tetap sama ...

from . import gemini_client as gemini_services
from utils import ai_utils 

_logger = logging.getLogger("noelle_bot.ai.mention_handler")

DEFAULT_SYSTEM_INSTRUCTION = "Berikan respons yang relatif singkat dan padat jika memungkinkan, idealnya muat dalam deskripsi embed Discord (sekitar 4000 karakter). Namun, jika informasi yang detail memang diperlukan, jangan ragu untuk memberikan respons yang lebih panjang."

class MentionHandlerCog(commands.Cog, name="AI Mention Handler"):
    def __init__(self, bot: commands.Bot): # ... (sama)
        self.bot = bot
        _logger.info("MentionHandlerCog instance dibuat.")

    @commands.Cog.listener("on_message")
    async def ai_mention_listener(self, message: discord.Message):
        if not gemini_services.is_ai_service_enabled() or \
           message.author.bot or message.guild is None or \
           gemini_services.get_gemini_client() is None: return
        bot_user = self.bot.user
        if not (bot_user and bot_user.mention in message.content): return 
        is_in_designated_ai_channel = message.channel.name.lower() == gemini_services.get_designated_ai_channel_name().lower()
        text_content_cleaned = message.content.replace(bot_user.mention, '').strip()
        is_just_a_mention = not text_content_cleaned and not message.attachments
        if is_in_designated_ai_channel and not is_just_a_mention: return 
        context_log_prefix = "Bot Mention"
        _logger.info(f"({context_log_prefix}) Memproses mention dari {message.author.name}.")
        async with message.channel.typing():
            try:
                if not text_content_cleaned: await message.reply("Halo! Ada yang bisa saya bantu?"); return
                client = gemini_services.get_gemini_client()
                
                # --- PERBAIKAN TOOL GROUNDING ---
                google_search_tool = genai_types.Tool(
                    google_search=genai_types.GoogleSearch() # Gunakan google_search
                )
                mention_config = genai_types.GenerateContentConfig(
                    system_instruction=DEFAULT_SYSTEM_INSTRUCTION,
                    tools=[google_search_tool]
                )
                # --------------------------------
                
                api_response = None; MAX_RETRIES = 1; retry_delay = 2 # Retry lebih sedikit untuk mention
                for attempt in range(MAX_RETRIES + 1):
                    try:
                        api_response = await asyncio.to_thread(
                            client.models.generate_content,
                            model=gemini_services.GEMINI_TEXT_MODEL_NAME,
                            contents=text_content_cleaned,
                            config=mention_config
                        )
                        _logger.info(f"({context_log_prefix}) Respons Gemini diterima (attempt {attempt+1}).")
                        break
                    except (ServerError, DeadlineExceeded) as se_mention:
                        _logger.warning(f"({context_log_prefix}) {type(se_mention).__name__} (attempt {attempt+1}/{MAX_RETRIES+1}): {se_mention}")
                        if attempt < MAX_RETRIES:
                            # Untuk mention, mungkin tidak perlu pesan retry ke channel, cukup log
                            await asyncio.sleep(retry_delay); retry_delay *= 2
                        else: raise # Re-raise jika semua retry gagal
                if api_response is None: await message.reply("Gagal dapat respons AI setelah retry."); return

                response_text_for_utils = ""; api_candidate = None
                if hasattr(api_response, 'candidates') and api_response.candidates:
                    api_candidate = api_response.candidates[0]
                    if hasattr(api_candidate, 'content') and hasattr(api_candidate.content, 'parts'):
                        response_text_for_utils = "".join([p.text for p in api_candidate.content.parts if hasattr(p, 'text') and p.text])
                    elif hasattr(api_candidate, 'text') and api_candidate.text: response_text_for_utils = api_candidate.text
                elif hasattr(api_response, 'text') and api_response.text: response_text_for_utils = api_response.text
                
                if not response_text_for_utils.strip() and not (api_candidate and hasattr(api_candidate, 'citation_metadata') and api_candidate.citation_metadata):
                    if hasattr(api_response, 'prompt_feedback') and api_response.prompt_feedback and \
                       api_response.prompt_feedback.block_reason != genai_types.BlockedReason.BLOCKED_REASON_UNSPECIFIED:
                        try: block_name = genai_types.BlockedReason(api_response.prompt_feedback.block_reason).name
                        except ValueError: block_name = f"UNKNOWN_{api_response.prompt_feedback.block_reason}"
                        await message.reply(f"Maaf, permintaan Anda diblokir ({block_name}).")
                    else: await message.reply("Maaf, saya tidak bisa memberikan respons saat ini.")
                    return

                await ai_utils.send_text_in_embeds(
                    target_channel=message.channel, response_text=response_text_for_utils,
                    footer_text=f"Untuk: {message.author.display_name}", api_candidate_obj=api_candidate,
                    reply_to_message=message, is_direct_ai_response=True, custom_title_prefix=None
                )
            except (ServerError, DeadlineExceeded) as e_server: _logger.error(f"({context_log_prefix}) Error Server/Timeout Gemini: {e_server}"); await message.reply("Server AI sibuk/timeout. Coba lagi nanti.")
            except (InvalidArgument, FailedPrecondition) as e_api_specific: _logger.warning(f"({context_log_prefix}) Error API (safety/prompt): {e_api_specific}"); await message.reply(f"Permintaan tidak dapat diproses: {e_api_specific}")
            except GoogleAPIError as e_google: _logger.error(f"({context_log_prefix}) Error API Google: {e_google}", exc_info=True); await message.reply(f"Error API AI: {e_google}")
            except Exception as e_general: _logger.error(f"({context_log_prefix}) Error tak terduga: {e_general}", exc_info=True); await message.reply(f"Error tak terduga: {type(e_general).__name__} - {e_general}")

async def setup(bot: commands.Bot): # ... (sama)
    client = gemini_services.get_gemini_client()
    if client is None or not gemini_services.is_ai_service_enabled():
        _logger.error("MentionHandlerCog: Klien Gemini tidak siap. Cog tidak dimuat.")
        return
    await bot.add_cog(MentionHandlerCog(bot))
    _logger.info(f"{MentionHandlerCog.__name__} Cog berhasil dimuat.")