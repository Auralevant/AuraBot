"""
GraspingStraw cog
------------------
!graspingstraw   -> opens a 20s lobby with a Join button
!claim <LETTER>  -> claims a math problem during the claiming phase

Rules:
  - Round problems = (alive players) + 1
  - Each round, players have 20s to !claim a lettered problem (one claim
    per player, one player per problem).
  - After 20s: anyone who didn't claim, OR who claimed the problem with the
    highest answer, OR who claimed the problem with the lowest answer,
    loses a life. Ties on highest/lowest hit everyone who claimed a tied
    problem.
  - 3 lives lost = eliminated. Last player standing wins.

Drop this file in your cogs folder and load it with:
    await bot.load_extension("graspingstraw")
"""

import asyncio
import random
import string
from dataclasses import dataclass, field

import discord
from discord.ext import commands

STARTING_LIVES = 3
JOIN_SECONDS = 15
CLAIM_SECONDS = 15
CLAIM_SECONDS_FLOOR = 5       # timer never shrinks below this
CLAIM_SHRINK_EVERY = 5        # every N rounds...
CLAIM_SHRINK_AMOUNT = 0.5     # ...timer drops by this many seconds
MIN_PLAYERS = 2               # 1 player = solo endurance mode, 0 = cancelled


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Player:
    member: discord.Member
    lives: int = STARTING_LIVES
    alive: bool = True


@dataclass
class Problem:
    display: str   # e.g. "8 x 5 - 3"
    answer: int


@dataclass
class Game:
    channel: discord.abc.Messageable
    host: discord.Member
    players: dict = field(default_factory=dict)      # user_id -> Player
    state: str = "lobby"                              # lobby | claiming | resolving | finished
    round_number: int = 0
    round_problems: dict = field(default_factory=dict)  # letter -> Problem
    claims: dict = field(default_factory=dict)           # user_id -> letter
    lobby_message: discord.Message = None
    solo: bool = False


# ---------------------------------------------------------------------------
# Math problem generation
# ---------------------------------------------------------------------------

def generate_problem() -> Problem:
    """Builds a small +/-/x expression with an integer answer."""
    terms = random.choice([2, 3])
    numbers = [random.randint(1, 12) for _ in range(terms)]
    ops = [random.choice(["+", "-", "x"]) for _ in range(terms - 1)]

    display_parts = [str(numbers[0])]
    eval_parts = [str(numbers[0])]
    for i, op in enumerate(ops):
        display_parts.append(op)
        display_parts.append(str(numbers[i + 1]))
        eval_parts.append("*" if op == "x" else op)
        eval_parts.append(str(numbers[i + 1]))

    display = " ".join(display_parts)
    answer = eval(" ".join(eval_parts))  # safe: only digits/+-* joined by us
    return Problem(display=display, answer=answer)


def make_round_problems(count: int) -> dict:
    letters = string.ascii_uppercase
    problems = {}
    for i in range(count):
        letter = letters[i] if i < len(letters) else f"P{i}"
        problems[letter] = generate_problem()
    return problems


# ---------------------------------------------------------------------------
# Join view
# ---------------------------------------------------------------------------

