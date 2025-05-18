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
    ''', (guild_id, embed_name, json.dumps(embed_data)))
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
        return discord.Embed(title="Empty Embed", description="This embed has no content yet.", color=discord.Color.gray())

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
         # Add timestamp if footer text exists but timestamp wasn't explicitly in stored data
        if 'text' in processed_data['footer'] and processed_data['footer']['text'] and 'timestamp' not in processed_data['footer']:
             processed_data['footer']['timestamp'] = True # Default add timestamp if footer text exists


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
            # Ensure field has 'inline' key, default to False if missing
            if 'inline' not in processed_field:
                processed_field['inline'] = False
            processed_fields.append(processed_field)
        processed_data['fields'] = processed_fields # Replace original fields list

    # Handle color - convert from int to discord.Color object during Embed creation
    # The stored data has 'color' as int, discord.Embed.from_dict handles this automatically
    # if 'color' in processed_data and isinstance(processed_data['color'], int):
    #     processed_data['color'] = discord.Color(processed_data['color'])


    try:
        # Create a discord.Embed object from the processed dictionary data
        embed = discord.Embed.from_dict(processed_data)
        return embed
    except Exception as e:
        print(f"Error creating embed object from processed data: {e}")
        # Return a simple error embed or None
        return discord.Embed(title="Embed Creation Error", description=f"Could not create embed: {e}", color=discord.Color.red())


# --- Separate Modal Classes ---

class BasicEmbedModal(ui.Modal, title='Edit Basic Embed Info'):
    """Modal for editing basic embed info: title, description, color."""
    embed_title = ui.TextInput(label='Title', style=discord.TextStyle.short, required=False, max_length=256)
    embed_description = ui.TextInput(label='Description', style=discord.TextStyle.long, required=False)
    embed_color = ui.TextInput(label='Color (Hex e.g. #RRGGBB)', style=discord.TextStyle.short, required=False, max_length=7, min_length=7)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict = None):
        super().__init__()
        self.embed_name = embed_name
        self.guild_id = guild_id
        # Store initial data to pre-fill
        if initial_data:
            self.embed_title.default = initial_data.get('title', '')
            self.embed_description.default = initial_data.get('description', '')
            color_int = initial_data.get('color')
            if color_int is not None:
                 self.embed_color.default = utils.get_color_hex(color_int)

    async def on_submit(self, interaction: discord.Interaction):
        # Retrieve the *latest* data from DB to avoid overwriting other changes
        current_data = get_custom_embed(self.guild_id, self.embed_name) or {} # Start with empty dict if not found

        # Get data from modal inputs
        title = self.embed_title.value.strip() or None
        description = self.embed_description.value.strip() or None
        color_str = self.embed_color.value.strip()
        color = utils.get_color_int(color_str) if color_str else None

        # Update current data
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

        # Save updated data
        save_custom_embed(self.guild_id, self.embed_name, current_data)

        # Re-fetch data, create processed embed, and edit the original message
        updated_data = get_custom_embed(self.guild_id, self.embed_name) # Fetch saved data
        processed_embed = create_processed_embed(updated_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)

        # Edit the message that triggered the modal (which is the message containing the View)
        await interaction.response.edit_message(embed=processed_embed) # Use edit_message to update the original message


class AuthorEmbedModal(ui.Modal, title='Edit Embed Author'):
    """Modal for editing embed author info: name, icon_url."""
    author_name = ui.TextInput(label='Author Name', style=discord.TextStyle.short, required=False, max_length=256)
    author_icon_url = ui.TextInput(label='Author Icon URL (optional)', style=discord.TextStyle.short, required=False)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict = None):
        super().__init__()
        self.embed_name = embed_name
        self.guild_id = guild_id
        # Store initial data to pre-fill
        if initial_data and 'author' in initial_data and isinstance(initial_data['author'], dict):
             self.author_name.default = initial_data['author'].get('name', '')
             self.author_icon_url.default = initial_data['author'].get('icon_url', '') # Note: Use icon_url here


    async def on_submit(self, interaction: discord.Interaction):
        current_data = get_custom_embed(self.guild_id, self.embed_name) or {}

        # Get data from modal inputs
        author_name = self.author_name.value.strip() or None
        author_icon_url = self.author_icon_url.value.strip() or None

        # Update current data
        if author_name: # Author requires at least a name
             author_dict = {'name': author_name}
             if author_icon_url:
                 author_dict['icon_url'] = author_icon_url
             current_data['author'] = author_dict
        elif 'author' in current_data: # Remove author if name input is empty and it existed before
             del current_data['author']

        save_custom_embed(self.guild_id, self.embed_name, current_data)

        updated_data = get_custom_embed(self.guild_id, self.embed_name)
        processed_embed = create_processed_embed(updated_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)

        await interaction.response.edit_message(embed=processed_embed)


class FooterEmbedModal(ui.Modal, title='Edit Embed Footer'):
    """Modal for editing embed footer info: text, timestamp (implicit)."""
    footer_text = ui.TextInput(label='Footer Text', style=discord.TextStyle.short, required=False, max_length=2048)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict = None):
        super().__init__()
        self.embed_name = embed_name
        self.guild_id = guild_id
        # Store initial data to pre-fill
        if initial_data and 'footer' in initial_data and isinstance(initial_data['footer'], dict):
             self.footer_text.default = initial_data['footer'].get('text', '')

        # We won't have a specific input for timestamp true/false in the modal
        # It will be added by default if footer_text is not empty on submit

    async def on_submit(self, interaction: discord.Interaction):
        current_data = get_custom_embed(self.guild_id, self.embed_name) or {}

        # Get data from modal inputs
        footer_text = self.footer_text.value.strip() or None

        # Update current data
        if footer_text: # Footer requires at least text
             footer_dict = {'text': footer_text}
             footer_dict['timestamp'] = True # Add timestamp by default if text is provided
             current_data['footer'] = footer_dict
        elif 'footer' in current_data: # Remove footer if text input is empty and it existed before
             del current_data['footer']

        save_custom_embed(self.guild_id, self.embed_name, current_data)

        updated_data = get_custom_embed(self.guild_id, self.embed_name)
        processed_embed = create_processed_embed(updated_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)

        await interaction.response.edit_message(embed=processed_embed)


# --- View with Buttons for Editing ---

class EmbedEditView(ui.View):
    """A view with buttons to open modals for editing different parts of an embed."""
    def __init__(self, embed_name: str, guild_id: int, *, timeout=180):
        super().__init__(timeout=timeout)
        self.embed_name = embed_name
        self.guild_id = guild_id

    # Timeout handler (optional) - removes the view when it times out
    async def on_timeout(self) -> None:
        # Disable all buttons when the view times out
        for item in self.children:
            item.disabled = True
        # Edit the original message to remove the view
        # This requires accessing the message the view is attached to
        # A common pattern is to store the message in the view after it's sent
        # For simplicity here, we assume the message is accessible via the last interaction
        # This might be brittle, storing the message ID is more robust
        # Let's just disable buttons for now. If we need to delete the view,
        # we'd need to store the message reference.
        # Example (if message stored): await self.message.edit(view=None)
        print(f"View for embed '{self.embed_name}' timed out.")
        pass # Simply pass, buttons will be disabled by discord automatically on timeout

    @ui.button(label='Edit Basic Info', style=discord.ButtonStyle.primary)
    async def edit_basic_button(self, interaction: discord.Interaction, button: ui.Button):
        """Button to open the Basic Embed Info modal."""
        # Retrieve current embed data before showing the modal
        current_data = get_custom_embed(self.guild_id, self.embed_name)
        modal = BasicEmbedModal(self.embed_name, self.guild_id, current_data)
        await interaction.response.send_modal(modal)

    @ui.button(label='Edit Author', style=discord.ButtonStyle.primary)
    async def edit_author_button(self, interaction: discord.Interaction, button: ui.Button):
        """Button to open the Embed Author modal."""
        current_data = get_custom_embed(self.guild_id, self.embed_name)
        modal = AuthorEmbedModal(self.embed_name, self.guild_id, current_data)
        await interaction.response.send_modal(modal)

    @ui.button(label='Edit Footer', style=discord.ButtonStyle.primary)
    async def edit_footer_button(self, interaction: discord.Interaction, button: ui.Button):
        """Button to open the Embed Footer modal."""
        current_data = get_custom_embed(self.guild_id, self.embed_name)
        modal = FooterEmbedModal(self.embed_name, self.guild_id, current_data)
        await interaction.response.send_modal(modal)

    # You might want a 'Done' button to remove the view eventually
    # @ui.button(label='Done', style=discord.ButtonStyle.success)
    # async def done_button(self, interaction: discord.Interaction, button: ui.Button):
    #    await interaction.response.edit_message(view=None) # Remove the view

# --- Embed Cog Class ---

class EmbedCog(commands.Cog):
    """Cog for managing custom server embeds and using them."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Event triggered when a new member joins the guild."""
        guild = member.guild
        channel = guild.system_channel

        if channel is not None:
            welcome_embed_data = get_custom_embed(guild.id, "welcome")
            if welcome_embed_data:
                try:
                    # Use the helper function to create the embed with variables processed
                    embed = create_processed_embed(welcome_embed_data, member=member, guild=guild, channel=channel)

                    # Add user avatar as thumbnail if embed doesn't have one and user has avatar (existing logic)
                    if member.avatar and not embed.thumbnail:
                         embed.set_thumbnail(url=member.avatar.url)

                    await channel.send(embed=embed)
                except Exception as e:
                    print(f"Error sending custom welcome embed: {e}")
                    await channel.send(f'Welcome {member.mention} to the {guild.name} server!')
            else:
                # Default welcome message if no "welcome" embed is found
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
        """Initiates creating a new custom embed."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # Check if embed name already exists
        existing_embed = get_custom_embed(interaction.guild_id, name)
        if existing_embed:
             await interaction.response.send_message(f"An embed named '{name}' already exists. Use `/embed edit {name}` to modify it.", ephemeral=True)
             return

        # Create an empty embed data dictionary and save it initially
        initial_data = {}
        save_custom_embed(interaction.guild_id, name, initial_data)

        # Create the initial preview embed and the view with buttons
        # Use the helper function
        preview_embed = create_processed_embed(initial_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)
        edit_view = EmbedEditView(name, interaction.guild_id)

        # Send the message with the preview and the buttons
        await interaction.response.send_message(
            f"Editing embed '{name}'. Use the buttons below to modify different parts."
            f"\nVariables like {{user.mention}}, {{server.name}}, {{channel.name}}, {{user.avatar_url}} are supported."
            , embed=preview_embed, view=edit_view, ephemeral=True # ephemeral=True might be useful to keep edit messages private
        )


    @embed_group.command(name='edit', description='Edit an existing custom embed template.')
    @app_commands.describe(name='The name of the embed template to edit.')
    @commands.has_permissions(manage_guild=True)
    async def embed_edit(self, interaction: discord.Interaction, name: str):
        """Initiates editing an existing custom embed."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # Retrieve existing embed data
        existing_data = get_custom_embed(interaction.guild_id, name)
        if existing_data is None:
            await interaction.response.send_message(f"No embed found with the name '{name}'.", ephemeral=True)
            return

        # Create the initial preview embed and the view with buttons
        # Use the helper function
        preview_embed = create_processed_embed(existing_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)
        edit_view = EmbedEditView(name, interaction.guild_id)

        # Send the message with the preview and the buttons
        await interaction.response.send_message(
            f"Editing embed '{name}'. Use the buttons below to modify different parts."
            f"\nVariables like {{user.mention}}, {{server.name}}, {{channel.name}}, {{user.avatar_url}} are supported."
             , embed=preview_embed, view=edit_view, ephemeral=True # ephemeral=True might be useful
        )


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


    @embed_group.command(name='view', description='Preview a custom embed template with variables replaced.')
    @app_commands.describe(name='The name of the embed template to preview.')
    async def embed_view(self, interaction: discord.Interaction, name: str):
        """Previews a custom embed with variables replaced."""
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        embed_data = get_custom_embed(interaction.guild_id, name)

        if embed_data is None:
            await interaction.response.send_message(f"No embed found with the name '{name}'.", ephemeral=True)
            return

        try:
            # Use the helper function to create the embed with variables processed
            embed = create_processed_embed(embed_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)
            await interaction.response.send_message("Preview:", embed=embed)
        except Exception as e:
            print(f"Error creating embed from data for view: {e}")
            # The helper function should return an error embed or handle errors internally,
            # but a fallback response is good
            await interaction.response.send_message(f"Could not create embed from data for '{name}'. Check bot logs for details.", ephemeral=True)


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

    async def embed_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for embed commands."""
        if isinstance(error, app_commands.MissingPermissions):
             await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, app_commands.CommandInvokeError):
             # Log the original exception from CommandInvokeError
             print(f"CommandInvokeError in embed command: {error.original}")
             await interaction.response.send_message(f"An error occurred while executing the command: {error.original}", ephemeral=True)
        else:
            print(f"An unexpected error occurred in embed command: {error}")
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)


    # Attach error handlers to commands
    embed_add.error(embed_command_error)
    embed_edit.error(embed_command_error)
    embed_list.error(embed_command_error)
    embed_view.error(embed_command_error) # Add error handler for view command
    embed_remove.error(embed_command_error)


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the Embed cog."""
    await bot.add_cog(EmbedCog(bot))