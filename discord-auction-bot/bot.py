import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
import asyncio
from datetime import datetime, timedelta
import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
# ... other imports ...
from fastapi.templating import Jinja2Templates
import uvicorn

# Initialize FastAPI first
app = FastAPI()

# Verify templates directory exists
try:
    os.listdir("templates")
    templates = Jinja2Templates(directory="templates")
except FileNotFoundError:
    print("ERROR: templates directory not found!")
    # Create it if missing in production?
    os.makedirs("templates", exist_ok=True)
    templates = Jinja2Templates(directory="templates")

# Load environment variables
TOKEN = os.getenv('DISCORD_TOKEN')
PORT = int(os.getenv('PORT', 8000))

if not TOKEN:
    raise ValueError("DISCORD_TOKEN not set in environment variables")

# Initialize Discord bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Database setup
DB_FILE = "auctions.json"
bidders_role = "Bidders"

def load_auctions():
    try:
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_auctions(auctions):
    with open(DB_FILE, 'w') as f:
        json.dump(auctions, f, indent=2)

# CORRECTED LINE (removed extra parenthesis)
auctions_db = load_auctions()
        
        await interaction.response.send_message(
            f"Auction ticket created: {channel.mention}",
            ephemeral=True
        )
        
        embed = discord.Embed(
            title=f"New Auction: {self.item_title.value}",
            description=self.item_description.value,
            color=0xBB86FC
        )
        embed.set_footer(text="Waiting for admin approval...")
        await channel.send(embed=embed)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="Auctions"
    ))
    
    bot.add_view(AuctionView())

