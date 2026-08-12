"""
Stopwatch "Beat the Clock" game.

Flow:
1. `!watchstop` with no game in progress (or after a finished run) -> shows
   the instructions/rundown (rules + a worked example) and puts the player
   into a "pending" state. Optionally pass a starting target here, e.g.
   `!watchstop 10`, and it'll be used once the game actually begins.
2. `!watchstop` again WHILE pending -> the game actually begins: the timer
   starts running for round 1. If more than PENDING_TIMEOUT (60s) passed
   since the instructions were shown, the pending game expires instead and
   the instructions are simply re-sent (they get a fresh 60s window).
3. `!watchstop` while the timer IS running -> stops it and scores it:
     * Elapsed <= target, and fewer than MAX_ROUNDS successful stops so far
       -> SUCCESS. +1 point, new target = the time they stopped at, and the
          NEXT round's timer starts immediately in the same response --
          there is no idle gap between rounds.
     * Elapsed <= target, and this WAS their MAX_ROUNDS-th successful stop
       -> SUCCESS, run complete (max attempts used). Final score shown.
     * Elapsed > target -> run ends immediately. Score shown.
   Either ending puts the run into a "finished" state awaiting a decision.
4. `!watchkeep` -> locks in a finished run's score and clears the game.
5. `!watchstop` again after a run is finished -> shows the instructions
   again for a brand-new run, discarding the unsaved score.

Other commands:
- `!watchquit` -> bail out of a run early (mid-timer), scoring it as an
  ended run so you can !watchkeep or !watchstop to retry.
- `!watchscore` -> peek at current status without affecting the timer.

Drop this file in your cogs/ folder and load it like your other cogs, e.g.
    await bot.load_extension("cogs.stopwatch_game")
"""

import time
from dataclasses import dataclass

import discord
from discord.ext import commands


@dataclass
class GameState:
    target: float             # seconds the player must stay at/under
    state: str                # "pending" | "running" | "finished"
    points: int = 0            # successful rounds so far this run
    attempts_used: int = 0     # stop-attempts used so far this run
    timer_start: float = 0.0   # perf_counter() timestamp when a round started
    pending_since: float = 0.0  # perf_counter() timestamp instructions were shown


