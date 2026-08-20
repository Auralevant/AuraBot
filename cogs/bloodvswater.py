"""
Blood vs Water — emoji math challenge cog (single-player).

Rules:
- !bloodvswater starts a 5-minute round for whoever ran the command — only they
  can answer; guesses from anyone else in the channel are ignored.
- The bot posts a row of droplet emojis: 💧 (water) = +1, 🩸 (blood) = -1.
- The player types just the number (e.g. "-4" or "7") — no command prefix — to guess.
- The FIRST guess on a set resolves it (further guesses on that set are ignored):
    - Correct: bot says "Correct!", the player scores a point, next set posts immediately.
    - Incorrect: bot says "Incorrect!" (and reveals the answer), then waits 5 seconds
      before posting the next set. No point awarded.
- Round lasts 5 minutes total; final score is announced when time's up, along
  with accuracy (correct guesses / total guesses) as a tiebreaker stat.
- Difficulty scales: Set 1 uses 3-5 emojis, Set 20 uses 18-20 emojis, capped at 25 max.

Drop this file in your cogs folder and load it with:
    await bot.load_extension("bloodvswater")
(or `bot.load_extension(...)` without await on discord.py 1.x)
"""

import asyncio
import random

import discord
from discord.ext import commands

WATER = "\U0001F4A7"  # 💧
BLOOD = "\U0001FA78"  # 🩸

GAME_DURATION = 300        # 5 minutes, in seconds
WRONG_GUESS_DELAY = 5      # seconds to wait after a wrong guess before the next set posts
MAX_EMOJIS = 25            # hard cap regardless of set number
DIFFICULTY_CAP_SET = 20    # set number at which difficulty stops increasing

# Difficulty curve anchors, per the spec:
#   Set 1  -> base 3  (range 3-5)
#   Set 20 -> base 18 (range 18-20)
_BASE_START = 3
_BASE_END = 18


class BloodVsWaterGame:
    """State for a single active Blood vs Water round in one channel."""

    def __init__(self, owner_id: int):
        self.owner_id = owner_id
        self.score = 0
        self.attempts = 0
        self.set_number = 0
        self.current_answer = 0
        self.active = True
        # True while a set has been resolved (correct or incorrect) and we're
        # waiting to post the next one — further guesses are ignored meanwhile.
        self.locked = False

    # -- scoring / state helpers -------------------------------------------------

    def add_point(self) -> None:
        self.score += 1
        self.attempts += 1

    def add_miss(self) -> None:
        self.attempts += 1

    @property
    def accuracy(self) -> float:
        """Accuracy as a fraction 0.0-1.0. 0 if no attempts were made yet."""
        return self.score / self.attempts if self.attempts else 0.0

    # -- set generation ------------------------------------------------------

    def next_set(self) -> list[str]:
        """Generate and store the next emoji set, returning the emoji list."""
        self.set_number += 1
        count = self._emoji_count_for_set(self.set_number)
        emojis = [random.choice((WATER, BLOOD)) for _ in range(count)]
        self.current_answer = emojis.count(WATER) - emojis.count(BLOOD)
        self.locked = False
        return emojis

    @staticmethod
    def _emoji_count_for_set(set_number: int) -> int:
        capped = min(set_number, DIFFICULTY_CAP_SET)
        # Linear interpolation from _BASE_START at set 1 to _BASE_END at set 20.
        base = _BASE_START + round(
            (capped - 1) * (_BASE_END - _BASE_START) / (DIFFICULTY_CAP_SET - 1)
        )
        low = min(base, MAX_EMOJIS)
        high = min(base + 2, MAX_EMOJIS)
        return random.randint(low, high)


