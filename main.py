# Noelle_Bot/main.py
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import logging
import asyncio
import sys
import pathlib

# --- Tambahkan path root proyek ke sys.path ---
# Ini membantu Python menemukan modul di direktori utils/ dan ai_services/
# serta cogs/ saat menjalankan main.py dari root.
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# ---------------------------------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
_logger = logging.getLogger("noelle_bot.main")

load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    _logger.critical("DISCORD_TOKEN tidak ditemukan! Bot tidak bisa jalan."); exit()

# Inisialisasi modul penting (klien Gemini dan koneksi DB)
from ai_services import gemini_client as gemini_services 
import database # Ini akan mencoba connect_to_mongo() jika dipanggil

intents = discord.Intents.default()
intents.message_content = True
intents.members = True # Untuk userinfo, on_member_join, dll.
intents.guilds = True # Untuk akses guild saat startup

# --- Inisialisasi bot dengan prefix command ---
bot = commands.Bot(command_prefix="#", intents=intents, help_command=None) # help_command=None jika ingin buat help custom

# --- Daftar Cog yang akan dimuat ---
COGS_TO_LOAD = [
    "cogs.basic_commands_cog",
    "cogs.moderation_cog",
    "cogs.embed_cog",
    "ai_services.message_handler", # Mengandung MessageHandlerCog
    "ai_services.mention_handler", # Mengandung MentionHandlerCog
    "ai_services.image_generator", # Mengandung ImageGeneratorCog (dengan grup /ai dan /generate_image)
]

# Flag untuk memastikan grup command /ai hanya didaftarkan sekali jika diperlukan manual
# Namun, dengan struktur cog yang benar, ini seharusnya tidak diperlukan.
# ai_group_registered_flag = False 

async def load_all_cogs():
    # global ai_group_registered_flag # Tidak perlu jika pendaftaran grup otomatis
    for cog_path in COGS_TO_LOAD:
        try:
            await bot.load_extension(cog_path)
            _logger.info(f"Cog berhasil dimuat: {cog_path}")

            # Logika pendaftaran grup command /ai dari ImageGeneratorCog secara manual
            # Seharusnya tidak diperlukan lagi jika grup command didefinisikan dengan benar di dalam cog.
            # if cog_path == "ai_services.image_generator" and not ai_group_registered_flag:
            #     cog_instance = bot.get_cog("AI Image Generator & Commands") 
            #     if cog_instance and hasattr(cog_instance, 'ai_commands_group'):
            #         bot.tree.add_command(cog_instance.ai_commands_group)
            #         _logger.info("Grup command '/ai' berhasil ditambahkan ke tree.")
            #         ai_group_registered_flag = True
            #     elif cog_instance:
            #          _logger.warning(f"Cog '{cog_path}' dimuat tapi tidak memiliki 'ai_commands_group'.")
            #     else:
            #         _logger.warning(f"Cog '{cog_path}' tidak ditemukan setelah load untuk registrasi grup.")

        except commands.ExtensionAlreadyLoaded:
            _logger.warning(f"Cog '{cog_path}' sudah dimuat.")
        except commands.NoEntryPointError:
             _logger.error(f"GAGAL MUAT: Ekstensi '{cog_path}' tidak memiliki fungsi 'setup'.")
        except commands.ExtensionFailed as e:
            _logger.error(f"GAGAL MUAT: Fungsi 'setup' di '{cog_path}' gagal: {e.name} - {e.original}", exc_info=False)
        except Exception as e:
            _logger.error(f"Gagal memuat Cog {cog_path}: {type(e).__name__} - {e}", exc_info=True)

