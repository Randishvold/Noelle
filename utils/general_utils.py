# Noelle_Bot/utils/general_utils.py
import discord
import re
import datetime
import logging 

_logger = logging.getLogger("noelle_bot.general_utils")

# ... (get_color_int, get_color_hex, format_date, get_current_timestamp_for_embed tetap sama) ...
def get_color_int(color_str: str | None):
    if not color_str: return None
    color_str = color_str.lstrip('#')
    try: return int(color_str, 16)
    except ValueError: return None

def get_color_hex(color_int: int | None):
    if color_int is None: return None
    return f"#{max(0, min(0xFFFFFF, color_int)):06X}"

def format_date(dt: datetime.datetime | None):
    if not isinstance(dt, datetime.datetime): return "Tanggal Tidak Valid"
    return dt.strftime('%Y-%m-%d %H:%M UTC')

def get_current_timestamp_for_embed(): 
    return datetime.datetime.now(datetime.timezone.utc)

# ... (_variable_mapping, VARIABLE_DESCRIPTIONS, get_available_variables, replace_variables tetap sama) ...
_variable_mapping = {
    'user.name': lambda user=None, member=None, **kwargs: (user.name if user else member.name) if (user or member) else 'Pengguna Tidak Dikenal',
    'user.tag': lambda user=None, member=None, **kwargs: f"{user.name}#{user.discriminator}" if user and user.discriminator != '0' else (user.name if user else (f"{member.name}#{member.discriminator}" if member and member.discriminator != '0' else (member.name if member else "Pengguna Tidak Dikenal"))),
    'user.mention': lambda user=None, member=None, **kwargs: (user.mention if user else member.mention) if (user or member) else '@PenggunaTidakDikenal',
    'user.id': lambda user=None, member=None, **kwargs: str(user.id if user else member.id) if (user or member) else 'ID Tidak Dikenal',
    'user.nickname': lambda user=None, member=None, **kwargs: (member.nick or (user.global_name if user else member.global_name) or (user.name if user else member.name)) if (user or member) else 'Pengguna Tidak Dikenal', 
    'user.avatar_url': lambda user=None, member=None, **kwargs: str(user.display_avatar.url if user else member.display_avatar.url) if (user or member) else '', 
    'server.name': lambda guild=None, **kwargs: guild.name if guild else 'Server Tidak Dikenal',
    'server.id': lambda guild=None, **kwargs: str(guild.id) if guild else 'ID Server Tidak Dikenal',
    'server.member_count': lambda guild=None, **kwargs: str(guild.member_count) if guild else 'N/A',
    'channel.name': lambda channel=None, **kwargs: channel.name if channel else 'Channel Tidak Dikenal',
    'channel.id': lambda channel=None, **kwargs: str(channel.id) if channel else 'ID Channel Tidak Dikenal',
    'channel.mention': lambda channel=None, **kwargs: channel.mention if channel else '#ChannelTidakDikenal',
}
VARIABLE_DESCRIPTIONS = { 
    'user.name': 'Nama pengguna global (tanpa discriminator).',
    'user.tag': 'Tag pengguna lengkap (Nama#discriminator atau Nama jika discriminator 0).',
    'user.mention': 'Mention pengguna (@NamaPengguna).',
    'user.id': 'ID unik pengguna.',
    'user.nickname': 'Nama panggilan server (atau nama global jika tidak ada, atau nama pengguna jika tidak ada global).',
    'user.avatar_url': 'URL avatar pengguna (avatar server jika ada, jika tidak avatar global).',
    'server.name': 'Nama server Discord.',
    'server.id': 'ID unik server Discord.',
    'server.member_count': 'Jumlah anggota di server.',
    'channel.name': 'Nama channel tempat variabel digunakan.',
    'channel.id': 'ID unik channel.',
    'channel.mention': 'Mention channel (#nama-channel).',
}
def get_available_variables(): return VARIABLE_DESCRIPTIONS.copy()

def replace_variables(text: str, user: discord.User = None, member: discord.Member = None, guild: discord.Guild = None, channel: discord.abc.GuildChannel | discord.Thread | discord.DMChannel | None = None) -> str:
    if not isinstance(text, str): return text
    pattern = re.compile(r'\{(\w+\.[\w_]+)\}')
    effective_guild_for_lambda = guild or (member.guild if member else None) or (getattr(channel, 'guild', None) if channel else None)
    effective_channel_for_lambda = channel
    def replacer(match):
        variable_name = match.group(1).lower()
        try:
            value_lambda = _variable_mapping.get(variable_name)
            if value_lambda:
                kwargs = {'user': user, 'member': member, 'guild': effective_guild_for_lambda, 'channel': effective_channel_for_lambda}
                lambda_args = value_lambda.__code__.co_varnames
                final_kwargs = {k: v for k, v in kwargs.items() if k in lambda_args}
                value = str(value_lambda(**final_kwargs))
                if variable_name.endswith('_url') and (not value or value == match.group(0) or value.startswith("{Error:")):
                    return "" 
                return value
            else: _logger.warning(f"Variabel tidak dikenal saat replace: '{variable_name}'"); return "" 
        except Exception as e: _logger.error(f"Error mengganti variabel '{variable_name}': {e}", exc_info=True); return ""
    return pattern.sub(replacer, text)