class BloodVsWater(commands.Cog):
    """Blood vs Water emoji math challenge."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games: dict[int, BloodVsWaterGame] = {}  # channel_id -> game
        self._timeout_tasks: dict[int, asyncio.Task] = {}

    def cog_unload(self) -> None:
        for task in self._timeout_tasks.values():
            task.cancel()

    # -- commands --------------------------------------------------------------

    @commands.command(name="bloodvswater")
    async def start_game(self, ctx: commands.Context):
        existing = self.games.get(ctx.channel.id)
        if existing and existing.active:
            owner = ctx.guild.get_member(existing.owner_id) if ctx.guild else None
            owner_name = owner.mention if owner else f"<@{existing.owner_id}>"
            await ctx.send(f"A Blood vs Water round is already running here for {owner_name}!")
            return

        game = BloodVsWaterGame(owner_id=ctx.author.id)
        self.games[ctx.channel.id] = game

        await ctx.send(
            f"{BLOOD}{WATER} **Blood vs Water** {WATER}{BLOOD}\n"
            f"{ctx.author.mention}'s round — only they can answer.\n"
            f"{WATER} = +1, {BLOOD} = \u22121. Add them up and just type the number when "
            "you know it (no command needed).\n"
            f"You have **5 minutes** — a wrong guess reveals the answer "
            f"and the next set posts in {WRONG_GUESS_DELAY} seconds."
        )
        await self._post_set(ctx.channel, game)

        task = asyncio.create_task(self._end_after_timeout(ctx.channel, game))
        self._timeout_tasks[ctx.channel.id] = task

    # -- guess handling ----------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        game = self.games.get(message.channel.id)
        if not game or not game.active or game.locked:
            return

        # Only the player who started this round may answer.
        if message.author.id != game.owner_id:
            return

        content = message.content.strip()
        guess = self._parse_guess(content)
        if guess is None:
            return

        # Lock immediately so a duplicate/rapid message can't double-resolve the set.
        game.locked = True

        if guess == game.current_answer:
            game.add_point()
            await message.channel.send(f"\u2705 **Correct!** {message.author.mention} scores a point.")
            await self._post_set(message.channel, game)
        else:
            game.add_miss()
            await message.channel.send(
                f"\u274C **Incorrect!** The answer was `{game.current_answer}`. "
                f"Next set in {WRONG_GUESS_DELAY} seconds..."
            )
            await asyncio.sleep(WRONG_GUESS_DELAY)
            if game.active:
                await self._post_set(message.channel, game)

    @staticmethod
    def _parse_guess(content: str) -> int | None:
        if not content:
            return None
        body = content[1:] if content[0] in "+-" else content
        if not body.isdigit():
            return None
        try:
            return int(content)
        except ValueError:
            return None

    # -- round lifecycle ---------------------------------------------------------

    async def _post_set(self, channel: discord.abc.Messageable, game: BloodVsWaterGame):
        emojis = game.next_set()
        await channel.send(" ".join(emojis))

    async def _end_after_timeout(self, channel: discord.abc.Messageable, game: BloodVsWaterGame):
        try:
            await asyncio.sleep(GAME_DURATION)
        except asyncio.CancelledError:
            return
        if not game.active:
            return
        game.active = False
        await self._announce_results(channel, game)

    async def _announce_results(self, channel: discord.abc.Messageable, game: BloodVsWaterGame):
        pct = game.accuracy * 100
        embed = discord.Embed(
            title=f"{WATER}{BLOOD} Blood vs Water — Results",
            color=discord.Color.red(),
        )
        embed.add_field(name="Player", value=f"<@{game.owner_id}>", inline=False)
        embed.add_field(name="Score", value=str(game.score), inline=True)
        embed.add_field(
            name="Accuracy",
            value=f"{game.score}/{game.attempts} ({pct:.1f}%)",
            inline=True,
        )
        embed.set_footer(text="Time's up!")

        result_message = await channel.send(embed=embed)
        try:
            await result_message.pin(reason="Blood vs Water round results")
        except (discord.Forbidden, discord.HTTPException):
            # Bot may lack "Manage Messages" or the pin limit was hit — results
            # still posted as an embed, just not pinned.
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(BloodVsWater(bot))
