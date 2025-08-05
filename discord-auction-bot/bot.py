import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
import asyncio
from datetime import datetime, timedelta
import os
import json
import threading
import time
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
import uvicorn

# Add to imports
import os
import pathlib
# Template initialization
try:
    # Get absolute path to templates directory
    templates_path = pathlib.Path(__file__).parent / "templates"
    print(f"Looking for templates at: {templates_path}")
    
    # Verify templates directory exists
    if not templates_path.exists():
        os.makedirs(templates_path, exist_ok=True)
        print(f"Created templates directory at: {templates_path}")
    
    # Verify dashboard.html exists
    dashboard_path = templates_path / "dashboard.html"
    if not dashboard_path.exists():
        with open(dashboard_path, "w") as f:
            f.write("<h1>Auction Dashboard</h1><p>Placeholder - create your dashboard.html</p>")
        print(f"Created placeholder dashboard.html at: {dashboard_path}")
    
    templates = Jinja2Templates(directory=str(templates_path))
    print(f"Templates initialized successfully with {len(os.listdir(templates_path))} files")
    
except Exception as e:
    print(f"CRITICAL TEMPLATE ERROR: {str(e)}")
    # Fallback to simple response
    @app.get("/")
    async def dashboard_fallback(request: Request):
        return HTMLResponse("""
        <h1>Auction Dashboard</h1>
        <p>Template system failed to initialize. Check logs.</p>
        <p>Path: {}</p>
        <p>Error: {}</p>
        """.format(templates_path, str(e)))
# =====================================================
# PHASE 1: MINIMAL FASTAPI SETUP (IMMEDIATE START)
# =====================================================
app = FastAPI()
start_time = time.time()

# Health check endpoint - responds immediately
@app.get("/health")
async def health_check():
    """Ultra-fast health check response"""
    return PlainTextResponse("ok")

# =====================================================
# PHASE 2: ENVIRONMENT VARIABLES AND DISCORD SETUP
# =====================================================
TOKEN = os.getenv('DISCORD_TOKEN')
PORT = int(os.getenv('PORT', 8000))

if not TOKEN:
    print("WARNING: DISCORD_TOKEN not set. Bot will not start")
    bot = None
else:
    # Initialize Discord bot
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    bot = commands.Bot(command_prefix='!', intents=intents)

# =====================================================
# PHASE 3: AUCTION DATABASE SETUP
# =====================================================
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

auctions_db = load_auctions()

# =====================================================
# PHASE 4: DISCORD BOT FUNCTIONALITY
# =====================================================
if bot:
    class AuctionCreationModal(Modal, title='Create Auction'):
        def __init__(self):
            super().__init__(timeout=None)
            self.item_title = TextInput(
                label="Item/Service Title",
                placeholder="What are you offering?",
                max_length=100
            )
            self.item_description = TextInput(
                label="Description",
                style=discord.TextStyle.paragraph,
                placeholder="Detailed description...",
                required=False
            )
            self.add_item(self.item_title)
            self.add_item(self.item_description)

        async def on_submit(self, interaction: discord.Interaction):
            # Create auction ticket
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True),
                discord.utils.get(interaction.guild.roles, name="Admin"): discord.PermissionOverwrite(read_messages=True)
            }
            
            channel = await interaction.guild.create_text_channel(
                name=f"auction-{self.item_title.value[:20]}",
                overwrites=overwrites
            )
            
            auctions_db[str(channel.id)] = {
                "creator": interaction.user.id,
                "title": self.item_title.value,
                "description": self.item_description.value,
                "status": "pending",
                "bids": [],
                "media": [],
                "guild_id": interaction.guild.id
            }
            save_auctions(auctions_db)
            
            await interaction.response.send_message(
                f"Auction ticket created: {channel.mention}",
                ephemeral=True
            )
            
            # Send initial auction message
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
        """Setup auction creation button"""
        view = AuctionView()
        embed = discord.Embed(
            title="Auction System",
            description="Click the button below to create a new auction",
            color=0xBB86FC
        )
        await ctx.send(embed=embed, view=view)

    # ... [OTHER BOT COMMANDS AND EVENTS - KEEP YOUR EXISTING CODE HERE] ...

# =====================================================
# PHASE 5: DASHBOARD ROUTES
# =====================================================
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    try:
        templates = Jinja2Templates(directory="templates")
        return templates.TemplateResponse(
            "dashboard.html",
            {"request": request, "auctions": list(auctions_db.values())}
        )
    except Exception as e:
        return HTMLResponse(f"<h1>Auction Dashboard</h1><p>Loading data... {str(e)}</p>")

@app.get("/auctions")
async def get_auctions():
    return JSONResponse(list(auctions_db.values()))

# =====================================================
# PHASE 6: STARTUP SEQUENCE
# =====================================================
def start_bot():
    """Start Discord bot in a background thread"""
    if TOKEN and bot:
        print("Starting Discord bot...")
        bot.run(TOKEN)

if __name__ == "__main__":
    # Start Discord bot in background thread
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    # Start web server in main thread
    print(f"Starting web server on port {PORT}")
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    server.run()

@app.get("/debug")
async def debug_info(request: Request):
    """Debug endpoint to verify file structure"""
    try:
        # List files in templates directory
        template_files = os.listdir(templates_path) if templates_path.exists() else []
        
        # List files in root directory
        root_files = os.listdir(pathlib.Path(__file__).parent)
        
        return HTMLResponse(f"""
        <h1>Debug Information</h1>
        <h2>Template Path: {templates_path}</h2>
        <h3>Template Files ({len(template_files)}):</h3>
        <ul>
            {"".join(f"<li>{f}</li>" for f in template_files)}
        </ul>
        <h3>Root Directory Files ({len(root_files)}):</h3>
        <ul>
            {"".join(f"<li>{f}</li>" for f in root_files)}
        </ul>
        <h3>Environment Variables:</h3>
        <ul>
            <li>PORT: {os.getenv('PORT', '8000')}</li>
            <li>DISCORD_TOKEN: {os.getenv('DISCORD_TOKEN', 'Not set')[:5]}...</li>
        </ul>
        """)
    except Exception as e:
        return HTMLResponse(f"<h1>Debug Error</h1><p>{str(e)}</p>")
