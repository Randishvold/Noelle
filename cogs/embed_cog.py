# Noelle_Bot/cogs/embed_cog.py
import discord
from discord.ext import commands
from discord import app_commands, ui # Pastikan ui diimpor
import logging
from core import database # Untuk menyimpan dan mengambil data embed
from utils import general_utils # Untuk create_processed_embed dan utilitas warna

_logger = logging.getLogger("noelle_bot.embed")

# --- Modal Classes (Ambil dari kode embed_cog.py Anda sebelumnya) ---
# Contoh:
class BasicEmbedModal(ui.Modal, title='Edit Info Dasar Embed'):
    embed_title = ui.TextInput(label='Judul', style=discord.TextStyle.short, required=False, max_length=256)
    embed_description = ui.TextInput(label='Deskripsi', style=discord.TextStyle.long, required=False, max_length=4096)
    embed_color = ui.TextInput(label='Warna (Hex: #RRGGBB)', style=discord.TextStyle.short, required=False, max_length=7)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict | None = None):
        super().__init__(timeout=300)
        self.embed_name = embed_name
        self.guild_id = guild_id
        self.initial_data = initial_data or {}
        
        self.embed_title.default = self.initial_data.get('title', '')
        self.embed_description.default = self.initial_data.get('description', '')
        color_val = self.initial_data.get('color')
        if isinstance(color_val, int): self.embed_color.default = general_utils.get_color_hex(color_val)
        elif isinstance(color_val, str): self.embed_color.default = color_val


    async def on_submit(self, interaction: discord.Interaction):
        current_data = database.get_custom_embed(self.guild_id, self.embed_name) or {}
        
        title = self.embed_title.value.strip()
        description = self.embed_description.value.strip()
        color_str = self.embed_color.value.strip()

        current_data['title'] = title if title else None
        current_data['description'] = description if description else None
        
        color_int = general_utils.get_color_int(color_str)
        current_data['color'] = color_int # Simpan sebagai integer

        if not title and 'title' in current_data: del current_data['title']
        if not description and 'description' in current_data: del current_data['description']
        if color_int is None and 'color' in current_data: del current_data['color']
            
        database.save_custom_embed(self.guild_id, self.embed_name, current_data)
        updated_data = database.get_custom_embed(self.guild_id, self.embed_name)
        processed_embed = general_utils.create_processed_embed(updated_data, interaction.user, interaction.user, interaction.guild, interaction.channel)
        await interaction.response.edit_message(content="Info dasar embed berhasil diperbarui!", embed=processed_embed)

# Tambahkan AuthorEmbedModal dan FooterEmbedModal dari kode Anda sebelumnya, pastikan menggunakan general_utils

class AuthorEmbedModal(ui.Modal, title='Edit Author Embed'):
    author_name = ui.TextInput(label='Nama Author', style=discord.TextStyle.short, required=False, max_length=256)
    author_icon_url = ui.TextInput(label='URL Ikon Author (Opsional)', style=discord.TextStyle.short, required=False)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict | None = None):
        super().__init__(timeout=300)
        self.embed_name = embed_name
        self.guild_id = guild_id
        author_data = (initial_data or {}).get('author', {})
        self.author_name.default = author_data.get('name', '')
        self.author_icon_url.default = author_data.get('icon_url', '')

    async def on_submit(self, interaction: discord.Interaction):
        current_data = database.get_custom_embed(self.guild_id, self.embed_name) or {}
        name = self.author_name.value.strip()
        icon_url = self.author_icon_url.value.strip()
        if name:
            current_data['author'] = {'name': name}
            if icon_url: current_data['author']['icon_url'] = icon_url
        elif 'author' in current_data: del current_data['author']
        database.save_custom_embed(self.guild_id, self.embed_name, current_data)
        updated_data = database.get_custom_embed(self.guild_id, self.embed_name)
        processed_embed = general_utils.create_processed_embed(updated_data, interaction.user, interaction.user, interaction.guild, interaction.channel)
        await interaction.response.edit_message(content="Author embed berhasil diperbarui!", embed=processed_embed)


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
        current_data = database.get_custom_embed(self.guild_id, self.embed_name) or {}
        text = self.footer_text.value.strip()
        show_ts = self.add_timestamp.value.strip().lower() == 'yes'
        
        if text or show_ts:
            current_data['footer'] = {}
            if text: current_data['footer']['text'] = text
            current_data['footer']['timestamp'] = show_ts # Simpan boolean
        elif 'footer' in current_data: del current_data['footer']
            
        database.save_custom_embed(self.guild_id, self.embed_name, current_data)
        updated_data = database.get_custom_embed(self.guild_id, self.embed_name)
        processed_embed = general_utils.create_processed_embed(updated_data, interaction.user, interaction.user, interaction.guild, interaction.channel)
        await interaction.response.edit_message(content="Footer embed berhasil diperbarui!", embed=processed_embed)

