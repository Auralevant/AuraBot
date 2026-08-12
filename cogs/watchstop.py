"""
Stopwatch "Beat the Clock" game.

Commands:
- `!watchstop` -- timer purposes + the very first run's instructions/start.
- `!watchagain` -- start a brand-new run after one has ended (this is what
  consumes one of your 3 total attempts).
- `!watchkeep`  -- lock in the score of a finished run and end the session.
- `!watchquit`  -- bail out of the current run early (while the timer runs).
- `!watchscore` -- peek at current status without affecting the timer.

Overall structure:
- A player gets up to MAX_RUNS (3) total RUNS.
- Within a single run there is NO limit on rounds -- you keep chaining
  successful stops (each one lowering the target) until you either go
  over the target or `!watchquit`. Either of those ENDS the run, but does
  NOT by itself use up an attempt.
- The attempt counter increments only at the moment a NEW run actually
  STARTS -- that's either the very first run (confirmed via `!watchstop`
  after the instructions) or any retry (started via `!watchagain`). It
  never decrements just because a run ended.

Flow:
1. `!watchstop` with no game in progress -> shows the instructions/rundown
   (rules + a worked example) and puts the player into a "pending" state.
   Optionally pass a starting target here, e.g. `!watchstop 10`.
2. `!watchstop` again WHILE pending -> the first run begins: attempt
   counter goes 0 -> 1, and the timer starts for round 1. If more than
   PENDING_TIMEOUT (60s) passed since the instructions were shown, the
   pending state simply expires (no attempt used) and the instructions
   are re-sent with a fresh 60s window.
3. `!watchstop` while the timer IS running -> stops it and scores it:
     * Elapsed <= target -> SUCCESS. +1 point, new target = the time they
       stopped at, and the NEXT round's timer starts immediately in the
       same response. No round cap -- this can keep chaining indefinitely.
     * Elapsed > target -> the RUN ends (no attempt consumed here).
4. When a run ends (by going over or `!watchquit`), the score is shown
   and:
     * If attempts remain -> `!watchkeep` to lock it in, or `!watchagain`
       to start a fresh run (this uses up one attempt, losing this score).
     * If all 3 attempts have already been used -> only `!watchkeep` is
       offered.

Drop this file in your cogs/ folder and load it like your other cogs, e.g.
    await bot.load_extension("cogs.stopwatch_game")
"""

import time
from dataclasses import dataclass

import discord
from discord.ext import commands


@dataclass
class GameState:
    target: float               # seconds the player must stay at/under
    state: str                  # "pending" | "running" | "finished"
    points: int = 0              # successful rounds so far THIS run
    runs_used: int = 0           # total runs STARTED so far THIS session
    timer_start: float = 0.0     # perf_counter() timestamp when the current round started
    pending_since: float = 0.0   # perf_counter() timestamp instructions were shown


