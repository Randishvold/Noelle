# Noelle_Bot/cogs/basic_commands_cog.py

import discord
from discord.ext import commands
import logging
from utils import general_utils, pattern_manager, ai_utils
from ai_services import gemini_client as gemini_services
import asyncio
import argparse

_logger = logging.getLogger("noelle_bot.basic")

class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise commands.BadArgument(message)

class BasicCommandsCog(commands.Cog, name="Perintah Dasar"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("BasicCommandsCog (Prefix-based) dimuat.")

    # --- Perintah Lama (ping, serverinfo, userinfo, listmodels) tetap sama ---
    @commands.command(name="ping", help="Cek latensi bot ke Discord.")
    async def ping_prefix(self, ctx: commands.Context):
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(f"Pong! 🏓 Latensi: **{latency_ms}** ms")

    @commands.command(name="serverinfo", aliases=['server'], help="Menampilkan informasi tentang server ini.")
    @commands.guild_only()
    async def serverinfo_prefix(self, ctx: commands.Context):
        # ... (kode serverinfo tidak berubah)
        guild = ctx.guild; embed = discord.Embed(title=f"Informasi Server: {guild.name}", color=discord.Color.blue()); 
        if guild.icon: embed.set_thumbnail(url=guild.icon.url);
        embed.add_field(name="👑 Pemilik", value=guild.owner.mention if guild.owner else "N/A", inline=True); embed.add_field(name="📆 Dibuat Pada", value=general_utils.format_date(guild.created_at), inline=True); embed.add_field(name="🆔 ID Server", value=guild.id, inline=False);
        online_members = sum(1 for m in guild.members if m.status != discord.Status.offline);
        embed.add_field(name="👥 Anggota", value=f"**{guild.member_count}** Total\n**{online_members}** Online", inline=True);
        embed.add_field(name="💬 Channels", value=f"**{len(guild.text_channels)}** Teks\n**{len(guild.voice_channels)}** Suara", inline=True);
        embed.add_field(name="🎭 Jumlah Peran", value=str(len(guild.roles)), inline=True);
        await ctx.send(embed=embed)

    @commands.command(name="userinfo", aliases=['user', 'whois'], help="Menampilkan info tentang pengguna (atau dirimu).\nContoh: $userinfo @pengguna")
    @commands.guild_only()
    async def userinfo_prefix(self, ctx: commands.Context, *, member: discord.Member = None):
        # ... (kode userinfo tidak berubah)
        target = member or ctx.author; embed = discord.Embed(title=f"Informasi Pengguna: {target.display_name}", color=target.color or discord.Color.blurple()); embed.set_thumbnail(url=target.display_avatar.url);
        username_tag = f"{target.name}#{target.discriminator}" if target.discriminator != "0" else target.name;
        embed.add_field(name="👤 Nama & Tag", value=username_tag, inline=True); embed.add_field(name="🆔 ID Pengguna", value=target.id, inline=True);
        embed.add_field(name="🎂 Akun Dibuat", value=general_utils.format_date(target.created_at), inline=False);
        if isinstance(target, discord.Member) and target.joined_at:
            embed.add_field(name="📥 Bergabung Server", value=general_utils.format_date(target.joined_at), inline=False);
            roles = [role.mention for role in reversed(target.roles) if role.name != "@everyone"];
            if roles:
                roles_display = ", ".join(roles[:5]);
                if len(roles) > 5: roles_display += f" dan {len(roles) - 5} lainnya...";
                embed.add_field(name=f"🎭 Peran ({len(roles)})", value=roles_display, inline=False);
            else: embed.add_field(name="🎭 Peran", value="Tidak ada", inline=False);
        await ctx.send(embed=embed)

    @commands.command(name="listmodels", aliases=['models'], help="Menampilkan model Gemini yang tersedia.\nContoh: $models -f flash")
    @commands.is_owner()
    async def list_models_prefix(self, ctx: commands.Context, *, args: str = ""):
        # ... (kode listmodels tidak berubah)
        client = gemini_services.get_gemini_client();
        if not client: return await ctx.send("Klien AI tidak terinisialisasi.");
        parser = SafeArgumentParser(add_help=False); parser.add_argument('-f', '--filter', type=str, default=None); parser.add_argument('-l', '--limit', type=int, default=25);
        try: parsed_args = parser.parse_args(args.split()); keyword_filter = parsed_args.filter.lower() if parsed_args.filter else None; display_limit = parsed_args.limit
        except commands.BadArgument as e: return await ctx.send(f"Argumen tidak valid: {e}");
        msg = await ctx.send(f"🔍 Mengambil daftar model...");
        try:
            models_iterator = await client.aio.models.list(); all_models = [model async for model in models_iterator];
            if keyword_filter: all_models = [m for m in all_models if keyword_filter in m.name.lower()];
            base_models = [m for m in all_models if 'tuned' not in m.name]; tuned_models = [m for m in all_models if 'tuned' in m.name];
            embed = discord.Embed(title="Daftar Model Gemini", color=discord.Color.green());
            if base_models:
                model_list_str = "".join([f"🔹 `{m.name.replace('models/', '')}`\n" for m in base_models[:display_limit]]);
                if len(base_models) > display_limit: model_list_str += f"... dan {len(base_models) - display_limit} lainnya.";
                embed.add_field(name=f"🤖 Model Dasar ({len(base_models)})", value=model_list_str, inline=False);
            if tuned_models:
                tuned_model_list_str = "".join([f"🔸 `{m.display_name}` ({m.name})\n" for m in tuned_models[:display_limit]]);
                if len(tuned_models) > display_limit: tuned_model_list_str += f"... dan {len(tuned_models) - display_limit} lainnya.";
                embed.add_field(name=f"🔧 Model Hasil Tuning ({len(tuned_models)})", value=tuned_model_list_str, inline=False);
            if not base_models and not tuned_models: embed.description = f"Tidak ada model cocok dengan filter `{keyword_filter}`.";
            await msg.edit(content=None, embed=embed);
        except Exception as e: await msg.edit(content=f"Terjadi error: `{e}`")

    # --- PERINTAH BARU: $pattern ---
    @commands.group(name="pattern", invoke_without_command=True, help="Gunakan Pattern AI untuk tugas spesifik.\nContoh: $pattern summarize [teks]\nGunakan '$pattern list' untuk melihat semua pattern.")
    async def pattern_prefix(self, ctx: commands.Context, pattern_name: str = None, *, user_input: str = ""):
        """Fungsi utama untuk menjalankan sebuah pattern AI."""
        if pattern_name is None:
            await ctx.send_help(ctx.command)
            return
            
        designated_channel_name = gemini_services.get_designated_ai_channel_name().lower()
        if ctx.channel.name.lower() != designated_channel_name:
            return await ctx.send(f"Perintah ini hanya bisa digunakan di channel `{designated_channel_name}`.")
            
        pattern_prompt_template = pattern_manager.get_pattern(pattern_name)
        
        if not pattern_prompt_template:
            return await ctx.send(f"Pattern `{pattern_name}` tidak ditemukan. Gunakan `$pattern list` untuk melihat daftar yang tersedia.")
            
        if not user_input.strip():
            return await ctx.send(f"Mohon berikan input untuk pattern `{pattern_name}`.")
            
        async with ctx.typing():
            try:
                client = gemini_services.get_gemini_client()
                if not client:
                    await ctx.send("Klien AI tidak terinisialisasi.")
                    return

                # Gabungkan template pattern dengan input dari pengguna
                final_prompt = pattern_prompt_template.replace("{{input}}", user_input)
                
                api_response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=gemini_services.GEMINI_TEXT_MODEL_NAME,
                    contents=final_prompt # Seluruh prompt yang sudah diformat menjadi konten
                )
                
                context_log_prefix = f"Pattern Command [Name: {pattern_name}]"
                await ai_utils.send_text_in_embeds(
                    target_channel=ctx.channel,
                    response_text=api_response.text,
                    footer_text=f"Pattern '{pattern_name}' digunakan oleh: {ctx.author.display_name}",
                    reply_to_message=ctx.message,
                    is_direct_ai_response=True
                )

            except Exception as e:
                _logger.error(f"Error saat menjalankan pattern '{pattern_name}': {e}", exc_info=True)
                await ctx.send(f"Terjadi kesalahan saat menjalankan pattern: `{e}`")

    @pattern_prefix.command(name="list")
    async def pattern_list_subcommand(self, ctx: commands.Context):
        """Menampilkan daftar semua Pattern AI yang tersedia."""
        available_patterns = pattern_manager.get_available_patterns()
        
        if not available_patterns:
            return await ctx.send("Saat ini tidak ada Pattern AI yang tersedia.")
            
        embed = discord.Embed(
            title="Daftar Pattern AI yang Tersedia",
            description=f"Gunakan sebuah pattern dengan format:\n`$pattern <nama_pattern> [input Anda]`",
            color=discord.Color.teal()
        )
        
        for name, description in sorted(available_patterns.items()):
            embed.add_field(name=f"`{name}`", value=description, inline=False)
            
        embed.set_footer(text=f"Total {len(available_patterns)} pattern ditemukan.")
        await ctx.send(embed=embed)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        # ... (Error handler tidak berubah) ...
        if isinstance(error, commands.NotOwner): return
        if isinstance(error, commands.MissingPermissions): await ctx.send(f"Maaf, kamu tidak punya izin.")
        elif isinstance(error, commands.MissingRequiredArgument): await ctx.send(f"Argumen `{error.param.name}` diperlukan.")
        elif isinstance(error, commands.BadArgument) or isinstance(error, commands.MemberNotFound): await ctx.send(f"Argumen atau pengguna tidak valid/ditemukan.")
        else:
            _logger.error(f"Error pada command '{ctx.command}': {error}", exc_info=True)
            await ctx.send("Terjadi kesalahan.")

async def setup(bot: commands.Bot):
    await bot.add_cog(BasicCommandsCog(bot))