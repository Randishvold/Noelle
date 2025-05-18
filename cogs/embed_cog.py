import discord
import os
import sqlite3
import json
from discord.ext import commands
from discord import app_commands
import discord.ui as ui
import utils # Import utils from the project root

# --- Database Setup ---
DB_PATH = os.path.join('data', 'embeds.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def init_db():
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

init_db()

# --- Database Helper Functions ---
# (save_custom_embed, get_custom_embed, get_all_custom_embed_names, delete_custom_embed remain the same)

def save_custom_embed(guild_id: int, embed_name: str, embed_data: dict):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO custom_embeds (guild_id, embed_name, embed_data)
        VALUES (?, ?, ?)
    ''', (guild_id, embed_name, json.dumps(embed_data, default=str))) # Added default=str for datetime
    conn.commit()
    conn.close()

def get_custom_embed(guild_id: int, embed_name: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT embed_data FROM custom_embeds
        WHERE guild_id = ? AND embed_name = ?
    ''', (guild_id, embed_name))
    row = cursor.fetchone()
    conn.close()
    if row:
        # Deserialize JSON. Need to handle potential datetime string back to object if necessary,
        # but Embed.from_dict usually handles standard ISO format strings.
        # Let's rely on from_dict for now. If issues arise, might need custom deserialization.
        return json.loads(row[0])
    return None

def get_all_custom_embed_names(guild_id: int):
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

# --- Helper function to create embed object from data with variable processing ---
def create_processed_embed(embed_data: dict, user: discord.User = None, member: discord.Member = None, guild: discord.Guild = None, channel: discord.TextChannel = None):
    """Creates a discord.Embed object from stored data after processing variables."""
    if not embed_data:
        return discord.Embed(title="Empty Embed", description="This embed has no content yet.", color=discord.Color.light_gray())

    # Make a copy to avoid modifying the stored data
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
        # The 'timestamp' key in footer_dict should be a boolean (True/False) in stored data,
        # not a datetime object string. We add it as True/False in modal submit.
        # We don't process variables on the timestamp *value* itself, only the text.


    # Process title, description, and fields for variables
    if 'title' in processed_data and processed_data['title']:
        processed_data['title'] = utils.replace_variables(processed_data['title'], user=user, member=member, guild=guild, channel=channel)
    if 'description' in processed_data and processed_data['description']:
        processed_data['description'] = utils.replace_variables(processed_data['description'], user=user, member=member, guild=guild, channel=channel)

    # Fields Processing
    if 'fields' in processed_data and isinstance(processed_data['fields'], list):
        processed_fields = []
        for field in processed_data['fields']:
            processed_field = field.copy() # Copy the field dictionary
            if 'name' in processed_field and processed_field['name']:
                processed_field['name'] = utils.replace_variables(processed_field['name'], user=user, member=member, guild=guild, channel=channel)
            if 'value' in processed_field and processed_field['value']:
                processed_field['value'] = utils.replace_variables(processed_field['value'], user=user, member=member, guild=guild, channel=channel)
            if 'inline' not in processed_field:
                processed_field['inline'] = False
            processed_fields.append(processed_field)
        processed_data['fields'] = processed_fields # Replace original fields list

    # Handle color - convert from int to discord.Color object during Embed creation
    # Handle timestamp field - ensure it's a datetime object if True in processed_data
    if 'footer' in processed_data and isinstance(processed_data['footer'], dict):
        if processed_data['footer'].get('timestamp') is True:
             # If timestamp is True in stored data, set the embed's timestamp field to the current time
             # This is how Discord displays the "ago" timestamp
             processed_data['timestamp'] = utils.get_current_timestamp()
        elif 'timestamp' in processed_data: # If timestamp was False or not boolean, and exists in processed_data
             del processed_data['timestamp'] # Remove it so Discord doesn't display it


    try:
        embed = discord.Embed.from_dict(processed_data)
        return embed
    except Exception as e:
        print(f"Error creating embed object from processed data: {e}")
        print(f"Problematic embed data: {processed_data}")
        return discord.Embed(title="Embed Creation Error", description=f"Could not create embed: {e}", color=discord.Color.red())


