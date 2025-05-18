import discord
import os
import google.generativeai as genai
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
# Import specific types and exceptions from genai.types
import google.generativeai.types as genai_types
# --- FIX: Import APIError directly from genai ---
from google.generativeai import APIError # Import APIError from the top level
# --- END FIX ---

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

# --- Get API Key ---
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# --- Initialize Google AI ---
# Use standard gemini-2.0-flash for mention responses and AI channel conversation/analysis
_flash_text_model = None
# Use gemini-2.0-flash-preview-image-generation ONLY for the explicit generate_image command
_flash_image_gen_model = None


def initialize_gemini():
    """Initializes the Google Generative AI client and the required models."""
    global _flash_text_model, _flash_image_gen_model

    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY environment variable not set. Skipping Gemini initialization. AI features will be unavailable.")
        return

    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        _logger.info("Gemini client configured.")

        # Initialize standard gemini-2.0-flash model (for text/vision in AI channel & mention text)
        try:
            _flash_text_model = genai.GenerativeModel('gemini-2.0-flash')
            _logger.info("Initialized text/vision model: gemini-2.0-flash")
        except Exception as e:
            _logger.error(f"Failed to initialize text/vision model 'gemini-2.0-flash': {e}", exc_info=True)

        # Initialize image generation model (for generate_image command)
        try:
            _flash_image_gen_model = genai.GenerativeModel('gemini-2.0-flash-preview-image-generation')
            _logger.info("Initialized image generation model: gemini-2.0-flash-preview-image-generation")
        except Exception as e:
            _logger.error(f"Failed to initialize image generation model 'gemini-2.0-flash-preview-image-generation': {e}", exc_info=True)
            _flash_image_gen_model = None # Ensure it's None if init fails

        if _flash_text_model or _flash_image_gen_model:
             _logger.info("At least one Gemini model initialized successfully.")
        else:
             _logger.error("All Gemini model initializations failed. AI features will be unavailable.")


    except Exception as e:
        _logger.error(f"An unexpected error occurred during Gemini configuration: {e}", exc_info=True)
        _flash_text_model = None
        _flash_image_gen_model = None


