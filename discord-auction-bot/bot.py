import discord
from discord.ext import commands
import os
import asyncio
import aiohttp
import time
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID'))
API_URL = os.getenv('API_URL', 'http://localhost:5000')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('discord_bot')

# Define intents
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Top-level event handler
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="auctions"))

class AuctionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auction_channel_id = CHANNEL_ID
        self.guild_id = GUILD_ID
        self.api_url = API_URL
        self.session = aiohttp.ClientSession()
        self.active_auctions = {}
        self.bid_tasks = {}

    async def get_user_balance(self, user_id):
        try:
            async with self.session.get(f"{self.api_url}/balance/{user_id}") as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('balance', 0)
                else:
                    logger.error(f"Failed to get balance for user {user_id}: {response.status}")
                    return 0
        except Exception as e:
            logger.error(f"Error getting balance: {str(e)}")
            return 0

    async def update_user_balance(self, user_id, amount):
        try:
            async with self.session.post(f"{self.api_url}/update_balance", json={"user_id": user_id, "amount": amount}) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Error updating balance: {str(e)}")
            return False

    async def record_transaction(self, user_id, amount, transaction_type, description):
        try:
            async with self.session.post(f"{self.api_url}/record_transaction", json={
                "user_id": user_id,
                "amount": amount,
                "type": transaction_type,
                "description": description
            }) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Error recording transaction: {str(e)}")
            return False

    async def get_auction_data(self):
        try:
            async with self.session.get(f"{self.api_url}/auctions") as response:
                if response.status == 200:
                    return await response.json()
                return []
        except Exception as e:
            logger.error(f"Error fetching auctions: {str(e)}")
            return []

    async def create_auction(self, item, start_price, duration_minutes, image_url=None):
        try:
            async with self.session.post(f"{self.api_url}/create_auction", json={
                "item": item,
                "start_price": start_price,
                "duration_minutes": duration_minutes,
                "image_url": image_url
            }) as response:
                if response.status == 201:
                    return await response.json()
                return None
        except Exception as e:
            logger.error(f"Error creating auction: {str(e)}")
            return None

    async def place_bid(self, auction_id, user_id, amount):
        try:
            async with self.session.post(f"{self.api_url}/place_bid", json={
                "auction_id": auction_id,
                "user_id": user_id,
                "amount": amount
            }) as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Error placing bid: {str(e)}")
            return False

    async def get_auction_details(self, auction_id):
        try:
            async with self.session.get(f"{self.api_url}/auction/{auction_id}") as response:
                if response.status == 200:
                    return await response.json()
                return None
        except Exception as e:
            logger.error(f"Error getting auction details: {str(e)}")
            return None

    async def end_auction(self, auction_id):
        try:
            async with self.session.post(f"{self.api_url}/end_auction/{auction_id}") as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Error ending auction: {str(e)}")
            return False

    async def auction_countdown(self, auction_id, duration):
        await asyncio.sleep(duration * 60)
        auction = await self.get_auction_details(auction_id)
        if auction and auction['status'] == 'active':
            await self.end_auction(auction_id)
            auction = await self.get_auction_details(auction_id)
            channel = self.bot.get_channel(self.auction_channel_id)
            if auction['highest_bidder']:
                winner = self.bot.get_user(int(auction['highest_bidder']))
                winner_message = f"🎉 Congratulations {winner.mention}! You won the auction for **{auction['item']}** with a bid of **${auction['current_price']}**!"
                
                # Create embed
                embed = discord.Embed(
                    title=f"Auction Ended: {auction['item']}",
                    description=f"Winner: {winner.mention}\nWinning Bid: ${auction['current_price']}",
                    color=discord.Color.green()
                )
                if auction.get('image_url'):
                    embed.set_image(url=auction['image_url'])
                
                await channel.send(winner_message, embed=embed)
                
                # Deduct balance from winner
                await self.update_user_balance(str(winner.id), -auction['current_price'])
                await self.record_transaction(
                    str(winner.id),
                    -auction['current_price'],
                    'debit',
                    f"Won auction for {auction['item']}"
                )
            else:
                await channel.send(f"⚠️ Auction for **{auction['item']}** ended with no bids.")
            del self.active_auctions[auction_id]
            if auction_id in self.bid_tasks:
                self.bid_tasks[auction_id].cancel()
                del self.bid_tasks[auction_id]

    @commands.command(name='startauction', help='Start a new auction! Usage: !startauction "Item Name" start_price duration_minutes [image_url]')
    @commands.has_role('Auction Manager')
    async def start_auction(self, ctx, item: str, start_price: float, duration_minutes: int, image_url: str = None):
        if duration_minutes <= 0:
            await ctx.send("Duration must be greater than 0 minutes.")
            return

        auction = await self.create_auction(item, start_price, duration_minutes, image_url)
        if auction:
            channel = self.bot.get_channel(self.auction_channel_id)
            
            # Create embed
            embed = discord.Embed(
                title=f"New Auction: {item}",
                description=f"Starting Price: **${start_price}**\nDuration: **{duration_minutes} minutes**",
                color=discord.Color.blue()
            )
            if image_url:
                embed.set_image(url=image_url)
            
            message = await channel.send(
                f"🚨 New auction started! 🚨\n"
                f"Item: **{item}**\n"
                f"Starting price: **${start_price}**\n"
                f"Auction ends in {duration_minutes} minutes!\n"
                f"Type `!bid {auction['id']} <amount>` to place a bid!",
                embed=embed
            )
            
            # Store auction info with correct syntax
            self.active_auctions[auction['id']] = {
                'message_id': message.id,
                'end_time': time.time() + duration_minutes * 60
            }
            self.bid_tasks[auction['id']] = asyncio.create_task(self.auction_countdown(auction['id'], duration_minutes))
            await ctx.send(f"Auction started successfully! Check <#{self.auction_channel_id}>")
        else:
            await ctx.send("Failed to start auction. Please try again.")

    @commands.command(name='bid', help='Place a bid on an auction! Usage: !bid auction_id amount')
    async def place_bid_command(self, ctx, auction_id: int, amount: float):
        user_id = str(ctx.author.id)
        auction = await self.get_auction_details(auction_id)
        
        if not auction:
            await ctx.send("Auction not found.")
            return
        
        if auction['status'] != 'active':
            await ctx.send("This auction is no longer active.")
            return
        
        if amount <= auction['current_price']:
            await ctx.send(f"Your bid must be higher than the current price of ${auction['current_price']}.")
            return
        
        balance = await self.get_user_balance(user_id)
        if balance < amount:
            await ctx.send(f"You don't have enough funds. Your balance is ${balance}.")
            return
        
        if await self.place_bid(auction_id, user_id, amount):
            # Update auction details
            auction['current_price'] = amount
            auction['highest_bidder'] = user_id
            
            channel = self.bot.get_channel(self.auction_channel_id)
            try:
                message = await channel.fetch_message(self.active_auctions[auction_id]['message_id'])
                
                # Update embed
                embed = message.embeds[0] if message.embeds else discord.Embed()
                embed.description = (
                    f"Current Price: **${amount}**\n"
                    f"Highest Bidder: <@{user_id}>\n"
                    f"Time Remaining: **{int((self.active_auctions[auction_id]['end_time'] - time.time()) // 60)} minutes**"
                )
                
                await message.edit(content=f"🚨 New bid placed! Current price for **{auction['item']}**: **${amount}** by <@{user_id}>", embed=embed)
            except Exception as e:
                logger.error(f"Error updating auction message: {str(e)}")
            
            await ctx.send(f"✅ Bid of **${amount}** placed successfully for **{auction['item']}**!")
        else:
            await ctx.send("Failed to place bid. Please try again.")

    @commands.command(name='balance', help='Check your balance')
    async def check_balance(self, ctx):
        balance = await self.get_user_balance(str(ctx.author.id))
        await ctx.send(f"Your current balance is **${balance}**")

    @commands.command(name='addfunds', help='Add funds to your account')
    async def add_funds(self, ctx, amount: float):
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return
        
        if await self.update_user_balance(str(ctx.author.id), amount):
            await self.record_transaction(
                str(ctx.author.id),
                amount,
                'credit',
                "Added funds"
            )
            await ctx.send(f"✅ **${amount}** added to your account!")
        else:
            await ctx.send("Failed to add funds. Please try again.")

    @commands.command(name='active', help='List active auctions')
    async def list_active_auctions(self, ctx):
        auctions = await self.get_auction_data()
        active_auctions = [a for a in auctions if a['status'] == 'active']
        
        if not active_auctions:
            await ctx.send("No active auctions currently.")
            return
        
        embed = discord.Embed(title="Active Auctions", color=discord.Color.blue())
        for auction in active_auctions:
            time_left = int((self.active_auctions[auction['id']]['end_time'] - time.time()) // 60)
            embed.add_field(
                name=f"Auction #{auction['id']}: {auction['item']}",
                value=(
                    f"Current Price: ${auction['current_price']}\n"
                    f"Highest Bidder: <@{auction['highest_bidder']}>\n"
                    f"Time Left: {time_left} minutes\n"
                    f"Bid with `!bid {auction['id']} <amount>`"
                ),
                inline=False
            )
        await ctx.send(embed=embed)

    @commands.command(name='forceend', help='Force end an auction')
    @commands.has_role('Auction Manager')
    async def force_end_auction(self, ctx, auction_id: int):
        if await self.end_auction(auction_id):
            if auction_id in self.bid_tasks:
                self.bid_tasks[auction_id].cancel()
                del self.bid_tasks[auction_id]
            await ctx.send(f"Auction #{auction_id} ended successfully.")
        else:
            await ctx.send("Failed to end auction.")

    @commands.command(name='helpauction', help='Show auction commands')
    async def auction_help(self, ctx):
        embed = discord.Embed(title="Auction Bot Commands", color=discord.Color.blue())
        embed.add_field(name="!startauction", value="Start a new auction (Auction Managers only)", inline=False)
        embed.add_field(name="!bid <auction_id> <amount>", value="Place a bid on an auction", inline=False)
        embed.add_field(name="!balance", value="Check your balance", inline=False)
        embed.add_field(name="!addfunds <amount>", value="Add funds to your account", inline=False)
        embed.add_field(name="!active", value="List active auctions", inline=False)
        embed.add_field(name="!helpauction", value="Show this help message", inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AuctionCog(bot))

# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)
