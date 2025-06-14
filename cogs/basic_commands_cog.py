# Noelle_Bot/cogs/basic_commands_cog.py

import discord
from discord.ext import commands
import logging
from utils import general_utils
from ai_services import gemini_client as gemini_services
import asyncio
import argparse # Library bawaan Python untuk parsing argumen

_logger = logging.getLogger("noelle_bot.basic")

# --- PERBAIKAN: Tambahkan definisi kelas yang hilang di sini ---
class SafeArgumentParser(argparse.ArgumentParser):
    """
    Kelas turunan dari ArgumentParser yang melempar commands.BadArgument
    alih-alih menghentikan program (SystemExit) saat terjadi error parsing.
    Ini membuatnya aman untuk digunakan di dalam command bot.
    """
    def error(self, message):
        # Override metode error bawaan
        raise commands.BadArgument(message)
# -----------------------------------------------------------

class BasicCommandsCog(commands.Cog, name="Perintah Dasar"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("BasicCommandsCog (Prefix-based) dimuat.")

    @commands.command(name="ping", help="Cek latensi bot ke Discord.")
    async def ping_prefix(self, ctx: commands.Context):
        """Menampilkan latensi bot saat ini."""
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! 🏓 Latensi: **{latency_ms}** ms")

    @commands.command(name="serverinfo", aliases=['server'], help="Menampilkan informasi tentang server ini.")
    @commands.guild_only()
    async def serverinfo_prefix(self, ctx: commands.Context):
        """Menampilkan informasi detail tentang server saat ini."""
        guild = ctx.guild
        if not guild: return

        embed = discord.Embed(title=f"Informasi Server: {guild.name}", color=discord.Color.blue())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
        embed.add_field(name="👑 Pemilik", value=guild.owner.mention if guild.owner else "N/A", inline=True)
        embed.add_field(name="📆 Dibuat Pada", value=general_utils.format_date(guild.created_at), inline=True)
        embed.add_field(name="🆔 ID Server", value=guild.id, inline=False)
        
        online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)
        embed.add_field(name="👥 Anggota", value=f"**{guild.member_count}** Total\n**{online_members}** Online", inline=True)
        
        embed.add_field(name="💬 Channels", value=f"**{len(guild.text_channels)}** Teks\n**{len(guild.voice_channels)}** Suara", inline=True)
        
        embed.add_field(name="🎭 Jumlah Peran", value=str(len(guild.roles)), inline=True)
        
        await ctx.send(embed=embed)

    @commands.command(name="userinfo", aliases=['user', 'whois'], help="Menampilkan info tentang pengguna (atau dirimu).\nContoh: #userinfo @pengguna")
    @commands.guild_only()
    async def userinfo_prefix(self, ctx: commands.Context, *, member: discord.Member = None):
        """Menampilkan informasi detail tentang seorang anggota server."""
        target = member or ctx.author

        embed = discord.Embed(title=f"Informasi Pengguna: {target.display_name}", color=target.color or discord.Color.blurple())
        embed.set_thumbnail(url=target.display_avatar.url)
        
        username_tag = f"{target.name}#{target.discriminator}" if target.discriminator != "0" else target.name
        embed.add_field(name="👤 Nama & Tag", value=username_tag, inline=True)
        embed.add_field(name="🆔 ID Pengguna", value=target.id, inline=True)
        
        embed.add_field(name="🎂 Akun Dibuat", value=general_utils.format_date(target.created_at), inline=False)
        
        if isinstance(target, discord.Member) and target.joined_at:
            embed.add_field(name="📥 Bergabung Server", value=general_utils.format_date(target.joined_at), inline=False)
            
            roles = [role.mention for role in reversed(target.roles) if role.name != "@everyone"]
            if roles:
                roles_display = ", ".join(roles[:5])
                if len(roles) > 5:
                    roles_display += f" dan {len(roles) - 5} lainnya..."
                embed.add_field(name=f"🎭 Peran ({len(roles)})", value=roles_display, inline=False)
            else:
                embed.add_field(name="🎭 Peran", value="Tidak ada", inline=False)

        await ctx.send(embed=embed)

    @commands.command(name="listmodels", aliases=['models'], help="Menampilkan model Gemini yang tersedia.\nContoh: #models -f flash -l 20")
    @commands.is_owner()
    async def list_models_prefix(self, ctx: commands.Context, *, args: str = ""):
        """
        Menampilkan daftar model AI yang dapat diakses oleh bot.
        Argumen:
          -f, --filter: Filter nama model (case-insensitive).
          -l, --limit: Jumlah model yang ditampilkan per kategori (default 25).
        """
        client = gemini_services.get_gemini_client()
        if not client:
            return await ctx.send("Klien AI tidak terinisialisasi. Tidak bisa mengambil daftar model.")

        parser = SafeArgumentParser(add_help=False, description="Parser for listmodels command")
        parser.add_argument('-f', '--filter', type=str, default=None, help="Filter nama model")
        parser.add_argument('-l', '--limit', type=int, default=25, help="Batas tampilan per kategori")

        try:
            parsed_args = parser.parse_args(args.split())
            keyword_filter = parsed_args.filter.lower() if parsed_args.filter else None
            display_limit = parsed_args.limit
        except commands.BadArgument as e:
            return await ctx.send(f"Argumen tidak valid: {e}\nKetik `#help models` untuk bantuan.")

        msg = await ctx.send(f"🔍 Mengambil daftar model dari Google AI (Filter: `{keyword_filter or 'Tidak ada'}`, Limit: `{display_limit}`)...")

        try:
            models_iterator = await client.aio.models.list()
            
            all_models = [model async for model in models_iterator]
            
            if keyword_filter:
                all_models = [m for m in all_models if keyword_filter in m.name.lower()]

            base_models = [m for m in all_models if 'tuned' not in m.name]
            tuned_models = [m for m in all_models if 'tuned' in m.name]
            
            embed = discord.Embed(
                title="Daftar Model Gemini yang Tersedia",
                description=f"Filter: `{keyword_filter or 'Tidak ada'}` | Total Ditemukan: `{len(all_models)}`",
                color=discord.Color.green()
            )

            if base_models:
                model_list_str = ""
                for model in base_models[:display_limit]:
                    clean_name = model.name.replace('models/', '')
                    model_list_str += f"🔹 `{clean_name}`\n"
                
                if len(base_models) > display_limit:
                    model_list_str += f"... dan {len(base_models) - display_limit} model lainnya."
                
                embed.add_field(name=f"🤖 Model Dasar ({len(base_models)})", value=model_list_str, inline=False)
            
            if tuned_models:
                tuned_model_list_str = ""
                for model in tuned_models[:display_limit]:
                     tuned_model_list_str += f"🔸 `{model.display_name}` ({model.name})\n"
                
                if len(tuned_models) > display_limit:
                    tuned_model_list_str += f"... dan {len(tuned_models) - display_limit} model lainnya."

                embed.add_field(name=f"🔧 Model Hasil Tuning ({len(tuned_models)})", value=tuned_model_list_str, inline=False)

            if not base_models and not tuned_models:
                embed.description = f"Tidak ada model yang cocok dengan filter `{keyword_filter}`."

            await msg.edit(content=None, embed=embed)

        except Exception as e:
            _logger.error(f"Gagal mengambil daftar model Gemini: {e}", exc_info=True)
            await msg.edit(content=f"Terjadi error saat mengambil daftar model: `{e}`")

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.NotOwner):
            return

        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"Maaf {ctx.author.mention}, kamu tidak punya izin untuk menggunakan perintah ini.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Argumen `{error.param.name}` diperlukan. Cek `{ctx.prefix}help {ctx.command.qualified_name}`")
        elif isinstance(error, commands.BadArgument) or isinstance(error, commands.MemberNotFound):
            await ctx.send(f"Argumen atau pengguna yang kamu sebutkan tidak valid/ditemukan.")
        else:
            _logger.error(f"Error pada prefix command '{ctx.command}': {error}", exc_info=True)
            await ctx.send("Terjadi kesalahan saat menjalankan perintah itu.")

async def setup(bot: commands.Bot):
    await bot.add_cog(BasicCommandsCog(bot))