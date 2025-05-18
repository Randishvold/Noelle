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

# Define the variable mapping (used by replace_variables)
_variable_mapping = {
    'user.name': lambda user=None, member=None, guild=None, channel=None: (user.name if user else member.name) if (user or member) else 'Unknown User',
    'user.tag': lambda user=None, member=None, guild=None, channel=None: (user.discriminator if user and user.discriminator != '0' else user.name if user else member.discriminator if member and member.discriminator != '0' else member.name if member else 'Unknown User') if (user or member) else 'Unknown User',
    'user.mention': lambda user=None, member=None, guild=None, channel=None: (user.mention if user else member.mention) if (user or member) else 'Unknown User',
    'user.id': lambda user=None, member=None, guild=None, channel=None: (user.id if user else member.id) if (user or member) else 'Unknown User',
    'user.created_at': lambda user=None, member=None, guild=None, channel=None: format_date((user.created_at if user else member.created_at)) if (user or member) else 'Unknown Date',
    'user.avatar_url': lambda user=None, member=None, guild=None, channel=None: (user.avatar.url if user and user.avatar else member.avatar.url if member and member.avatar else '') if (user or member) else '',
    'user.nickname': lambda user=None, member=None, guild=None, channel=None: (member.nick if member and member.nick is not None else (user.name if user else member.name)) if (user or member) else 'Unknown User', # <-- New variable logic: prefer member.nick
    # Note: {user.nickname} requires a 'member' object context to work correctly.
    # In interactions, interaction.user is also a member if in a guild.


    'server.name': lambda user=None, member=None, guild=None, channel=None: guild.name if guild else 'Unknown Server',
    'server.id': lambda user=None, member=None, guild=None, channel=None: guild.id if guild else 'Unknown Server',
    'server.member_count': lambda user=None, member=None, guild=None, channel=None: guild.member_count if guild else 'Unknown Count',
    'server.created_at': lambda user=None, member=None, guild=None, channel=None: format_date(guild.created_at) if guild and guild.created_at else 'Unknown Date',

    'channel.name': lambda user=None, member=None, guild=None, channel=None: channel.name if channel else 'Unknown Channel',
    'channel.id': lambda user=None, member=None, guild=None, channel=None: channel.id if channel else 'Unknown Channel',
    'channel.mention': lambda user=None, member=None, guild=None, channel=None: channel.mention if channel else 'Unknown Channel',
}

