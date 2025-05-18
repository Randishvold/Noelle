import discord
import os
# Remove sqlite3 import
# import sqlite3
import json
import datetime
from discord.ext import commands
from discord import app_commands
import discord.ui as ui
import utils
# --- Import database functions ---
import database # Import the database module

# --- Database Setup (Removed from here) ---
# DB_PATH, os.makedirs, init_db functions are removed.
# Database connection and index creation are handled in database.py

# --- Database Helper Functions (Removed from here) ---
# save_custom_embed, get_custom_embed, get_all_custom_embed_names, delete_custom_embed
# These functions are now in database.py and will be called via database.function_name


# --- Separate Modal Classes ---

class BasicEmbedModal(ui.Modal, title='Edit Basic Embed Info'):
    embed_title = ui.TextInput(label='Title', style=discord.TextStyle.short, required=False, max_length=256)
    embed_description = ui.TextInput(label='Description', style=discord.TextStyle.long, required=False)
    embed_color = ui.TextInput(label='Color (Hex e.g. #RRGGBB)', style=discord.TextStyle.short, required=False, max_length=7, min_length=7)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict = None):
        super().__init__()
        self.embed_name = embed_name
        self.guild_id = guild_id
        self.initial_data = initial_data or {} # Store initial data

        self.embed_title.default = self.initial_data.get('title', '')
        self.embed_description.default = self.initial_data.get('description', '')
        color_int = self.initial_data.get('color')
        if color_int is not None:
             self.embed_color.default = utils.get_color_hex(color_int)

    async def on_submit(self, interaction: discord.Interaction):
        # Retrieve the *latest* data from DB to avoid overwriting other changes
        # Use the get_custom_embed from database.py
        current_data = database.get_custom_embed(self.guild_id, self.embed_name) or {}

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

        # Save updated data using save_custom_embed from database.py
        database.save_custom_embed(self.guild_id, self.embed_name, current_data)

        # Re-fetch data, create processed embed, and edit the original message
        # Use get_custom_embed from database.py
        updated_data = database.get_custom_embed(self.guild_id, self.embed_name) # Fetch saved data
        processed_embed = create_processed_embed(updated_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)

        # Edit the message that triggered the modal (which is the message containing the View)
        await interaction.response.edit_message(embed=processed_embed)


class AuthorEmbedModal(ui.Modal, title='Edit Embed Author'):
    author_name = ui.TextInput(label='Author Name', style=discord.TextStyle.short, required=False, max_length=256)
    author_icon_url = ui.TextInput(label='Author Icon URL (optional)', style=discord.TextStyle.short, required=False)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict = None):
        super().__init__()
        self.embed_name = embed_name
        self.guild_id = guild_id
        self.initial_data = initial_data or {} # Store initial data

        if 'author' in self.initial_data and isinstance(self.initial_data['author'], dict):
             self.author_name.default = self.initial_data['author'].get('name', '')
             self.author_icon_url.default = self.initial_data['author'].get('icon_url', '')


    async def on_submit(self, interaction: discord.Interaction):
        current_data = database.get_custom_embed(self.guild_id, self.embed_name) or {}

        author_name = self.author_name.value.strip() or None
        author_icon_url = self.author_icon_url.value.strip() or None

        if author_name:
             author_dict = {'name': author_name}
             if author_icon_url:
                 author_dict['icon_url'] = author_icon_url
             current_data['author'] = author_dict
        elif 'author' in current_data:
             del current_data['author']

        database.save_custom_embed(self.guild_id, self.embed_name, current_data)

        updated_data = database.get_custom_embed(self.guild_id, self.embed_name)
        processed_embed = create_processed_embed(updated_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)

        await interaction.response.edit_message(embed=processed_embed)


# --- Footer Embed Modal (Modified) ---
class FooterEmbedModal(ui.Modal, title='Edit Embed Footer'):
    """Modal for editing embed footer info: text, timestamp toggle."""
    footer_text = ui.TextInput(label='Footer Text', style=discord.TextStyle.short, required=False, max_length=2048)
    add_timestamp = ui.TextInput(label='Add Timestamp? (yes/no)', style=discord.TextStyle.short, required=False, max_length=3)

    def __init__(self, embed_name: str, guild_id: int, initial_data: dict = None):
        super().__init__()
        self.embed_name = embed_name
        self.guild_id = guild_id
        self.initial_data = initial_data or {} # Store initial data

        if 'footer' in self.initial_data and isinstance(self.initial_data['footer'], dict):
             self.footer_text.default = self.initial_data['footer'].get('text', '')
             timestamp_enabled = self.initial_data['footer'].get('timestamp', False)
             self.add_timestamp.default = 'yes' if timestamp_enabled else 'no'

    async def on_submit(self, interaction: discord.Interaction):
        current_data = database.get_custom_embed(self.guild_id, self.embed_name) or {}

        footer_text = self.footer_text.value.strip() or None
        add_timestamp_input = self.add_timestamp.value.strip().lower()

        timestamp_enabled = add_timestamp_input == 'yes'

        if footer_text:
             footer_dict = {'text': footer_text}
             # Store the boolean value for timestamp in the footer dict
             footer_dict['timestamp'] = timestamp_enabled # <-- Store True/False here
             current_data['footer'] = footer_dict
        elif 'footer' in current_data:
             del current_data['footer']

        database.save_custom_embed(self.guild_id, self.embed_name, current_data)

        updated_data = database.get_custom_embed(self.guild_id, self.embed_name)
        processed_embed = create_processed_embed(updated_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)

        await interaction.response.edit_message(embed=processed_embed)


