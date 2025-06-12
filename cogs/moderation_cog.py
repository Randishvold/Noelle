# Noelle_Bot/cogs/moderation_cog.py
import discord
from discord.ext import commands
import logging
import asyncio # Diperlukan untuk sleep

_logger = logging.getLogger("noelle_bot.moderation")

class ModerationCog(commands.Cog, name="Moderasi"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("ModerationCog dimuat.")

    # --- KICK & BAN (Sudah ada, kita rapikan sedikit) ---

    @commands.command(name="kick", help="Mengeluarkan pengguna dari server.\nContoh: #kick @Pengguna Alasannya")
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    async def kick_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Tidak ada alasan diberikan."):
        if member == ctx.author:
            return await ctx.send("Kamu tidak bisa mengeluarkan dirimu sendiri!")
        if member == ctx.guild.owner:
            return await ctx.send("Kamu tidak bisa mengeluarkan pemilik server!")
        # Periksa hierarki role
        if ctx.author.top_role <= member.top_role and ctx.guild.owner != ctx.author:
            return await ctx.send("Kamu tidak bisa mengeluarkan seseorang dengan peran yang sama atau lebih tinggi darimu!")
        if ctx.guild.me.top_role <= member.top_role:
            return await ctx.send(f"Aku tidak bisa mengeluarkan {member.mention} karena perannya lebih tinggi atau sama denganku.")

        try:
            # Kirim DM ke pengguna sebelum di-kick (best practice)
            try:
                await member.send(f"Kamu telah dikeluarkan dari server **{ctx.guild.name}**.\n**Alasan:** {reason}")
            except discord.Forbidden:
                _logger.warning(f"Tidak bisa mengirim DM ke {member.name} (kick notification).")

            await member.kick(reason=f"Dikeluarkan oleh {ctx.author.display_name}: {reason}")
            await ctx.send(f"👢 **{member.display_name}** telah dikeluarkan dari server. Alasan: {reason}")
            _logger.info(f"{member} dikeluarkan oleh {ctx.author} dengan alasan: {reason} di server {ctx.guild.name}")
        except discord.Forbidden:
            await ctx.send("Aku tidak memiliki izin untuk mengeluarkan pengguna tersebut.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")
            _logger.error(f"Error saat kick {member}: {e}", exc_info=True)

    @commands.command(name="ban", help="Memblokir pengguna dari server.\nContoh: #ban @Pengguna Spamming berat")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    async def ban_prefix(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Tidak ada alasan diberikan."):
        if member == ctx.author:
            return await ctx.send("Kamu tidak bisa memblokir dirimu sendiri!")
        if member == ctx.guild.owner:
            return await ctx.send("Kamu tidak bisa memblokir pemilik server!")
        if ctx.author.top_role <= member.top_role and ctx.guild.owner != ctx.author:
            return await ctx.send("Kamu tidak bisa memblokir seseorang dengan peran yang sama atau lebih tinggi darimu!")
        if ctx.guild.me.top_role <= member.top_role:
            return await ctx.send(f"Aku tidak bisa memblokir {member.mention} karena perannya lebih tinggi atau sama denganku.")

        try:
            # Kirim DM sebelum di-ban
            try:
                await member.send(f"Kamu telah diblokir dari server **{ctx.guild.name}**.\n**Alasan:** {reason}")
            except discord.Forbidden:
                _logger.warning(f"Tidak bisa mengirim DM ke {member.name} (ban notification).")

            await member.ban(reason=f"Diblokir oleh {ctx.author.display_name}: {reason}", delete_message_days=0)
            await ctx.send(f"🚫 **{member.display_name}** telah diblokir dari server. Alasan: {reason}")
            _logger.info(f"{member} diblokir oleh {ctx.author} dengan alasan: {reason} di server {ctx.guild.name}")
        except discord.Forbidden:
            await ctx.send("Aku tidak memiliki izin untuk memblokir pengguna tersebut.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")
            _logger.error(f"Error saat ban {member}: {e}", exc_info=True)

    # --- COMMAND MODERASI BARU ---

    @commands.command(name="unban", help="Membuka blokir pengguna berdasarkan ID.\nContoh: #unban 123456789012345678")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    async def unban_prefix(self, ctx: commands.Context, user_id: int, *, reason: str = "Blokir dicabut oleh moderator."):
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=f"Blokir dicabut oleh {ctx.author.display_name}: {reason}")
            await ctx.send(f"✅ Blokir untuk **{user.name}** (`{user.id}`) telah dicabut.")
            _logger.info(f"Blokir untuk {user} dicabut oleh {ctx.author} di server {ctx.guild.name}")
        except discord.NotFound:
            await ctx.send("Pengguna dengan ID tersebut tidak ditemukan dalam daftar blokir server ini.")
        except discord.Forbidden:
            await ctx.send("Aku tidak memiliki izin untuk membuka blokir pengguna.")
        except ValueError:
            await ctx.send("ID pengguna tidak valid. Harap masukkan ID numerik yang benar.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")
            _logger.error(f"Error saat unban {user_id}: {e}", exc_info=True)
    
    @commands.command(name="purge", aliases=['clear'], help="Menghapus sejumlah pesan di channel.\nContoh: #purge 50")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def purge_prefix(self, ctx: commands.Context, amount: int):
        if amount <= 0:
            return await ctx.send("Jumlah pesan harus lebih dari 0.")
        if amount > 100:
            return await ctx.send("Kamu hanya bisa menghapus maksimal 100 pesan sekaligus.")

        try:
            # Tambah 1 untuk menghapus pesan perintah itu sendiri
            deleted = await ctx.channel.purge(limit=amount + 1)
            response_msg = await ctx.send(f"🗑️ Berhasil menghapus **{len(deleted) - 1}** pesan.", delete_after=5)
            _logger.info(f"{len(deleted) - 1} pesan dihapus di #{ctx.channel.name} oleh {ctx.author.name}")
        except discord.Forbidden:
            await ctx.send("Aku tidak punya izin untuk menghapus pesan di channel ini.")
        except Exception as e:
            await ctx.send(f"Terjadi kesalahan: {e}")
            _logger.error(f"Error saat purge di #{ctx.channel.name}: {e}", exc_info=True)

    # --- ERROR HANDLER UNTUK COG INI ---
    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"Maaf {ctx.author.mention}, kamu tidak punya izin untuk menggunakan perintah moderasi ini.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(f"Pengguna `{error.argument}` tidak ditemukan di server ini.")
        elif isinstance(error, commands.UserNotFound):
            await ctx.send(f"Pengguna dengan ID `{error.argument}` tidak ditemukan.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Argumen `{error.param.name}` diperlukan. Contoh: `{ctx.prefix}{ctx.command.name} @Pengguna alasan`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Argumen yang kamu berikan tidak valid. Pastikan kamu memasukkan tipe data yang benar (misalnya, angka untuk jumlah pesan).")
        else:
            _logger.error(f"Error pada prefix command moderasi '{ctx.command}': {error}", exc_info=True)
            await ctx.send("Terjadi kesalahan saat menjalankan perintah moderasi itu.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))