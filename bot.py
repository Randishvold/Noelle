import discord
import os
import json
from discord.ext import commands
from dotenv import load_dotenv
from discord import app_commands, ui
import asyncpg # Import asyncpg library

# Load environment variables from .env file if it exists (for local testing)
load_dotenv()

# Access the token from environment variables
TOKEN = os.getenv('DISCORD_TOKEN')
# Access the database URL from environment variables
# Railway automatically provides DATABASE_URL for PostgreSQL addons
DATABASE_URL = os.getenv('DATABASE_URL')

# Define Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Create a bot instance
bot = commands.Bot(command_prefix='!', intents=intents)

# Global variable to store the database connection pool
# We'll initialize this in on_ready
bot.db_pool = None

# --- Database Functions ---

async def create_embeds_table():
    """Creates the embeds table if it doesn't exist."""
    # Check if db_pool is initialized
    if bot.db_pool is None:
        print("Database pool not initialized!")
        return

    async with bot.db_pool.acquire() as connection:
        # Use connection to execute SQL commands
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS server_embeds (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                embed_name TEXT NOT NULL,
                embed_data TEXT NOT NULL, -- Store embed structure as JSON string
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (guild_id, embed_name) -- Ensure name is unique per guild
            )
        ''')
    print("Database table 'server_embeds' checked/created successfully.")

async def get_embed(guild_id: int, embed_name: str):
    """Retrieves an embed's data by name for a specific guild."""
    if bot.db_pool is None: return None
    async with bot.db_pool.acquire() as connection:
        return await connection.fetchrow(
            'SELECT embed_data FROM server_embeds WHERE guild_id = $1 AND embed_name = $2',
            guild_id, embed_name.lower() # Store/lookup names case-insensitively
        )

async def get_all_embed_names(guild_id: int):
    """Retrieves all embed names for a specific guild."""
    if bot.db_pool is None: return []
    async with bot.db_pool.acquire() as connection:
        rows = await connection.fetch(
            'SELECT embed_name FROM server_embeds WHERE guild_id = $1 ORDER BY embed_name',
            guild_id
        )
        return [row['embed_name'] for row in rows]

async def add_or_update_embed(guild_id: int, embed_name: str, embed_data: str):
    """Adds a new embed or updates an existing one."""
    if bot.db_pool is None: return False
    async with bot.db_pool.acquire() as connection:
        # Use INSERT ... ON CONFLICT to handle both add and update
        await connection.execute(
            '''
            INSERT INTO server_embeds (guild_id, embed_name, embed_data)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, embed_name)
            DO UPDATE SET embed_data = EXCLUDED.embed_data, updated_at = CURRENT_TIMESTAMP
            ''',
            guild_id, embed_name.lower(), embed_data
        )
    return True # Indicate success

async def delete_embed(guild_id: int, embed_name: str):
    """Deletes an embed by name for a specific guild."""
    if bot.db_pool is None: return False
    async with bot.db_pool.acquire() as connection:
        result = await connection.execute(
            'DELETE FROM server_embeds WHERE guild_id = $1 AND embed_name = $2',
            guild_id, embed_name.lower()
        )
        # asyncpg execute returns 'DELETE N' where N is the number of rows deleted
        return result == 'DELETE 1'

# --- Modals for Input ---

class EmbedModal(ui.Modal, title='Embed Data'):
    """Modal for adding or editing embed JSON data."""
    def __init__(self, existing_name: str = None, existing_data: str = None):
        super().__init__()
        self.existing_name = existing_name
        self.is_edit = existing_name is not None

        self.name_input = ui.TextInput(
            label="Embed Name",
            placeholder="Enter a unique name for this embed",
            max_length=50,
            default=existing_name,
            row=0,
            # Disable name editing if in edit mode
            disabled=self.is_edit
        )
        self.data_input = ui.TextInput(
            label="Embed JSON Data",
            style=discord.TextStyle.long, # Use long style for multi-line text
            placeholder="Paste your embed JSON here (e.g., from an online embed builder)",
            default=existing_data,
            required=True,
            row=1
        )
        self.add_item(self.name_input)
        self.add_item(self.data_input)

    async def on_submit(self, interaction: discord.Interaction):
        embed_name = self.name_input.value.strip()
        embed_data_string = self.data_input.value.strip()
        guild_id = interaction.guild_id

        if not embed_name:
             # This shouldn't happen if TextInput required=True, but as a safeguard
            await interaction.response.send_message("Embed name cannot be empty.", ephemeral=True)
            return

        # Validate JSON
        try:
            embed_data_json = json.loads(embed_data_string)
            # Basic check if it looks like embed data (optional but good practice)
            if not isinstance(embed_data_json, dict):
                 raise json.JSONDecodeError("Data is not a valid JSON object.", embed_data_string, 0)

        except json.JSONDecodeError as e:
            await interaction.response.send_message(f"Invalid JSON data provided: {e}", ephemeral=True)
            return
        except Exception as e:
             await interaction.response.send_message(f"An unexpected error occurred parsing JSON: {e}", ephemeral=True)
             return

        # Save to database
        success = await add_or_update_embed(guild_id, embed_name, embed_data_string)

        if success:
            action = "updated" if self.is_edit else "added"
            await interaction.response.send_message(f"Embed '{embed_name}' has been {action}.", ephemeral=True)
        else:
            await interaction.response.send_message("Failed to save embed.", ephemeral=True)

# --- Cog for Embed Commands ---

class EmbedCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="embed", description="Manage custom server embeds.")
    @app_commands.guild_only() # Ensure command is only used in a guild
    async def embed_group(self, interaction: discord.Interaction):
        # This function serves as the root for the command group.
        # Subcommands handle the actual logic.
        pass # This command group root doesn't need to do anything itself

    @embed_group.command(name="add", description="Add a new custom embed template.")
    @app_commands.guild_only()
    async def embed_add(self, interaction: discord.Interaction):
        """Prompts user to add a new embed via modal."""
        # Show the modal for adding a new embed
        await interaction.response.send_modal(EmbedModal())

    @embed_group.command(name="edit", description="Edit an existing custom embed template.")
    @app_commands.describe(name="The name of the embed to edit.")
    @app_commands.guild_only()
    async def embed_edit(self, interaction: discord.Interaction, name: str):
        """Prompts user to edit an existing embed via modal."""
        guild_id = interaction.guild_id
        embed_record = await get_embed(guild_id, name)

        if embed_record is None:
            await interaction.response.send_message(f"Embed '{name}' not found in this server.", ephemeral=True)
            return

        # Show the modal with existing data pre-filled
        await interaction.response.send_modal(EmbedModal(existing_name=name, existing_data=embed_record['embed_data']))

    @embed_group.command(name="view", description="View details or list all custom embed templates.")
    @app_commands.describe(name="Optional: The name of the embed to view details for.")
    @app_commands.guild_only()
    async def embed_view(self, interaction: discord.Interaction, name: str = None):
        """Views details of a specific embed or lists all embeds."""
        guild_id = interaction.guild_id

        if name:
            # View specific embed
            embed_record = await get_embed(guild_id, name)
            if embed_record is None:
                await interaction.response.send_message(f"Embed '{name}' not found in this server.", ephemeral=True)
                return

            embed_data_string = embed_record['embed_data']

            # Try to create a discord.Embed object and send a preview
            try:
                embed_json = json.loads(embed_data_string)
                # discord.Embed.from_dict can create an embed from a dictionary
                preview_embed = discord.Embed.from_dict(embed_json)
                # Send the preview embed and the JSON data (formatted)
                await interaction.response.send_message(
                    f"**Preview of embed '{name}':**",
                    embed=preview_embed,
                    file=discord.File(fp=json.dumps(embed_json, indent=2).encode('utf-8'), filename=f"{name}_embed.json"),
                    ephemeral=True # Send ephemerally so only the user sees the JSON file
                )
            except json.JSONDecodeError:
                 await interaction.response.send_message(f"Embed '{name}' contains invalid JSON.", ephemeral=True)
            except Exception as e:
                 # If preview fails, just send the raw JSON string
                 await interaction.response.send_message(
                     f"Could not generate embed preview for '{name}'. Raw JSON:\n```json\n{embed_data_string}\n```",
                     ephemeral=True
                )

        else:
            # List all embeds
            embed_names = await get_all_embed_names(guild_id)
            if not embed_names:
                await interaction.response.send_message("No custom embeds found in this server.", ephemeral=True)
            else:
                embed_list = "\n".join(f"- {name}" for name in embed_names)
                await interaction.response.send_message(
                    f"**Custom Embeds in this server:**\n{embed_list}",
                    ephemeral=True # Keep the list private
                )


    @embed_group.command(name="delete", description="Delete a custom embed template.")
    @app_commands.describe(name="The name of the embed to delete.")
    @app_commands.guild_only()
    async def embed_delete(self, interaction: discord.Interaction, name: str):
        """Deletes an embed by name."""
        guild_id = interaction.guild_id
        success = await delete_embed(guild_id, name)

        if success:
            await interaction.response.send_message(f"Embed '{name}' has been deleted.", ephemeral=True)
        else:
            # Could be not found or DB error
            await interaction.response.send_message(f"Could not delete embed '{name}'. It might not exist.", ephemeral=True)

    @embed_group.command(name="send", description="Send a custom embed to a channel.")
    @app_commands.describe(name="The name of the embed to send.", channel="The channel to send the embed to.")
    @app_commands.guild_only()
    @commands.has_permissions(manage_messages=True) # Require permission to manage messages or similar
    async def embed_send(self, interaction: discord.Interaction, name: str, channel: discord.TextChannel):
        """Sends a stored embed to a specified channel."""
        guild_id = interaction.guild_id
        embed_record = await get_embed(guild_id, name)

        if embed_record is None:
            await interaction.response.send_message(f"Embed '{name}' not found in this server.", ephemeral=True)
            return

        embed_data_string = embed_record['embed_data']

        # Try to create a discord.Embed object and send it
        try:
            embed_json = json.loads(embed_data_string)
            send_embed = discord.Embed.from_dict(embed_json)
            await channel.send(embed=send_embed)
            await interaction.response.send_message(f"Embed '{name}' sent to {channel.mention}.", ephemeral=True)

        except json.JSONDecodeError:
            await interaction.response.send_message(f"Embed '{name}' contains invalid JSON and cannot be sent.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred while sending the embed: {e}", ephemeral=True)

    # Error handler for embed_send permissions
    @embed_send.error
    async def embed_send_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("You don't have permission to use this command (requires Manage Messages).", ephemeral=True)
        else:
            await interaction.response.send_message(f"An error occurred: {error}", ephemeral=True)


# --- Bot Events ---

@bot.event
async def on_ready():
    """Event triggered when the bot is ready and connected."""
    print(f'{bot.user} is connected to Discord!')
    print(f'Connected to {len(bot.guilds)} guilds.')

    # Initialize database pool and create table
    if DATABASE_URL is None:
        print("ERROR: DATABASE_URL environment variable not found.")
        print("Please add the PostgreSQL addon in Railway.")
    else:
        try:
            # Create a database connection pool
            bot.db_pool = await asyncpg.create_pool(DATABASE_URL)
            print("Database pool created successfully.")
            await create_embeds_table()
        except Exception as e:
            print(f"Error connecting to database or creating table: {e}")
            # You might want to exit or handle this error appropriately

    # Add the EmbedCommands Cog
    try:
        await bot.add_cog(EmbedCommands(bot))
        print("EmbedCommands cog added successfully.")
    except Exception as e:
         print(f"Failed to add EmbedCommands cog: {e}")


    # Sync Slash Commands - Needs to happen *after* adding the cog
    # Note: Syncing can happen here or after cog addition, but ensure the cog is added
    # before syncing the commands within it.
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # Optional: Change bot status
    await bot.change_presence(activity=discord.Game(name="managing embeds!"))


@bot.event
async def on_member_join(member):
    """Event triggered when a new member joins the guild."""
    guild = member.guild
    channel = guild.system_channel # Or get a specific channel by ID

    if channel is not None:
        # Basic welcome message (you could modify this to use a *stored* welcome embed later!)
        embed = discord.Embed(
            title=f"Welcome to {guild.name}!",
            description=f"Hello {member.mention}, welcome aboard!",
            color=discord.Color.green()
        )
        if member.avatar:
             embed.set_thumbnail(url=member.avatar.url)
        await channel.send(embed=embed)


# --- Run Bot ---

if __name__ == "__main__":
    if TOKEN is None:
        print("ERROR: Environment variable 'DISCORD_TOKEN' not found.")
        print("Make sure you have set the DISCORD_TOKEN variable:")
        print("- Locally: Create a .env file with DISCORD_TOKEN=YOUR_BOT_TOKEN")
        print("- On Railway: Add a variable with NAME='DISCORD_TOKEN' and VALUE='YOUR_BOT_TOKEN'.")
    elif DATABASE_URL is None and not os.path.exists('.env'): # Check for DB URL unless running purely local without .env
         # This check helps remind you about the DB on Railway
         print("WARNING: DATABASE_URL environment variable not found.")
         print("Ensure the PostgreSQL addon is linked/added in Railway.")
         print("Proceeding, but database features will not work.")
         bot.run(TOKEN) # Run bot without database functionality
    else:
        print("Starting bot...")
        # Bot run will block until bot is disconnected
        bot.run(TOKEN)