@bot.event
async def on_ready():
    _logger.info(f'{bot.user.name}#{bot.user.discriminator} (Noelle Bot) telah terhubung ke Discord!')
    _logger.info(f'ID Bot: {bot.user.id}')
    _logger.info(f'Terhubung ke {len(bot.guilds)} guilds.')

    # Coba koneksi ke database saat ready jika belum
    if not database._mongo_client: # Cek apakah klien sudah ada
        _logger.info("Mencoba koneksi ke MongoDB saat on_ready...")
        database.connect_to_mongo()

    if not gemini_services.is_ai_service_enabled():
        _logger.warning("Layanan AI tidak aktif atau klien Gemini tidak terinisialisasi.")
    else:
        _logger.info("Klien Gemini aktif dan layanan AI diaktifkan.")

    await load_all_cogs()

    try:
        # Sinkronisasi global untuk slash commands
        # Jika Anda punya command spesifik guild, Anda bisa sync per guild
        # await bot.tree.sync() # Untuk sinkronisasi global
        # Untuk pengembangan, lebih aman sync ke satu guild dulu:
        # TEST_GUILD_ID = 123456789012345678 # Ganti dengan ID server tes Anda
        # guild_obj = discord.Object(id=TEST_GUILD_ID)
        # bot.tree.copy_global_to(guild=guild_obj)
        # synced = await bot.tree.sync(guild=guild_obj)
        
        # Sinkronisasi Global (gunakan ini jika siap untuk semua server)
        synced = await bot.tree.sync()
        _logger.info(f"Menyinkronkan {len(synced)} application command(s).")
        if synced:
            # _logger.debug("Synced commands:")
            # for cmd in synced: _logger.debug(f"- Name: {cmd.name}, ID: {cmd.id}, Type: {cmd.type}")
            pass

    except Exception as e:
        _logger.error(f"Gagal menyinkronkan application commands: {e}", exc_info=True)

    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="#help | /help"))

@bot.event
async def on_connect():
    _logger.info("Bot berhasil terhubung ke Discord Gateway.")

@bot.event
async def on_disconnect():
    _logger.warning("Bot terputus dari Discord Gateway.")

@bot.event
async def on_resumed():
    _logger.info("Bot berhasil menyambung kembali sesi dengan Discord Gateway.")

# Tambahkan help command dasar untuk prefix command
@bot.command(name="help", help="Menampilkan pesan bantuan ini.")
async def custom_help_command(ctx: commands.Context, *, command_name: str = None):
    prefix = ctx.prefix
    if command_name:
        command = bot.get_command(command_name)
        if command and not command.hidden:
            embed = discord.Embed(title=f"Bantuan untuk `{prefix}{command.name}`", description=command.help or "Tidak ada detail.", color=discord.Color.blurple())
            if command.aliases:
                embed.add_field(name="Alias", value=", ".join([f"`{prefix}{a}`" for a in command.aliases]), inline=False)
            if command.signature:
                embed.add_field(name="Penggunaan", value=f"`{prefix}{command.name} {command.signature}`", inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"Perintah `{command_name}` tidak ditemukan atau disembunyikan.")
    else:
        embed = discord.Embed(title="Bantuan Perintah Noelle", description=f"Gunakan `{prefix}help [nama_perintah]` untuk info detail.\nSlash commands juga tersedia, ketik `/` untuk melihatnya.", color=discord.Color.gold())
        
        # Kelompokkan command berdasarkan cog (jika ada nama cog)
        cogs_commands = {}
        for cmd in bot.commands:
            if not cmd.hidden:
                cog_name = cmd.cog_name or "Lainnya"
                if cog_name not in cogs_commands:
                    cogs_commands[cog_name] = []
                aliases_str = f" (alias: {', '.join(cmd.aliases)})" if cmd.aliases else ""
                cogs_commands[cog_name].append(f"`{prefix}{cmd.name}{aliases_str}` - {cmd.help.splitlines()[0] if cmd.help else 'Tidak ada deskripsi.'}")

        for cog_name, cmds_list in cogs_commands.items():
            if cmds_list: # Hanya tambah field jika ada command
                embed.add_field(name=f"**{cog_name}**", value="\n".join(cmds_list), inline=False)
        
        await ctx.send(embed=embed)


async def main_async():
    async with bot:
        # Inisialisasi koneksi database di sini jika belum dari modul database
        if not database._mongo_client:
            _logger.info("Mencoba koneksi awal ke MongoDB...")
            if not database.connect_to_mongo():
                _logger.warning("Gagal koneksi ke MongoDB. Fitur database mungkin tidak berfungsi.")
        
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        _logger.info("Bot Noelle dihentikan.")
    finally:
        if hasattr(database, 'close_mongo_connection'): # Pastikan modul database punya fungsi ini
            database.close_mongo_connection()
        _logger.info("Proses bot selesai.")