class JoinView(discord.ui.View):
    def __init__(self, cog: "GraspingStraw", game: Game):
        super().__init__(timeout=JOIN_SECONDS)
        self.cog = cog
        self.game = game

    def build_embed(self) -> discord.Embed:
        names = "\n".join(f"• {p.member.display_name}" for p in self.game.players.values()) or "*No one yet*"
        embed = discord.Embed(
            title="🎯 Grasping Straws — Lobby Open!",
            description=f"Press **Join** below to enter! Starting in {JOIN_SECONDS}s.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name=f"Players ({len(self.game.players)})", value=names, inline=False)
        return embed

    @discord.ui.button(label="Join", style=discord.ButtonStyle.green, emoji="✋")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game.state != "lobby":
            await interaction.response.send_message("This lobby has already closed.", ephemeral=True)
            return
        if interaction.user.id in self.game.players:
            await interaction.response.send_message("You're already in!", ephemeral=True)
            return

        self.game.players[interaction.user.id] = Player(member=interaction.user)
        await interaction.response.send_message("You're in! Good luck.", ephemeral=True)
        try:
            await self.game.lobby_message.edit(embed=self.build_embed(), view=self)
        except discord.HTTPException:
            pass

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.game.lobby_message.edit(view=self)
        except discord.HTTPException:
            pass
        await self.cog.begin_game(self.game)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class GraspingStraw(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games: dict[int, Game] = {}  # channel_id -> Game

    # -- helpers -----------------------------------------------------------

    def lives_str(self, player: Player) -> str:
        return "❤️" * player.lives + "🖤" * (STARTING_LIVES - player.lives)

    def alive_players(self, game: Game):
        return [p for p in game.players.values() if p.alive]

    def claim_time_for_round(self, round_number: int) -> float:
        """Timer shrinks by CLAIM_SHRINK_AMOUNT every CLAIM_SHRINK_EVERY rounds, down to a floor."""
        decrements = (round_number - 1) // CLAIM_SHRINK_EVERY
        t = CLAIM_SECONDS - (CLAIM_SHRINK_AMOUNT * decrements)
        return max(CLAIM_SECONDS_FLOOR, t)

    # -- start command -------------------------------------------------------

    @commands.command(name="graspingstraw", aliases=["gs"])
    async def graspingstraw(self, ctx: commands.Context):
        existing = self.games.get(ctx.channel.id)
        if existing and existing.state != "finished":
            await ctx.send("A game is already running in this channel.")
            return

        game = Game(channel=ctx.channel, host=ctx.author)
        self.games[ctx.channel.id] = game

        view = JoinView(self, game)
        game.lobby_message = await ctx.send(embed=view.build_embed(), view=view)

    async def begin_game(self, game: Game):
        if len(game.players) == 0:
            await game.channel.send("No one joined in time. Game cancelled.")
            game.state = "finished"
            self.games.pop(game.channel.id, None)
            return

        if len(game.players) == 1:
            game.solo = True
            solo_player = next(iter(game.players.values()))
            await game.channel.send(
                f"Only **{solo_player.member.display_name}** joined — starting **Endurance Mode**! "
                "Survive as many rounds as you can before you run out of lives. 🍀"
            )
        else:
            await game.channel.send(
                f"**{len(game.players)} players** are in! Grasping Straws begins now. 🍀"
            )

        await self.start_round(game)

    # -- round flow ----------------------------------------------------------

    async def start_round(self, game: Game):
        alive = self.alive_players(game)
        game_over = (len(alive) == 0) if game.solo else (len(alive) <= 1)
        if game_over:
            await self.end_game(game)
            return

        game.round_number += 1
        problem_count = 3 if game.solo else len(alive) + 1
        game.round_problems = make_round_problems(problem_count)
        game.claims = {}
        game.state = "claiming"

        claim_time = self.claim_time_for_round(game.round_number)

        lines = [f"**{letter}.** {p.display}" for letter, p in game.round_problems.items()]
        title = f"🧮 Round {game.round_number}" + (" (Endurance)" if game.solo else "") + " — Claim a problem!"
        embed = discord.Embed(
            title=title,
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.add_field(
            name="How to claim",
            value=f"Type `!claim <letter>` (e.g. `!claim A`). You have {claim_time:g}s.\n"
                  "Avoid the highest AND lowest answers — good luck!",
            inline=False,
        )
        if not game.solo:
            alive_names = ", ".join(p.member.display_name for p in alive)
            embed.add_field(name="Still in it", value=alive_names, inline=False)
        await game.channel.send(embed=embed)

        await asyncio.sleep(claim_time)
        await self.resolve_round(game)

    @commands.command(name="claim")
    async def claim(self, ctx: commands.Context, letter: str = None):
        game = self.games.get(ctx.channel.id)
        if not game or game.state != "claiming":
            return  # no active claiming phase; stay quiet to avoid spam

        player = game.players.get(ctx.author.id)
        if not player or not player.alive:
            await ctx.send(f"{ctx.author.mention} you're not an active player in this game.", delete_after=8)
            return

        if not letter:
            await ctx.send(f"{ctx.author.mention} usage: `!claim <letter>`", delete_after=8)
            return

        letter = letter.strip().upper()
        if letter not in game.round_problems:
            await ctx.send(f"{ctx.author.mention} `{letter}` isn't a valid problem this round.", delete_after=8)
            return

        if ctx.author.id in game.claims:
            await ctx.send(f"{ctx.author.mention} you already claimed **{game.claims[ctx.author.id]}**.", delete_after=8)
            return

        if letter in game.claims.values():
            await ctx.send(f"{ctx.author.mention} **{letter}** is already claimed by someone else.", delete_after=8)
            return

        game.claims[ctx.author.id] = letter
        await ctx.message.add_reaction("✅")

    async def resolve_round(self, game: Game):
        game.state = "resolving"

        answers = {letter: prob.answer for letter, prob in game.round_problems.items()}
        max_val = max(answers.values())
        min_val = min(answers.values())
        high_letters = {l for l, v in answers.items() if v == max_val}
        low_letters = {l for l, v in answers.items() if v == min_val}

        alive = self.alive_players(game)
        losers = []

        for player in alive:
            claimed = game.claims.get(player.member.id)
            reason = None
            if claimed is None:
                reason = "didn't claim in time"
            elif claimed in high_letters:
                reason = f"claimed **{claimed}** (highest answer)"
            elif claimed in low_letters:
                reason = f"claimed **{claimed}** (lowest answer)"

            if reason:
                player.lives -= 1
                eliminated = player.lives <= 0
                if eliminated:
                    player.alive = False
                losers.append((player, reason, eliminated))

        # Build results embed
        lines = []
        for letter, prob in sorted(game.round_problems.items()):
            tag = ""
            if letter in high_letters:
                tag = " 🔺 highest"
            elif letter in low_letters:
                tag = " 🔻 lowest"
            claimant = next((p.member.display_name for p, l in
                              ((game.players[uid], l) for uid, l in game.claims.items()) if l == letter), None)
            claimant_str = f" — claimed by {claimant}" if claimant else " — unclaimed"
            lines.append(f"**{letter}.** {prob.display} = {prob.answer}{tag}{claimant_str}")

        embed = discord.Embed(
            title=f"📊 Round {game.round_number} Results",
            description="\n".join(lines),
            color=discord.Color.red(),
        )

        if losers:
            loser_lines = []
            for player, reason, eliminated in losers:
                status = "☠️ ELIMINATED" if eliminated else self.lives_str(player)
                loser_lines.append(f"{player.member.display_name} — {reason} → {status}")
            embed.add_field(name="Lost a life", value="\n".join(loser_lines), inline=False)
        else:
            embed.add_field(name="Lost a life", value="No one! Everyone claimed safely.", inline=False)

        await game.channel.send(embed=embed)

        still_alive = self.alive_players(game)
        game_over = (len(still_alive) == 0) if game.solo else (len(still_alive) <= 1)
        if game_over:
            await self.end_game(game)
        else:
            await asyncio.sleep(3)
            await self.start_round(game)

    async def end_game(self, game: Game):
        game.state = "finished"
        alive = self.alive_players(game)

        if game.solo:
            solo_player = next(iter(game.players.values()))
            rounds_survived = game.round_number - 1  # they were eliminated on round_number, so cleared this many
            await game.channel.send(
                f"💀 **{solo_player.member.display_name}** was eliminated!\n"
                f"🏁 **Endurance result: {rounds_survived} round(s) survived.**"
            )
        elif len(alive) == 1:
            winner = alive[0]
            await game.channel.send(f"🏆 **{winner.member.display_name} wins Grasping Straws!** 🏆")
        elif len(alive) == 0:
            await game.channel.send("💀 Everyone was eliminated at once — no winner this time!")
        else:
            await game.channel.send("Game ended.")

        self.games.pop(game.channel.id, None)


async def setup(bot: commands.Bot):
    await bot.add_cog(GraspingStraw(bot))


async def setup(bot: commands.Bot):
    await bot.add_cog(GraspingStraw(bot))
