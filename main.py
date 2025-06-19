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
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.logging_config import setup_logging
setup_logging()
_logger = logging.getLogger("noelle_bot.main")

load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
if not DISCORD_TOKEN:
    _logger.critical("DISCORD_TOKEN tidak ditemukan! Bot tidak bisa jalan.")
    exit()

# Inisialisasi modul penting (klien Gemini dan koneksi DB)
# Impor ini akan menjalankan initialize_client() di dalamnya
from ai_services import gemini_client as gemini_services 
from core import database

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="$", intents=intents, help_command=None)

# --- Daftar Cog yang akan dimuat ---
COGS_TO_LOAD = [
    "cogs.basic_commands_cog",
    "cogs.moderation_cog",
    "cogs.embed_cog",
    "ai_services.ai_commands_cog",
    "ai_services.message_handler",
    "ai_services.mention_handler",
    "ai_services.image_generator",
]

async def load_all_cogs():
    for cog_path in COGS_TO_LOAD:
        try:
            await bot.load_extension(cog_path)
            _logger.info(f"Cog berhasil dimuat: {cog_path}")
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
    if not database.get_db_status():
        _logger.info("Mencoba koneksi ke MongoDB saat on_ready...")
        await database.connect_to_mongo()

    # --- PERBAIKAN: Gunakan fungsi pengecekan yang baru dan lebih spesifik ---
    if gemini_services.is_text_service_enabled():
        _logger.info("✅ Layanan AI Teks (Chat/Mention) aktif.")
    else:
        _logger.warning("❌ Layanan AI Teks (Chat/Mention) TIDAK aktif.")
        
    if gemini_services.is_image_service_enabled():
        _logger.info("✅ Layanan AI Gambar (Generator) aktif.")
    else:
        _logger.warning("❌ Layanan AI Gambar (Generator) TIDAK aktif.")
    # ----------------------------------------------------------------------

    await load_all_cogs()

    try:
        # Sinkronisasi Global untuk slash commands
        synced = await bot.tree.sync()
        if synced:
            _logger.info(f"Menyinkronkan {len(synced)} application command(s).")
        else:
            _logger.info("Tidak ada application command baru untuk disinkronkan.")
    except Exception as e:
        _logger.error(f"Gagal menyinkronkan application commands: {e}", exc_info=True)

    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="$help | /help"))
    

@bot.event
async def on_connect():
    _logger.info("Bot berhasil terhubung ke Discord Gateway.")

@bot.event
async def on_disconnect():
    _logger.warning("Bot terputus dari Discord Gateway.")

@bot.event
async def on_resumed():
    _logger.info("Bot berhasil menyambung kembali sesi dengan Discord Gateway.")

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
        
        cogs_commands = {}
        for cmd in bot.commands:
            if not cmd.hidden:
                cog_name = cmd.cog_name or "Lainnya"
                if cog_name not in cogs_commands:
                    cogs_commands[cog_name] = []
                aliases_str = f" (alias: {', '.join(cmd.aliases)})" if cmd.aliases else ""
                # Ambil baris pertama dari help text untuk ringkasan
                help_summary = cmd.help.splitlines()[0] if cmd.help else 'Tidak ada deskripsi.'
                cogs_commands[cog_name].append(f"`{prefix}{cmd.name}{aliases_str}` - {help_summary}")

        for cog_name, cmds_list in sorted(cogs_commands.items()):
            if cmds_list:
                embed.add_field(name=f"**{cog_name}**", value="\n".join(cmds_list), inline=False)
        
        await ctx.send(embed=embed)


async def main_async():
    async with bot:
        # Pengecekan koneksi DB di sini juga bagus untuk log awal
        if not database.get_db_status():
            _logger.info("Mencoba koneksi awal ke MongoDB...")
            if not await database.connect_to_mongo():
                _logger.warning("Gagal koneksi ke MongoDB. Fitur database mungkin tidak berfungsi.")
        
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        _logger.info("Bot Noelle dihentikan.")
    finally:
        # Pastikan koneksi DB ditutup dengan benar saat bot berhenti
        if database.get_db_status():
            try:
                # Pastikan loop event berjalan untuk menutup koneksi async
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(database.close_mongo_connection())
                else:
                    asyncio.run(database.close_mongo_connection())
            except RuntimeError:
                pass # Loop mungkin sudah tertutup
        _logger.info("Proses bot selesai.")