# --- View (Ambil dari kode embed_cog.py Anda sebelumnya) ---
class EmbedEditView(ui.View):
    def __init__(self, embed_name: str, guild_id: int, interaction_message: discord.Message, *, timeout=300): # Tambah interaction_message
        super().__init__(timeout=timeout)
        self.embed_name = embed_name
        self.guild_id = guild_id
        self.interaction_message = interaction_message # Simpan pesan interaksi

    async def on_timeout(self) -> None:
        if self.interaction_message: # Gunakan pesan yang disimpan
            try:
                for item in self.children: item.disabled = True
                await self.interaction_message.edit(view=self)
                _logger.info(f"View untuk embed '{self.embed_name}' timeout, tombol dinonaktifkan.")
            except discord.NotFound: _logger.warning("Pesan view edit embed tidak ditemukan saat timeout.")
            except Exception as e: _logger.error(f"Error timeout view edit embed: {e}")

    @ui.button(label='Info Dasar', style=discord.ButtonStyle.primary, custom_id="edit_basic")
    async def edit_basic_button(self, interaction: discord.Interaction, button: ui.Button):
        current_data = database.get_custom_embed(self.guild_id, self.embed_name)
        await interaction.response.send_modal(BasicEmbedModal(self.embed_name, self.guild_id, current_data))

    @ui.button(label='Author', style=discord.ButtonStyle.secondary, custom_id="edit_author")
    async def edit_author_button(self, interaction: discord.Interaction, button: ui.Button):
        current_data = database.get_custom_embed(self.guild_id, self.embed_name)
        await interaction.response.send_modal(AuthorEmbedModal(self.embed_name, self.guild_id, current_data))

    @ui.button(label='Footer', style=discord.ButtonStyle.secondary, custom_id="edit_footer")
    async def edit_footer_button(self, interaction: discord.Interaction, button: ui.Button):
        current_data = database.get_custom_embed(self.guild_id, self.embed_name)
        await interaction.response.send_modal(FooterEmbedModal(self.embed_name, self.guild_id, current_data))
    
    # Tambahkan tombol untuk Fields, Image, Thumbnail jika Anda punya modalnya

