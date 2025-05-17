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
    'user.name': lambda user=None, member=None: (user.name if user else member.name) if (user or member) else 'Unknown User',
    'user.tag': lambda user=None, member=None: (user.discriminator if user and user.discriminator != '0' else user.name if user else member.discriminator if member and member.discriminator != '0' else member.name if member else 'Unknown User') if (user or member) else 'Unknown User', # Handle new Discord username system
    'user.mention': lambda user=None, member=None: (user.mention if user else member.mention) if (user or member) else 'Unknown User',
    'user.id': lambda user=None, member=None: (user.id if user else member.id) if (user or member) else 'Unknown User',
    'user.created_at': lambda user=None, member=None: format_date((user.created_at if user else member.created_at)) if (user or member) else 'Unknown Date',

    'server.name': lambda guild=None: guild.name if guild else 'Unknown Server',
    'server.id': lambda guild=None: guild.id if guild else 'Unknown Server',
    'server.member_count': lambda guild=None: guild.member_count if guild else 'Unknown Count',
    'server.created_at': lambda guild=None: format_date(guild.created_at) if guild and guild.created_at else 'Unknown Date',

    'channel.name': lambda channel=None: channel.name if channel else 'Unknown Channel',
    'channel.id': lambda channel=None: channel.id if channel else 'Unknown Channel',
    'channel.mention': lambda channel=None: channel.mention if channel else 'Unknown Channel',
}

# Define user-friendly descriptions for each variable
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
# (replace_variables function remains mostly the same, uses _variable_mapping)

def replace_variables(text: str, user: discord.User = None, member: discord.Member = None, guild: discord.Guild = None, channel: discord.TextChannel = None):
    """Replaces placeholder variables in text with actual values."""
    if not isinstance(text, str):
        return text

    # Regex to find patterns like {category.variable}
    pattern = re.compile(r'\{(\w+\.\w+)\}')

    def replacer(match):
        """Function to replace each matched variable pattern."""
        variable_name = match.group(1) # e.g., 'user.mention'
        # Look up the variable name in the mapping and call the lambda
        # Pass available context objects to the lambda
        try:
            # Get the lambda function from the mapping
            value_lambda = _variable_mapping.get(variable_name)
            if value_lambda:
                # Call the lambda, passing the relevant context objects
                # Use **locals() if you want to pass all current local variables,
                # but explicitly passing is clearer.
                # We pass the context objects the lambda expects (user, member, guild, channel)
                return str(value_lambda(user=user, member=member, guild=guild, channel=channel))
            else:
                 # If variable name not in mapping
                 print(f"Warning: Unknown variable '{variable_name}' found in text.")
                 return match.group(0) # Return original pattern if not found

        except Exception as e:
            # Log error if value retrieval fails (e.g., missing required context for the specific lambda)
            print(f"Error replacing variable '{variable_name}': {e}")
            # Return an error indicator, maybe with a description if available
            desc = VARIABLE_DESCRIPTIONS.get(variable_name, "Unknown variable")
            return f"{{error:{variable_name}: {desc}}}"


    # Perform the replacement
    processed_text = pattern.sub(replacer, text)

    return processed_text