class StopwatchGame(commands.Cog):
    """Get as close to the target time as you can without going over."""

    DEFAULT_TARGET = 15.0
    MAX_ROUNDS = 3
    PENDING_TIMEOUT = 60.0  # seconds allowed between instructions and starting

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # key: user id -> GameState
        self.games: dict[int, GameState] = {}

    def _fmt(self, seconds: float) -> str:
        return f"{seconds:.3f}"

    def _decision_prompt(self) -> str:
        return "Type `!watchkeep` to lock in that score, or `!watchstop` to try again (this score will be lost)."

    def _instructions(self, target: float) -> str:
        return (
            "🎮 **Beat the Clock — Instructions**\n"
            f"• Stop the timer as close to the target as you can **without going over**.\n"
            f"• Every successful stop scores a point, and the time you stopped at becomes "
            f"the new (lower) target for the next round — it gets harder each time.\n"
            f"• You get up to **{self.MAX_ROUNDS}** rounds. Go over the target at any point "
            f"and the run ends immediately.\n"
            f"• Rounds run back-to-back with no waiting — the moment you stop one round, "
            f"the next one's timer starts right away.\n"
            f"• When the run ends (either you finish all {self.MAX_ROUNDS} rounds or go over), "
            f"you can `!watchkeep` your score or `!watchstop` to try again from scratch.\n\n"
            f"**Example:** Target starts at {self._fmt(target)}s. You stop at 14.5s → success! "
            f"New target is 14.5s. Next round you stop at 14.2s → success! New target is 14.2s. "
            f"Round 3 you stop at 14.6s → over 14.2s, run ends. Final score: **2**.\n\n"
            f"⏳ Send `!watchstop` again within **{int(self.PENDING_TIMEOUT)} seconds** to begin!"
        )

    @commands.command(name="watchstop")
    async def watchstop(self, ctx: commands.Context, start_target: float = None):
        """Show instructions, confirm start, or stop-and-immediately-start the next round."""
        user_id = ctx.author.id
        game = self.games.get(user_id)
        now = time.perf_counter()

        # ---- No game, or previous run finished: show instructions, wait to begin ----
        if game is None or game.state == "finished":
            target = start_target if start_target and start_target > 0 else self.DEFAULT_TARGET
            game = GameState(target=target, state="pending", pending_since=now)
            self.games[user_id] = game
            await ctx.send(self._instructions(target))
            return

        # ---- Pending: waiting for confirmation to actually begin ----
        if game.state == "pending":
            if now - game.pending_since > self.PENDING_TIMEOUT:
                # Expired -- reset and re-show instructions with a fresh window.
                target = start_target if start_target and start_target > 0 else self.DEFAULT_TARGET
                game = GameState(target=target, state="pending", pending_since=now)
                self.games[user_id] = game
                await ctx.send(
                    f"⌛ **{ctx.author.display_name}**, that took longer than "
                    f"{int(self.PENDING_TIMEOUT)}s, so here are the instructions again.\n\n"
                    + self._instructions(target)
                )
                return

            game.state = "running"
            game.timer_start = now
            await ctx.send(
                f"🏁 **{ctx.author.display_name}**, go! Beat **{self._fmt(game.target)}s** — "
                f"stop the timer with `!watchstop`!"
            )
            return

        # ---- Running: stop it and score it ----
        elapsed = now - game.timer_start
        game.attempts_used += 1

        if elapsed <= game.target:
            game.points += 1
            old_target = game.target

            if game.attempts_used < self.MAX_ROUNDS:
                # Success, rounds remain -> chain straight into the next round.
                game.target = elapsed
                game.timer_start = now
                await ctx.send(
                    f"✅ **{ctx.author.display_name}** stopped at **{self._fmt(elapsed)}s** "
                    f"(target was {self._fmt(old_target)}s)! Point #{game.points}. "
                    f"Next timer is already running — beat **{self._fmt(elapsed)}s**! "
                    f"({self.MAX_ROUNDS - game.attempts_used} attempt"
                    f"{'s' if self.MAX_ROUNDS - game.attempts_used != 1 else ''} left)"
                )
            else:
                game.state = "finished"
                await ctx.send(
                    f"✅ **{ctx.author.display_name}** stopped at **{self._fmt(elapsed)}s** "
                    f"(target was {self._fmt(old_target)}s)! Point #{game.points}. "
                    f"That was your final attempt ({self.MAX_ROUNDS}/{self.MAX_ROUNDS}) — run complete!\n"
                    f"🏁 Final score: **{game.points}**. {self._decision_prompt()}"
                )
        else:
            game.state = "finished"
            await ctx.send(
                f"💥 **{ctx.author.display_name}** stopped at **{self._fmt(elapsed)}s**, "
                f"over the {self._fmt(game.target)}s target — run over.\n"
                f"🏁 Final score: **{game.points}**. {self._decision_prompt()}"
            )

    @commands.command(name="watchkeep")
    async def watchkeep(self, ctx: commands.Context):
        """Lock in the score from a finished run."""
        user_id = ctx.author.id
        game = self.games.get(user_id)
        if game is None or game.state != "finished":
            await ctx.send(
                f"{ctx.author.display_name}, there's no finished run to keep right now."
            )
            return
        final_score = game.points
        del self.games[user_id]
        await ctx.send(
            f"💾 **{ctx.author.display_name}** locked in a final score of "
            f"**{final_score}** point{'s' if final_score != 1 else ''}!"
        )

    @commands.command(name="watchquit")
    async def watchquit(self, ctx: commands.Context):
        """Bail out of the current run early (while the timer is running)."""
        user_id = ctx.author.id
        game = self.games.get(user_id)
        if game is None or game.state != "running":
            await ctx.send(f"{ctx.author.display_name}, you don't have a run in progress.")
            return
        game.state = "finished"
        await ctx.send(
            f"🏳️ **{ctx.author.display_name}** stopped early with a score of "
            f"**{game.points}** point{'s' if game.points != 1 else ''}. {self._decision_prompt()}"
        )

    @commands.command(name="watchscore")
    async def watchscore(self, ctx: commands.Context):
        """Check your current score/target without affecting the timer."""
        game = self.games.get(ctx.author.id)
        if game is None:
            await ctx.send(f"{ctx.author.display_name}, no run in progress. Start one with `!watchstop`.")
            return
        if game.state == "pending":
            remaining = max(0, self.PENDING_TIMEOUT - (time.perf_counter() - game.pending_since))
            await ctx.send(
                f"📊 **{ctx.author.display_name}** — instructions sent, waiting for you to "
                f"confirm with `!watchstop` ({remaining:.0f}s left before it expires)."
            )
            return
        if game.state == "finished":
            await ctx.send(
                f"📊 **{ctx.author.display_name}** — run finished, score: **{game.points}**. "
                f"{self._decision_prompt()}"
            )
            return
        await ctx.send(
            f"📊 **{ctx.author.display_name}** — score: **{game.points}**, "
            f"current target: **{self._fmt(game.target)}s**, "
            f"attempt {game.attempts_used + 1}/{self.MAX_ROUNDS} (timer running)."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(StopwatchGame(bot))