class EmbedCog(commands.Cog, name="Custom Embeds"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _logger.info("EmbedCog dimuat.")

    # Listener on_member_join bisa diambil dari kode lama jika masih relevan
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        # Cek jika guild punya sistem channel atau channel selamat datang yang diset
        # Anda mungkin perlu mengambil ini dari database config server jika ada settingan khusus
        target_channel = guild.system_channel # Atau logic lain untuk menentukan channel
        
        if target_channel:
            welcome_embed_data = database.get_custom_embed(guild.id, "welcome") # Nama embed khusus "welcome"
            if welcome_embed_data:
                try:
                    embed = general_utils.create_processed_embed(welcome_embed_data, member=member, guild=guild, channel=target_channel)
                    if member.display_avatar and not embed.thumbnail: # Tambah thumbnail jika belum diset
                        embed.set_thumbnail(url=member.display_avatar.url)
                    await target_channel.send(embed=embed)
                except discord.Forbidden: _logger.warning(f"Tidak bisa kirim welcome embed ke {target_channel.name} (Forbidden).")
                except Exception as e: _logger.error(f"Error kirim custom welcome embed: {e}", exc_info=True)
            # else: (opsional: kirim pesan selamat datang default jika tidak ada custom embed 'welcome')
            #     await target_channel.send(f"Selamat datang {member.mention} di server **{guild.name}**!")


    embed_group = app_commands.Group(name="embed", description="Manajemen custom embed server.")

    @embed_group.command(name="buat", description="Membuat template embed baru.")
    @app_commands.describe(nama="Nama unik untuk embed ini.")
    @commands.has_permissions(manage_guild=True)
    async def embed_add(self, interaction: discord.Interaction, nama: str):
        if not interaction.guild_id: return await interaction.response.send_message("Hanya di server.", ephemeral=True)
        nama = nama.lower().strip()
        if not nama: return await interaction.response.send_message("Nama embed tidak boleh kosong.", ephemeral=True)

        if database.get_custom_embed(interaction.guild_id, nama):
            return await interaction.response.send_message(f"Embed '{nama}' sudah ada. Gunakan `/embed edit`.", ephemeral=True)
        
        initial_data = {"title": f"Embed Baru: {nama}", "description": "Mulai edit embed ini!"}
        if database.save_custom_embed(interaction.guild_id, nama, initial_data):
            preview_embed = general_utils.create_processed_embed(initial_data, interaction.user, interaction.user, interaction.guild, interaction.channel)
            # Kirim pesan dan simpan untuk timeout view
            await interaction.response.send_message(
                f"Mengedit embed **{nama}**. Variabel: `{{user.name}}`, `{{server.name}}`, dll.", 
                embed=preview_embed, 
                view=EmbedEditView(nama, interaction.guild_id, await interaction.original_response()), # Pass original response
                ephemeral=True
            )
        else:
            await interaction.response.send_message("Gagal menyimpan embed baru ke database.", ephemeral=True)

    @embed_group.command(name="edit", description="Mengedit template embed yang sudah ada.")
    @app_commands.describe(nama="Nama embed yang akan diedit.")
    @commands.has_permissions(manage_guild=True)
    async def embed_edit(self, interaction: discord.Interaction, nama: str):
        if not interaction.guild_id: return await interaction.response.send_message("Hanya di server.", ephemeral=True)
        nama = nama.lower().strip()
        existing_data = database.get_custom_embed(interaction.guild_id, nama)
        if not existing_data:
            return await interaction.response.send_message(f"Embed '{nama}' tidak ditemukan.", ephemeral=True)

        preview_embed = general_utils.create_processed_embed(existing_data, interaction.user, interaction.user, interaction.guild, interaction.channel)
        await interaction.response.send_message(
            f"Mengedit embed **{nama}**.", 
            embed=preview_embed, 
            view=EmbedEditView(nama, interaction.guild_id, await interaction.original_response()),
            ephemeral=True
        )
    
    @embed_group.command(name="list", description="Menampilkan semua template embed kustom di server ini.")
    async def embed_list(self, interaction: discord.Interaction): # Tidak perlu manage_guild, semua bisa lihat
        if not interaction.guild_id or not interaction.guild: return await interaction.response.send_message("Hanya di server.", ephemeral=True)
        
        embed_names = database.get_all_custom_embed_names(interaction.guild_id)
        if not embed_names:
            return await interaction.response.send_message("Belum ada embed kustom di server ini.", ephemeral=True)
        
        embed = discord.Embed(title=f"Embed Kustom di {interaction.guild.name}", color=discord.Color.blue())
        embed.description = "\n".join(f"- `{name}`" for name in sorted(embed_names))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @embed_group.command(name="hapus", description="Menghapus template embed kustom.")
    @app_commands.describe(nama="Nama embed yang akan dihapus.")
    @commands.has_permissions(manage_guild=True)
    async def embed_remove(self, interaction: discord.Interaction, nama: str):
        if not interaction.guild_id: return await interaction.response.send_message("Hanya di server.", ephemeral=True)
        nama = nama.lower().strip()
        if database.delete_custom_embed(interaction.guild_id, nama):
            await interaction.response.send_message(f"Embed '{nama}' berhasil dihapus.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Embed '{nama}' tidak ditemukan atau gagal dihapus.", ephemeral=True)

    @embed_group.command(name="tampil", description="Menampilkan pratinjau embed kustom.")
    @app_commands.describe(nama="Nama embed yang akan ditampilkan.")
    async def embed_view(self, interaction: discord.Interaction, nama: str): # Tidak perlu manage_guild
        if not interaction.guild_id: return await interaction.response.send_message("Hanya di server.", ephemeral=True)
        nama = nama.lower().strip()
        embed_data = database.get_custom_embed(interaction.guild_id, nama)
        if not embed_data:
            return await interaction.response.send_message(f"Embed '{nama}' tidak ditemukan.", ephemeral=True)
        
        processed_embed = general_utils.create_processed_embed(embed_data, interaction.user, interaction.user, interaction.guild, interaction.channel)
        # Kirim sebagai pesan non-ephemeral agar bisa dilihat
        await interaction.response.send_message(f"Pratinjau embed **{nama}**:", embed=processed_embed)

    # Error handler untuk EmbedCog slash commands
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original_error = getattr(error, 'original', error)
        _logger.error(f"Error pada EmbedCog command '{interaction.command.name if interaction.command else 'N/A'}': {original_error}", exc_info=True)
        msg = "Terjadi kesalahan internal pada perintah embed."
        if isinstance(error, app_commands.MissingPermissions): msg = "Kamu tidak punya izin untuk ini."
        elif isinstance(error, app_commands.CommandInvokeError): msg = f"Error saat menjalankan: {original_error}"
        
        if interaction.response.is_done(): await interaction.followup.send(msg, ephemeral=True)
        else: await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    # Jika embed_group didefinisikan sebagai atribut kelas, tidak perlu add_command manual
    # bot.tree.add_command(EmbedCog.embed_group) # Ini akan error jika embed_group bukan static
    await bot.add_cog(EmbedCog(bot))
    _logger.info("EmbedCog (Custom Embeds) berhasil dimuat.")