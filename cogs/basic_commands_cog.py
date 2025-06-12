# Noelle_Bot/cogs/basic_commands_cog.py

import discord
from discord.ext import commands
# from discord import app_commands # Kita tidak lagi menggunakan app_commands di file ini
import logging
from utils import general_utils # Impor utilitas umum

_logger = logging.getLogger("noelle_bot.basic")

class BasicCommandsCog(commands.Cog, name="Perintah Dasar"): # Ubah nama Cog agar lebih sesuai
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("BasicCommandsCog (Prefix-based) dimuat.")

    # --- PREFIX COMMANDS ---

    @commands.command(name="ping", help="Cek latensi bot ke Discord.")
    async def ping_prefix(self, ctx: commands.Context):
        """Menampilkan latensi bot saat ini."""
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! 🏓 Latensi: **{latency_ms}** ms")

    # Perintah #sapa dan #katakan dihapus sesuai permintaan.

    # --- KONVERSI DARI SLASH KE PREFIX ---

    @commands.command(name="serverinfo", aliases=['server'], help="Menampilkan informasi tentang server ini.")
    @commands.guild_only()
    async def serverinfo_prefix(self, ctx: commands.Context):
        """Menampilkan informasi detail tentang server saat ini."""
        guild = ctx.guild
        if not guild: return # Pengaman, meskipun sudah ada guild_only()

        embed = discord.Embed(title=f"Informasi Server: {guild.name}", color=discord.Color.blue())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
        embed.add_field(name="👑 Pemilik", value=guild.owner.mention if guild.owner else "N/A", inline=True)
        embed.add_field(name="📆 Dibuat Pada", value=general_utils.format_date(guild.created_at), inline=True)
        embed.add_field(name="🆔 ID Server", value=guild.id, inline=False)
        
        # Informasi anggota
        online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)
        embed.add_field(name="👥 Anggota", value=f"**{guild.member_count}** Total\n**{online_members}** Online", inline=True)
        
        # Informasi channel
        embed.add_field(name="💬 Channels", value=f"**{len(guild.text_channels)}** Teks\n**{len(guild.voice_channels)}** Suara", inline=True)
        
        embed.add_field(name="🎭 Jumlah Peran", value=str(len(guild.roles)), inline=True)
        
        await ctx.send(embed=embed)

    @commands.command(name="userinfo", aliases=['user', 'whois'], help="Menampilkan info tentang pengguna (atau dirimu).\nContoh: #userinfo @pengguna")
    @commands.guild_only()
    async def userinfo_prefix(self, ctx: commands.Context, *, member: discord.Member = None):
        """Menampilkan informasi detail tentang seorang anggota server."""
        # Jika tidak ada member yang di-mention, targetnya adalah penulis command
        target = member or ctx.author

        embed = discord.Embed(title=f"Informasi Pengguna: {target.display_name}", color=target.color or discord.Color.blurple())
        embed.set_thumbnail(url=target.display_avatar.url)
        
        username_tag = f"{target.name}#{target.discriminator}" if target.discriminator != "0" else target.name
        embed.add_field(name="👤 Nama & Tag", value=username_tag, inline=True)
        embed.add_field(name="🆔 ID Pengguna", value=target.id, inline=True)
        
        embed.add_field(name="🎂 Akun Dibuat", value=general_utils.format_date(target.created_at), inline=False)
        
        if isinstance(target, discord.Member) and target.joined_at:
            embed.add_field(name="📥 Bergabung Server", value=general_utils.format_date(target.joined_at), inline=False)
            
            # Ambil 5 peran teratas untuk ditampilkan agar tidak terlalu panjang
            roles = [role.mention for role in reversed(target.roles) if role.name != "@everyone"]
            if roles:
                roles_display = ", ".join(roles[:5])
                if len(roles) > 5:
                    roles_display += f" dan {len(roles) - 5} lainnya..."
                embed.add_field(name=f"🎭 Peran ({len(roles)})", value=roles_display, inline=False)
            else:
                embed.add_field(name="🎭 Peran", value="Tidak ada", inline=False)

        await ctx.send(embed=embed)

    # --- ERROR HANDLER UNTUK COG INI ---
    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        # Handler ini akan menangkap error hanya dari command di dalam cog ini
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"Maaf {ctx.author.mention}, kamu tidak punya izin untuk menggunakan perintah ini.")
        elif isinstance(error, commands.CommandNotFound):
            # Sebaiknya biarkan on_command_error global yang menangani ini, atau hapus saja
            pass 
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Argumen `{error.param.name}` diperlukan untuk perintah ini. Cek `{ctx.prefix}help {ctx.command.qualified_name}`")
        elif isinstance(error, commands.BadArgument) or isinstance(error, commands.MemberNotFound):
            await ctx.send(f"Pengguna yang kamu sebutkan tidak ditemukan. Pastikan kamu me-mention pengguna yang benar.")
        elif isinstance(error, commands.GuildNotFound):
             await ctx.send(f"Perintah ini hanya bisa digunakan di dalam server.")
        else:
            _logger.error(f"Error pada prefix command '{ctx.command}': {error}", exc_info=True)
            await ctx.send("Terjadi kesalahan saat menjalankan perintah itu.")


async def setup(bot: commands.Bot):
    await bot.add_cog(BasicCommandsCog(bot))