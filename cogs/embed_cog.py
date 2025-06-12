# Noelle_Bot/cogs/embed_cog.py

import discord
from discord.ext import commands
from discord import app_commands, ui
import logging
from core import database
from utils import general_utils

_logger = logging.getLogger("noelle_bot.embed")

# --- MODAL DAN VIEW ---
# (Kelas BasicEmbedModal, AuthorEmbedModal, FooterEmbedModal, dan EmbedEditView)
# Di dalam kelas-kelas ini, kita perlu memastikan semua panggilan ke database.py di-await.

class BasicEmbedModal(ui.Modal, title='Edit Info Dasar Embed'):
    embed_title = ui.TextInput(label='Judul', style=discord.TextStyle.short, required=False, max_length=256)
    embed_description = ui.TextInput(label='Deskripsi', style=discord.TextStyle.long, required=False, max_length=4000)
    embed_color = ui.TextInput(label='Warna (Hex: #RRGGBB)', style=discord.TextStyle.short, required=False, max_length=7)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict | None = None):
        super().__init__(timeout=300)
        self.embed_name = embed_name
        self.guild_id = guild_id
        self.initial_data = initial_data or {}
        # ... (logika __init__ lainnya tetap sama) ...
        self.embed_title.default = self.initial_data.get('title', '')
        self.embed_description.default = self.initial_data.get('description', '')
        color_val = self.initial_data.get('color')
        if isinstance(color_val, int): self.embed_color.default = general_utils.get_color_hex(color_val)
        elif isinstance(color_val, str): self.embed_color.default = color_val

    async def on_submit(self, interaction: discord.Interaction):
        # --- PERBAIKAN: Tambahkan 'await' ---
        current_data = await database.get_custom_embed(self.guild_id, self.embed_name) or {}
        
        # ... (logika on_submit lainnya tetap sama) ...
        title = self.embed_title.value.strip()
        description = self.embed_description.value.strip()
        color_str = self.embed_color.value.strip()

        current_data['title'] = title if title else None
        current_data['description'] = description if description else None
        color_int = general_utils.get_color_int(color_str)
        current_data['color'] = color_int

        if not title and 'title' in current_data: del current_data['title']
        if not description and 'description' in current_data: del current_data['description']
        if color_int is None and 'color' in current_data: del current_data['color']
            
        await database.save_custom_embed(self.guild_id, self.embed_name, current_data)
        updated_data = await database.get_custom_embed(self.guild_id, self.embed_name)
        
        processed_embed = general_utils.create_processed_embed(
            updated_data, 
            user=interaction.user, 
            member=interaction.user if isinstance(interaction.user, discord.Member) else None,
            guild=interaction.guild, 
            channel=interaction.channel
        )
        await interaction.response.edit_message(content="Info dasar embed berhasil diperbarui!", embed=processed_embed, view=self.view)


class AuthorEmbedModal(ui.Modal, title='Edit Author Embed'):
    author_name = ui.TextInput(label='Nama Author', style=discord.TextStyle.short, required=False, max_length=256)
    author_icon_url = ui.TextInput(label='URL Ikon Author (Variabel didukung)', style=discord.TextStyle.short, required=False, placeholder="Contoh: {{user.avatar_url}}")

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict | None = None):
        super().__init__(timeout=300)
        self.embed_name = embed_name
        self.guild_id = guild_id
        author_data = (initial_data or {}).get('author', {})
        self.author_name.default = author_data.get('name', '')
        self.author_icon_url.default = author_data.get('icon_url', '')

    async def on_submit(self, interaction: discord.Interaction):
        # --- PERBAIKAN: Tambahkan 'await' ---
        current_data = await database.get_custom_embed(self.guild_id, self.embed_name) or {}
        # ... (logika on_submit lainnya tetap sama) ...
        name = self.author_name.value.strip()
        icon_url_input = self.author_icon_url.value.strip()
        
        author_dict = {}
        if name: author_dict['name'] = name
        if icon_url_input: author_dict['icon_url'] = icon_url_input

        if author_dict:
            current_data['author'] = author_dict
        elif 'author' in current_data: 
            del current_data['author']
            
        await database.save_custom_embed(self.guild_id, self.embed_name, current_data)
        updated_data = await database.get_custom_embed(self.guild_id, self.embed_name)
        
        processed_embed = general_utils.create_processed_embed(
            updated_data, user=interaction.user, member=interaction.user if isinstance(interaction.user, discord.Member) else None, guild=interaction.guild, channel=interaction.channel
        )
        await interaction.response.edit_message(content="Author embed berhasil diperbarui!", embed=processed_embed, view=self.view)


