import discord
import os
import sqlite3
import json
from discord.ext import commands
from discord import app_commands, ui

# --- Database Setup ---
# Path to the SQLite database file
# Use a path relative to the script execution directory
DB_PATH = os.path.join('data', 'embeds.db')

# Ensure the data directory exists when this module is loaded
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def init_db():
    """Initializes the SQLite database and creates the table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_embeds (
            guild_id INTEGER NOT NULL,
            embed_name TEXT NOT NULL,
            embed_data TEXT NOT NULL,
            PRIMARY KEY (guild_id, embed_name)
        )
    ''')
    conn.commit()
    conn.close()

# Initialize the database when the cog module is loaded
init_db()

# --- Database Helper Functions ---
# (Same functions as before, accessing DB_PATH)

def save_custom_embed(guild_id: int, embed_name: str, embed_data: dict):
    """Saves or updates a custom embed in the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO custom_embeds (guild_id, embed_name, embed_data)
        VALUES (?, ?, ?)
    ''', (guild_id, embed_name, json.dumps(embed_data)))
    conn.commit()
    conn.close()

def get_custom_embed(guild_id: int, embed_name: str):
    """Retrieves a custom embed from the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT embed_data FROM custom_embeds
        WHERE guild_id = ? AND embed_name = ?
    ''', (guild_id, embed_name))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return None

