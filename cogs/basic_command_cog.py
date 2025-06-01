# Noelle_Bot/cogs/basic_commands_cog.py
import discord
from discord.ext import commands
from discord import app_commands # Untuk slash command /help_prefix
import logging
from utils import general_utils # Impor utilitas umum

_logger = logging.getLogger("noelle_bot.basic")

class BasicCommandsCog(commands.Cog, name="Basic Commands"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("BasicCommandsCog dimuat.")

    @commands.command(name="ping", help="Cek latensi bot.")
    async def ping_prefix(self, ctx: commands.Context):
        await ctx.send(f"Pong! Latensi: {round(self.bot.latency * 1000)}ms")

    @commands.command(name="sapa", help="Noelle akan menyapamu kembali!")
    async def hello_prefix(self, ctx: commands.Context):
        await ctx.send(f"Halo juga, {ctx.author.mention}!")

    @commands.command(name="katakan", aliases=["say", "echo"], help="Membuat bot mengirim pesan yang kamu tulis.\nContoh: #katakan Halo semua!")
    @commands.has_permissions(manage_messages=True) # Hanya yang bisa manage message
    async def say_prefix(self, ctx: commands.Context, *, teks: str):
        if not teks:
            await ctx.send("Kamu mau aku bilang apa?")
            return
        # Hapus command invokasi dari teks (misal "#katakan " atau "#say ")
        # Ini cara sederhana, bisa diperbaiki agar lebih robust
        # invocation_parts = [ctx.prefix + ctx.invoked_with] + [ctx.prefix + alias for alias in ctx.command.aliases]
        # for part in invocation_parts:
        #     if teks.startswith(part):
        #         teks = teks[len(part):].lstrip()
        #         break
        # Cara yang lebih aman adalah mengambil dari args, tapi karena pakai *, teks sudah bersih.
        
        try:
            await ctx.message.delete() # Hapus pesan command pengguna
        except discord.Forbidden:
            _logger.warning(f"Tidak bisa menghapus pesan command dari {ctx.author} di {ctx.guild.name if ctx.guild else 'DM'}")
        except discord.HTTPException:
            _logger.warning(f"Gagal menghapus pesan command (HTTP Exception).")
            
        await ctx.send(teks)

    # --- Slash Commands untuk Info (bisa tetap slash atau diubah ke prefix) ---
    @app_commands.command(name="serverinfo", description="Menampilkan informasi tentang server ini.")
    @app_commands.guild_only()
    async def serverinfo_slash(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild: return # Seharusnya tidak terjadi karena guild_only

        embed = discord.Embed(title=f"Info Server: {guild.name}", color=discord.Color.blue())
        if guild.icon: embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="ID Server", value=guild.id)
        embed.add_field(name="Pemilik", value=guild.owner.mention if guild.owner else "N/A")
        embed.add_field(name="Dibuat Pada", value=general_utils.format_date(guild.created_at))
        embed.add_field(name="Jumlah Anggota", value=str(guild.member_count))
        embed.add_field(name="Jumlah Channel", value=str(len(guild.text_channels) + len(guild.voice_channels) + len(guild.stage_channels) + len(guild.forums))) # Lebih detail
        embed.add_field(name="Jumlah Peran", value=str(len(guild.roles)))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Menampilkan info tentang pengguna (atau dirimu).")
    @app_commands.describe(member="Pengguna yang ingin dilihat infonya.")
    @app_commands.guild_only()
    async def userinfo_slash(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        embed = discord.Embed(title=f"Info Pengguna: {target.display_name}", color=target.color or discord.Color.blurple())
        embed.set_thumbnail(url=target.display_avatar.url)
        username_tag = f"{target.name}#{target.discriminator}" if target.discriminator != "0" else target.name
        embed.add_field(name="Nama & Tag", value=username_tag)
        embed.add_field(name="ID", value=target.id)
        embed.add_field(name="Akun Dibuat", value=general_utils.format_date(target.created_at))
        if isinstance(target, discord.Member) and target.joined_at: # Pastikan target adalah Member
            embed.add_field(name="Bergabung Server", value=general_utils.format_date(target.joined_at))
            roles = [role.mention for role in reversed(target.roles) if role.name != "@everyone"]
            embed.add_field(name=f"Peran ({len(roles)})", value=", ".join(roles) if roles else "Tidak ada", inline=False)
        await interaction.response.send_message(embed=embed)
        
    @app_commands.command(name="list_prefix_commands", description="Menampilkan daftar perintah prefix '#' yang tersedia.")
    async def list_prefix_commands_slash(self, interaction: discord.Interaction):
        prefix = "#" # Prefix yang kita gunakan
        embed = discord.Embed(title=f"Daftar Perintah dengan Prefix `{prefix}`", color=discord.Color.green())
        
        commands_list = []
        for command in self.bot.commands:
            if not command.hidden: # Hanya tampilkan command yang tidak disembunyikan
                help_text = command.help or "Tidak ada deskripsi."
                aliases = ""
                if command.aliases:
                    aliases = f" (Alias: {', '.join([prefix+a for a in command.aliases])})"
                commands_list.append(f"`{prefix}{command.name}{aliases}`: {help_text.splitlines()[0]}") # Ambil baris pertama help

        if commands_list:
            embed.description = "\n".join(commands_list)
        else:
            embed.description = "Tidak ada perintah prefix yang tersedia saat ini."
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # Error handler untuk prefix commands di cog ini
    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"Maaf {ctx.author.mention}, kamu tidak punya izin untuk menggunakan perintah ini.")
        elif isinstance(error, commands.CommandNotFound):
            await ctx.send(f"Perintah `{ctx.invoked_with}` tidak ditemukan. Ketik `{ctx.prefix}help` untuk daftar perintah.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Argumen `{error.param.name}` diperlukan untuk perintah ini. Contoh: `{ctx.prefix}{ctx.command.name} {ctx.command.signature}`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Argumen yang kamu berikan tidak valid. Silakan cek kembali.")
        else:
            _logger.error(f"Error pada prefix command '{ctx.command}': {error}", exc_info=True)
            await ctx.send("Terjadi kesalahan saat menjalankan perintah itu.")


async def setup(bot: commands.Bot):
    await bot.add_cog(BasicCommandsCog(bot))