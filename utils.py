import discord
import re
import datetime

# --- Helper Functions ---
# (get_color_int, get_color_hex, format_date remain the same)

def get_color_int(color_str: str):
    """Converts hex color string (#RRGGBB) to integer."""
    if not color_str:
        return None
    color_str = color_str.lstrip('#')
    try:
        return int(color_str, 16)
    except ValueError:
        return None # Invalid hex color

def get_color_hex(color_int: int):
    """Converts color integer to hex color string (#RRGGBB)."""
    if color_int is None:
        return ""
    color_int = max(0, min(0xFFFFFF, color_int))
    return f"#{color_int:06X}"

def format_date(dt: datetime.datetime):
    """Formats a datetime object into a readable string."""
    if not isinstance(dt, datetime.datetime):
        return "Invalid Date"
    return dt.strftime('%Y-%m-%d %H:%M UTC')

# --- Variable Definitions and Descriptions ---
# (_variable_mapping and VARIABLE_DESCRIPTIONS remain the same)

_variable_mapping = {
    'user.name': lambda user=None, member=None, guild=None, channel=None: (user.name if user else member.name) if (user or member) else 'Unknown User',
    'user.tag': lambda user=None, member=None, guild=None, channel=None: (user.discriminator if user and user.discriminator != '0' else user.name if user else member.discriminator if member and member.discriminator != '0' else member.name if member else 'Unknown User') if (user or member) else 'Unknown User',
    'user.mention': lambda user=None, member=None, guild=None, channel=None: (user.mention if user else member.mention) if (user or member) else 'Unknown User',
    'user.id': lambda user=None, member=None, guild=None, channel=None: (user.id if user else member.id) if (user or member) else 'Unknown User',
    'user.created_at': lambda user=None, member=None, guild=None, channel=None: format_date((user.created_at if user else member.created_at)) if (user or member) else 'Unknown Date',
    'user.avatar_url': lambda user=None, member=None, guild=None, channel=None: (user.avatar.url if user and user.avatar else member.avatar.url if member and member.avatar else '') if (user or member) else '',
    'user.nickname': lambda user=None, member=None, guild=None, channel=None: (member.nick if member and member.nick is not None else (user.name if user else member.name)) if (user or member) else 'Unknown User',

    'server.name': lambda user=None, member=None, guild=None, channel=None: guild.name if guild else 'Unknown Server',
    'server.id': lambda user=None, member=None, guild=None, channel=None: guild.id if guild else 'Unknown Server',
    'server.member_count': lambda user=None, member=None, guild=None, channel=None: guild.member_count if guild else 'Unknown Count',
    'server.created_at': lambda user=None, member=None, guild=None, channel=None: format_date(guild.created_at) if guild and guild.created_at else 'Unknown Date',

    'channel.name': lambda user=None, member=None, guild=None, channel=None: channel.name if channel else 'Unknown Channel',
    'channel.id': lambda user=None, member=None, guild=None, channel=None: channel.id if channel else 'Unknown Channel',
    'channel.mention': lambda user=None, member=None, guild=None, channel=None: channel.mention if channel else 'Unknown Channel',
}

VARIABLE_DESCRIPTIONS = {
    'user.name': 'Nama pengguna global (mis: NamaPengguna).',
    'user.tag': 'Tag pengguna (mis: NamaPengguna#1234).',
    'user.mention': 'Mention pengguna (@NamaPengguna).',
    'user.id': 'ID unik pengguna.',
    'user.created_at': 'Waktu akun pengguna dibuat.',
    'user.avatar_url': 'URL gambar avatar pengguna.',
    'user.nickname': 'Nama panggilan pengguna di server ini (prefer nickname, fallback ke username).',

    'server.name': 'Nama server Discord.',
    'server.id': 'ID unik server Discord.',
    'server.member_count': 'Jumlah total anggota di server.',
    'server.created_at': 'Waktu server dibuat.',

    'channel.name': 'Nama channel.',
    'channel.id': 'ID unik channel.',
    'channel.mention': 'Mention channel (#nama-channel).',
}

def get_available_variables():
    """Returns a dictionary of available variables and their descriptions."""
    return VARIABLE_DESCRIPTIONS

# --- Variable Replacement Function ---
# (replace_variables remains the same)

