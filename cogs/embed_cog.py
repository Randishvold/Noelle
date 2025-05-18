import discord
import os
import sqlite3
import json
from discord.ext import commands
from discord import app_commands
import discord.ui as ui
import utils

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


# --- Modal for Embed Input ---

class EmbedModal(ui.Modal, title='Edit Custom Embed'):
    """Modal for creating and editing embed data."""
    embed_title = ui.TextInput(label='Title', style=discord.TextStyle.short, required=False, max_length=256)
    embed_description = ui.TextInput(label='Description', style=discord.TextStyle.long, required=False)
    embed_color = ui.TextInput(label='Color (Hex e.g. #RRGGBB)', style=discord.TextStyle.short, required=False, max_length=7, min_length=7)
    field1_name = ui.TextInput(label='Field 1 Name', style=discord.TextStyle.short, required=False, max_length=256)
    field1_value = ui.TextInput(label='Field 1 Value', style=discord.TextStyle.long, required=False)
    # --- New Inputs for Author and Footer ---
    author_name = ui.TextInput(label='Author Name', style=discord.TextStyle.short, required=False, max_length=256)
    author_icon_url = ui.TextInput(label='Author Icon URL (optional)', style=discord.TextStyle.short, required=False)
    footer_text = ui.TextInput(label='Footer Text', style=discord.TextStyle.short, required=False, max_length=2048) # Increased max length for footer

    def __init__(self, embed_name: str, existing_data: dict = None):
        super().__init__()
        self.embed_name = embed_name
        self.existing_data = existing_data

        if existing_data:
            self.embed_title.default = existing_data.get('title', '')
            self.embed_description.default = existing_data.get('description', '')
            color_int = existing_data.get('color')
            if color_int is not None:
                 self.embed_color.default = utils.get_color_hex(color_int)

            fields = existing_data.get('fields')
            if fields and isinstance(fields, list) and len(fields) > 0:
                if 'name' in fields[0]:
                    field_name_value = fields[0].get('name', '')
                    self.field1_name.default = str(field_name_value) if field_name_value is not None else ''
                if 'value' in fields[0]:
                    field_value_value = fields[0].get('value', '')
                    self.field1_value.default = str(field_value_value) if field_value_value is not None else ''

            # --- Pre-fill Author and Footer ---
            author_data = existing_data.get('author')
            if author_data and isinstance(author_data, dict):
                 self.author_name.default = author_data.get('name', '')
                 self.author_icon_url.default = author_data.get('icon_url', '') # Note: Use icon_url here

            footer_data = existing_data.get('footer')
            if footer_data and isinstance(footer_data, dict):
                 self.footer_text.default = footer_data.get('text', '')


    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        if guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        title = self.embed_title.value.strip() or None
        description = self.embed_description.value.strip() or None
        color_str = self.embed_color.value.strip()
        color = utils.get_color_int(color_str) if color_str else None

        # --- Get Author and Footer Data from Inputs ---
        author_name = self.author_name.value.strip() or None
        author_icon_url = self.author_icon_url.value.strip() or None
        footer_text = self.footer_text.value.strip() or None

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

        # --- Add Author and Footer to embed_data if not empty ---
        if author_name: # Author requires at least a name
             author_dict = {'name': author_name}
             if author_icon_url:
                 author_dict['icon_url'] = author_icon_url
             embed_data['author'] = author_dict

        if footer_text: # Footer requires at least text
             footer_dict = {'text': footer_text}
             footer_dict['timestamp'] = True # Add timestamp by default
             embed_data['footer'] = footer_dict


        try:
            save_custom_embed(guild_id, self.embed_name, embed_data)
            action = "updated" if self.existing_data else "created"
            await interaction.response.send_message(
                f"Custom embed '{self.embed_name}' {action} successfully!"
                f"\nYou can use variables like {{user.mention}}, {{server.name}}, {{channel.name}}, {{user.avatar_url}}, etc."
                f"\nUse `/embed view {self.embed_name}` to preview."
                , ephemeral=True)

        except Exception as e:
            print(f"Database error saving embed: {e}")
            await interaction.response.send_message(f"An error occurred while saving the embed: {e}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        print(f'Ignoring exception in EmbedModal:\n{error}')
        await interaction.response.send_message('Oops! Something went wrong.', ephemeral=True)


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
                    processed_embed_data = welcome_embed_data.copy()

                    # --- Process Variables in Author and Footer ---
                    if 'author' in processed_embed_data and isinstance(processed_embed_data['author'], dict):
                        if 'name' in processed_embed_data['author'] and processed_embed_data['author']['name']:
                             processed_embed_data['author']['name'] = utils.replace_variables(processed_embed_data['author']['name'], member=member, guild=guild, channel=channel)
                        if 'icon_url' in processed_embed_data['author'] and processed_embed_data['author']['icon_url']:
                             processed_embed_data['author']['icon_url'] = utils.replace_variables(processed_embed_data['author']['icon_url'], member=member, guild=guild, channel=channel)

                    if 'footer' in processed_embed_data and isinstance(processed_embed_data['footer'], dict):
                        if 'text' in processed_embed_data['footer'] and processed_embed_data['footer']['text']:
                             processed_embed_data['footer']['text'] = utils.replace_variables(processed_embed_data['footer']['text'], member=member, guild=guild, channel=channel)
                        # Note: timestamp is boolean, no variable replacement needed

                    # Process title, description, and fields for variables (existing logic)
                    if 'title' in processed_embed_data and processed_embed_data['title']:
                        processed_embed_data['title'] = utils.replace_variables(processed_embed_data['title'], member=member, guild=guild, channel=channel)
                    if 'description' in processed_embed_data and processed_embed_data['description']:
                        processed_embed_data['description'] = utils.replace_variables(processed_embed_data['description'], member=member, guild=guild, channel=channel)

                    if 'fields' in processed_embed_data and isinstance(processed_embed_data['fields'], list):
                        for field in processed_embed_data['fields']:
                            if 'name' in field and field['name']:
                                field['name'] = utils.replace_variables(field['name'], member=member, guild=guild, channel=channel)
                            if 'value' in field and field['value']:
                                field['value'] = utils.replace_variables(field['value'], member=member, guild=guild, channel=channel)

                    embed = discord.Embed.from_dict(processed_embed_data)

                    # Add user avatar as thumbnail if embed doesn't have one and user has avatar (existing logic)
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
            processed_embed_data = embed_data.copy()

            # --- Process Variables in Author and Footer for View Command ---
            if 'author' in processed_embed_data and isinstance(processed_embed_data['author'], dict):
                if 'name' in processed_embed_data['author'] and processed_embed_data['author']['name']:
                     processed_embed_data['author']['name'] = utils.replace_variables(processed_embed_data['author']['name'], user=interaction.user, guild=interaction.guild, channel=interaction.channel)
                if 'icon_url' in processed_embed_data['author'] and processed_embed_data['author']['icon_url']:
                     processed_embed_data['author']['icon_url'] = utils.replace_variables(processed_embed_data['author']['icon_url'], user=interaction.user, guild=interaction.guild, channel=interaction.channel)

            if 'footer' in processed_embed_data and isinstance(processed_embed_data['footer'], dict):
                if 'text' in processed_embed_data['footer'] and processed_embed_data['footer']['text']:
                     processed_embed_data['footer']['text'] = utils.replace_variables(processed_embed_data['footer']['text'], user=interaction.user, guild=interaction.guild, channel=interaction.channel)
                # Note: timestamp is boolean, no variable replacement needed

            # Process title, description, and fields for variables (existing logic)
            if 'title' in processed_embed_data and processed_embed_data['title']:
                processed_embed_data['title'] = utils.replace_variables(processed_embed_data['title'], user=interaction.user, guild=interaction.guild, channel=interaction.channel)
            if 'description' in processed_embed_data and processed_embed_data['description']:
                processed_embed_data['description'] = utils.replace_variables(processed_embed_data['description'], user=interaction.user, guild=interaction.guild, channel=interaction.channel)

            if 'fields' in processed_embed_data and isinstance(processed_embed_data['fields'], list):
                for field in processed_embed_data['fields']:
                    if 'name' in field and field['name']:
                        field['name'] = utils.replace_variables(field['name'], user=interaction.user, guild=interaction.guild, channel=interaction.channel)
                    if 'value' in field and field['value']:
                        field['value'] = utils.replace_variables(field['value'], user=interaction.user, guild=interaction.guild, channel=interaction.channel)

            embed = discord.Embed.from_dict(processed_embed_data)
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

    async def embed_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Error handler for embed commands."""
        if isinstance(error, app_commands.MissingPermissions):
             await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        else:
            print(f"Error in embed command: {error}")
            await interaction.response.send_message(f"An unexpected error occurred: {error}", ephemeral=True)

    embed_add.error(embed_command_error)
    embed_edit.error(embed_command_error)
    embed_list.error(embed_command_error)
    embed_remove.error(embed_command_error)


# --- Setup function ---
async def setup(bot: commands.Bot):
    """Sets up the Embed cog."""
    await bot.add_cog(EmbedCog(bot))