class AuctionView(View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @discord.ui.button(
        label="Create Auction", 
        style=discord.ButtonStyle.primary,
        custom_id="create_auction"
    )
    async def create_auction(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AuctionCreationModal())

@bot.command()
@commands.has_role('Admin')
async def setup(ctx):
    view = AuctionView()
    embed = discord.Embed(
        title="Auction System",
        description="Click the button below to create a new auction",
        color=0xBB86FC
    )
    await ctx.send(embed=embed, view=view)

@bot.command()
@commands.has_role('Admin')
async def start_auction(ctx, duration: str = "30m"):
    try:
        time_units = {'m': 60, 'h': 3600, 'd': 86400}
        unit = duration[-1]
        value = int(duration[:-1])
        seconds = value * time_units[unit]
        
        auction = auctions_db.get(str(ctx.channel.id))
        if not auction:
            await ctx.send("❌ This channel is not an active auction ticket")
            return
            
        auction["status"] = "active"
        auction["end_time"] = (datetime.now() + timedelta(seconds=seconds)).isoformat()
        save_auctions(auctions_db)
        
        bidder_role = discord.utils.get(ctx.guild.roles, name=bidders_role)
        if bidder_role:
            await ctx.channel.set_permissions(
                bidder_role,
                read_messages=True,
                send_messages=True
            )
        else:
            await ctx.send(f"❌ Role '{bidders_role}' not found. Please create it.")
            return
        
        end_time = datetime.fromisoformat(auction["end_time"])
        embed = discord.Embed(
            title=f"🚀 Auction Started: {auction['title']}",
            description=f"Bidding open for {duration}\n\n{auction['description']}",
            color=0x00FF00
        )
        embed.add_field(
            name="How to Bid",
            value="Type your bid in chat or react with 💰",
            inline=False
        )
        embed.set_footer(text=f"Auction ends at {end_time.strftime('%Y-%m-%d %H:%M UTC')}")
        
        await ctx.send(embed=embed)
        
        await asyncio.sleep(seconds)
        await end_auction(ctx.channel)
        
    except Exception as e:
        await ctx.send(f"❌ Error starting auction: {str(e)}")

async def end_auction(channel):
    auction = auctions_db.get(str(channel.id))
    if not auction or auction["status"] != "active":
        return
        
    auction["status"] = "ended"
    save_auctions(auctions_db)
    
    bidder_role = discord.utils.get(channel.guild.roles, name=bidders_role)
    if bidder_role:
        await channel.set_permissions(
            bidder_role,
            send_messages=False
        )
    
    winner = None
    if auction["bids"]:
        winner = auction["bids"][-1]
    
    embed = discord.Embed(
        title=f"⏰ Auction Ended: {auction['title']}",
        color=0xFF0000
    )
    
    if winner:
        winner_user = await bot.fetch_user(winner["bidder"])
        embed.add_field(
            name="🏆 Highest Bid",
            value=f"{winner_user.mention} with:\n{winner.get('offer', 'No details')}",
            inline=False
        )
        
        creator = await bot.fetch_user(auction["creator"])
        overwrites = {
            channel.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            winner_user: discord.PermissionOverwrite(read_messages=True),
            creator: discord.PermissionOverwrite(read_messages=True)
        }
        
        transaction_channel = await channel.guild.create_text_channel(
            name=f"transaction-{auction['title'][:15]}",
            overwrites=overwrites
        )
        
        embed.add_field(
            name="💼 Next Steps",
            value=f"Complete transaction in {transaction_channel.mention}",
            inline=False
        )
        
        transaction_embed = discord.Embed(
            title=f"Transaction for: {auction['title']}",
            description=f"**Seller**: {creator.mention}\n**Buyer**: {winner_user.mention}",
            color=0xBB86FC
        )
        transaction_embed.add_field(
            name="Agreed Terms",
            value=winner.get('offer', 'No details provided'),
            inline=False
        )
        await transaction_channel.send(
            content=f"{creator.mention} {winner_user.mention}",
            embed=transaction_embed
        )
    else:
        embed.description = "No bids were placed."
    
    await channel.send(embed=embed)

@bot.command()
@commands.has_role('Admin')
async def extend(ctx, duration: str):
    try:
        auction = auctions_db.get(str(ctx.channel.id))
        if not auction or auction["status"] != "active":
            await ctx.send("❌ No active auction in this channel")
            return
            
        time_units = {'m': 60, 'h': 3600, 'd': 86400}
        unit = duration[-1]
        value = int(duration[:-1])
        seconds = value * time_units[unit]
        
        end_time = datetime.fromisoformat(auction["end_time"]) + timedelta(seconds=seconds)
        auction["end_time"] = end_time.isoformat()
        save_auctions(auctions_db)
        
        await ctx.send(f"⏳ Auction extended by {duration}. New end time: {end_time.strftime('%H:%M UTC')}")
    except Exception as e:
        await ctx.send(f"❌ Error extending auction: {str(e)}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
        
    channel_data = auctions_db.get(str(message.channel.id))
    if channel_data and channel_data["status"] == "active":
        bid = {
            "bidder": message.author.id,
            "offer": message.content,
            "timestamp": datetime.now().isoformat(),
            "value": None
        }
        
        channel_data["bids"].append(bid)
        save_auctions(auctions_db)
        await message.add_reaction("💰")
        
    await bot.process_commands(message)

@bot.event
async def on_raw_reaction_add(payload):
    channel_data = auctions_db.get(str(payload.channel_id))
    if (channel_data and 
        channel_data["status"] == "active" and
        payload.emoji.name == "💰" and
        payload.member and payload.member.id != bot.user.id):
        
        channel = bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        
        bid = {
            "bidder": payload.user_id,
            "offer": f"Reaction to message: {message.content[:50]}...",
            "timestamp": datetime.now().isoformat(),
            "value": None
        }
        
        channel_data["bids"].append(bid)
        save_auctions(auctions_db)
        await channel.send(f"💰 <@{payload.user_id}> placed a bid via reaction!")

# FastAPI Routes
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "auctions": list(auctions_db.values())}
    )

@app.get("/auctions")
async def get_auctions():
    return JSONResponse(list(auctions_db.values()))

# Combined startup
async def run_bot():
    await bot.start(TOKEN)

async def run_webserver():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await asyncio.gather(
        run_bot(),
        run_webserver()
    )

if __name__ == "__main__":
    asyncio.run(main())

# Combined startup
async def run_bot():
    await bot.start(TOKEN)

async def run_webserver():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    # Create a new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Run both services concurrently
        loop.run_until_complete(asyncio.gather(
            run_bot(),
            run_webserver()
        ))
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        loop.close()