def replace_variables(text: str, user: discord.User = None, member: discord.Member = None, guild: discord.Guild = None, channel: discord.TextChannel = None):
    """Replaces placeholder variables in text with actual values."""
    if not isinstance(text, str):
        return text

    pattern = re.compile(r'\{(\w+\.\w+)\}')

    def replacer(match):
        variable_name = match.group(1)

        try:
            value_lambda = _variable_mapping.get(variable_name)
            if value_lambda:
                return str(value_lambda(user=user, member=member, guild=guild, channel=channel))
            else:
                 print(f"Warning: Unknown variable '{variable_name}' found in text.")
                 return match.group(0)

        except Exception as e:
            desc = VARIABLE_DESCRIPTIONS.get(variable_name, "Unknown variable")
            print(f"Error replacing variable '{variable_name}': {e}")
            return f"{{error:{variable_name}: {desc}}}"


    processed_text = pattern.sub(replacer, text)

    return processed_text

# --- Timestamp Function for Embed Footer ---
# (get_current_timestamp remains the same)

def get_current_timestamp():
    """Returns a Discord-compatible timestamp (datetime object in UTC)."""
    return datetime.datetime.now(datetime.timezone.utc)

# --- New: Helper function to create embed object from data with variable processing ---
# (This function is moved from cogs/embed_cog.py)
def create_processed_embed(embed_data: dict, user: discord.User = None, member: discord.Member = None, guild: discord.Guild = None, channel: discord.TextChannel = None):
    """Creates a discord.Embed object from stored data after processing variables."""
    if not embed_data:
        return discord.Embed(title="Empty Embed", description="This embed has no content yet.", color=discord.Color.light_gray())

    processed_data = embed_data.copy()

    # Process Variables in Author
    if 'author' in processed_data and isinstance(processed_data['author'], dict):
        if 'name' in processed_data['author'] and processed_data['author']['name']:
             processed_data['author']['name'] = replace_variables(processed_data['author']['name'], user=user, member=member, guild=guild, channel=channel)
        if 'icon_url' in processed_data['author'] and processed_data['author']['icon_url']:
             processed_data['author']['icon_url'] = replace_variables(processed_data['author']['icon_url'], user=user, member=member, guild=guild, channel=channel)

    # Process Variables in Footer
    if 'footer' in processed_data and isinstance(processed_data['footer'], dict):
        if 'text' in processed_data['footer'] and processed_data['footer']['text']:
             processed_data['footer']['text'] = replace_variables(processed_data['footer']['text'], user=user, member=member, guild=guild, channel=channel)
        # The 'timestamp' key in footer_dict is a boolean (True/False) in stored data.
        # We handle setting the embed's timestamp field below if it's True.


    # Process title, description, and fields for variables
    if 'title' in processed_data and processed_data['title']:
        processed_data['title'] = replace_variables(processed_data['title'], user=user, member=member, guild=guild, channel=channel)
    if 'description' in processed_data and processed_data['description']:
        processed_data['description'] = replace_variables(processed_data['description'], user=user, member=member, guild=guild, channel=channel)

    # Fields Processing
    if 'fields' in processed_data and isinstance(processed_data['fields'], list):
        processed_fields = []
        for field in processed_data['fields']:
            processed_field = field.copy()
            if 'name' in processed_field and processed_field['name']:
                processed_field['name'] = replace_variables(processed_field['name'], user=user, member=member, guild=guild, channel=channel)
            if 'value' in processed_field and processed_field['value']:
                processed_field['value'] = replace_variables(processed_field['value'], user=user, member=member, guild=guild, channel=channel)
            if 'inline' not in processed_field:
                processed_field['inline'] = False
            processed_fields.append(processed_field)
        processed_data['fields'] = processed_fields

    # --- Handle timestamp for Embed.from_dict ---
    # Check if the *stored* data indicated timestamp should be added (boolean True/False in footer)
    should_add_timestamp = processed_data.get('footer', {}).get('timestamp') is True

    # Remove the boolean 'timestamp' key from the footer dict in processed_data
    # to avoid discord.Embed.from_dict trying to interpret the boolean as part of footer data.
    processed_footer = processed_data.get('footer', {}).copy()
    if 'timestamp' in processed_footer:
         del processed_footer['timestamp']

    if 'footer' in processed_data:
         processed_data['footer'] = processed_footer

    # Add the actual datetime object (or its string) to the *top level* of processed_data
    # ONLY if should_add_timestamp is True.
    if should_add_timestamp:
        # Use the get_current_timestamp function defined in this utils module
        processed_data['timestamp'] = get_current_timestamp().isoformat() # Add as ISO string


    try:
        embed = discord.Embed.from_dict(processed_data)
        return embed
    except Exception as e:
        print(f"Error creating embed object from processed data: {e}")
        print(f"Problematic embed data: {processed_data}")
        return discord.Embed(title="Embed Creation Error", description=f"Could not create embed: {e}", color=discord.Color.red())