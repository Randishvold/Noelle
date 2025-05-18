import discord
import os
# --- Import from google.genai ---
import google.genai as genai # Use google.genai
from google.genai import types # Import types from google.genai
# --- END FIX ---
import database # Import database module
import utils # Import utils module (if needed in the future)
from discord.ext import commands
from discord import app_commands
import logging
from PIL import Image # Required for handling image inputs
import io # Required for handling image bytes
import asyncio # Required for async operations like sleep and typing
import re # Required for potential URL finding
import base64 # Required for decoding inline image data
# --- Import GoogleAPIError from google.api_core.exceptions ---
from google.api_core.exceptions import GoogleAPIError # Import GoogleAPIError
# --- END FIX ---

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

# --- Get API Key ---
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# --- Initialize Google AI Client and Models ---
# Use standard gemini-2.0-flash for mention responses and AI channel conversation/analysis
_flash_text_model = None
# Use gemini-2.0-flash-preview-image-generation ONLY for the explicit generate_image command
_flash_image_gen_model = None


def initialize_gemini():
    """Initializes the Google AI client and gets model objects."""
    global _ai_client, _flash_text_model, _flash_image_gen_model

    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY environment variable not set. Skipping Gemini initialization. AI features will be unavailable.")
        return

    try:
        # --- Initialize client from google.genai ---
        _ai_client = genai.Client(api_key=GOOGLE_API_KEY)
        _logger.info("Google AI client initialized.")
        # --- END FIX ---

        # Get model objects - Check if models exist first is good practice
        try:
            # Get model objects by name
            _flash_text_model = _ai_client.models.get(_flash_text_model_name)
            _logger.info(f"Got model object: {_flash_text_model_name}")
        except Exception as e:
            _logger.error(f"Failed to get model object '{_flash_text_model_name}': {e}", exc_info=True)
            _flash_text_model = None

        try:
            _flash_image_gen_model = _ai_client.models.get(_flash_image_gen_model_name)
            _logger.info(f"Got model object: {_flash_image_gen_model_name}")
        except Exception as e:
            _logger.error(f"Failed to get model object '{_flash_image_gen_model_name}': {e}", exc_info=True)
            _flash_image_gen_model = None # Ensure it's None if init fails

        if _flash_text_model or _flash_image_gen_model:
             _logger.info("At least one Gemini model object obtained successfully.")
        else:
             _logger.error("All Gemini model objects failed to obtain. AI features will be unavailable.")

    except Exception as e:
        _logger.error(f"An unexpected error occurred during Google AI client initialization: {e}", exc_info=True)
        _ai_client = None # Ensure client is None if initialization fails
        _flash_text_model = None
        _flash_image_gen_model = None


# Initialize Google AI when this cog file is imported
initialize_gemini()