def get_all_custom_embed_names(guild_id: int):
    """Retrieves the names of all custom embeds for a guild."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT embed_name FROM custom_embeds
        WHERE guild_id = ?
    ''', (guild_id,))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def delete_custom_embed(guild_id: int, embed_name: str):
    """Deletes a custom embed from the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        DELETE FROM custom_embeds
        WHERE guild_id = ? AND embed_name = ?
    ''', (guild_id, embed_name))
    changes = cursor.rowcount
    conn.commit()
    conn.close()
    return changes > 0

# --- Helper Functions ---
# (Same color helpers as before)

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
    # Ensure it's within 24-bit range
    color_int = max(0, min(0xFFFFFF, color_int))
    return f"#{color_int:06X}"

# --- Modal for Embed Input ---
# (Same EmbedModal class as before)

class EmbedModal(ui.Modal, title='Edit Custom Embed'):
    """Modal for creating and editing embed data."""
    embed_title = ui.TextInput(label='Title', style=discord.TextStyle.short, required=False, max_length=256)
    embed_description = ui.TextInput(label='Description', style=discord.TextStyle.long, required=False)
    embed_color = ui.TextInput(label='Color (Hex e.g. #RRGGBB)', style=discord.TextStyle.short, required=False, max_length=7, min_length=7)
    field1_name = ui.TextInput(label='Field 1 Name', style=discord.TextStyle.short, required=False, max_length=256)
    field1_value = ui.TextInput(label='Field 1 Value', style=discord.TextStyle.long, required=False)

    def __init__(self, embed_name: str, existing_data: dict = None):
        super().__init__()
        self.embed_name = embed_name
        self.existing_data = existing_data

        if existing_data:
            self.embed_title.default = existing_data.get('title', '')
            self.embed_description.default = existing_data.get('description', '')
            color_int = existing_data.get('color')
            if color_int is not None:
                 self.embed_color.default = get_color_hex(color_int)

            fields = existing_data.get('fields')
            if fields and isinstance(fields, list) and len(fields) > 0:
                if 'name' in fields[0]:
                    self.field1_name.default = fields[0]['name']
                if 'value' in fields[0]:
                    self.field1_value.default = fields[0]['value']

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        title = self.embed_title.value.strip() or None
        description = self.embed_description.value.strip() or None
        color_str = self.embed_color.value.strip()
        color = get_color_int(color_str) if color_str else None

        embed_data = {}
        if title:
            embed_data['title'] = title
        if description:
            embed_data['description'] = description
        if color is not None:
            embed_data['color'] = color

        field1_name = self.field1_name.value.strip()
        field1_value = self.field1_value.value.strip()

        if field1_name and field1_value:
             embed_data['fields'] = [{'name': field1_name, 'value': field1_value, 'inline': False}]

        try:
            save_custom_embed(guild_id, self.embed_name, embed_data)
            action = "updated" if self.existing_data else "created"
            await interaction.response.send_message(f"Custom embed '{self.embed_name}' {action} successfully!", ephemeral=True)

        except Exception as e:
            print(f"Database error saving embed: {e}")
            await interaction.response.send_message(f"An error occurred while saving the embed: {e}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        print(f'Ignoring exception in EmbedModal:\n{error}')
        await interaction.response.send_message('Oops! Something went wrong.', ephemeral=True)


# --- Embed Cog Class ---

class EmbedCog(commands.Cog):
    """Cog for managing custom server embeds."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Event Listener example moved into Cog
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Event triggered when a new member joins the guild."""
        guild = member.guild
        channel = guild.system_channel # Or get a specific channel by ID

        if channel is not None:
            welcome_embed_data = get_custom_embed(guild.id, "welcome")
            if welcome_embed_data:
                try:
                    embed = discord.Embed.from_dict(welcome_embed_data)
                    if embed.description:
                         embed.description = embed.description.replace("{user}", member.mention).replace("{server}", guild.name)
                    elif not embed.description and embed.title:
                         embed.description = f"Hello {member.mention}!"

                    await channel.send(embed=embed)
                except Exception as e:
                    print(f"Error sending custom welcome embed: {e}")
                    await channel.send(f'Welcome {member.mention} to the {guild.name} server!')
            else:
                embed = discord.Embed(
                    title=f"Welcome to {guild.name}!",
                    description=f"Hello {member.mention}, welcome aboard!",
                    color=discord.Color.green()
                )
                if member.avatar:
                     embed.set_thumbnail(url=member.avatar.url)
                await channel.send(embed=embed)


    # Embed Management Slash Command Group (defined within the Cog)
    # Commands defined directly in the Cog class become part of its command tree
    # Use self.bot.tree if you want global commands from this cog

    # Create a command group named 'embed'
    embed_group = app_commands.Group(name='embed', description='Manage custom server embeds.')

    # Add the group's commands as methods
    # The group is automatically added to the bot's tree when the cog is added

    @embed_group.command(name='add', description='Create a new custom embed template.')
    @app_commands.describe(name='A unique name for this embed template.')
    @commands.has_permissions(manage_guild=True)
    async def embed_add(self, interaction: discord.Interaction, name: str):
        """Initiates creating a new custom embed."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        existing_embed = get_custom_embed(interaction.guild_id, name)
        if existing_embed:
             await interaction.response.send_message(f"An embed named '{name}' already exists. Use `/embed edit {name}` to modify it.", ephemeral=True)
             return

        await interaction.response.send_modal(EmbedModal(embed_name=name, existing_data=None))

    @embed_group.command(name='edit', description='Edit an existing custom embed template.')
    @app_commands.describe(name='The name of the embed template to edit.')
    @commands.has_permissions(manage_guild=True)
    async def embed_edit(self, interaction: discord.Interaction, name: str):
        """Initiates editing an existing custom embed."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        existing_data = get_custom_embed(interaction.guild_id, name)
        if existing_data is None:
            await interaction.response.send_message(f"No embed found with the name '{name}'.", ephemeral=True)
            return

        await interaction.response.send_modal(EmbedModal(embed_name=name, existing_data=existing_data))

    @embed_group.command(name='list', description='List all custom embed templates for this server.')
    @commands.has_permissions(manage_guild=True)
    async def embed_list(self, interaction: discord.Interaction):
        """Lists custom embeds."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        embed_names = get_all_custom_embed_names(interaction.guild_id)

        if not embed_names:
            await interaction.response.send_message("No custom embeds found for this server.", ephemeral=True)
        else:
            embed = discord.Embed(
                title=f"Custom Embeds for {interaction.guild.name}",
                description="\n".join(f"- `{name}`" for name in embed_names),
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Total: {len(embed_names)} embeds")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @embed_group.command(name='view', description='Preview a custom embed template.')
    @app_commands.describe(name='The name of the embed template to preview.')
    async def embed_view(self, interaction: discord.Interaction, name: str):
        """Previews a custom embed."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        embed_data = get_custom_embed(interaction.guild_id, name)

        if embed_data is None:
            await interaction.response.send_message(f"No embed found with the name '{name}'.", ephemeral=True)
            return

        try:
            embed = discord.Embed.from_dict(embed_data)
            await interaction.response.send_message("Preview:", embed=embed)
        except Exception as e:
            print(f"Error creating embed from data: {e}")
            await interaction.response.send_message(f"Could not create embed from data for '{name}'. Error: {e}", ephemeral=True)

    @embed_group.command(name='remove', description='Delete a custom embed template.')
    @app_commands.describe(name='The name of the embed template to delete.')
    @commands.has_permissions(manage_guild=True)
    async def embed_remove(self, interaction: discord.Interaction, name: str):
        """Deletes a custom embed."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        deleted = delete_custom_embed(interaction.guild_id, name)

        if deleted:
            await interaction.response.send_message(f"Custom embed '{name}' deleted successfully.", ephemeral=True)
        else:
            await interaction.response.send_message(f"No embed found with the name '{name}'.", ephemeral=True)

    # Error handlers for the embed command group
    async def embed_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for embed commands."""
        if isinstance(error, app_commands.MissingPermissions):
             await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        else:
            print(f"Error in embed command: {error}")
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

    # Attach error handlers to commands
    # This needs to be done after the methods are defined
    embed_add.error(embed_command_error)
    embed_edit.error(embed_command_error)
    embed_list.error(embed_command_error)
    embed_remove.error(embed_command_error)


# --- Setup function ---
# This is required by discord.py to load the cog
async def setup(bot: commands.Bot):
    """Sets up the Embed cog."""
    await bot.add_cog(EmbedCog(bot))
    # No need to sync here, sync is done in on_ready in bot.py