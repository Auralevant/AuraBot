"""
Blood vs Water — emoji math challenge cog.

Rules:
- !bloodvswater starts a round in the current channel.
- The bot posts a row of droplet emojis: 💧 (water) = +1, 🩸 (blood) = -1.
- Players type just the number (e.g. "-4" or "7") — no command prefix — to guess.
- Correct guess: player scores a point, next (slightly harder) set is posted immediately.
- Wrong guess: player gets a 5 second cooldown before their next guess is accepted.
- Round lasts 5 minutes total; whoever has the most points when time's up wins.
- Difficulty scales: Set 1 uses 3-5 emojis, Set 20 uses 18-20 emojis, capped at 25 max.

Drop this file in your cogs folder and load it with:
    await bot.load_extension("bloodvswater")
(or `bot.load_extension(...)` without await on discord.py 1.x)
"""

import asyncio
import random
import time

import discord
from discord.ext import commands

WATER = "\U0001F4A7"  # 💧
BLOOD = "\U0001FA78"  # 🩸

GAME_DURATION = 240        # 4 minutes, in seconds
PENALTY_SECONDS = 5        # cooldown after a wrong guess
MAX_EMOJIS = 25            # hard cap regardless of set number
DIFFICULTY_CAP_SET = 20    # set number at which difficulty stops increasing

# Difficulty curve anchors, per the spec:
#   Set 1  -> base 3  (range 3-5)
#   Set 20 -> base 18 (range 18-20)
_BASE_START = 3
_BASE_END = 18


class BloodVsWaterGame:
    """State for a single active Blood vs Water round in one channel."""

    def __init__(self):
        self.scores: dict[int, int] = {}
        self.set_number = 0
        self.current_answer = 0
        self.cooldowns: dict[int, float] = {}  # user_id -> monotonic time cooldown ends
        self.active = True

    # -- scoring / state helpers -------------------------------------------------

    def add_point(self, user_id: int) -> None:
        self.scores[user_id] = self.scores.get(user_id, 0) + 1

    def cooldown_remaining(self, user_id: int) -> float:
        remaining = self.cooldowns.get(user_id, 0.0) - time.monotonic()
        return max(0.0, remaining)

    def apply_penalty(self, user_id: int) -> None:
        self.cooldowns[user_id] = time.monotonic() + PENALTY_SECONDS

    # -- set generation ------------------------------------------------------

    def next_set(self) -> list[str]:
        """Generate and store the next emoji set, returning the emoji list."""
        self.set_number += 1
        count = self._emoji_count_for_set(self.set_number)
        emojis = [random.choice((WATER, BLOOD)) for _ in range(count)]
        self.current_answer = emojis.count(WATER) - emojis.count(BLOOD)
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
            await ctx.send("A Blood vs Water round is already running in this channel!")
            return

        game = BloodVsWaterGame()
        self.games[ctx.channel.id] = game

        await ctx.send(
            f"{BLOOD}{WATER} **Blood vs Water** {WATER}{BLOOD}\n"
            f"{WATER} = +1, {BLOOD} = \u22121. Add them up and just type the number when "
            "you know it (no command needed).\n"
            f"You have **5 minutes** — most points wins. A wrong guess costs you a "
            f"{PENALTY_SECONDS}s penalty before you can guess again."
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
        if not game or not game.active:
            return

        content = message.content.strip()
        guess = self._parse_guess(content)
        if guess is None:
            return

        user_id = message.author.id
        if game.cooldown_remaining(user_id) > 0:
            # Still serving a penalty — ignore further guesses quietly.
            return

        if guess == game.current_answer:
            game.add_point(user_id)
            try:
                await message.add_reaction("\u2705")  # ✅
            except discord.HTTPException:
                pass
            await self._post_set(message.channel, game)
        else:
            game.apply_penalty(user_id)
            try:
                await message.add_reaction("\u274C")  # ❌
            except discord.HTTPException:
                pass

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
        if not game.scores:
            await channel.send(f"\u23F0 Time's up! Nobody scored a point this round. {WATER}{BLOOD}")
            return

        ranked = sorted(game.scores.items(), key=lambda kv: kv[1], reverse=True)
        winner_id, winner_score = ranked[0]

        lines = ["\u23F0 **Time's up!** Final scores:"]
        for uid, score in ranked:
            lines.append(f"<@{uid}>: {score}")
        lines.append(f"\n\U0001F3C6 <@{winner_id}> wins with {winner_score} point(s)!")
        await channel.send("\n".join(lines))


async def setup(bot: commands.Bot):
    await bot.add_cog(BloodVsWater(bot))
