import discord
import os
import google.generativeai as genai
import database # Import database module
import utils # Import utils module (if needed in the future, currently not directly used here)
from discord.ext import commands
from discord import app_commands
import logging
from PIL import Image # Required for handling image inputs
import io # Required for handling image bytes
import asyncio # Required for async operations like sleep and typing
import re # Required for potential URL finding

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

# --- Get API Key ---
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# --- Initialize Google AI ---
_flash_model = None # Only using gemini-2.0-flash as requested

def initialize_gemini():
    """Initializes the Google Generative AI client and the gemini-2.0-flash model."""
    global _flash_model

    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY environment variable not set. Skipping Gemini initialization. AI features will be unavailable.")
        return

    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        _logger.info("Gemini client configured.")

        # Initialize the requested model
        try:
            _flash_model = genai.GenerativeModel('gemini-2.0-flash')
            _logger.info("Initialized model: gemini-2.0-flash")
        except Exception as e:
            _logger.error(f"Failed to initialize model 'gemini-2.0-flash': {e}")
            _flash_model = None

        if _flash_model:
             _logger.info("Gemini model initialized successfully.")
        else:
             _logger.error("Gemini model failed to initialize. AI features will be unavailable.")

    except Exception as e:
        _logger.error(f"An unexpected error occurred during Gemini configuration: {e}")
        _flash_model = None # Ensure model is None if configuration fails


# Initialize Gemini when this cog file is imported
initialize_gemini()


