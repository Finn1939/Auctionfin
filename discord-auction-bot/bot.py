import os
import discord
from discord.ext import commands
import motor.motor_asyncio

# 1. Get ENV variables
TOKEN = os.getenv('DISCORD_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
PREFIX = os.getenv('PREFIX', '!')  # Default to '!' 

# 2. Configure bot
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# 3. Connect to MongoDB
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = mongo_client.auction_bot

# 4. Load cogs (make sure cogs folder exists!)
@bot.event
async def on_ready():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            await bot.load_extension(f'cogs.{filename[:-3]}')
    print(f'Logged in as {bot.user}')

# 5. Start bot
if __name__ == "__main__":
    bot.run(TOKEN)