# --- View with Buttons for Editing ---
# (EmbedEditView remains the same, it uses the Modals)

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

    @ui.button(label='Edit Basic Info', style=discord.ButtonStyle.primary)
    async def edit_basic_button(self, interaction: discord.Interaction, button: ui.Button):
        # Use get_custom_embed from database.py
        current_data = database.get_custom_embed(self.guild_id, self.embed_name)
        modal = BasicEmbedModal(self.embed_name, self.guild_id, current_data)
        await interaction.response.send_modal(modal)

    @ui.button(label='Edit Author', style=discord.ButtonStyle.primary)
    async def edit_author_button(self, interaction: discord.Interaction, button: ui.Button):
        # Use get_custom_embed from database.py
        current_data = database.get_custom_embed(self.guild_id, self.embed_name)
        modal = AuthorEmbedModal(self.embed_name, self.guild_id, current_data)
        await interaction.response.send_modal(modal)

    @ui.button(label='Edit Footer', style=discord.ButtonStyle.primary)
    async def edit_footer_button(self, interaction: discord.Interaction, button: ui.Button):
        # Use get_custom_embed from database.py
        current_data = database.get_custom_embed(self.guild_id, self.embed_name)
        modal = FooterEmbedModal(self.embed_name, self.guild_id, current_data)
        await interaction.response.send_modal(modal)


# --- Embed Cog Class ---
# (EmbedCog methods use database functions)

class EmbedCog(commands.Cog):
    """Cog for managing custom server embeds and using them."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        channel = guild.system_channel

        if channel is not None:
            # Use get_custom_embed from database.py
            welcome_embed_data = database.get_custom_embed(guild.id, "welcome")
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

        # Use get_custom_embed from database.py
        existing_embed = database.get_custom_embed(interaction.guild_id, name)
        if existing_embed:
             await interaction.response.send_message(f"An embed named '{name}' already exists. Use `/embed edit {name}` to modify it.", ephemeral=True)
             return

        initial_data = {}
        # Use save_custom_embed from database.py
        database.save_custom_embed(interaction.guild_id, name, initial_data)

        preview_embed = create_processed_embed(initial_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)
        edit_view = EmbedEditView(name, interaction.guild_id)

        await interaction.response.send_message(
            f"Editing embed '{name}'. Use the buttons below to modify different parts."
            f"\nVariables like {{user.mention}}, {{server.name}}, {{channel.name}}, {{user.avatar_url}}, {{user.nickname}} are supported."
            , embed=preview_embed, view=edit_view, ephemeral=True
        )


    @embed_group.command(name='edit', description='Edit an existing custom embed template.')
    @app_commands.describe(name='The name of the embed template to edit.')
    @commands.has_permissions(manage_guild=True)
    async def embed_edit(self, interaction: discord.Interaction, name: str):
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # Use get_custom_embed from database.py
        existing_data = database.get_custom_embed(interaction.guild_id, name)
        if existing_data is None:
            await interaction.response.send_message(f"No embed found with the name '{name}'.", ephemeral=True)
            return

        preview_embed = create_processed_embed(existing_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)
        edit_view = EmbedEditView(name, interaction.guild_id)

        await interaction.response.send_message(
            f"Editing embed '{name}'. Use the buttons below to modify different parts."
            f"\nVariables like {{user.mention}}, {{server.name}}, {{channel.name}}, {{user.avatar_url}}, {{user.nickname}} are supported."
             , embed=preview_embed, view=edit_view, ephemeral=True
        )


    @embed_group.command(name='list', description='List all custom embed templates for this server.')
    @commands.has_permissions(manage_guild=True)
    async def embed_list(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # Use get_all_custom_embed_names from database.py
        embed_names = database.get_all_custom_embed_names(interaction.guild_id)

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

        # Use get_custom_embed from database.py
        embed_data = database.get_custom_embed(interaction.guild_id, name)

        if embed_data is None:
            await interaction.response.send_message(f"No embed found with the name '{name}'.", ephemeral=True)
            return

        try:
            embed = create_processed_embed(embed_data, user=interaction.user, guild=interaction.guild, channel=interaction.channel)
            await interaction.response.send_message("Preview:", embed=embed)
        except Exception as e:
            print(f"Error creating embed from data for view: {e}")
            print(f"Problematic embed data: {embed_data}")
            await interaction.response.send_message(f"Could not create embed from data for '{name}'. Check bot logs for details.", ephemeral=True)


    @embed_group.command(name='remove', description='Delete a custom embed template.')
    @app_commands.describe(name='The name of the embed template to delete.')
    @commands.has_permissions(manage_guild=True)
    async def embed_remove(self, interaction: discord.Interaction, name: str):
        if interaction.guild_id is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        # Use delete_custom_embed from database.py
        deleted = database.delete_custom_embed(interaction.guild_id, name)

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