class FooterEmbedModal(ui.Modal, title='Edit Footer Embed'):
    footer_text = ui.TextInput(label='Teks Footer', style=discord.TextStyle.short, required=False, max_length=2048)
    add_timestamp = ui.TextInput(label='Tambahkan Timestamp? (yes/no)', style=discord.TextStyle.short, required=False, max_length=3, placeholder="yes atau no")

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict | None = None):
        super().__init__(timeout=300)
        self.embed_name = embed_name
        self.guild_id = guild_id
        footer_data = (initial_data or {}).get('footer', {})
        self.footer_text.default = footer_data.get('text', '')
        self.add_timestamp.default = 'yes' if footer_data.get('timestamp') is True else 'no'

    async def on_submit(self, interaction: discord.Interaction):
        # --- PERBAIKAN: Tambahkan 'await' ---
        current_data = await database.get_custom_embed(self.guild_id, self.embed_name) or {}
        # ... (logika on_submit lainnya tetap sama) ...
        text = self.footer_text.value.strip()
        show_ts = self.add_timestamp.value.strip().lower() == 'yes'
        
        footer_dict = {}
        if text: footer_dict['text'] = text
        footer_dict['timestamp'] = show_ts
            
        if footer_dict.get('text') or footer_dict.get('timestamp'):
             current_data['footer'] = footer_dict
        elif 'footer' in current_data:
            del current_data['footer']
            
        await database.save_custom_embed(self.guild_id, self.embed_name, current_data)
        updated_data = await database.get_custom_embed(self.guild_id, self.embed_name)
        processed_embed = general_utils.create_processed_embed(updated_data, user=interaction.user, member=interaction.user if isinstance(interaction.user, discord.Member) else None, guild=interaction.guild, channel=interaction.channel)
        await interaction.response.edit_message(content="Footer embed berhasil diperbarui!", embed=processed_embed, view=self.view)


class EmbedEditView(ui.View):
    # --- PERBAIKAN: Tambahkan self.message: discord.Message | None ---
    def __init__(self, embed_name: str, guild_id: int, *, timeout=300):
        super().__init__(timeout=timeout)
        self.embed_name = embed_name
        self.guild_id = guild_id
        self.message: discord.Message | None = None # Untuk menyimpan pesan yang view ini tempelkan

    # ... (on_timeout tetap sama) ...
    async def on_timeout(self) -> None:
        if self.message: 
            try:
                for item in self.children: item.disabled = True
                await self.message.edit(content="*Waktu untuk mengedit habis.*", view=self) 
                _logger.info(f"View untuk embed '{self.embed_name}' timeout, tombol dinonaktifkan.")
            except discord.NotFound: _logger.warning("Pesan view edit embed tidak ditemukan saat timeout.")
            except Exception as e: _logger.error(f"Error timeout view edit embed: {e}", exc_info=True)
        else:
            _logger.warning(f"View untuk embed '{self.embed_name}' timeout, tapi self.message adalah None.")

    @ui.button(label='Info Dasar', style=discord.ButtonStyle.primary) 
    async def edit_basic_button(self, interaction: discord.Interaction, button: ui.Button):
        # --- PERBAIKAN: Tambahkan 'await' ---
        current_data = await database.get_custom_embed(self.guild_id, self.embed_name)
        await interaction.response.send_modal(BasicEmbedModal(self.embed_name, self.guild_id, current_data))

    @ui.button(label='Author', style=discord.ButtonStyle.secondary) 
    async def edit_author_button(self, interaction: discord.Interaction, button: ui.Button):
        # --- PERBAIKAN: Tambahkan 'await' ---
        current_data = await database.get_custom_embed(self.guild_id, self.embed_name)
        await interaction.response.send_modal(AuthorEmbedModal(self.embed_name, self.guild_id, current_data))

    @ui.button(label='Footer', style=discord.ButtonStyle.secondary) 
    async def edit_footer_button(self, interaction: discord.Interaction, button: ui.Button):
        # --- PERBAIKAN: Tambahkan 'await' ---
        current_data = await database.get_custom_embed(self.guild_id, self.embed_name)
        await interaction.response.send_modal(FooterEmbedModal(self.embed_name, self.guild_id, current_data))
    