class AICog(commands.Cog):
    """Cog for AI interaction features using on_message listener."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Store the initialized model
        self.flash_model = _flash_model


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Processes messages for AI interaction."""
        # Ignore messages from bots
        if message.author.bot:
            return

        # Ignore messages not in a guild
        if message.guild is None:
            return

        # Ensure the AI model is initialized
        if self.flash_model is None:
             # _logger.debug(f"Skipping AI processing for message in guild {message.guild.id}: Gemini model not initialized.")
             return # Silently ignore if model is missing


        # Get server configuration
        config = database.get_server_config(message.guild.id)
        ai_channel_id = config.get('ai_channel_id')

        # --- Scenario 1: Bot is mentioned (@NamaBot) in ANY channel ---
        # Check if the bot is mentioned and the message is NOT in the designated AI channel (if set)
        if self.bot.user in message.mentions and (ai_channel_id is None or message.channel.id != ai_channel_id):
             _logger.info(f"Processing bot mention message in guild {message.guild.name} ({message.guild.id}), channel {message.channel.name} ({message.channel.id}).")

             # Indicate that the bot is typing
             async with message.channel.typing():
                 try:
                     content_parts = []
                     # Extract text content, removing the bot's mention
                     text_content = message.content.replace(self.bot.user.mention, '').strip()

                     # Check for attachments (images) in the mention message
                     image_attachments = [att for att in message.attachments if 'image' in att.content_type]

                     if image_attachments:
                         # Limit number of images per prompt for mention responses too
                         if len(image_attachments) > 2: # Maybe a smaller limit for quicker mention responses?
                            await message.reply("Please provide no more than 2 images when mentioning me.")
                            return

                         for attachment in image_attachments:
                             try:
                                 image_bytes = await attachment.read()
                                 pil_image = Image.open(io.BytesIO(image_bytes))
                                 content_parts.append(pil_image)
                                 _logger.info(f"Added image attachment {attachment.filename} for mention response.")
                             except Exception as img_e:
                                 _logger.error(f"Failed to process image attachment {attachment.filename} for mention: {img_e}")
                                 # Send warning and continue if other parts exist
                                 await message.channel.send(f"Warning: Could not process image '{attachment.filename}' for mention response.")
                                 if len(image_attachments) == 1 and not text_content:
                                      await message.reply("Could not process the image you sent with the mention.")
                                      return


                     if text_content:
                         content_parts.append(text_content)
                         _logger.info("Added text content for mention response.")


                     if not content_parts:
                         # If only unsupported attachments or just the mention
                         await message.reply("Halo! Ada yang bisa saya bantu? (Anda menyebut saya tapi tidak ada teks atau gambar yang bisa diproses).")
                         return

                     # Call the Flash model for the mention response
                     response = await self.flash_model.generate_content(content_parts)
                     _logger.info(f"Received response from Gemini Flash for mention.")

                     # Extract text response (ignoring potential image output for simple mention)
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
                         # Handle empty response or blocked prompt for mention
                         if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason != genai.protos.enums.content.BlockReason.BLOCK_REASON_UNSPECIFIED:
                              block_reason = response.prompt_feedback.block_reason.name
                              _logger.warning(f"Mention prompt blocked by Gemini safety filter. Reason: {block_reason}.")
                              await message.reply("Maaf, permintaan ini diblokir oleh filter keamanan AI.")
                         else:
                             _logger.warning("Gemini Flash returned an empty response for mention.")
                             await message.reply("Maaf, saya tidak bisa memberikan respons saat ini.")
                     else:
                         # Send the one-off text response
                         # Do NOT split response for mention - keep it concise if possible, or truncate
                         if len(response_text) > 1500: # Shorter limit for one-off
                             response_text = response_text[:1500] + "..." # Truncate long responses
                             _logger.info(f"Truncated mention response to 1500 chars.")

                         await message.reply(response_text)
                         _logger.info("Mention response sent.")

                 # --- Error Handling for Mention Scenario ---
                 except genai.types.BlockedPromptException as e:
                     _logger.warning(f"Mention prompt blocked by Gemini API: {e}")
                     await message.reply("Maaf, permintaan ini melanggar kebijakan penggunaan AI.")
                 except genai.types.StopCandidateException as e:
                      _logger.warning(f"Gemini response stopped prematurely for mention: {e}")
                      await message.reply("Maaf, respons AI terhenti.")
                 except genai.types.APIError as e:
                     _logger.error(f"Gemini API Error during mention processing: {e}")
                     await message.reply(f"Terjadi error pada API AI: {e}")
                 except Exception as e:
                     _logger.error(f"An unexpected error occurred during mention processing: {e}")
                     await message.reply(f"Terjadi error saat memproses permintaan AI: {e}")

             return # Stop processing after handling the mention

        # --- Scenario 2: Message is in the designated AI channel ---
        # Check if this is the designated AI channel AND it's not just a bot mention that was already handled
        if ai_channel_id is not None and message.channel.id == ai_channel_id:
            _logger.info(f"Processing AI channel message in guild {message.guild.name} ({message.guild.id}), channel {message.channel.name} ({message.channel.id}).")

            # Indicate that the bot is typing
            async with message.channel.typing():
                try:
                    content_parts = []

                    # Check for attachments (images)
                    image_attachments = [att for att in message.attachments if 'image' in att.content_type]

                    if image_attachments:
                         if len(image_attachments) > 4: # Limit number of images per prompt for AI channel
                            await message.reply("Please provide no more than 4 images at a time for analysis.")
                            return

                         for attachment in image_attachments:
                             try:
                                 image_bytes = await attachment.read()
                                 pil_image = Image.open(io.BytesIO(image_bytes))
                                 content_parts.append(pil_image)
                                 _logger.info(f"Added image attachment {attachment.filename} to content parts.")
                             except Exception as img_e:
                                 _logger.error(f"Failed to process image attachment {attachment.filename} in AI channel: {img_e}")
                                 await message.channel.send(f"Warning: Could not process image '{attachment.filename}': {img_e}")
                                 if len(image_attachments) == 1 and not message.content.strip():
                                      await message.reply("Could not process the image you sent in the AI channel.")
                                      return


                    # Add text content if any
                    text_content = message.content.strip()
                    # Remove bot mention if it's at the start and was not handled by the mention scenario
                    # (This might happen if someone @mentions the bot *at the start* of a message *in the AI channel*)
                    # Although the mention scenario above *should* catch this, this is a safety.
                    if self.bot.user and text_content.startswith(self.bot.user.mention):
                         text_content = text_content.replace(self.bot.user.mention, '', 1).strip()


                    if text_content:
                        content_parts.append(text_content)
                        _logger.info("Added text content to content parts.")


                    if not content_parts:
                        _logger.debug("Message in AI channel had no processable content (text or supported images). Ignoring.")
                        return


                    # Use the Flash model for ALL processing in the AI channel
                    model = self.flash_model
                    if model is None: # Double check just in case init failed
                         await message.reply("AI model is not available. Please check the bot configuration or logs.")
                         return
                    _logger.info("Using Flash model for AI channel message.")


                    # Call the Gemini API with the combined content
                    response = await model.generate_content(content_parts)
                    _logger.info(f"Received response from Gemini API for AI channel message.")

                    # --- Parsing the response ---
                    # We will check for both text and potential image output.
                    # Image output from Flash is uncertain, but we'll try to parse it if it exists.
                    response_text = ""
                    image_urls = []
                    # Check for candidates and content parts first
                    if hasattr(response, 'candidates') and response.candidates:
                         candidate = response.candidates[0]
                         if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                             for part in candidate.content.parts:
                                  if hasattr(part, 'text'):
                                       response_text += str(part.text) # Accumulate text parts
                                  # Attempt to find image output parts - highly speculative for Flash
                                  elif hasattr(part, 'inline_data') and part.inline_data.mime_type.startswith('image/'):
                                       _logger.warning("AI Channel: Received inline image data. Not currently supported for sending.")
                                       image_urls.append("Inline image data received (cannot display directly yet).") # Indicate received data
                                  elif hasattr(part, 'file_data') and hasattr(part.file_data, 'file_uri'):
                                       image_urls.append(part.file_data.file_uri)
                                       _logger.info(f"AI Channel: Found file_uri in response: {part.file_data.file_uri}")
                                  # Add other checks based on API docs if they exist
                         # Fallback checks if structure is different (less likely for multimodal)
                         elif hasattr(candidate, 'text'):
                              response_text = str(candidate.text)
                    # Check top level text attribute as a final fallback
                    elif hasattr(response, 'text'):
                         response_text = str(response.text)

                    # Additionally, check accumulated response_text for markdown image links as a heuristic
                    # (Models sometimes generate markdown links instead of structured image output)
                    if response_text:
                         markdown_image_pattern = r'!\[.*?\]\((https?://\S+\.(?:png|jpg|jpeg|gif|webp))\)'
                         found_markdown_urls = re.findall(markdown_image_pattern, response_text)
                         image_urls.extend(found_markdown_urls)
                         if found_markdown_urls:
                             _logger.info(f"AI Channel: Found markdown image URLs in text: {found_markdown_urls}")
                             # Optionally, remove the markdown links from the text response if URLs are found
                             # response_text = re.sub(markdown_image_pattern, '', response_text).strip()


                    # --- Send Response ---
                    if not response_text.strip() and not image_urls:
                         # Handle empty response or blocked prompt
                         if hasattr(response, 'prompt_feedback') and response.prompt_feedback and response.prompt_feedback.block_reason != genai.protos.enums.content.BlockReason.BLOCK_REASON_UNSPECIFIED:
                             block_reason = response.prompt_feedback.block_reason.name
                             _logger.warning(f"AI Channel prompt blocked by Gemini safety filter. Reason: {block_reason}.")
                             await message.reply("Maaf, respons ini diblokir oleh filter keamanan AI.")
                         else:
                            _logger.warning("Gemini Flash returned an empty response in AI channel.")
                            await message.reply("Maaf, saya tidak bisa memberikan respons saat ini.")
                         return # Stop processing

                    # Send image URLs first if any were found
                    if image_urls:
                        # Send each image URL in a separate message or combine? Separate is safer.
                        for url in image_urls:
                            # Can check if it's our placeholder text for inline data
                            if url.startswith("Inline image data"):
                                await message.reply(url)
                            else:
                                await message.reply(f"Generated Image URL: {url}")
                            await asyncio.sleep(0.5) # Small delay

                    # Send text response if any
                    if response_text.strip():
                        if len(response_text) > 2000:
                            _logger.info("AI Channel: Splitting long text response into multiple messages.")
                            chunks = [response_text[i:i+2000] for i in range(0, len(response_text), 2000)]
                            for i, chunk in enumerate(chunks):
                                header = f"(Bagian {i+1}/{len(chunks)}):\n" if len(chunks) > 1 else ""
                                await message.reply(header + chunk)
                                await asyncio.sleep(0.5)
                        else:
                            await message.reply(response_text)
                        _logger.info("AI Channel text response sent.")

                # --- Error Handling for AI Channel Scenario ---
                except genai.types.BlockedPromptException as e:
                    _logger.warning(f"AI Channel prompt blocked by Gemini API: {e}")
                    await message.reply("Maaf, permintaan ini melanggar kebijakan penggunaan AI dan tidak bisa diproses.")
                except genai.types.StopCandidateException as e:
                     _logger.warning(f"Gemini response stopped prematurely in AI channel: {e}")
                     await message.reply("Maaf, respons AI terhenti di tengah jalan.")
                except genai.types.APIError as e:
                    _logger.error(f"Gemini API Error during AI channel processing: {e}")
                    await message.reply(f"Terjadi error pada API AI: {e}")
                except Exception as e:
                    _logger.error(f"An unexpected error occurred during AI processing (AI channel): {e}")
                    await message.reply(f"Terjadi error saat memproses permintaan AI: {e}")

        # If not in AI channel and not a bot mention, just ignore the message.
        # No 'else' block needed, function simply ends.


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the AICog."""
    # Check API Key availability before attempting to load the cog
    if GOOGLE_API_KEY is None:
        _logger.error("GOOGLE_API_KEY environment variable not found. AICog will not be loaded.")
        return # Do not load the cog if the API key is missing

    # Initialize Gemini model
    initialize_gemini()

    # Check if the model was initialized successfully before adding the cog
    if _flash_model is None:
         _logger.error("Gemini model failed to initialize. AICog will not be loaded.")
         return # Do not load the cog if the model is unavailable

    await bot.add_cog(AICog(bot))
    _logger.info("AICog loaded.")

    # No slash commands in this cog, so no slash command error handlers to attach