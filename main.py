# Noelle_AI_Bot/main.py
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import logging
import asyncio

# Konfigurasi logging dasar
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger(__name__)

# Muat environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    _logger.critical("DISCORD_TOKEN tidak ditemukan di .env! Bot tidak dapat dijalankan.")
    exit()

# Inisialisasi klien Gemini (ini akan dieksekusi saat modul diimpor)
# Pastikan gemini_client.py ada di sys.path atau diimpor dengan benar
from ai_services import gemini_client as gemini_services # Ini juga akan memanggil initialize_client() di dalamnya

# Tentukan Intents
intents = discord.Intents.default()
intents.message_content = True # Diperlukan untuk membaca konten pesan
intents.members = True # Opsional, jika ada command yang butuh info member detail

bot = commands.Bot(command_prefix="!", intents=intents) # Prefix tidak terlalu relevan jika hanya slash command

# --- Daftar modul Cog yang akan dimuat ---
# Kita memisahkan logika menjadi modul-modul yang bertindak seperti Cog
AI_MODULES_TO_LOAD = [
    "ai_services.message_handler", # Untuk on_message di AI channel
    "ai_services.mention_handler", # Untuk on_message mention
    "ai_services.image_generator", # Untuk /generate_image dan command /ai lainnya
]

# Flag untuk memastikan grup command /ai hanya didaftarkan sekali
ai_group_registered = False

async def load_ai_modules():
    global ai_group_registered
    for module_path in AI_MODULES_TO_LOAD:
        try:
            # Cog di discord.py biasanya adalah kelas dalam file.
            # Jika modul kita berisi kelas Cog, kita load sebagai extension.
            # Contoh: jika image_generator.py punya kelas ImageGeneratorCog(commands.Cog)
            await bot.load_extension(module_path)
            _logger.info(f"Berhasil memuat modul/cog AI: {module_path}")

            # Khusus untuk grup command /ai, daftarkan sekali saja
            if not ai_group_registered and module_path == "ai_services.image_generator":
                 # Asumsi ImageGeneratorCog memiliki atribut ai_commands_group
                 cog_instance = bot.get_cog("AI Image Generator") # Nama Cog dari ImageGeneratorCog
                 if cog_instance and hasattr(cog_instance, 'ai_commands_group'):
                     bot.tree.add_command(cog_instance.ai_commands_group)
                     _logger.info("Grup command '/ai' telah ditambahkan ke tree.")
                     ai_group_registered = True
                 else:
                     _logger.warning(f"Tidak dapat mendaftarkan grup '/ai' dari {module_path}.")

        except commands.ExtensionAlreadyLoaded:
            _logger.warning(f"Modul/cog AI '{module_path}' sudah dimuat.")
        except Exception as e:
            _logger.error(f"Gagal memuat modul/cog AI {module_path}: {e}", exc_info=True)

@bot.event
async def on_ready():
    _logger.info(f'{bot.user} telah terhubung ke Discord!')
    _logger.info(f'Terhubung ke {len(bot.guilds)} guilds.')

    if not gemini_services.is_ai_service_enabled() or gemini_services.get_gemini_client() is None:
        _logger.warning("Layanan AI tidak aktif atau klien Gemini tidak terinisialisasi. Fitur AI mungkin terbatas/tidak berfungsi.")
    else:
        _logger.info("Klien Gemini aktif dan layanan AI diaktifkan.")

    await load_ai_modules()

    try:
        synced = await bot.tree.sync()
        _logger.info(f"Menyinkronkan {len(synced)} slash command(s).")
        # if synced:
        #     _logger.info("Synced commands:")
        #     for command in synced:
        #         _logger.info(f"- {command.name} (ID: {command.id})")
    except Exception as e:
        _logger.error(f"Gagal menyinkronkan slash commands: {e}")

    await bot.change_presence(activity=discord.Game(name="dengan Model Gemini"))

async def main():
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _logger.info("Bot dihentikan oleh pengguna.")
    finally:
        # Pastikan koneksi DB ditutup jika ada
        if 'database' in globals() and hasattr(database, 'close_mongo_connection'):
            database.close_mongo_connection() 