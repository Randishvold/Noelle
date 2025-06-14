# Noelle_Bot/ai_services/image_generator.py

import discord
from discord.ext import commands
from discord import app_commands
import google.genai as genai
from google.genai import types as genai_types
from google.api_core import exceptions as google_exceptions
import asyncio
import io
import logging

from . import gemini_client as gemini_services
from utils import ai_utils

_logger = logging.getLogger("noelle_bot.ai.image_generator")

class ImageGeneratorCog(commands.Cog, name="AI Image Generator"):
    """Cog ini menangani command /generate_image secara mandiri."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("ImageGeneratorCog (Mandiri) instance dibuat.")
    
    async def _ensure_ai_channel(self, interaction: discord.Interaction) -> bool:
        designated_name = gemini_services.get_designated_ai_channel_name().lower()
        
        # Cek jika interaksi sudah di-defer/direspons
        send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message

        if not isinstance(interaction.channel, discord.TextChannel) or interaction.channel.name.lower() != designated_name:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            
            await interaction.followup.send(f"Perintah ini hanya bisa digunakan di channel `{gemini_services.get_designated_ai_channel_name()}`.", ephemeral=True)
            return False
        return True

    @app_commands.command(name='generate_image', description='Membuat gambar dari teks di channel AI.')
    @app_commands.describe(prompt='Deskripsikan gambar yang ingin Anda buat.')
    @app_commands.guild_only()
    async def generate_image_command(self, interaction: discord.Interaction, prompt: str):
        if not await self._ensure_ai_channel(interaction):
            return
            
        if not prompt.strip():
            send_method = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
            return await send_method("Mohon berikan deskripsi gambar.", ephemeral=True)
        
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=False)

        try:
            client = gemini_services.get_gemini_client()
            model_name = gemini_services.GEMINI_IMAGE_GEN_MODEL_NAME
            _logger.info(f"IMAGE_GEN: Memanggil model '{model_name}' dengan prompt: '{prompt}'.")
            
            # --- PERBAIKAN FINAL DAN KRITIS ---
            # Kita harus meminta KOMBINASI [TEXT, IMAGE] seperti yang diminta oleh pesan error.
            config = genai_types.GenerateContentConfig(
                response_modalities=[genai_types.Modality.TEXT, genai_types.Modality.IMAGE]
            )
            # ------------------------------------

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model_name,
                contents=prompt,
                config=config 
            )
            
            _logger.info("IMAGE_GEN: Menerima respons dari API.")

            img_bytes = None
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and 'image' in part.inline_data.mime_type:
                        img_bytes = part.inline_data.data
                        break

            if img_bytes:
                img_file = discord.File(io.BytesIO(img_bytes), filename="noelle_art.png")
                description_content = f"**Prompt:** \"{discord.utils.escape_markdown(prompt[:1500])}{'...' if len(prompt)>1500 else ''}\""
                
                img_embed = discord.Embed(
                    title="Gambar Dihasilkan oleh Noelle ✨",
                    description=description_content,
                    color=discord.Color.random()
                )
                img_embed.set_image(url=f"attachment://{img_file.filename}")
                img_embed.set_footer(text=f"Diminta oleh: {interaction.user.display_name}")

                await interaction.followup.send(embed=img_embed, file=img_file)
            else:
                text_response = response.text if hasattr(response, 'text') else "Tidak ada gambar yang dihasilkan."
                _logger.warning(f"Tidak ada gambar di respons. Respons teks: {text_response}")
                await interaction.followup.send(f"Maaf, saya tidak dapat menghasilkan gambar dari prompt tersebut. Mungkin coba deskripsi yang berbeda?\n\n*Respons Teks dari AI: \"{text_response[:1500]}\"*", ephemeral=True)

        except Exception as e:
            _logger.error(f"Error tak terduga dalam /generate_image: {e}", exc_info=True)
            if not interaction.is_expired():
                try:
                    await interaction.followup.send("Terjadi kesalahan internal saat membuat gambar.", ephemeral=True)
                except discord.errors.HTTPException:
                    pass

async def setup(bot: commands.Bot):
    if gemini_services.is_image_service_enabled():
        await bot.add_cog(ImageGeneratorCog(bot))
        _logger.info("ImageGeneratorCog (Mandiri) berhasil dimuat.")
    else:
        _logger.warning("ImageGeneratorCog tidak dimuat karena layanan gambar dinonaktifkan.")