class StopwatchGame(commands.Cog):
    """Get as close to the target time as you can without going over."""

    DEFAULT_TARGET = 15.0
    MAX_RUNS = 3
    PENDING_TIMEOUT = 60.0  # seconds allowed between instructions and starting

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # key: user id -> GameState
        self.games: dict[int, GameState] = {}

    def _fmt(self, seconds: float) -> str:
        return f"{seconds:.3f}"

    def _decision_prompt(self, runs_used: int) -> str:
        remaining = self.MAX_RUNS - runs_used
        if remaining > 0:
            return (
                f"Type `!watchkeep` to lock in that score, or `!watchagain` to start a fresh "
                f"run (this score will be lost) -- {remaining} attempt{'s' if remaining != 1 else ''} left."
            )
        return "That was your last attempt -- type `!watchkeep` to lock in that score."

    def _instructions(self, target: float) -> str:
        return (
            "🎮 **Beat the Clock — Instructions**\n"
            f"• Stop the timer as close to the target as you can **without going over**.\n"
            f"• Every successful stop scores a point, and the time you stopped at becomes "
            f"the new (lower) target for the next round — it gets harder each time. "
            f"There's **no limit** on how many rounds you can chain in a single run.\n"
            f"• Rounds run back-to-back with no waiting — the moment you stop one round, "
            f"the next one's timer starts right away.\n"
            f"• A run ends the moment you go over the target. You get **{self.MAX_RUNS}** "
            f"total attempts at a run, across the whole game.\n"
            f"• Commands: `!watchstop` starts/stops the timer, `!watchagain` starts a fresh "
            f"run once one has ended, and `!watchkeep` locks in your score for good.\n\n"
            f"**Example:** Target starts at {self._fmt(target)}s. You stop at 14.5s → success! "
            f"New target is 14.5s. Next round you stop at 14.2s → success! New target is 14.2s. "
            f"You keep going... stop at 13.9s → success! New target 13.9s. Eventually you stop "
            f"at 14.1s → over 13.9s, run ends. Final score: **3**.\n\n"
            f"⏳ Send `!watchstop` again within **{int(self.PENDING_TIMEOUT)} seconds** to begin!"
        )

    @commands.command(name="watchstop")
    async def watchstop(self, ctx: commands.Context, start_target: float = None):
        """Show instructions, confirm the first start, or stop-and-chain the current run."""
        user_id = ctx.author.id
        game = self.games.get(user_id)
        now = time.perf_counter()

        # ---- No game at all yet: show instructions, wait to begin ----
        if game is None:
            target = start_target if start_target and start_target > 0 else self.DEFAULT_TARGET
            self.games[user_id] = GameState(target=target, state="pending", pending_since=now)
            await ctx.send(self._instructions(target))
            return

        # ---- A run already finished: !watchstop no longer handles retries ----
        if game.state == "finished":
            await ctx.send(
                f"{ctx.author.display_name}, that run is over. Use `!watchagain` to start a "
                f"fresh run or `!watchkeep` to lock in your score of **{game.points}**."
            )
            return

        # ---- Pending: waiting for confirmation to actually begin the first run ----
        if game.state == "pending":
            if now - game.pending_since > self.PENDING_TIMEOUT:
                # Expired -- reset and re-show instructions. No attempt used.
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
            game.runs_used = 1
            game.timer_start = now
            await ctx.send(
                f"🏁 **{ctx.author.display_name}**, go! (Attempt {game.runs_used}/{self.MAX_RUNS}) "
                f"Beat **{self._fmt(game.target)}s** — stop the timer with `!watchstop`!"
            )
            return

        # ---- Running: stop it and score it ----
        elapsed = now - game.timer_start

        if elapsed <= game.target:
            game.points += 1
            old_target = game.target
            game.target = elapsed
            game.timer_start = now
            await ctx.send(
                f"✅ **{ctx.author.display_name}** stopped at **{self._fmt(elapsed)}s** "
                f"(target was {self._fmt(old_target)}s)! Point #{game.points}. "
                f"Next timer is already running — beat **{self._fmt(elapsed)}s**!"
            )
        else:
            game.state = "finished"
            await ctx.send(
                f"💥 **{ctx.author.display_name}** stopped at **{self._fmt(elapsed)}s**, "
                f"over the {self._fmt(game.target)}s target — run over.\n"
                f"🏁 Final score: **{game.points}**. {self._decision_prompt(game.runs_used)}"
            )

    @commands.command(name="watchagain")
    async def watchagain(self, ctx: commands.Context, start_target: float = None):
        """Start a brand-new run after the current one has ended. Uses up one attempt."""
        user_id = ctx.author.id
        game = self.games.get(user_id)

        if game is None:
            await ctx.send(f"{ctx.author.display_name}, you haven't played yet -- use `!watchstop` to begin.")
            return

        if game.state != "finished":
            await ctx.send(
                f"{ctx.author.display_name}, your current run isn't over yet. "
                f"Use `!watchstop` to stop the timer or `!watchquit` to end it early."
            )
            return

        if game.runs_used >= self.MAX_RUNS:
            await ctx.send(
                f"{ctx.author.display_name}, you've used all {self.MAX_RUNS} attempts. "
                f"Use `!watchkeep` to lock in your final score of **{game.points}**."
            )
            return

        target = start_target if start_target and start_target > 0 else self.DEFAULT_TARGET
        new_runs_used = game.runs_used + 1
        now = time.perf_counter()
        self.games[user_id] = GameState(
            target=target, state="running", runs_used=new_runs_used, timer_start=now
        )
        await ctx.send(
            f"🔄 **{ctx.author.display_name}**, fresh run started! (Attempt {new_runs_used}/{self.MAX_RUNS}) "
            f"Beat **{self._fmt(target)}s** — stop the timer with `!watchstop`!"
        )

    @commands.command(name="watchkeep")
    async def watchkeep(self, ctx: commands.Context):
        """Lock in the score from a finished run and end the session."""
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
            f"**{game.points}** point{'s' if game.points != 1 else ''}. "
            f"{self._decision_prompt(game.runs_used)}"
        )

    @commands.command(name="watchscore")
    async def watchscore(self, ctx: commands.Context):
        """Check your current score/target without affecting the timer."""
        game = self.games.get(ctx.author.id)
        if game is None:
            await ctx.send(f"{ctx.author.display_name}, no run in progress. Start one with `!watchstop`.")
            return
        if game.state == "pending":
            remaining_time = max(0, self.PENDING_TIMEOUT - (time.perf_counter() - game.pending_since))
            await ctx.send(
                f"📊 **{ctx.author.display_name}** — instructions sent, waiting for you to "
                f"confirm with `!watchstop` ({remaining_time:.0f}s left before it expires)."
            )
            return
        if game.state == "finished":
            await ctx.send(
                f"📊 **{ctx.author.display_name}** — run finished, score: **{game.points}**. "
                f"{self._decision_prompt(game.runs_used)}"
            )
            return
        await ctx.send(
            f"📊 **{ctx.author.display_name}** — attempt {game.runs_used}/{self.MAX_RUNS}, "
            f"score: **{game.points}**, current target: **{self._fmt(game.target)}s** (timer running)."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(StopwatchGame(bot))
