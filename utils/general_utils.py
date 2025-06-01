# Noelle_Bot/utils/general_utils.py
import discord
import re
import datetime

# --- Fungsi Warna ---
def get_color_int(color_str: str | None):
    if not color_str: return None
    color_str = color_str.lstrip('#')
    try: return int(color_str, 16)
    except ValueError: return None

def get_color_hex(color_int: int | None):
    if color_int is None: return None
    return f"#{max(0, min(0xFFFFFF, color_int)):06X}"

# --- Fungsi Tanggal ---
def format_date(dt: datetime.datetime | None):
    if not isinstance(dt, datetime.datetime): return "Tanggal Tidak Valid"
    return dt.strftime('%Y-%m-%d %H:%M UTC')

def get_current_timestamp_for_embed(): # Untuk embed timestamp
    return datetime.datetime.now(datetime.timezone.utc)

# --- Variabel dan Penggantiannya (jika masih dipakai di luar AI) ---
_variable_mapping = {
    'user.name': lambda user=None, member=None, guild=None, channel=None: (user.name if user else member.name) if (user or member) else 'Pengguna Tidak Dikenal',
    'user.tag': lambda user=None, member=None, guild=None, channel=None: f"{user.name}#{user.discriminator}" if user and user.discriminator != '0' else (user.name if user else (f"{member.name}#{member.discriminator}" if member and member.discriminator != '0' else (member.name if member else "Pengguna Tidak Dikenal"))),
    'user.mention': lambda user=None, member=None, guild=None, channel=None: (user.mention if user else member.mention) if (user or member) else '@PenggunaTidakDikenal',
    'user.id': lambda user=None, member=None, guild=None, channel=None: str(user.id if user else member.id) if (user or member) else 'ID Tidak Dikenal',
    'user.nickname': lambda user=None, member=None, guild=None, channel=None: (member.nick or (user.name if user else member.name)) if (user or member) else 'Pengguna Tidak Dikenal',
    'user.avatar_url': lambda user=None, member=None, guild=None, channel=None: str(user.display_avatar.url if user else member.display_avatar.url) if (user or member) else '',
    'server.name': lambda guild=None, **kwargs: guild.name if guild else 'Server Tidak Dikenal',
    'server.id': lambda guild=None, **kwargs: str(guild.id) if guild else 'ID Server Tidak Dikenal',
    'server.member_count': lambda guild=None, **kwargs: str(guild.member_count) if guild else 'N/A',
    'channel.name': lambda channel=None, **kwargs: channel.name if channel else 'Channel Tidak Dikenal',
    'channel.id': lambda channel=None, **kwargs: str(channel.id) if channel else 'ID Channel Tidak Dikenal',
    'channel.mention': lambda channel=None, **kwargs: channel.mention if channel else '#ChannelTidakDikenal',
}

VARIABLE_DESCRIPTIONS = {
    'user.name': 'Nama pengguna (tanpa discriminator).',
    'user.tag': 'Tag pengguna lengkap (Nama#discriminator atau Nama jika discriminator 0).',
    'user.mention': 'Mention pengguna (@NamaPengguna).',
    'user.id': 'ID unik pengguna.',
    'user.nickname': 'Nama panggilan pengguna di server ini (jika ada, jika tidak nama pengguna global).',
    'user.avatar_url': 'URL avatar pengguna.',
    'server.name': 'Nama server Discord.',
    'server.id': 'ID unik server Discord.',
    'server.member_count': 'Jumlah anggota di server.',
    'channel.name': 'Nama channel tempat variabel digunakan.',
    'channel.id': 'ID unik channel.',
    'channel.mention': 'Mention channel (#nama-channel).',
}

def get_available_variables():
    return VARIABLE_DESCRIPTIONS.copy()

def replace_variables(text: str, user: discord.User = None, member: discord.Member = None, guild: discord.Guild = None, channel: discord.TextChannel | discord.VoiceChannel | discord.Thread | None = None) -> str:
    if not isinstance(text, str): return text
    pattern = re.compile(r'\{(\w+\.[\w_]+)\}') # Izinkan underscore di nama variabel
    
    # Tentukan konteks berdasarkan apa yang tersedia
    effective_user = member or user
    effective_guild = guild or (member.guild if member else None) or (channel.guild if hasattr(channel, 'guild') else None)
    effective_channel = channel

    def replacer(match):
        variable_name = match.group(1)
        try:
            value_lambda = _variable_mapping.get(variable_name)
            if value_lambda:
                # Siapkan argumen yang mungkin diperlukan oleh lambda
                kwargs = {}
                if 'user' in value_lambda.__code__.co_varnames: kwargs['user'] = user
                if 'member' in value_lambda.__code__.co_varnames: kwargs['member'] = member
                if 'guild' in value_lambda.__code__.co_varnames: kwargs['guild'] = effective_guild
                if 'channel' in value_lambda.__code__.co_varnames: kwargs['channel'] = effective_channel
                
                # Panggil lambda dengan argumen yang relevan
                return str(value_lambda(**kwargs))
            else:
                _logger.warning(f"Variabel tidak dikenal: '{variable_name}'")
                return match.group(0) # Kembalikan placeholder asli jika tidak dikenal
        except Exception as e:
            _logger.error(f"Error mengganti variabel '{variable_name}': {e}")
            return f"{{Error: {variable_name}}}"
    return pattern.sub(replacer, text)

