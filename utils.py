import discord
import re
import datetime

# --- Helper Functions ---

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
    # You can adjust the format string as needed
    return dt.strftime('%Y-%m-%d %H:%M UTC')

# --- Variable Replacement Function ---

def replace_variables(text: str, user: discord.User = None, member: discord.Member = None, guild: discord.Guild = None, channel: discord.TextChannel = None):
    """Replaces placeholder variables in text with actual values."""
    if not isinstance(text, str):
        return text

    variable_mapping = {
        'user.name': lambda: (user.name if user else member.name) if (user or member) else 'Unknown User',
        'user.tag': lambda: (user.discriminator if user and user.discriminator != '0' else user.name if user else member.discriminator if member and member.discriminator != '0' else member.name if member else 'Unknown User') if (user or member) else 'Unknown User',
        'user.mention': lambda: (user.mention if user else member.mention) if (user or member) else 'Unknown User',
        'user.id': lambda: (user.id if user else member.id) if (user or member) else 'Unknown User',
        'user.created_at': lambda: format_date((user.created_at if user else member.created_at)) if (user or member) else 'Unknown Date',

        'server.name': lambda: guild.name if guild else 'Unknown Server',
        'server.id': lambda: guild.id if guild else 'Unknown Server',
        'server.member_count': lambda: guild.member_count if guild else 'Unknown Count',
        'server.created_at': lambda: format_date(guild.created_at) if guild and guild.created_at else 'Unknown Date',

        'channel.name': lambda: channel.name if channel else 'Unknown Channel',
        'channel.id': lambda: channel.id if channel else 'Unknown Channel',
        'channel.mention': lambda: channel.mention if channel else 'Unknown Channel',
    }

    pattern = re.compile(r'\{(\w+\.\w+)\}')

    def replacer(match):
        variable_name = match.group(1)
        try:
            # Use .get() with a default lambda that returns the original match
            return str(variable_mapping.get(variable_name, lambda: match.group(0))())
        except Exception as e:
            print(f"Error replacing variable '{variable_name}': {e}")
            return f"{{error:{variable_name}}}"

    processed_text = pattern.sub(replacer, text)

    return processed_text