# --- Separate Modal Classes ---

# Basic Embed Modal (remains the same)
class BasicEmbedModal(ui.Modal, title='Edit Basic Embed Info'):
    embed_title = ui.TextInput(label='Title', style=discord.TextStyle.short, required=False, max_length=256)
    embed_description = ui.TextInput(label='Description', style=discord.TextStyle.long, required=False)
    embed_color = ui.TextInput(label='Color (Hex e.g. #RRGGBB)', style=discord.TextStyle.short, required=False, max_length=7, min_length=7)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict = None):
        super().__init__()
        self.embed_name = embed_name
        self.guild_id = guild_id
        if initial_data:
            self.embed_title.default = initial_data.get('title', '')
            self.embed_description.default = initial_data.get('description', '')
            color_int = initial_data.get('color')
            if color_int is not None:
                 self.embed_color.default = utils.get_color_hex(color_int)

    async def on_submit(self, interaction: discord.Interaction):
        current_data = get_custom_embed(self.guild_id, self.embed_name) or {}

        title = self.embed_title.value.strip() or None
        description = self.embed_description.value.strip() or None
        color_str = self.embed_color.value.strip()
        color = utils.get_color_int(color_str) if color_str else None

        if title is not None:
             current_data['title'] = title
        elif 'title' in current_data:
             del current_data['title']

        if description is not None:
             current_data['description'] = description
        elif 'description' in current_data:
             del current_data['description']

        if color is not None:
             current_data['color'] = color
        elif 'color' in current_data:
             del current_data['color']

        save_custom_embed(self.guild_id, self.embed_name, current_data)

        updated_data = get_custom_embed(self.guild_id, self.embed_name)
        processed_embed = create_processed_embed(updated_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)

        await interaction.response.edit_message(embed=processed_embed)


# Author Embed Modal (remains the same)
class AuthorEmbedModal(ui.Modal, title='Edit Embed Author'):
    author_name = ui.TextInput(label='Author Name', style=discord.TextStyle.short, required=False, max_length=256)
    author_icon_url = ui.TextInput(label='Author Icon URL (optional)', style=discord.TextStyle.short, required=False)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict = None):
        super().__init__()
        self.embed_name = embed_name
        self.guild_id = guild_id
        if initial_data and 'author' in initial_data and isinstance(initial_data['author'], dict):
             self.author_name.default = initial_data['author'].get('name', '')
             self.author_icon_url.default = initial_data['author'].get('icon_url', '')


    async def on_submit(self, interaction: discord.Interaction):
        current_data = get_custom_embed(self.guild_id, self.embed_name) or {}

        author_name = self.author_name.value.strip() or None
        author_icon_url = self.author_icon_url.value.strip() or None

        if author_name:
             author_dict = {'name': author_name}
             if author_icon_url:
                 author_dict['icon_url'] = author_icon_url
             current_data['author'] = author_dict
        elif 'author' in current_data:
             del current_data['author']

        save_custom_embed(self.guild_id, self.embed_name, current_data)

        updated_data = get_custom_embed(self.guild_id, self.embed_name)
        processed_embed = create_processed_embed(updated_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)

        await interaction.response.edit_message(embed=processed_embed)


