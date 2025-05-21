# Noelle_AI_Bot/main.py
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import logging
import asyncio
import sys # Untuk menambah path jika perlu

# Tambahkan path root proyek ke sys.path agar bisa impor dari utils dan ai_services
# Ini mungkin tidak perlu jika struktur Anda sudah benar dan Python bisa menemukannya
# import pathlib
# PROJECT_ROOT = pathlib.Path(__file__).parent.resolve()
# sys.path.insert(0, str(PROJECT_ROOT))


logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    _logger.critical("DISCORD_TOKEN tidak ditemukan! Bot tidak bisa jalan."); exit()

# Inisialisasi gemini_client akan terjadi saat modul gemini_services diimpor
from ai_services import gemini_client as gemini_services 

intents = discord.Intents.default()
intents.message_content = True
intents.members = True # Sesuaikan jika tidak butuh

bot = commands.Bot(command_prefix="noelleai!", intents=intents) # Ganti prefix jika mau

AI_COGS_TO_LOAD = [
    "ai_services.message_handler", # Mengandung MessageHandlerCog
    "ai_services.mention_handler", # Mengandung MentionHandlerCog
    "ai_services.image_generator", # Mengandung ImageGeneratorCog (dengan grup /ai dan /generate_image)
]

ai_group_registered_flag = False # Flag untuk memastikan grup /ai hanya didaftarkan sekali

async def load_cogs():
    global ai_group_registered_flag
    for cog_path in AI_COGS_TO_LOAD:
        try:
            await bot.load_extension(cog_path)
            _logger.info(f"Cog AI berhasil dimuat: {cog_path}")

            # Daftarkan grup /ai dari ImageGeneratorCog sekali saja
            if cog_path == "ai_services.image_generator" and not ai_group_registered_flag:
                cog_instance = bot.get_cog("AI Image Generator & Commands") # Sesuaikan dengan nama Cog
                if cog_instance and hasattr(cog_instance, 'ai_commands_group'):
                    bot.tree.add_command(cog_instance.ai_commands_group) # Tambahkan grup ke tree
                    _logger.info("Grup command '/ai' berhasil ditambahkan ke tree.")
                    ai_group_registered_flag = True
                elif cog_instance:
                     _logger.warning(f"Cog '{cog_path}' dimuat tapi tidak memiliki 'ai_commands_group'.")
                else:
                    _logger.warning(f"Cog '{cog_path}' tidak ditemukan setelah load untuk registrasi grup.")

        except commands.ExtensionAlreadyLoaded:
            _logger.warning(f"Cog AI '{cog_path}' sudah dimuat.")
        except Exception as e:
            _logger.error(f"Gagal memuat Cog AI {cog_path}: {e}", exc_info=True)

@bot.event
async def on_ready():
    _logger.info(f'{bot.user} (Noelle AI) telah terhubung ke Discord!')
    _logger.info(f'Terhubung ke {len(bot.guilds)} guilds.')

    if not gemini_services.is_ai_service_enabled():
        _logger.warning("Layanan AI tidak aktif atau klien Gemini tidak terinisialisasi.")
    else:
        _logger.info("Klien Gemini aktif dan layanan AI diaktifkan.")

    await load_cogs()

    try:
        synced = await bot.tree.sync() # Sinkronisasi global
        _logger.info(f"Menyinkronkan {len(synced)} slash command(s) global.")
    except Exception as e:
        _logger.error(f"Gagal menyinkronkan slash commands: {e}", exc_info=True)

    await bot.change_presence(activity=discord.Game(name="Menjawab dengan AI"))

async def main_async():
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        _logger.info("Bot Noelle AI dihentikan.")
    # Tidak perlu close_mongo_connection lagi