class AICog(commands.Cog):
    """Cog for AI interaction features using on_message listener and slash commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Store the initialized models
        self.flash_text_model = _flash_text_model # For mention & AI channel conversation/analysis
        self.flash_image_gen_model = _flash_image_gen_model # For generate_image command
        _logger.info("AICog instance created.")


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Processes messages for AI interaction in the designated channel or when mentioned."""
        # Ignore messages from bots
        if message.author.bot:
            return

        # Ignore messages not in a guild
        if message.guild is None:
            return

        # Ensure at least the text model is initialized for on_message scenarios
        if self.flash_text_model is None:
             # _logger.debug(f"Skipping on_message AI processing for message in guild {message.guild.id}: Text model not initialized.")
             return # Silently ignore if text model is missing

        # Get server configuration
        config = database.get_server_config(message.guild.id)
        ai_channel_id = config.get('ai_channel_id')

        bot_user = self.bot.user
        is_mentioned = False
        # Check if bot_user is not None and the mention string is actually in the message content
        if bot_user and bot_user.mention in message.content:
             is_mentioned = True # Simple check for mention presence

        # --- Scenario 1: Message is in the designated AI channel ---
        # Check if this is the designated AI channel
        if ai_channel_id is not None and message.channel.id == ai_channel_id:
            # Check if it's just a bot mention in the AI channel - if so, let the mention scenario handle it below
            if is_mentioned and message.content.strip() == bot_user.mention:
                 _logger.debug(f"Message in AI channel {message.channel.id} is a bot mention-only. Letting mention scenario handle.")
                 pass # Continue to the mention check below
            else:
                _logger.info(f"Processing AI channel message from {message.author.id} in guild {message.guild.name} ({message.guild.id}), channel {message.channel.name} ({message.channel.id}).")

                model = self.flash_text_model # Use the standard Flash model for conversation/analysis in AI channel

                # Indicate that the bot is typing
                async with message.channel.typing():
                    try:
                        content_parts = []

                        # Process attachments (images) for analysis/multimodal input
                        image_attachments = [att for att in message.attachments if 'image' in att.content_type]

                        if image_attachments:
                             if len(image_attachments) > 4: # Limit number of images for API
                                await message.reply("Mohon berikan maksimal 4 gambar pada satu waktu untuk analisis/percakapan.")
                                return

                             for attachment in image_attachments:
                                 try:
                                     image_bytes = await attachment.read()
                                     pil_image = Image.open(io.BytesIO(image_bytes))
                                     # Append PIL Image object to content_parts for multimodal input
                                     content_parts.append(pil_image)
                                     _logger.info(f"Added image attachment {attachment.filename} to content parts for AI channel.")
                                 except Exception as img_e:
                                     _logger.error(f"Failed to process image attachment {attachment.filename} in AI channel: {img_e}", exc_info=True)
                                     try:
                                         await message.channel.send(f"Peringatan: Tidak dapat memproses gambar '{attachment.filename}': {img_e}")
                                     except Exception as send_e:
                                          _logger.error(f"Failed to send image processing warning in AI channel {message.channel.id}: {send_e}")

                                     if len(image_attachments) == 1 and not message.content.strip():
                                          await message.reply("Tidak dapat memproses gambar yang Anda kirim di channel AI.")
                                          return


                        # Add text content
                        text_content = message.content.strip()
                        # Remove bot mention if it's at the start (fallback for mentions in AI channel)
                        if bot_user and text_content.startswith(bot_user.mention):
                             text_content = text_content.replace(bot_user.mention, '', 1).strip()

                        if text_content:
                            content_parts.append(text_content)
                            _logger.info("Added text content to content parts for AI channel.")

                        if not content_parts:
                            _logger.debug("Message in AI channel had no processable content. Ignoring.")
                            return

                        # Call the standard Flash model (USE asyncio.to_thread)
                        # In google-genai, generate_content is synchronous. We must use to_thread.
                        if not hasattr(model, 'generate_content'):
                            _logger.error(f"Model object for '{_flash_text_model_name}' has no 'generate_content' method.")
                            await message.reply("Terjadi error internal: Model AI tidak dapat memproses permintaan.")
                            return

                        response = await asyncio.to_thread(model.generate_content, content_parts)
                        _logger.info(f"Received response from Gemini Flash for AI channel message.")

                        # --- Parsing Text Response (expecting text from this model here) ---
                        # Parsing syntax should be similar for google-genai
                        response_text = ""
                        if hasattr(response, 'candidates') and response.candidates:
                             candidate = response.candidates[0]
                             if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                                 response_text = "".join(str(part.text) for part in candidate.content.parts if hasattr(part, 'text'))
                             elif hasattr(candidate, 'text'):
                                 response_text = str(candidate.text)
                        elif hasattr(response, 'text'):
                             response_text = str(response.text)

                        # --- Send Text Response ---
                        if not response_text.strip():
                             if hasattr(response, 'prompt_feedback') and response.prompt_feedback and hasattr(response.prompt_feedback, 'block_reason') and response.prompt_feedback.block_reason != types.content.BlockReason.BLOCK_REASON_UNSPECIFIED:
                                 block_reason = types.content.BlockReason(response.prompt_feedback.block_reason).name
                                 _logger.warning(f"AI Channel prompt blocked by Gemini safety filter. Reason: {block_reason}. Full feedback: {response.prompt_feedback}")
                                 await message.reply("Maaf, respons ini diblokir oleh filter keamanan AI.")
                             else:
                                _logger.warning(f"Gemini Flash returned an empty response in AI channel. Full response object: {response}")
                                await message.reply("Maaf, saya tidak bisa memberikan respons saat ini.")
                             return # Stop processing

                        # Use chunk size 1990 to leave space for the header
                        if len(response_text) > 1990:
                            _logger.info("AI Channel: Splitting long text response into multiple messages (chunk size 1990).")
                            chunks = [response_text[i:i+1990] for i in range(0, len(response_text), 1990)]
                            for i, chunk in enumerate(chunks):
                                header = f"(Bagian {i+1}/{len(chunks)}):\n" if len(chunks) > 1 else ""
                                try:
                                     await message.reply(header + chunk)
                                     _logger.debug(f"Sent chunk {i+1}/{len(chunks)}.")
                                except discord.errors.HTTPException as http_e:
                                     _logger.error(f"HTTPException when sending chunk {i+1}/{len(chunks)}: {http_e}", exc_info=True)
                                     try:
                                         await message.channel.send(f"Gagal mengirim bagian {i+1} respons karena error: {http_e}")
                                     except Exception as send_e:
                                         _logger.error(f"Failed to send error message for failed chunk: {send_e}")
                                except Exception as send_e:
                                     _logger.error(f"An unexpected error occurred when sending chunk {i+1}/{len(chunks)}: {send_e}", exc_info=True)
                                     try:
                                         await message.channel.send(f"Gagal mengirim bagian {i+1} respons karena error tak terduga: {send_e}")
                                     except Exception as send_e_again:
                                          _logger.error(f"Failed to send unexpected error message for failed chunk: {send_e_again}")

                                await asyncio.sleep(0.5)
                        else:
                            # Send the whole text response if it fits
                            if len(response_text) <= 2000: # Final safety check against Discord limit
                                await message.reply(response_text)
                                _logger.info("AI Channel text response sent (single message).")
                            else: # Should not happen with 1990 chunking, but as a fallback
                                _logger.error(f"AI Channel response text length ({len(response_text)}) > 2000 but didn't trigger 1990 chunking.")
                                try:
                                     await message.reply(response_text[:1990] + "...") # Send truncated fallback message
                                except Exception as e:
                                     _logger.error(f"Failed to send truncated fallback message: {e}")
                                     await message.reply("Gagal mengirim respons panjang.")


                    # --- Error Handling for AI Channel Scenario (on_message) ---
                    except types.BlockedPromptException as e: # Use types from google.genai
                        _logger.warning(f"AI Channel prompt blocked by Gemini API: {e}")
                        await message.reply("Maaf, permintaan ini melanggar kebijakan penggunaan AI dan tidak bisa diproses.")
                    except types.StopCandidateException as e: # Use types from google.genai
                         _logger.warning(f"Gemini response stopped prematurely in AI channel: {e}")
                         await message.reply("Maaf, respons AI terhenti di tengah jalan.")
                    except GoogleAPIError as e: # Use GoogleAPIError from google.api_core.exceptions
                        _logger.error(f"Gemini API Error during AI channel processing (on_message): {e}", exc_info=True)
                        await message.reply(f"Terjadi error pada API AI: {e}")
                    except Exception as e: # Catch any other unexpected errors during processing *before* sending
                        _logger.error(f"An unexpected error occurred during AI processing (AI channel on_message): {e}", exc_info=True)
                        await message.reply(f"Terjadi error tak terduga saat memproses permintaan AI: {e}")

                return # Stop processing after handling the AI channel message

        # --- Scenario 2: Bot is mentioned (@NamaBot) in ANY channel (outside AI channel) ---
        # Check if the bot is mentioned and the message is NOT in the designated AI channel (or AI channel is not set)
        # This check happens AFTER the AI channel check.
        # This ensures mentions *in* the AI channel with other content are handled by Scenario 1.
        # Mention-only messages in the AI channel *will* fall through to here.
        if is_mentioned and (ai_channel_id is None or message.channel.id != ai_channel_id or message.content.strip() == bot_user.mention):
             # If it's a mention (and not in AI channel) OR it's a mention-only message in the AI channel
             _logger.info(f"Processing bot mention message from {message.author.id} in guild {message.guild.name} ({message.guild.id}), channel {message.channel.name} ({message.channel.id}). (Mention Scenario)")

             if self.flash_text_model is None:
                  _logger.warning(f"Skipping mention response: Standard Flash model not available.")
                  return # Silently skip if model is missing

             # Indicate that the bot is typing
             async with message.channel.typing():
                 try:
                     content_parts = []
                     # Extract text content, removing the bot's mention
                     text_content = message.content.replace(bot_user.mention, '', 1).strip()

                     # For mention response (one-off text only), we only use text input
                     # Images attached to mention messages will be ignored for API input in this scenario.
                     if text_content:
                         content_parts.append(text_content)
                         _logger.info("Added text content for mention response.")

                     if not content_parts:
                         await message.reply("Halo! Ada yang bisa saya bantu? (Anda menyebut saya tapi tidak ada teks yang bisa diproses).")
                         return

                     # Call the standard Flash model (USE asyncio.to_thread)
                     response = await asyncio.to_thread(self.flash_text_model.generate_content, content_parts)
                     _logger.info(f"Received response from Gemini Flash for mention.")

                     # Extract text response
                     response_text = ""
                     if hasattr(response, 'candidates') and response.candidates:
                         candidate = response.candidates[0]
                         if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                            response_text = "".join(str(part.text) for part in candidate.content.parts if hasattr(part, 'text'))
                         elif hasattr(candidate, 'text'):
                             response_text = str(candidate.text)
                     elif hasattr(response, 'text'):
                          response_text = str(response.text)


                     if not response_text.strip():
                         if hasattr(response, 'prompt_feedback') and response.prompt_feedback and hasattr(response.prompt_feedback, 'block_reason') and response.prompt_feedback.block_reason != types.content.BlockReason.BLOCK_REASON_UNSPECIFIED:
                              block_reason = types.content.BlockReason(response.prompt_feedback.block_reason).name
                              _logger.warning(f"Mention prompt blocked by Gemini safety filter. Reason: {block_reason}. Full feedback: {response.prompt_feedback}")
                              await message.reply("Maaf, permintaan ini diblokir oleh filter keamanan AI.")
                         else:
                             _logger.warning(f"Gemini Flash returned an empty response for mention. Full response object: {response}")
                             await message.reply("Maaf, saya tidak bisa memberikan respons saat ini.")
                     else:
                         if len(response_text) > 1500: # Shorter limit for one-off
                             response_text = response_text[:1500] + "..." # Truncate long responses
                             _logger.info(f"Truncated mention response to 1500 chars.")

                         await message.reply(response_text)
                         _logger.info("Mention response sent.")

                 except types.BlockedPromptException as e: # Use types from google.genai
                     _logger.warning(f"Mention prompt blocked by Gemini API: {e}")
                     await message.reply("Maaf, permintaan ini melanggar kebijakan penggunaan AI.")
                 except types.StopCandidateException as e: # Use types from google.genai
                      _logger.warning(f"Gemini response stopped prematurely for mention: {e}")
                      await message.reply("Maaf, respons AI terhenti.")
                 except GoogleAPIError as e: # Use GoogleAPIError from google.api_core.exceptions
                     _logger.error(f"Gemini API Error during mention processing: {e}", exc_info=True)
                     await message.reply(f"Terjadi error pada API AI: {e}")
                 except Exception as e:
                     _logger.error(f"An unexpected error occurred during mention processing: {e}", exc_info=True)
                     await message.reply(f"Terjadi error saat memproses permintaan AI: {e}")

             return # Stop processing after handling the mention

        # If not in AI channel and not a bot mention, just ignore the message.
        # No 'else' block needed, function simply ends.


    # --- Image Generation Command ---
    @app_commands.command(name='generate_image', description='Generates an image based on a text prompt using AI.')
    @app_commands.describe(prompt='Describe the image you want to generate.')
    @app_commands.guild_only() # Ensure command is in guild
    async def generate_image_slash(self, interaction: discord.Interaction, prompt: str):
        """Generates an image based on a text prompt using the image generation model."""
        _logger.info(f"Received /generate_image command from {interaction.user.id} with prompt: '{prompt}' in guild {interaction.guild_id}.")

        # Check if the command is used in the designated AI channel for this server
        config = database.get_server_config(interaction.guild_id)
        ai_channel_id = config.get('ai_channel_id')

        if ai_channel_id is None or interaction.channel_id != ai_channel_id:
             ai_channel = self.bot.get_channel(ai_channel_id) if ai_channel_id else None
             channel_mention = ai_channel.mention if ai_channel else '`/config ai_channel` untuk mengaturnya'

             await interaction.response.send_message(
                 f"Command ini hanya bisa digunakan di channel AI yang sudah ditentukan. Silakan gunakan {channel_mention}.",
                 ephemeral=True
             )
             _logger.warning(f"/generate_image used outside AI channel {ai_channel_id} by user {interaction.user.id} in channel {interaction.channel_id}.")
             return

        # Ensure the image generation model is available
        model = self.flash_image_gen_model
        if model is None:
             _logger.warning(f"Skipping generate_image in guild {interaction.guild.id}: Image generation model not available.")
             await interaction.response.send_message("Layanan AI untuk generate gambar tidak tersedia. Model AI untuk generate gambar gagal diinisialisasi atau tidak tersedia.", ephemeral=True)
             return

        if not prompt.strip():
             await interaction.response.send_message("Mohon berikan deskripsi untuk gambar yang ingin Anda buat.", ephemeral=True)
             return


        await interaction.response.defer(ephemeral=False) # Defer the response, visible to everyone

        try:
            _logger.info(f"Calling image generation model for prompt: '{prompt}'.")
            # Call the image generation model (USE asyncio.to_thread for synchronous method)
            # Use generate_content from the model object
            # Pass response_modalities here according to google-genai client.models syntax
            response = await asyncio.to_thread(
                model.generate_content,
                prompt, # Input is just the text prompt
                generation_config=types.GenerationConfig(), # GenerationConfig object
                response_modalities=['TEXT', 'IMAGE'] # Pass response_modalities here
            )
            _logger.info(f"Received response from Gemini API for image generation.")

            # --- Parsing the response for both text and potentially unexpected image outputs ---
            response_text = "" # Accompanying text
            image_urls = [] # Collect image URLs if returned
            image_data_parts = [] # Collect inline image data parts if returned

            if hasattr(response, 'candidates') and response.candidates:
                 candidate = response.candidates[0]
                 # Check if candidate has a valid finish_reason indicating success, but proceed if content parts exist
                 if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                     for part in candidate.content.parts:
                          if hasattr(part, 'text'):
                               response_text += str(part.text) # Accumulate text parts
                          # Check for structured image output - this might be returned by this model with response_modalities
                          # In google-genai, inline_data and file_data are likely under Part object
                          elif hasattr(part, 'inline_data') and hasattr(part.inline_data, 'mime_type') and part.inline_data.mime_type.startswith('image/'):
                               _logger.info("Generate Image: Received inline image data in response.")
                               image_data_parts.append(part) # Store the part to process later
                          elif hasattr(part, 'file_data') and hasattr(part.file_data, 'file_uri'):
                               _logger.info("Generate Image: Found file_uri in response!")
                               image_urls.append(part.file_data.file_uri)

            # Also check accumulated response_text for markdown image links as a heuristic
            # (Models sometimes generate markdown links instead of structured image output)
            if response_text:
                 markdown_image_pattern = r'!\[.*?\]\((https?://\S+\.(?:png|jpg|jpeg|gif|webp))\)'
                 found_markdown_urls = re.findall(markdown_image_pattern, response_text)
                 image_urls.extend(found_markdown_urls)
                 if found_markdown_urls:
                     _logger.info(f"Generate Image: Found markdown image URLs in text: {found_markdown_urls}")
                     # Optionally, remove the markdown links from the text response if URLs are added to image_urls list
                     # response_text = re.sub(markdown_image_pattern, '', response_text).strip()

            # --- Send Response ---
            response_sent = False # Flag to track if any message was sent

            # Send image outputs first if any were found (even if unexpected)
            if image_urls:
                 _logger.info(f"Generate Image: Sending {len(image_urls)} image URLs.")
                 for url in image_urls:
                     if url and (url.lower().endswith('.png') or url.lower().endswith('.jpg') or url.lower().endswith('.jpeg') or url.lower().endswith('.gif') or url.lower().endswith('.webp')):
                          image_embed = discord.Embed(color=discord.Color.blue())
                          image_embed.set_image(url=url)
                          prompt_text_footer = prompt[:100] + ('...' if len(prompt) > 100 else '')
                          image_embed.set_footer(text=f"Dihasilkan untuk \"{prompt_text_footer}\"")
                          try:
                               await interaction.followup.send(embed=image_embed)
                               _logger.info(f"Sent image embed for URL: {url}")
                               response_sent = True
                          except Exception as embed_e:
                               _logger.error(f"Failed to send image embed for URL {url}: {embed_e}", exc_info=True)
                               # Fallback to just sending the URL as text if embed fails
                               try:
                                    await interaction.followup.send(f"URL Gambar yang Dihasilkan: {url}")
                                    response_sent = True
                               except Exception as fallback_send_e:
                                     _logger.error(f"Failed to send fallback image URL text: {fallback_send_e}", exc_info=True)
                     else:
                          _logger.warning(f"Skipping image embed for potential non-image URL: {url}")
                          try:
                               await interaction.followup.send(f"URL yang Ditemukan (mungkin bukan gambar): {url}")
                               response_sent = True
                          except Exception as send_e:
                               _logger.error(f"Failed to send non-image URL text: {send_e}", exc_info=True)
                     await asyncio.sleep(0.5) # Small delay

            # Handle inline image data parts (requires sending as discord.File)
            if image_data_parts:
                 _logger.warning(f"Generate Image: Found {len(image_data_parts)} inline image data parts. Attempting to send as files.")
                 # Send a message indicating attempting to send files
                 try:
                      await interaction.followup.send("Mendeteksi data gambar inline dalam respons. Mencoba mengirim sebagai file...")
                      response_sent = True
                 except Exception as send_e:
                      _logger.error(f"Failed to send inline data pending message: {send_e}", exc_info=True)

                 for i, part in enumerate(image_data_parts):
                      try:
                           # Decode base64 data
                           # In google-genai, inline_data.data is bytes, no need for b64decode
                           # Check if part.inline_data.data is bytes or base64 string
                           image_bytes = part.inline_data.data # Assume it's bytes directly
                           # If it's a string and looks like base64, decode it:
                           # if isinstance(image_bytes, str):
                           #     image_bytes = base64.b64decode(image_bytes)

                           # Create a discord.File object
                           # Guess file extension from mime type
                           mime_type = part.inline_data.mime_type
                           extension = mime_type.split('/')[-1] if '/' in mime_type else 'png' # Default to png
                           file_name = f"generated_image_{i+1}.{extension}"

                           discord_file = discord.File(io.BytesIO(image_bytes), filename=file_name)

                           # Send the file
                           await interaction.followup.send(f"Gambar #{i+1}:", file=discord_file)
                           _logger.info(f"Successfully sent inline image data as file {file_name}.")
                           response_sent = True
                      except Exception as file_e:
                           _logger.error(f"Failed to send inline image data part {i+1} as file: {file_e}", exc_info=True)
                           try:
                               await interaction.followup.send(f"Gagal mengirim gambar inline #{i+1}.")
                           except Exception as send_e:
                                _logger.error(f"Failed to send error message for failed inline image file: {send_e}")

                      await asyncio.sleep(0.5)


            # Send accompanying text response if any (after images)
            if response_text.strip():
                 # For slash command response, we can just send the text directly via followup
                 try:
                      # Check if the text alone is too long
                      if len(response_text) > 1990:
                           _logger.warning(f"Generate Image: Accompanying text is very long ({len(response_text)}), chunking for safety.")
                           chunks = [response_text[i:i+1990] for i in range(0, len(response_text), 1990)]
                           for i, chunk in enumerate(chunks):
                               header = f"(Teks Pendamping Bagian {i+1}/{len(chunks)}):\n" if len(chunks) > 1 else "" # Differentiate from image parts
                               try:
                                     await interaction.followup.send(header + chunk)
                                     _logger.debug(f"Sent accompanying text chunk {i+1}/{len(chunks)}.")
                                     response_sent = True
                                except Exception as send_e:
                                     _logger.error(f"Failed to send accompanying text chunk {i+1}/{len(chunks)}: {send_e}", exc_info=True)
                                     try:
                                          await interaction.channel.send(f"Gagal mengirim bagian teks pendamping {i+1} karena error: {send_e}") # Send in channel as followup might be limited
                                     except Exception as send_e_again:
                                          _logger.error(f"Failed to send error message for failed accompanying text chunk: {send_e_again}")
                                     await asyncio.sleep(0.5)
                      else:
                           await interaction.followup.send(response_text)
                           _logger.info("Generate Image: Accompanying text response sent.")
                           response_sent = True

                 except Exception as send_e:
                      _logger.error(f"Failed to send accompanying text response: {send_e}", exc_info=True)
                      try:
                          await interaction.channel.send(f"Terjadi error saat mengirim teks pendamping: {send_e}")
                          response_sent = True
                      except Exception as fallback_send_e:
                          _logger.error(f"Failed to send fallback accompanying text in channel: {fallback_send_e}", exc_info=True)


            # If nothing was sent (no text, no images) and not blocked
            if not response_sent:
                 if hasattr(response, 'prompt_feedback') and response.prompt_feedback and hasattr(response.prompt_feedback, 'block_reason') and response.prompt_feedback.block_reason != types.content.BlockReason.BLOCK_REASON_UNSPECIFIED:
                     block_reason = types.content.BlockReason(response.prompt_feedback.block_reason).name
                     _logger.warning(f"Generate Image prompt was blocked, but response_sent is false. Reason: {block_reason}. Full feedback: {response.prompt_feedback}")
                     try:
                         await interaction.followup.send("Maaf, permintaan generate gambar ini diblokir oleh filter keamanan AI.")
                     except Exception as send_e:
                          _logger.error(f"Failed to send blocked message: {send_e}", exc_info=True)

                 else:
                    _logger.warning(f"Image generation command returned empty response with no block reason. Full response object: {response}")
                    try:
                         await interaction.followup.send("Gagal menghasilkan gambar. AI memberikan respons yang tidak terduga atau kosong.")
                    except Exception as send_e:
                         _logger.error(f"Failed to send empty response message: {send_e}", exc_info=True)


        # --- Error Handling for generate_image command ---
        except types.BlockedPromptException as e: # Use types from google.genai
             _logger.warning(f"Generate Image prompt blocked by Gemini API: {e}")
             try:
                  await interaction.followup.send("Maaf, permintaan generate gambar ini melanggar kebijakan penggunaan AI dan tidak bisa diproses.")
             except Exception as send_e:
                  _logger.error(f"Failed to send BlockedPromptException message: {send_e}", exc_info=True)
        except types.StopCandidateException as e: # Use types from google.genai
             _logger.warning(f"Gemini response stopped prematurely during image generation: {e}")
             try:
                  await interaction.followup.send("Maaf, proses generate gambar terhenti di tengah jalan.")
             except Exception as send_e:
                  _logger.error(f"Failed to send StopCandidateException message: {send_e}", exc_info=True)
        except GoogleAPIError as e: # Use GoogleAPIError from google.api_core.exceptions
            _logger.error(f"Gemini API Error during generate_image: {e}", exc_info=True)
            try:
                 await interaction.followup.send(f"Terjadi error pada API AI saat generate gambar: {e}")
            except Exception as send_e:
                 _logger.error(f"Failed to send GoogleAPIError message: {send_e}", exc_info=True)
        except Exception as e:
            _logger.error(f"An unexpected error occurred during image generation: {e}", exc_info=True)
            try:
                 await interaction.followup.send(f"Terjadi error tak terduga saat mencoba generate gambar: {e}")
            except Exception as send_e:
                 _logger.error(f"Failed to send unexpected Exception message: {send_e}", exc_info=True)


    # --- Shared Error Handler for AI Cog Slash Commands ---
    # This handler catches errors specifically for slash commands defined in THIS cog (e.g., /generate_image).
    async def ai_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for AI slash commands."""
        _logger.error(f"Handling AI command error for command {interaction.command.name if interaction.command else 'Unknown'} by user {interaction.user.id if interaction.user else 'Unknown'} in guild {interaction.guild_id if interaction.guild_id else 'DM'}.", exc_info=True) # Log handler start and traceback

        # Ensure we can send a message even if interaction response is done
        # For slash commands, followup is preferred after defer.
        if interaction.response.is_done():
            send_func = interaction.followup.send
            _logger.debug("Interaction response is done, using followup.")
        else:
            send_func = interaction.response.send_message
            _logger.debug("Interaction response is not done, using response.send_message.")


        # Try to send the error message
        try:
            if isinstance(error, app_commands.CheckFailure): # Catches app_commands.guild_only or custom checks
                 _logger.warning(f"AI command check failed: {error}")
                 # The custom check for AI channel already sends a message, so avoid sending again here.
                 # If it's a guild_only check failure, send a generic message.
                 if "Command ini hanya bisa digunakan di server" in str(error): # Check if it's likely from guild_only()
                     await send_func("Command ini hanya bisa digunakan di server.", ephemeral=True)
                 elif "channel AI yang sudah ditentukan" in str(error): # Check if it's from our custom channel check message
                      # Message already sent by the check itself in the command body
                      pass # Do nothing, message already sent
                 else: # Other custom check failures
                      await send_func(f"Check command gagal: {str(error)}", ephemeral=True) # Include error message for clarity

            elif isinstance(error, app_commands.CommandInvokeError):
                 _logger.error(f"CommandInvokeError in AI command: {error.original}", exc_info=error.original)
                 # Check if the original error is a GoogleAPIError or Gemini-specific exception
                 if isinstance(error.original, GoogleAPIError):
                      await send_func(f"Terjadi error pada API AI: {error.original}", ephemeral=True)
                 elif isinstance(error.original, types.BlockedPromptException) or isinstance(error.original, types.StopCandidateException): # Use types from google.genai
                       # These should ideally be caught in the command itself, but handle here as fallback
                       await send_func(f"Respons AI diblokir atau terhenti: {error.original}", ephemeral=True)
                 # Catch specific TypeErrors related to API call if they somehow reach here
                 elif isinstance(error.original, TypeError):
                      _logger.error(f"Unexpected TypeError caught in error handler: {error.original}", exc_info=True)
                      await send_func("Terjadi error konfigurasi internal AI saat memproses permintaan. Mohon laporkan ini ke administrator.", ephemeral=True)
                 else: # Other invoke errors
                      await send_func(f"Terjadi error saat mengeksekusi command AI: {error.original}", ephemeral=True)

            elif isinstance(error, app_commands.TransformerError):
                 _logger.warning(f"TransformerError in AI command: {error.original}")
                 await send_func(f"Nilai tidak valid diberikan untuk argumen '{error.param_name}': {error.original}", ephemeral=True)
            else:
                _logger.error(f"An unexpected error occurred in AI command: {error}", exc_info=True)
                await send_func(f"Terjadi error tak terduga: {error}", ephemeral=True)

        except Exception as send_error_e:
            _logger.error(f"Failed to send error message in AI command error handler: {send_error_e}", exc_info=True)
            # As a last resort, print to console or send via raw channel send if interaction fails completely
            print(f"FATAL ERROR in AI command handler for {interaction.command.name}: {error}. Also failed to send error message: {send_error_e}")


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the AICog."""
    # Check API Key availability before attempting to load the cog
    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY environment variable not found. AICog will not be loaded.")
        return # Do not load the cog if the API key is missing

    # Initialize Gemini models
    initialize_gemini()

    # Check if at least one model was initialized successfully
    # Load the cog if *either* is available, checks inside on_message/commands will handle disabled features.
    if _flash_text_model is None and _flash_image_gen_model is None:
         _logger.error("All Gemini models failed to initialize. AI features will be unavailable.")
         return # Do not load the cog if no models are available

    cog_instance = AICog(bot)
    await bot.add_cog(cog_instance)
    _logger.info("AICog loaded.")

    # Attach error handlers to the slash commands defined in THIS cog
    cog_instance.generate_image_slash.error(cog_instance.ai_command_error)