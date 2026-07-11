import discord
from discord.ext import commands
import random
import asyncio
import time

boom_games = {}
stopwatch_games = {}

# =========================
# BOOM GAME VIEW
# =========================

class RiskView(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=300)
        self.player = player
        self.score = random.randint(1,10)
        self.last_roll = self.score
        self.booms = 0
        self.message = None

    def embed(self,title="🎲 Risk It!",color=discord.Color.blue()):
        e=discord.Embed(title=title,color=color)
        e.add_field(name="Current Score",value=str(self.score),inline=True)
        e.add_field(name="Last Roll",value=str(self.last_roll),inline=True)
        e.add_field(name="💥 BOOMs Next Roll",value=str(self.booms),inline=False)
        return e

    async def animate(self,interaction):
        frames=[
            "🎲 Rolling...\n⬜⬜🟩⬜💥",
            "🎲 Rolling...\n💥⬜⬜🟩⬜",
            "🎲 Rolling...\n⬜💥⬜⬜🟩",
            "🎲 Rolling...\n🟩⬜💥⬜⬜",
            "🎲 Rolling...\n⬜🟩⬜💥⬜",
        ]
        for f in frames:
            await interaction.edit_original_response(
                embed=discord.Embed(description=f,color=discord.Color.orange()),
                view=self
            )
            await asyncio.sleep(0.25)

    @discord.ui.button(label="🎲 Risk",style=discord.ButtonStyle.green)
    async def risk(self,interaction:discord.Interaction,button:discord.ui.Button):
        if interaction.user.id!=self.player.id:
            await interaction.response.send_message("This isn't your game!",ephemeral=True)
            return
        await interaction.response.defer()
        await self.animate(interaction)
        wheel=list(range(1,11))+["BOOM"]*self.booms
        result=random.choice(wheel)
        if result=="BOOM":
            self.score=0
            for c in self.children: c.disabled=True
            await interaction.edit_original_response(
                embed=discord.Embed(title="💥 BOOM!",description="You lost everything!\nFinal Score: **0**",color=discord.Color.red()),
                view=self
            )
            boom_games.pop(self.player.id,None)
            return
        self.last_roll=result
        self.score+=result
        self.booms+=1
        await interaction.edit_original_response(embed=self.embed(),view=self)

    @discord.ui.button(label="💰 Keep",style=discord.ButtonStyle.blurple)
    async def keep(self,interaction:discord.Interaction,button:discord.ui.Button):
        if interaction.user.id!=self.player.id:
            await interaction.response.send_message("This isn't your game!",ephemeral=True)
            return
        for c in self.children: c.disabled=True
        await interaction.response.edit_message(
            embed=discord.Embed(title="🏆 You Kept Your Score!",description=f"Final Score: **{self.score}**",color=discord.Color.green()),
            view=self
        )
        boom_games.pop(self.player.id,None)

    async def on_timeout(self):
        for c in self.children: c.disabled=True
        if self.message:
            try:
                await self.message.edit(
                    embed=discord.Embed(title="⌛ Game Timed Out",color=discord.Color.dark_grey()),
                    view=self)
            except:
                pass
        boom_games.pop(self.player.id,None)

# =========================
# GAMES COG
# =========================

class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="boom")
    async def boom(self, ctx):
        if ctx.author.id in boom_games:
            await ctx.send("You already have a game running!")
            return
        view = RiskView(ctx.author)
        msg = await ctx.send(embed=view.embed(), view=view)
        view.message = msg
        boom_games[ctx.author.id] = view

    @commands.command(name="stopwatch")
    async def stopwatch(self, ctx):

        # Start stopwatch
        if ctx.author.id not in stopwatch_games:

            stopwatch_games[ctx.author.id] = time.perf_counter()

            await ctx.send(
                f"⏱️ {ctx.author.mention} Stopwatch started!"
            )
            return

        # Stop stopwatch
        start_time = stopwatch_games.pop(ctx.author.id)

        elapsed = time.perf_counter() - start_time

        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)

        # Milliseconds (thousandths)
        milliseconds = int((elapsed * 1000) % 1000)

        # Dynamic time formatting
        if hours > 0:
            formatted_time = (
                f"{hours}:{minutes:02}:{seconds:02}.{milliseconds:03}"
            )

        elif minutes > 0:
            formatted_time = (
                f"{minutes}:{seconds:02}.{milliseconds:03}"
            )

        else:
            formatted_time = (
                f"{seconds}.{milliseconds:03}"
            )

        await ctx.send(
            f"⏱️ {ctx.author.mention} Stopwatch stopped!\n"
            f"**Final Time: {formatted_time}**"
        )

async def setup(bot):
    await bot.add_cog(Games(bot))