def create_processed_embed(embed_data: dict, 
                           user: discord.User = None, 
                           member: discord.Member = None, 
                           guild: discord.Guild = None, 
                           channel: discord.abc.GuildChannel | discord.Thread | discord.DMChannel | None = None) -> discord.Embed:
    if not embed_data:
        return discord.Embed(title="Embed Kosong", description="Embed ini belum memiliki konten.", color=discord.Color.light_gray())

    processed_data = embed_data.copy()

    def process_url_field(data_dict, key, default_val=None):
        if key in data_dict and data_dict[key]:
            processed_url = replace_variables(data_dict[key], user, member, guild, channel)
            if not processed_url or processed_url.startswith("{") or "Error:" in processed_url:
                # Jika default_val adalah None atau tidak diberikan, hapus fieldnya
                if default_val is None and key in data_dict: 
                    del data_dict[key]
                else: # Jika ada default_val, set ke default_val (misal {'url': None} untuk thumbnail/image)
                    data_dict[key] = default_val 
            else:
                data_dict[key] = processed_url
        elif key in data_dict and data_dict[key] is None and default_val is not None: # Jika sudah None dan ada default
            data_dict[key] = default_val


    author_info = processed_data.get('author')
    if isinstance(author_info, dict):
        if 'name' in author_info and author_info['name']: 
            author_info['name'] = replace_variables(author_info['name'], user, member, guild, channel)
        process_url_field(author_info, 'icon_url') 
        if not author_info.get('name'): processed_data['author'] = None 
        else: processed_data['author'] = author_info

    footer_info = processed_data.get('footer')
    if isinstance(footer_info, dict):
        if 'text' in footer_info and footer_info['text']: 
            footer_info['text'] = replace_variables(footer_info['text'], user, member, guild, channel)
        process_url_field(footer_info, 'icon_url') 
        if not footer_info.get('text') and not footer_info.get('timestamp') and not footer_info.get('icon_url'): 
            processed_data['footer'] = None
        else: processed_data['footer'] = footer_info
    
    process_url_field(processed_data, 'url')

    # Untuk thumbnail dan image, pastikan strukturnya dict jika ada 'url'
    if 'thumbnail' in processed_data and isinstance(processed_data['thumbnail'], dict):
        process_url_field(processed_data['thumbnail'], 'url')
        if not processed_data['thumbnail'].get('url'): processed_data['thumbnail'] = None # Hapus jika URL jadi None
    elif 'thumbnail' in processed_data: # Jika bukan dict (mungkin hanya string URL lama)
        process_url_field(processed_data, 'thumbnail') # Akan menghapusnya jika jadi string kosong
    
    if 'image' in processed_data and isinstance(processed_data['image'], dict):
        process_url_field(processed_data['image'], 'url')
        if not processed_data['image'].get('url'): processed_data['image'] = None
    elif 'image' in processed_data:
        process_url_field(processed_data, 'image')


    if 'title' in processed_data and processed_data['title']: processed_data['title'] = replace_variables(processed_data['title'], user, member, guild, channel)
    if 'description' in processed_data and processed_data['description']: processed_data['description'] = replace_variables(processed_data['description'], user, member, guild, channel)
    
    if 'fields' in processed_data and isinstance(processed_data['fields'], list):
        new_fields = []
        for field_dict in processed_data['fields']:
            if isinstance(field_dict, dict):
                new_field = field_dict.copy()
                if 'name' in new_field and new_field['name']: new_field['name'] = replace_variables(new_field['name'], user, member, guild, channel)
                if 'value' in new_field and new_field['value']: new_field['value'] = replace_variables(new_field['value'], user, member, guild, channel)
                if new_field.get('name') and new_field.get('value'):
                    new_fields.append(new_field)
        processed_data['fields'] = new_fields if new_fields else None

    color_value_from_data = processed_data.get('color')
    final_color_int = None
    if isinstance(color_value_from_data, str):
        final_color_int = get_color_int(color_value_from_data)
    elif isinstance(color_value_from_data, int):
        final_color_int = color_value_from_data
    
    if final_color_int is not None:
        processed_data['color'] = final_color_int
    elif 'color' in processed_data: # Jika tidak valid dan ada di data, hapus
        del processed_data['color']


    should_add_timestamp = False
    current_footer_obj = processed_data.get('footer')
    if isinstance(current_footer_obj, dict) and current_footer_obj.get('timestamp') is True:
        should_add_timestamp = True
        temp_footer = current_footer_obj.copy()
        if 'timestamp' in temp_footer: del temp_footer['timestamp']
        # Set footer ke None jika hanya berisi timestamp boolean dan sekarang kosong
        if not temp_footer.get('text') and not temp_footer.get('icon_url'):
            processed_data['footer'] = None
        else:
            processed_data['footer'] = temp_footer

    if should_add_timestamp:
        processed_data['timestamp'] = get_current_timestamp_for_embed().isoformat()
    
    # Pembersihan akhir: hapus kunci jika nilainya None
    keys_to_clean = ['author', 'footer', 'fields', 'thumbnail', 'image', 'url', 'title', 'description']
    for key in keys_to_clean:
        if key in processed_data and processed_data[key] is None:
            del processed_data[key]
    # Khusus untuk warna, jika tidak ada, tidak perlu ada field 'color' sama sekali
    if 'color' not in processed_data or processed_data.get('color') is None:
        if 'color' in processed_data: del processed_data['color']

    try:
        embed = discord.Embed.from_dict(processed_data)
        return embed
    except Exception as e:
        _logger.error(f"Error membuat embed dari dict: {e}\nData yang diproses untuk from_dict: {processed_data}", exc_info=True)
        return discord.Embed(title="Error Pembuatan Embed", description=f"Tidak dapat membuat embed: {e}", color=discord.Color.red())