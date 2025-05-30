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

# Noelle_AI_Bot/main.py
# ... (impor dan kode lainnya tetap sama) ...

AI_COGS_TO_LOAD = [
    "ai_services.message_handler",
    "ai_services.mention_handler",
    "ai_services.image_generator", 
]

async def load_cogs():
    # global ai_group_registered # Tidak perlu lagi
    for cog_path in AI_COGS_TO_LOAD:
        try:
            await bot.load_extension(cog_path) # Cukup ini, fungsi setup di cog akan menangani sisanya
            _logger.info(f"Berhasil memuat cog AI: {cog_path}")

        except commands.ExtensionAlreadyLoaded:
            _logger.warning(f"Cog AI '{cog_path}' sudah dimuat.")
        except commands.NoEntryPointError: # Tangani error ini secara spesifik
             _logger.error(f"GAGAL MUAT: Ekstensi '{cog_path}' tidak memiliki fungsi 'setup'.")
        except commands.ExtensionFailed as e: # Tangani error jika setup di cog raise ExtensionFailed
            _logger.error(f"GAGAL MUAT: Fungsi 'setup' di '{cog_path}' gagal: {e.name} - {e.original}", exc_info=False) # Jangan tampilkan traceback penuh jika sudah ditangani
        except Exception as e:
            _logger.error(f"Gagal memuat cog AI {cog_path}: {type(e).__name__} - {e}", exc_info=True)

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