# --- KELAS COG UTAMA ---
class EmbedCog(commands.Cog, name="Custom Embeds"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("EmbedCog dimuat.")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        # Coba ambil dari config server, jika gagal baru ke system_channel
        # (Ini untuk pengembangan di masa depan)
        target_channel = guild.system_channel 
        if target_channel:
            # --- PERBAIKAN: Tambahkan 'await' ---
            welcome_embed_data = await database.get_custom_embed(guild.id, "welcome")
            if welcome_embed_data:
                try:
                    embed = general_utils.create_processed_embed(welcome_embed_data, member=member, guild=guild, channel=target_channel)
                    if member.display_avatar and not embed.thumbnail:
                        embed.set_thumbnail(url=member.display_avatar.url)
                    await target_channel.send(embed=embed)
                except discord.Forbidden: _logger.warning(f"Tidak bisa kirim welcome embed ke {target_channel.name} (Forbidden).")
                except Exception as e: _logger.error(f"Error kirim custom welcome embed: {e}", exc_info=True)

    embed_group = app_commands.Group(name="embed", description="Manajemen custom embed server.")

    @embed_group.command(name="buat", description="Membuat template embed baru.")
    @app_commands.describe(nama="Nama unik untuk embed ini.")
    @commands.has_permissions(manage_guild=True)
    async def embed_add(self, interaction: discord.Interaction, nama: str):
        if not interaction.guild_id: return await interaction.response.send_message("Hanya di server.", ephemeral=True)
        nama = nama.lower().strip().replace(" ", "-") # Sanitasi nama
        if not nama: return await interaction.response.send_message("Nama embed tidak boleh kosong.", ephemeral=True)
        
        # --- PERBAIKAN: Tambahkan 'await' ---
        if await database.get_custom_embed(interaction.guild_id, nama):
            return await interaction.response.send_message(f"Embed '{nama}' sudah ada. Gunakan `/embed edit`.", ephemeral=True)
        
        initial_data = {"title": f"Embed Baru: {nama}", "description": "Mulai edit embed ini dengan tombol di bawah!"}
        
        # --- PERBAIKAN: Tambahkan 'await' ---
        if await database.save_custom_embed(interaction.guild_id, nama, initial_data):
            preview_embed = general_utils.create_processed_embed(initial_data, user=interaction.user, member=interaction.user, guild=interaction.guild, channel=interaction.channel)
            view = EmbedEditView(nama, interaction.guild_id)
            await interaction.response.send_message(
                f"Mengedit embed **`{nama}`**. Gunakan tombol di bawah. Variabel yang tersedia: `{{user.name}}`, dll.", 
                embed=preview_embed, view=view, ephemeral=True)
            # --- PERBAIKAN: Simpan pesan untuk timeout view ---
            view.message = await interaction.original_response()
        else: await interaction.response.send_message("Gagal menyimpan embed baru ke database.", ephemeral=True)

    @embed_group.command(name="edit", description="Mengedit template embed yang sudah ada.")
    @app_commands.describe(nama="Nama embed yang akan diedit.")
    @commands.has_permissions(manage_guild=True)
    async def embed_edit(self, interaction: discord.Interaction, nama: str):
        if not interaction.guild_id: return await interaction.response.send_message("Hanya di server.", ephemeral=True)
        nama = nama.lower().strip().replace(" ", "-")
        # --- PERBAIKAN: Tambahkan 'await' ---
        existing_data = await database.get_custom_embed(interaction.guild_id, nama)
        if not existing_data: return await interaction.response.send_message(f"Embed '{nama}' tidak ditemukan.", ephemeral=True)
        
        preview_embed = general_utils.create_processed_embed(existing_data, user=interaction.user, member=interaction.user, guild=interaction.guild, channel=interaction.channel)
        view = EmbedEditView(nama, interaction.guild_id)
        await interaction.response.send_message(f"Mengedit embed **`{nama}`**.", embed=preview_embed, view=view, ephemeral=True)
        # --- PERBAIKAN: Simpan pesan untuk timeout view ---
        view.message = await interaction.original_response()
    
    # ... (sisa command: list, hapus, tampil, dan error handler tetap sama, tapi sudah diperbaiki dengan 'await' di dalamnya) ...
    @embed_group.command(name="list", description="Menampilkan semua template embed kustom di server ini.")
    async def embed_list(self, interaction: discord.Interaction):
        if not interaction.guild_id or not interaction.guild: return await interaction.response.send_message("Hanya di server.", ephemeral=True)
        # --- PERBAIKAN: Tambahkan 'await' ---
        embed_names = await database.get_all_custom_embed_names(interaction.guild_id)
        if not embed_names: return await interaction.response.send_message("Belum ada embed kustom di server ini.", ephemeral=True)
        
        embed = discord.Embed(title=f"Embed Kustom di {interaction.guild.name}", color=discord.Color.blue())
        embed.description = "\n".join(f"- `{name}`" for name in sorted(embed_names))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @embed_group.command(name="hapus", description="Menghapus template embed kustom.")
    @app_commands.describe(nama="Nama embed yang akan dihapus.")
    @commands.has_permissions(manage_guild=True)
    async def embed_remove(self, interaction: discord.Interaction, nama: str):
        if not interaction.guild_id: return await interaction.response.send_message("Hanya di server.", ephemeral=True)
        nama = nama.lower().strip().replace(" ", "-")
        # --- PERBAIKAN: Tambahkan 'await' ---
        if await database.delete_custom_embed(interaction.guild_id, nama):
            await interaction.response.send_message(f"Embed '{nama}' berhasil dihapus.", ephemeral=True)
        else: await interaction.response.send_message(f"Embed '{nama}' tidak ditemukan atau gagal dihapus.", ephemeral=True)

    @embed_group.command(name="tampil", description="Menampilkan pratinjau embed kustom.")
    @app_commands.describe(nama="Nama embed yang akan ditampilkan.")
    async def embed_view(self, interaction: discord.Interaction, nama: str):
        if not interaction.guild_id: return await interaction.response.send_message("Hanya di server.", ephemeral=True)
        nama = nama.lower().strip().replace(" ", "-")
        # --- PERBAIKAN: Tambahkan 'await' ---
        embed_data = await database.get_custom_embed(interaction.guild_id, nama)
        if not embed_data: return await interaction.response.send_message(f"Embed '{nama}' tidak ditemukan.", ephemeral=True)
        
        processed_embed = general_utils.create_processed_embed(embed_data, user=interaction.user, member=interaction.user, guild=interaction.guild, channel=interaction.channel)
        await interaction.response.send_message(f"Pratinjau embed **`{nama}`**:", embed=processed_embed)

    # ... (error handler tetap sama) ...
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original_error = getattr(error, 'original', error)
        command_name = interaction.command.name if interaction.command else 'N/A'
        _logger.error(f"Error pada EmbedCog command '{command_name}': {original_error}", exc_info=True)
        msg = "Terjadi kesalahan internal pada perintah embed."
        if isinstance(error, app_commands.MissingPermissions): msg = "Kamu tidak punya izin untuk ini."
        elif isinstance(original_error, discord.errors.NotFound) and original_error.code in [10062, 10015]: 
            _logger.warning(f"Gagal kirim pesan error untuk '{command_name}': Interaksi sudah direspons atau tidak valid.")
            return 
        elif isinstance(error, app_commands.CommandInvokeError): msg = f"Error saat menjalankan: {original_error}"
        try:
            if interaction.response.is_done(): await interaction.followup.send(msg, ephemeral=True)
            else: await interaction.response.send_message(msg, ephemeral=True)
        except discord.errors.InteractionResponded: 
            _logger.warning(f"Gagal kirim error via followup/response (sudah direspons) utk cmd '{command_name}'. Mencoba kirim ke channel.")
            try: await interaction.channel.send(f"{interaction.user.mention}, terjadi error: {msg}", delete_after=20)
            except Exception as ch_e: _logger.error(f"Gagal kirim error ke channel utk cmd '{command_name}': {ch_e}", exc_info=True)
        except Exception as e: _logger.error(f"Gagal kirim pesan error utk cmd '{command_name}' (unknown exception): {e}", exc_info=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedCog(bot))
    _logger.info("EmbedCog (Custom Embeds) berhasil dimuat.")