# --- Footer Embed Modal (Modified) ---
class FooterEmbedModal(ui.Modal, title='Edit Embed Footer'):
    """Modal for editing embed footer info: text, timestamp toggle."""
    footer_text = ui.TextInput(label='Footer Text', style=discord.TextStyle.short, required=False, max_length=2048)
    # New: Input for timestamp toggle
    add_timestamp = ui.TextInput(label='Add Timestamp? (yes/no)', style=discord.TextStyle.short, required=False, max_length=3)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict = None):
        super().__init__()
        self.embed_name = embed_name
        self.guild_id = guild_id
        # Store initial data to pre-fill
        if initial_data and 'footer' in initial_data and isinstance(initial_data['footer'], dict):
             self.footer_text.default = initial_data['footer'].get('text', '')
             # Pre-fill timestamp toggle
             timestamp_enabled = initial_data['footer'].get('timestamp', False) # Default to False
             self.add_timestamp.default = 'yes' if timestamp_enabled else 'no' # Pre-fill with 'yes' or 'no'

    async def on_submit(self, interaction: discord.Interaction):
        current_data = get_custom_embed(self.guild_id, self.embed_name) or {}

        # Get data from modal inputs
        footer_text = self.footer_text.value.strip() or None
        add_timestamp_input = self.add_timestamp.value.strip().lower()

        # Determine timestamp boolean based on input
        timestamp_enabled = add_timestamp_input == 'yes'

        # Update current data
        if footer_text: # Footer requires at least text
             footer_dict = {'text': footer_text}
             # Add timestamp boolean based on user input
             footer_dict['timestamp'] = timestamp_enabled
             current_data['footer'] = footer_dict
        elif 'footer' in current_data: # Remove footer if text input is empty and it existed before
             del current_data['footer']
        # If footer_text is empty and timestamp_enabled is False, nothing changes or footer is removed

        save_custom_embed(self.guild_id, self.embed_name, current_data)

        updated_data = get_custom_embed(self.guild_id, self.embed_name)
        processed_embed = create_processed_embed(updated_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)

        await interaction.response.edit_message(embed=processed_embed)


# --- View with Buttons for Editing ---
# (EmbedEditView remains the same)

class EmbedEditView(ui.View):
    """A view with buttons to open modals for editing different parts of an embed."""
    def __init__(self, embed_name: str, guild_id: int, *, timeout=180):
        super().__init__(timeout=timeout)
        self.embed_name = embed_name
        self.guild_id = guild_id

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        print(f"View for embed '{self.embed_name}' timed out.")
        # Consider editing the message to remove the view explicitly if desired

    @ui.button(label='Edit Basic Info', style=discord.ButtonStyle.primary)
    async def edit_basic_button(self, interaction: discord.Interaction, button: ui.Button):
        current_data = get_custom_embed(self.guild_id, self.embed_name)
        modal = BasicEmbedModal(self.embed_name, self.guild_id, current_data)
        await interaction.response.send_modal(modal)

    @ui.button(label='Edit Author', style=discord.ButtonStyle.primary)
    async def edit_author_button(self, interaction: discord.Interaction, button: ui.Button):
        current_data = get_custom_embed(self.guild_id, self.embed_name)
        modal = AuthorEmbedModal(self.embed_name, self.guild_id, current_data)
        await interaction.response.send_modal(modal)

    @ui.button(label='Edit Footer', style=discord.ButtonStyle.primary)
    async def edit_footer_button(self, interaction: discord.Interaction, button: ui.Button):
        current_data = get_custom_embed(self.guild_id, self.embed_name)
        modal = FooterEmbedModal(self.embed_name, self.guild_id, current_data)
        await interaction.response.send_modal(modal)


# --- Embed Cog Class ---
# (EmbedCog remains the same, it uses create_processed_embed and EmbedEditView)