# --- Fungsi untuk Embed (dipindahkan dari utils.py lama / embed_cog.py) ---
def create_processed_embed(embed_data: dict, 
                           user: discord.User = None, 
                           member: discord.Member = None, 
                           guild: discord.Guild = None, 
                           channel: discord.TextChannel | discord.VoiceChannel | discord.Thread | None = None) -> discord.Embed:
    """Membuat objek discord.Embed dari data yang disimpan setelah memproses variabel."""
    if not embed_data:
        return discord.Embed(title="Embed Kosong", description="Embed ini belum memiliki konten.", color=discord.Color.light_gray())

    processed_data = embed_data.copy() # Hindari modifikasi dict asli

    # Proses variabel di berbagai field embed
    author_info = processed_data.get('author')
    if isinstance(author_info, dict):
        if 'name' in author_info: author_info['name'] = replace_variables(author_info['name'], user, member, guild, channel)
        if 'icon_url' in author_info: author_info['icon_url'] = replace_variables(author_info['icon_url'], user, member, guild, channel)
        processed_data['author'] = author_info # Update kembali

    footer_info = processed_data.get('footer')
    if isinstance(footer_info, dict):
        if 'text' in footer_info: footer_info['text'] = replace_variables(footer_info['text'], user, member, guild, channel)
        # 'timestamp' boolean ditangani di bawah
        processed_data['footer'] = footer_info

    if 'title' in processed_data: processed_data['title'] = replace_variables(processed_data['title'], user, member, guild, channel)
    if 'description' in processed_data: processed_data['description'] = replace_variables(processed_data['description'], user, member, guild, channel)
    
    if 'fields' in processed_data and isinstance(processed_data['fields'], list):
        new_fields = []
        for field in processed_data['fields']:
            new_field = field.copy()
            if 'name' in new_field: new_field['name'] = replace_variables(new_field['name'], user, member, guild, channel)
            if 'value' in new_field: new_field['value'] = replace_variables(new_field['value'], user, member, guild, channel)
            new_fields.append(new_field)
        processed_data['fields'] = new_fields

    # Konversi warna dari int (jika disimpan sebagai int) ke objek discord.Color
    # atau dari hex string ke int lalu ke discord.Color
    color_value = processed_data.get('color')
    if isinstance(color_value, str): # Jika hex string
        color_int_val = get_color_int(color_value)
        if color_int_val is not None:
            processed_data['color'] = color_int_val # from_dict mengharapkan int untuk warna
    elif not isinstance(color_value, int) and color_value is not None:
        _logger.warning(f"Format warna tidak valid di embed_data: {color_value}. Menggunakan default.")
        if 'color' in processed_data: del processed_data['color']


    # Penanganan timestamp
    should_add_timestamp = False
    if 'footer' in processed_data and isinstance(processed_data['footer'], dict) and \
       processed_data['footer'].get('timestamp') is True:
        should_add_timestamp = True
        # Hapus kunci boolean 'timestamp' dari footer agar from_dict tidak error
        temp_footer = processed_data['footer'].copy()
        if 'timestamp' in temp_footer: del temp_footer['timestamp']
        processed_data['footer'] = temp_footer if temp_footer else None # Set None jika footer jadi kosong

    if should_add_timestamp:
        processed_data['timestamp'] = get_current_timestamp_for_embed().isoformat()

    try:
        # Pastikan color adalah integer jika ada
        if 'color' in processed_data and not isinstance(processed_data['color'], int):
            if isinstance(processed_data['color'], str):
                color_int = get_color_int(processed_data['color'])
                if color_int is not None:
                    processed_data['color'] = color_int
                else:
                    del processed_data['color'] # Hapus jika tidak valid
            else:
                 del processed_data['color'] # Hapus jika tidak valid

        # Hapus author atau footer jika value-nya None atau dict kosong setelah proses
        if 'author' in processed_data and not processed_data['author']:
            del processed_data['author']
        if 'footer' in processed_data and not processed_data['footer']:
            del processed_data['footer']


        embed = discord.Embed.from_dict(processed_data)
        return embed
    except Exception as e:
        _logger.error(f"Error membuat embed dari dict: {e}\nData: {processed_data}", exc_info=True)
        return discord.Embed(title="Error Embed", description=f"Gagal membuat embed: {e}", color=discord.Color.red())