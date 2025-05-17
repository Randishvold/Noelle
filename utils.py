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
# FIX: Modify all lambdas to accept all potential context arguments as optional keyword arguments
_variable_mapping = {
    'user.name': lambda user=None, member=None, guild=None, channel=None: (user.name if user else member.name) if (user or member) else 'Unknown User',
    'user.tag': lambda user=None, member=None, guild=None, channel=None: (user.discriminator if user and user.discriminator != '0' else user.name if user else member.discriminator if member and member.discriminator != '0' else member.name if member else 'Unknown User') if (user or member) else 'Unknown User', # Handle new Discord username system
    'user.mention': lambda user=None, member=None, guild=None, channel=None: (user.mention if user else member.mention) if (user or member) else 'Unknown User',
    'user.id': lambda user=None, member=None, guild=None, channel=None: (user.id if user else member.id) if (user or member) else 'Unknown User',
    'user.created_at': lambda user=None, member=None, guild=None, channel=None: format_date((user.created_at if user else member.created_at)) if (user or member) else 'Unknown Date',

    'server.name': lambda user=None, member=None, guild=None, channel=None: guild.name if guild else 'Unknown Server',
    'server.id': lambda user=None, member=None, guild=None, channel=None: guild.id if guild else 'Unknown Server',
    'server.member_count': lambda user=None, member=None, guild=None, channel=None: guild.member_count if guild else 'Unknown Count',
    'server.created_at': lambda user=None, member=None, guild=None, channel=None: format_date(guild.created_at) if guild and guild.created_at else 'Unknown Date',

    'channel.name': lambda user=None, member=None, guild=None, channel=None: channel.name if channel else 'Unknown Channel',
    'channel.id': lambda user=None, member=None, guild=None, channel=None: channel.id if channel else 'Unknown Channel',
    'channel.mention': lambda user=None, member=None, guild=None, channel=None: channel.mention if channel else 'Unknown Channel',
}

# Define user-friendly descriptions (remains the same)
VARIABLE_DESCRIPTIONS = {
    'user.name': 'Nama pengguna (mis: NamaPengguna).',
    'user.tag': 'Tag pengguna (mis: NamaPengguna#1234).',
    'user.mention': 'Mention pengguna (@NamaPengguna).',
    'user.id': 'ID unik pengguna.',
    'user.created_at': 'Waktu akun pengguna dibuat.',

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

def replace_variables(text: str, user: discord.User = None, member: discord.Member = None, guild: discord.Guild = None, channel: discord.TextChannel = None):
    """Replaces placeholder variables in text with actual values."""
    if not isinstance(text, str):
        return text

    pattern = re.compile(r'\{(\w+\.\w+)\}')

    def replacer(match):
        """Function to replace each matched variable pattern."""
        variable_name = match.group(1)

        try:
            value_lambda = _variable_mapping.get(variable_name)
            if value_lambda:
                # FIX: Explicitly pass all context arguments to the lambda
                return str(value_lambda(user=user, member=member, guild=guild, channel=channel))
            else:
                 print(f"Warning: Unknown variable '{variable_name}' found in text.")
                 return match.group(0)

        except Exception as e:
            # Log error and return error indicator
            desc = VARIABLE_DESCRIPTIONS.get(variable_name, "Unknown variable")
            print(f"Error replacing variable '{variable_name}': {e}")
            # Include the variable name and description in the error output
            return f"{{error:{variable_name}: {desc}}}"


    processed_text = pattern.sub(replacer, text)

    return processed_text