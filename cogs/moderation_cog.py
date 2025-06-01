# Noelle_Bot/cogs/moderation_cog.py
import discord
from discord.ext import commands
import logging
from core import database # Untuk cek mod_roles jika diperlukan

_logger = logging.getLogger("noelle_bot.moderation")

# --- Custom Check untuk Role Moderasi (Contoh) ---
# Anda bisa memindahkan ini ke general_utils jika dipakai di banyak tempat
# Atau definisikan role ID langsung di sini atau ambil dari config
# MOD_ROLE_IDS = [123456789012345678, ...] # Contoh ID peran moderator

# async def is_moderator(ctx: commands.Context):
#     # config = database.get_server_config(ctx.guild.id)
#     # mod_role_ids_from_db = config.get('mod_roles', [])
#     # if not mod_role_ids_from_db: # Jika tidak ada role di DB, mungkin default ke admin?
#     #     return await commands.has_permissions(administrator=True).predicate(ctx)
      
#     # user_roles_ids = [role.id for role in ctx.author.roles]
#     # return any(role_id in mod_role_ids_from_db for role_id in user_roles_ids) or ctx.author.guild_permissions.administrator
#     # Untuk sekarang, kita gunakan permission bawaan discord.py saja
#     return True # Placeholder, check asli di bawah


class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("ModerationCog dimuat.")

    @commands.command(name="kick", help="Mengeluarkan pengguna dari server.\nContoh: #kick @Pengguna Alasannya")
    @commands.guild_only()
    @commands.has_permissions(kick_members=True) # Membutuhkan izin kick
    # @commands.check(is_moderator) # Atau gunakan check custom
    async def kick_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Tidak ada alasan diberikan."):
        if member == ctx.author:
            await ctx.send("Kamu tidak bisa mengeluarkan dirimu sendiri!")
            return
        if member == ctx.guild.owner:
            await ctx.send("Kamu tidak bisa mengeluarkan pemilik server!")
            return
        if ctx.author.top_role <= member.top_role and ctx.guild.owner != ctx.author :
            await ctx.send("Kamu tidak bisa mengeluarkan seseorang dengan peran yang sama atau lebih tinggi darimu!")
            return
        if ctx.guild.me.top_role <= member.top_role:
            await ctx.send(f"Aku tidak bisa mengeluarkan {member.mention} karena perannya lebih tinggi atau sama denganku.")
            return

        try:
            await member.kick(reason=f"Dikeluarkan oleh {ctx.author.name}#{ctx.author.discriminator}: {reason}")
            await ctx.send(f"👢 {member.mention} telah dikeluarkan dari server. Alasan: {reason}")
            _logger.info(f"{member} dikeluarkan oleh {ctx.author} dengan alasan: {reason} di server {ctx.guild.name}")
        except discord.Forbidden:
            await ctx.send("Aku tidak memiliki izin untuk mengeluarkan pengguna tersebut.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")
            _logger.error(f"Error saat kick {member}: {e}", exc_info=True)

    @commands.command(name="ban", help="Memblokir pengguna dari server.\nContoh: #ban @Pengguna Spamming berat")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True) # Membutuhkan izin ban
    # @commands.check(is_moderator)
    async def ban_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Tidak ada alasan diberikan."):
        if member == ctx.author:
            await ctx.send("Kamu tidak bisa memblokir dirimu sendiri!"); return
        if member == ctx.guild.owner:
            await ctx.send("Kamu tidak bisa memblokir pemilik server!"); return
        if ctx.author.top_role <= member.top_role and ctx.guild.owner != ctx.author :
            await ctx.send("Kamu tidak bisa memblokir seseorang dengan peran yang sama atau lebih tinggi darimu!"); return
        if ctx.guild.me.top_role <= member.top_role:
            await ctx.send(f"Aku tidak bisa memblokir {member.mention} karena perannya lebih tinggi atau sama denganku."); return

        try:
            await member.ban(reason=f"Diblokir oleh {ctx.author.name}#{ctx.author.discriminator}: {reason}", delete_message_days=0) # delete_message_days opsional
            await ctx.send(f"🚫 {member.mention} telah diblokir dari server. Alasan: {reason}")
            _logger.info(f"{member} diblokir oleh {ctx.author} dengan alasan: {reason} di server {ctx.guild.name}")
        except discord.Forbidden:
            await ctx.send("Aku tidak memiliki izin untuk memblokir pengguna tersebut.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")
            _logger.error(f"Error saat ban {member}: {e}", exc_info=True)

    # Error handler untuk prefix commands di cog ini
    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"Maaf {ctx.author.mention}, kamu tidak punya izin untuk menggunakan perintah moderasi ini.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(f"Pengguna `{error.argument}` tidak ditemukan.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Argumen `{error.param.name}` diperlukan. Contoh: `{ctx.prefix}{ctx.command.name} @Pengguna alasan`")
        else:
            _logger.error(f"Error pada prefix command moderasi '{ctx.command}': {error}", exc_info=True)
            await ctx.send("Terjadi kesalahan saat menjalankan perintah moderasi itu.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))