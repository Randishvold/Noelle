import discord
import os
from discord.ext import commands

# Define Intents
# Pastikan intents yang diaktifkan di portal developer juga diaktifkan di kode
intents = discord.Intents.default()
intents.message_content = True # WAJIB jika bot perlu membaca isi pesan
intents.members = True # Berguna untuk fitur member/server
intents.presences = True # Berguna untuk status user/bot

# Create a bot instance
# prefix='!' artinya perintah bot diawali dengan '!' contoh: !ping
bot = commands.Bot(command_prefix='!', intents=intents)

# Event: Bot siap
@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Guilds connected: {len(bot.guilds)}') # Menampilkan jumlah server tempat bot bergabung

    # Mengubah status bot (opsional)
    await bot.change_presence(activity=discord.Game(name="with server utilities"))

# Event: Menyambut member baru (contoh utilitas sederhana)
@bot.event
async def on_member_join(member):
    guild = member.guild
    if guild.system_channel is not None:
        await guild.system_channel.send(f'Welcome {member.mention} to the {guild.name} server!')

# Command: Ping
# Ketika user mengetik '!ping'
@bot.command(name='ping', help='Responds with pong!')
async def ping(ctx):
    await ctx.send('Pong!')

# Command: Hello
# Ketika user mengetik '!hello'
@bot.command(name='hello', help='Says hello!')
async def hello(ctx):
    await ctx.send(f'Hello {ctx.author.mention}!')

# Jalankan bot
if __name__ == "__main__":
    if DC_TOKEN is None:
        print("Error: DISCORD_TOKEN not found in environment variables!")
    else:
        bot.run(os.environ["DC_TOKEN"])