# Define user-friendly descriptions for each variable
VARIABLE_DESCRIPTIONS = {
    'user.name': 'Nama pengguna global (mis: NamaPengguna).',
    'user.tag': 'Tag pengguna (mis: NamaPengguna#1234).', # Still relevant for old style tags
    'user.mention': 'Mention pengguna (@NamaPengguna).',
    'user.id': 'ID unik pengguna.',
    'user.created_at': 'Waktu akun pengguna dibuat.',
    'user.avatar_url': 'URL gambar avatar pengguna.',
    'user.nickname': 'Nama panggilan pengguna di server ini (prefer nickname, fallback ke username).', # <-- New variable description

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
    

# --- Helper function to create embed object from data with variable processing ---
# (This function remains largely the same, it uses utils)
def create_processed_embed(embed_data: dict, user: discord.User = None, member: discord.Member = None, guild: discord.Guild = None, channel: discord.TextChannel = None):
    """Creates a discord.Embed object from stored data after processing variables."""
    if not embed_data:
        return discord.Embed(title="Empty Embed", description="This embed has no content yet.", color=discord.Color.light_gray())

    processed_data = embed_data.copy()

    # Process Variables in Author
    if 'author' in processed_data and isinstance(processed_data['author'], dict):
        if 'name' in processed_data['author'] and processed_data['author']['name']:
             processed_data['author']['name'] = utils.replace_variables(processed_data['author']['name'], user=user, member=member, guild=guild, channel=channel)
        if 'icon_url' in processed_data['author'] and processed_data['author']['icon_url']:
             processed_data['author']['icon_url'] = utils.replace_variables(processed_data['author']['icon_url'], user=user, member=member, guild=guild, channel=channel)


    # Process Variables in Footer
    if 'footer' in processed_data and isinstance(processed_data['footer'], dict):
        if 'text' in processed_data['footer'] and processed_data['footer']['text']:
             processed_data['footer']['text'] = utils.replace_variables(processed_data['footer']['text'], user=user, member=member, guild=guild, channel=channel)
        # The 'timestamp' key in footer_dict should be a boolean (True/False) in stored data.
        # We handle setting the embed's timestamp field below if it's True.

    # Process title, description, and fields for variables
    if 'title' in processed_data and processed_data['title']:
        processed_data['title'] = utils.replace_variables(processed_data['title'], user=user, member=member, guild=guild, channel=channel)
    if 'description' in processed_data and processed_data['description']:
        processed_data['description'] = utils.replace_variables(processed_data['description'], user=user, member=member, guild=guild, channel=channel)

    # Fields Processing
    if 'fields' in processed_data and isinstance(processed_data['fields'], list):
        processed_fields = []
        for field in processed_data['fields']:
            processed_field = field.copy()
            if 'name' in processed_field and processed_field['name']:
                processed_field['name'] = utils.replace_variables(processed_field['name'], user=user, member=member, guild=guild, channel=channel)
            if 'value' in processed_field and processed_field['value']:
                processed_field['value'] = utils.replace_variables(processed_field['value'], user=user, member=member, guild=guild, channel=channel)
            if 'inline' not in processed_field:
                processed_field['inline'] = False
            processed_fields.append(processed_field)
        processed_data['fields'] = processed_fields

    # --- Handle timestamp for Embed.from_dict ---
    # Check if the *stored* data indicated timestamp should be added (boolean True/False in footer)
    should_add_timestamp = processed_data.get('footer', {}).get('timestamp') is True

    # Remove the boolean 'timestamp' key from the footer dict in processed_data
    # to avoid discord.Embed.from_dict trying to interpret the boolean as part of footer data.
    # This key is for *our internal logic* (should we add the timestamp?), not Discord's footer structure.
    # Make a copy of footer dict if it exists to avoid modifying processed_data directly
    processed_footer = processed_data.get('footer', {}).copy() # Copy the footer dict
    if 'timestamp' in processed_footer:
         del processed_footer['timestamp'] # Remove the boolean timestamp flag

    # Update processed_data with the cleaned footer (if footer exists in original data)
    if 'footer' in processed_data: # Only update if original data had a 'footer' key
         processed_data['footer'] = processed_footer

    # Now, add the actual datetime object (or its string) to the *top level* of processed_data
    # ONLY if should_add_timestamp is True.
    # discord.Embed.from_dict expects an ISO 8601 formatted string for the top-level 'timestamp' key.
    if should_add_timestamp:
        processed_data['timestamp'] = datetime.datetime.now(datetime.timezone.utc).isoformat() # Add as ISO string

    # The color in stored data is an integer. discord.Embed.from_dict handles this automatically.


    try:
        # Create a discord.Embed object from the processed dictionary data
        # This dictionary now has a top-level 'timestamp' key with an ISO string if enabled
        # The footer dict within processed_data no longer has the boolean 'timestamp' flag
        embed = discord.Embed.from_dict(processed_data)
        return embed
    except Exception as e:
        print(f"Error creating embed object from processed data: {e}")
        print(f"Problematic embed data: {processed_data}")
        return discord.Embed(title="Embed Creation Error", description=f"Could not create embed: {e}", color=discord.Color.red())


# --- Variable Replacement Function ---

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

# --- New Timestamp Function for Embed Footer ---

def get_current_timestamp():
    """Returns a Discord-compatible timestamp (datetime object in UTC)."""
    # Discord automatically formats the timestamp when the embed object has a 'timestamp' field
    # set to a timezone-aware datetime object (usually UTC).
    # discord.py's Embed.from_dict and setting embed.timestamp handles this.
    # We just need to return a datetime object if the user toggles timestamp ON.
    # Note: This function isn't used for variable replacement {timestamp}, but for the embed's timestamp field.
    return datetime.datetime.now(datetime.timezone.utc) # Get current time in UTC