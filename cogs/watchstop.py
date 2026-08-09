"""
Stopwatch "Beat the Clock" game.

Rules:
- !watchstop with no game running for that user -> starts a new game and
  starts the timer for round 1. Target defaults to 15.0 seconds, or pass
  a number: `!watchstop 10` to set a custom starting target.
- !watchstop while the timer IS running -> stops the timer and checks the
  elapsed time against the target:
    * elapsed <= target  -> SUCCESS. +1 point. New target = elapsed time.
                             Timer resets to idle; player calls !watchstop
                             again whenever they're ready for the next round.
    * elapsed > target   -> GAME OVER. Final score is reported and the
                             game state is cleared.
- !watchquit -> abandon the current game early (reports current score).
- !watchscore -> show current in-progress score/target without stopping anything.

Drop this file in your cogs/ folder and load it like your other cogs, e.g.
    await bot.load_extension("cogs.stopwatch_game")
"""

import time
from dataclasses import dataclass

import discord
from discord.ext import commands


@dataclass
class GameState:
    target: float          # seconds the player must stay at/under
    points: int = 0         # successful rounds so far
    running: bool = False   # is the timer currently ticking?
    start_time: float = 0.0  # perf_counter() timestamp when round started


class StopwatchGame(commands.Cog):
    """Get as close to the target time as you can without going over."""

    DEFAULT_TARGET = 15.0

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # key: user id -> GameState
        self.games: dict[int, GameState] = {}

    def _fmt(self, seconds: float) -> str:
        return f"{seconds:.3f}"

    @commands.command(name="watchstop")
    async def watchstop(self, ctx: commands.Context, start_target: float = None):
        """Start or stop the stopwatch. Call it once to start, again to stop."""
        user_id = ctx.author.id
        game = self.games.get(user_id)

        # ---- No game in progress: create one and start round 1 ----
        if game is None:
            target = start_target if start_target and start_target > 0 else self.DEFAULT_TARGET
            game = GameState(target=target, running=True, start_time=time.perf_counter())
            self.games[user_id] = game
            await ctx.send(
                f"⏱️ **{ctx.author.display_name}**, timer started! "
                f"Stop it as close to **{self._fmt(target)}s** as you can "
                f"without going over. Use `!watchstop` again to stop."
            )
            return

        # ---- Game exists but is idle (between rounds): start next round ----
        if not game.running:
            game.running = True
            game.start_time = time.perf_counter()
            await ctx.send(
                f"⏱️ **{ctx.author.display_name}**, round started! "
                f"Beat **{self._fmt(game.target)}s** (score so far: {game.points})."
            )
            return

        # ---- Game exists and timer is running: stop it and score ----
        elapsed = time.perf_counter() - game.start_time
        game.running = False

        if elapsed <= game.target:
            game.points += 1
            old_target = game.target
            game.target = elapsed
            await ctx.send(
                f"✅ **{ctx.author.display_name}** stopped at **{self._fmt(elapsed)}s** "
                f"(target was {self._fmt(old_target)}s)! Point #{game.points}. "
                f"New target: **{self._fmt(elapsed)}s**. Call `!watchstop` when ready for the next round."
            )
        else:
            final_score = game.points
            del self.games[user_id]
            await ctx.send(
                f"💥 **{ctx.author.display_name}** stopped at **{self._fmt(elapsed)}s**, "
                f"over the {self._fmt(game.target)}s target — **GAME OVER**. "
                f"Final score: **{final_score}** point{'s' if final_score != 1 else ''}. "
                f"Use `!watchstop` to play again!"
            )

    @commands.command(name="watchquit")
    async def watchquit(self, ctx: commands.Context):
        """Abandon the current game and report your score."""
        user_id = ctx.author.id
        game = self.games.pop(user_id, None)
        if game is None:
            await ctx.send(f"{ctx.author.display_name}, you don't have a game running.")
            return
        await ctx.send(
            f"🏳️ **{ctx.author.display_name}** quit with a final score of "
            f"**{game.points}** point{'s' if game.points != 1 else ''}."
        )

    @commands.command(name="watchscore")
    async def watchscore(self, ctx: commands.Context):
        """Check your current score and target without affecting the timer."""
        game = self.games.get(ctx.author.id)
        if game is None:
            await ctx.send(f"{ctx.author.display_name}, no game in progress. Start one with `!watchstop`.")
            return
        status = "timer is running" if game.running else "waiting for you to start the next round"
        await ctx.send(
            f"📊 **{ctx.author.display_name}** — score: **{game.points}**, "
            f"current target: **{self._fmt(game.target)}s** ({status})."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(StopwatchGame(bot))