class EmbedCog(commands.Cog):
    """Cog for managing custom server embeds and using them."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        channel = guild.system_channel

        if channel is not None:
            welcome_embed_data = get_custom_embed(guild.id, "welcome")
            if welcome_embed_data:
                try:
                    embed = create_processed_embed(welcome_embed_data, member=member, guild=guild, channel=channel)

                    if member.avatar and not embed.thumbnail:
                         embed.set_thumbnail(url=member.avatar.url)

                    await channel.send(embed=embed)
                except Exception as e:
                    print(f"Error sending custom welcome embed: {e}")
                    await channel.send(f'Welcome {member.mention} to the {guild.name} server!')
            else:
                embed = discord.Embed(
                    title=f"Welcome to {guild.name}!",
                    description=f"Hello {member.mention}, welcome aboard!",
                    color=utils.get_color_int("00FF00")
                )
                if member.avatar:
                     embed.set_thumbnail(url=member.avatar.url)
                await channel.send(embed=embed)


    embed_group = app_commands.Group(name='embed', description='Manage custom server embeds.')

    @embed_group.command(name='add', description='Create a new custom embed template.')
    @app_commands.describe(name='A unique name for this embed template.')
    @commands.has_permissions(manage_guild=True)
    async def embed_add(self, interaction: discord.Interaction, name: str):
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        existing_embed = get_custom_embed(interaction.guild_id, name)
        if existing_embed:
             await interaction.response.send_message(f"An embed named '{name}' already exists. Use `/embed edit {name}` to modify it.", ephemeral=True)
             return

        initial_data = {}
        save_custom_embed(interaction.guild_id, name, initial_data)

        preview_embed = create_processed_embed(initial_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)
        edit_view = EmbedEditView(name, interaction.guild_id)

        await interaction.response.send_message(
            f"Editing embed '{name}'. Use the buttons below to modify different parts."
            f"\nVariables like {{user.mention}}, {{server.name}}, {{channel.name}}, {{user.avatar_url}}, {{user.nickname}} are supported." # Added nickname to message
            , embed=preview_embed, view=edit_view, ephemeral=True
        )


    @embed_group.command(name='edit', description='Edit an existing custom embed template.')
    @app_commands.describe(name='The name of the embed template to edit.')
    @commands.has_permissions(manage_guild=True)
    async def embed_edit(self, interaction: discord.Interaction, name: str):
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        existing_data = get_custom_embed(interaction.guild_id, name)
        if existing_data is None:
            await interaction.response.send_message(f"No embed found with the name '{name}'.", ephemeral=True)
            return

        preview_embed = create_processed_embed(existing_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)
        edit_view = EmbedEditView(name, interaction.guild_id)

        await interaction.response.send_message(
            f"Editing embed '{name}'. Use the buttons below to modify different parts."
            f"\nVariables like {{user.mention}}, {{server.name}}, {{channel.name}}, {{user.avatar_url}}, {{user.nickname}} are supported." # Added nickname to message
             , embed=preview_embed, view=edit_view, ephemeral=True
        )


    @embed_group.command(name='list', description='List all custom embed templates for this server.')
    @commands.has_permissions(manage_guild=True)
    async def embed_list(self, interaction: discord.Interaction):
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


    @embed_group.command(name='view', description='Preview a custom embed template with variables replaced.')
    @app_commands.describe(name='The name of the embed template to preview.')
    async def embed_view(self, interaction: discord.Interaction, name: str):
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        embed_data = get_custom_embed(interaction.guild_id, name)

        if embed_data is None:
            await interaction.response.send_message(f"No embed found with the name '{name}'.", ephemeral=True)
            return

        try:
            embed = create_processed_embed(embed_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)
            await interaction.response.send_message("Preview:", embed=embed)
        except Exception as e:
            print(f"Error creating embed from data for view: {e}")
            print(f"Problematic embed data: {embed_data}") # Print original data for context
            await interaction.response.send_message(f"Could not create embed from data for '{name}'. Check bot logs for details.", ephemeral=True)


    @embed_group.command(name='remove', description='Delete a custom embed template.')
    @app_commands.describe(name='The name of the embed template to delete.')
    @commands.has_permissions(manage_guild=True)
    async def embed_remove(self, interaction: discord.Interaction, name: str):
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        deleted = delete_custom_embed(interaction.guild_id, name)

        if deleted:
            await interaction.response.send_message(f"Custom embed '{name}' deleted successfully.", ephemeral=True)
        else:
            await interaction.response.send_message(f"No embed found with the name '{name}'.", ephemeral=True)

    async def embed_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
             await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, app_commands.CommandInvokeError):
             print(f"CommandInvokeError in embed command: {error.original}")
             await interaction.response.send_message(f"An error occurred while executing the command: {error.original}", ephemeral=True)
        else:
            print(f"An unexpected error occurred in embed command: {error}")
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)


    embed_add.error(embed_command_error)
    embed_edit.error(embed_command_error)
    embed_list.error(embed_command_error)
    embed_view.error(embed_command_error)
    embed_remove.error(embed_command_error)


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the Embed cog."""
    await bot.add_cog(EmbedCog(bot))