# Initialize Gemini when this cog file is imported
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

                        # Call the standard Flash model (ASYNC)
                        # Note: This call is for conversation/analysis, NOT explicit image generation.
                        response = await model.generate_content_async(content_parts)
                        _logger.info(f"Received response from Gemini Flash for AI channel message.")

                        # --- Parsing Text Response (expecting text from this model here) ---
                        response_text = ""
                        if hasattr(response, 'candidates') and response.candidates:
                             candidate = response.candidates[0]
                             if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                                 # Accumulate text parts
                                 response_text = "".join(str(part.text) for part in candidate.content.parts if hasattr(part, 'text'))
                             elif hasattr(candidate, 'text'):
                                 response_text = str(candidate.text)
                        elif hasattr(response, 'text'):
                             response_text = str(response.text)

                        # --- Send Text Response ---
                        if not response_text.strip():
                             if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason != genai_types.content.BlockReason.BLOCK_REASON_UNSPECIFIED:
                                 block_reason = response.prompt_feedback.block_reason.name
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
                    except genai_types.BlockedPromptException as e:
                        _logger.warning(f"AI Channel prompt blocked by Gemini API: {e}")
                        await message.reply("Maaf, permintaan ini melanggar kebijakan penggunaan AI dan tidak bisa diproses.")
                    except genai_types.StopCandidateException as e:
                         _logger.warning(f"Gemini response stopped prematurely in AI channel: {e}")
                         await message.reply("Maaf, respons AI terhenti di tengah jalan.")
                    # --- FIX: Changed genai_types.APIError to genai.APIError ---
                    except APIError as e: # Catches API errors from generate_content_async
                        _logger.error(f"Gemini API Error during AI channel processing (on_message): {e}", exc_info=True)
                        await message.reply(f"Terjadi error pada API AI: {e}")
                    # --- END FIX ---
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
                  _logger.warning(f"Skipping mention response: Standard Flash model not initialized.")
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

                     # Call the standard Flash model for the mention response (ASYNC)
                     response = await self.flash_text_model.generate_content_async(content_parts)
                     _logger.info(f"Received response from Gemini Flash for mention.")

                     # Extract text response (only expect text from this model/scenario)
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
                         if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason != genai_types.content.BlockReason.BLOCK_REASON_UNSPECIFIED:
                              block_reason = response.prompt_feedback.block_reason.name
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

                 except genai_types.BlockedPromptException as e:
                     _logger.warning(f"Mention prompt blocked by Gemini API: {e}")
                     await message.reply("Maaf, permintaan ini melanggar kebijakan penggunaan AI.")
                 except genai_types.StopCandidateException as e:
                      _logger.warning(f"Gemini response stopped prematurely for mention: {e}")
                      await message.reply("Maaf, respons AI terhenti.")
                 # --- FIX: Changed genai_types.APIError to APIError (imported from genai) ---
                 except APIError as e:
                     _logger.error(f"Gemini API Error during mention processing: {e}", exc_info=True)
                     await message.reply(f"Terjadi error pada API AI: {e}")
                 # --- END FIX ---
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

        # We check interaction.channel_id specifically, as interaction.channel is a TextChannel object
        if ai_channel_id is None or interaction.channel_id != ai_channel_id:
             # Get the channel object to mention it if possible
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
             _logger.warning(f"Skipping generate_image in guild {interaction.guild.id}: Image generation model not initialized.")
             await interaction.response.send_message("Layanan AI untuk generate gambar tidak tersedia. Model AI untuk generate gambar gagal diinisialisasi.", ephemeral=True)
             return

        if not prompt.strip():
             await interaction.response.send_message("Mohon berikan deskripsi untuk gambar yang ingin Anda buat.", ephemeral=True)
             return


        await interaction.response.defer(ephemeral=False) # Defer the response, visible to everyone

        try:
            _logger.info(f"Calling image generation model for prompt: '{prompt}'.")
            # Call the image generation model with required config (ASYNC)
            # --- FIX: Removed response_modalities from GenerationConfig constructor ---
            response = await model.generate_content_async(
                 prompt, # Input is just the text prompt for generation
                 generation_config=genai_types.GenerationConfig(), # GenerationConfig object (empty or with parameters like temperature)
                 response_modalities=['TEXT', 'IMAGE'] # Pass response_modalities directly to generate_content_async
            )
            # --- END FIX ---
            _logger.info(f"Received response from Gemini API for image generation.")

            # --- Parsing the response for both text and image ---
            response_text = "" # Accompanying text
            image_urls = [] # Collect image URLs if returned
            image_data_parts = [] # Collect inline image data parts if returned

            if hasattr(response, 'candidates') and response.candidates:
                 candidate = response.candidates[0]
                 if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                     for part in candidate.content.parts:
                          if hasattr(part, 'text'):
                               response_text += str(part.text) # Accumulate text parts
                          # Check for structured image output
                          elif hasattr(part, 'inline_data') and hasattr(part.inline_data, 'mime_type') and part.inline_data.mime_type.startswith('image/'):
                               _logger.info("Generate Image: Received inline image data in response.")
                               image_data_parts.append(part) # Store the part to process later
                          elif hasattr(part, 'file_data') and hasattr(part.file_data, 'file_uri'):
                               # API returned a file URI
                               image_urls.append(part.file_data.file_uri)
                               _logger.info(f"Generate Image: Found file_uri in response: {part.file_data.file_uri}")

            # --- Send Response ---
            if not response_text.strip() and not image_urls and not image_data_parts:
                 # Handle empty response or blocked prompt
                 if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason != genai_types.content.BlockReason.BLOCK_REASON_UNSPECIFIED:
                     block_reason = response.prompt_feedback.block_reason.name
                     _logger.warning(f"Generate Image prompt blocked by Gemini safety filter. Reason: {block_reason}. Full feedback: {response.prompt_feedback}")
                     await interaction.followup.send("Maaf, permintaan generate gambar ini diblokir oleh filter keamanan AI.")
                 else:
                    _logger.warning(f"Image generation model returned an empty response. Full response object: {response}")
                    await interaction.followup.send("Gagal menghasilkan gambar. AI memberikan respons yang tidak terduga atau kosong.")
                 return # Stop processing

            # Send image outputs first
            if image_urls:
                 _logger.info(f"Generate Image: Sending {len(image_urls)} image URLs.")
                 for url in image_urls:
                     # Ensure the URL is valid format for embed image
                     if url and (url.lower().endswith('.png') or url.lower().endswith('.jpg') or url.lower().endswith('.jpeg') or url.lower().endswith('.gif') or url.lower().endswith('.webp')):
                          image_embed = discord.Embed(color=discord.Color.blue())
                          image_embed.set_image(url=url)
                          prompt_text_footer = prompt[:100] + ('...' if len(prompt) > 100 else '')
                          image_embed.set_footer(text=f"Dihasilkan untuk \"{prompt_text_footer}\"")
                          try:
                               await interaction.followup.send(embed=image_embed)
                               _logger.info(f"Sent image embed for URL: {url}")
                          except Exception as embed_e:
                               _logger.error(f"Failed to send image embed for URL {url}: {embed_e}", exc_info=True)
                               await interaction.followup.send(f"URL Gambar yang Dihasilkan: {url}") # Fallback
                     else:
                          _logger.warning(f"Skipping image embed for potential non-image URL: {url}")
                          await interaction.followup.send(f"URL yang Ditemukan (mungkin bukan gambar): {url}")
                     await asyncio.sleep(0.5) # Small delay

            # Handle inline image data parts (requires sending as discord.File)
            if image_data_parts:
                 _logger.warning(f"Generate Image: Found {len(image_data_parts)} inline image data parts. Attempting to send as files.")
                 await interaction.followup.send("Mendeteksi data gambar inline dalam respons. Mencoba mengirim sebagai file...")
                 for i, part in enumerate(image_data_parts):
                      try:
                           # Decode base64 data
                           image_bytes = base64.b64decode(part.inline_data.data)
                           # Create a discord.File object
                           # Guess file extension from mime type
                           mime_type = part.inline_data.mime_type
                           extension = mime_type.split('/')[-1] if '/' in mime_type else 'png' # Default to png
                           file_name = f"generated_image_{i+1}.{extension}"

                           discord_file = discord.File(io.BytesIO(image_bytes), filename=file_name)

                           # Send the file
                           await interaction.followup.send(f"Gambar #{i+1}:", file=discord_file)
                           _logger.info(f"Successfully sent inline image data as file {file_name}.")

                      except Exception as file_e:
                           _logger.error(f"Failed to send inline image data part {i+1} as file: {file_e}", exc_info=True)
                           try:
                               await interaction.followup.send(f"Gagal mengirim gambar inline #{i+1}.")
                           except Exception as send_e:
                                _logger.error(f"Failed to send error message for failed inline image file: {send_e}")

                      await asyncio.sleep(0.5)


            # Send accompanying text response if any (after images)
            if response_text.strip():
                 # For slash command response, we can just send the text directly
                 # No need for chunking if sent via followup, Discord handles it better.
                 # But check if the total response (including images) exceeds limits or if text alone is huge.
                 # For safety, let's still chunk if the text alone is very long.
                 if len(response_text) > 1990: # Use 1990 to be safe if combined with other things later
                      _logger.info("Generate Image: Splitting accompanying text response into multiple messages (chunk size 1990).")
                      chunks = [response_text[i:i+1990] for i in range(0, len(response_text), 1990)]
                      for i, chunk in enumerate(chunks):
                           header = f"(Teks Bagian {i+1}/{len(chunks)}):\n" if len(chunks) > 1 else "" # Differentiate from image parts
                           try:
                               await interaction.followup.send(header + chunk)
                               _logger.debug(f"Sent accompanying text chunk {i+1}/{len(chunks)}.")
                           except Exception as send_e:
                                _logger.error(f"Failed to send accompanying text chunk {i+1}/{len(chunks)}: {send_e}", exc_info=True)
                                # Attempt to send error message in channel if followup fails
                                try:
                                     await interaction.channel.send(f"Gagal mengirim bagian teks pendamping {i+1} karena error: {send_e}")
                                except Exception as send_e_again:
                                     _logger.error(f"Failed to send error message for failed accompanying text chunk: {send_e_again}")

                           await asyncio.sleep(0.5)
                 else:
                      await interaction.followup.send(response_text)
                      _logger.info("Generate Image: Accompanying text response sent (single message).")


            # If no image or text was generated but no block reason
            # This case is handled at the beginning of the 'Send Response' block.
            # Adding an extra check here might be redundant but doesn't hurt.
            # if not image_urls and not image_data_parts and not response_text.strip():
            #      _logger.warning(f"Image generation command returned empty response with no block reason. Full response object: {response}")
            #      await interaction.followup.send("Gagal menghasilkan gambar. AI memberikan respons kosong.")


        # --- Error Handling for generate_image command ---
        except genai_types.BlockedPromptException as e:
             _logger.warning(f"Generate Image prompt blocked by Gemini API: {e}")
             await interaction.followup.send("Maaf, permintaan generate gambar ini diblokir oleh filter keamanan AI.")
        except genai_types.StopCandidateException as e:
             _logger.warning(f"Gemini response stopped prematurely during image generation: {e}")
             await interaction.followup.send("Maaf, proses generate gambar terhenti di tengah jalan.")
        # --- FIX: Changed genai_types.APIError to APIError (imported from genai) ---
        except APIError as e:
            _logger.error(f"Gemini API Error during generate_image: {e}", exc_info=True)
            await interaction.followup.send(f"Terjadi error pada API AI saat generate gambar: {e}")
        # --- END FIX ---
        except Exception as e:
            _logger.error(f"An unexpected error occurred during image generation: {e}", exc_info=True)
            await interaction.followup.send(f"Terjadi error tak terduga saat mencoba generate gambar: {e}")


    # --- Shared Error Handler for AI Cog Slash Commands ---
    # This handler catches errors specifically for slash commands defined in THIS cog (e.g., /generate_image).
    # --- FIX: Updated signature to accept standard interaction and error ---
    async def ai_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for AI slash commands."""
        _logger.error(f"Handling AI command error for command {interaction.command.name if interaction.command else 'Unknown'} by user {interaction.user.id if interaction.user else 'Unknown'} in guild {interaction.guild_id if interaction.guild_id else 'DM'}.", exc_info=True) # Log handler start and traceback

        # Ensure we can send a message even if interaction response is done
        # For slash commands, followup is preferred after defer.
        # Check if interaction is already responded
        if interaction.response.is_done():
            send_func = interaction.followup.send
            _logger.debug("Interaction response is done, using followup.")
        else:
            send_func = interaction.response.send_message
            _logger.debug("Interaction response is not done, using response.send_message.")
            # If response is not done and it's a CommandInvokeError, defer first if not deferred already?
            # No, send_message should work if not deferred. Deferring is usually done at command start.
            # Just use send_message directly.

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
                 # Check if the original error is an APIError from Google
                 if isinstance(error.original, APIError):
                      await send_func(f"Terjadi error pada API AI: {error.original}", ephemeral=True)
                 elif isinstance(error.original, genai_types.BlockedPromptException) or isinstance(error.original, genai_types.StopCandidateException):
                       # These should ideally be caught in the command itself, but handle here as fallback
                       await send_func(f"Respons AI diblokir atau terhenti: {error.original}", ephemeral=True)
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
    # --- END FIX ---


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