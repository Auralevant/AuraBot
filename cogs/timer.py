"""
Timer Cog for discord.py
-------------------------
Adds a !timer command that parses durations like:
    !timer 30s        -> 30 seconds
    !timer 30m        -> 30 minutes
    !timer 30h        -> 30 hours
    !timer 1m 30s      -> 90 seconds
    !timer 1h 5m 10s   -> 1 hour, 5 minutes, 10 seconds

The bot posts a NEW message (separate from the command message) that
counts UP every few seconds until the total duration is reached, then
announces completion. Supports multiple concurrent timers per server
and a !canceltimer command to stop your own timer early.

Setup
-----
1. pip install -U discord.py
2. Put this file in your bot's cogs folder (or same folder as main file).
3. In your main bot file:

    import asyncio
    import discord
    from discord.ext import commands

    intents = discord.Intents.default()
    intents.message_content = True  # required to read !commands

    bot = commands.Bot(command_prefix="!", intents=intents)

    async def main():
        async with bot:
            await bot.add_cog(TimerCog(bot))  # or await bot.load_extension("timer_cog")
            await bot.start("YOUR_TOKEN_HERE")

    asyncio.run(main())

   (If you use bot.load_extension, keep the setup() function at the
   bottom of this file, which lets discord.py load it as an extension.)
"""

import re
import time
import asyncio

import discord
from discord.ext import commands, tasks

# How often the "counting up" message is edited, in seconds.
# Discord rate-limits message edits, so don't go below ~2-3s,
# especially if many timers might run at once.
UPDATE_INTERVAL = 5

# Regex that matches chunks like "1h", "30m", "45s" (case-insensitive,
# spaces optional between chunks: "1h30m10s" or "1h 30m 10s" both work)
DURATION_PATTERN = re.compile(r"(\d+)\s*(h|m|s)", re.IGNORECASE)


def parse_duration(text: str) -> int | None:
    """
    Parse a duration string like '30s', '1m 30s', '1h 5m 10s' into
    total seconds. Returns None if nothing valid was found.
    """
    matches = DURATION_PATTERN.findall(text)
    if not matches:
        return None

    total_seconds = 0
    unit_seconds = {"h": 3600, "m": 60, "s": 1}

    for value, unit in matches:
        total_seconds += int(value) * unit_seconds[unit.lower()]

    return total_seconds if total_seconds > 0 else None


def format_duration(seconds: int) -> str:
    """Turn a number of seconds into a readable 'Xh Ym Zs' string."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


class TimerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Tracks active timers so users can cancel their own:
        # key = (channel_id, user_id) -> asyncio.Task
        self.active_timers: dict[tuple[int, int], asyncio.Task] = {}

    @commands.command(name="timer")
    async def timer(self, ctx: commands.Context, *, duration_str: str):
        """
        !timer 30s
        !timer 30m
        !timer 30h
        !timer 1m 30s
        """
        total_seconds = parse_duration(duration_str)

        if total_seconds is None:
            await ctx.send(
                "Couldn't parse that duration. Try formats like "
                "`30s`, `30m`, `30h`, or `1m 30s`."
            )
            return

        # Cap to something sane so nobody starts a 10-year timer by accident.
        MAX_SECONDS = 24 * 3600  # 24 hours
        if total_seconds > MAX_SECONDS:
            await ctx.send("Max timer length is 24 hours.")
            return

        key = (ctx.channel.id, ctx.author.id)
        if key in self.active_timers:
            await ctx.send(
                f"{ctx.author.mention} you already have a timer running "
                f"in this channel. Use `!canceltimer` to stop it."
            )
            return

        # Separate message that will be edited as the timer counts up.
        timer_message = await ctx.send(
            f"⏱️ **Timer started by {ctx.author.mention}** — "
            f"target: {format_duration(total_seconds)}\n"
            f"`0s / {format_duration(total_seconds)}`"
        )

        task = asyncio.create_task(
            self._run_timer(ctx, timer_message, total_seconds, key)
        )
        self.active_timers[key] = task

    @commands.command(name="canceltimer")
    async def cancel_timer(self, ctx: commands.Context):
        """Cancel your own running timer in this channel."""
        key = (ctx.channel.id, ctx.author.id)
        task = self.active_timers.get(key)

        if not task:
            await ctx.send(f"{ctx.author.mention} you don't have a timer running here.")
            return

        task.cancel()
        await ctx.send(f"{ctx.author.mention} your timer was cancelled.")

    async def _run_timer(
        self,
        ctx: commands.Context,
        message: discord.Message,
        total_seconds: int,
        key: tuple[int, int],
    ):
        start = time.monotonic()

        try:
            while True:
                elapsed = time.monotonic() - start
                remaining = total_seconds - elapsed

                if remaining <= 0:
                    break

                # Sleep until either the next update tick or timer end,
                # whichever comes first.
                await asyncio.sleep(min(UPDATE_INTERVAL, remaining))

                elapsed = time.monotonic() - start
                elapsed_display = min(int(elapsed), total_seconds)

                try:
                    await message.edit(
                        content=(
                            f"⏱️ **Timer running for {ctx.author.mention}** — "
                            f"target: {format_duration(total_seconds)}\n"
                            f"`{format_duration(elapsed_display)} / {format_duration(total_seconds)}`"
                        )
                    )
                except discord.HTTPException:
                    # Message deleted, or a transient rate-limit/network
                    # error — just skip this edit and try again next tick.
                    pass

            # Final update.
            await message.edit(
                content=(
                    f"✅ **Timer done!** {ctx.author.mention} — "
                    f"{format_duration(total_seconds)} elapsed."
                )
            )

        except asyncio.CancelledError:
            await message.edit(
                content=(
                    f"🛑 **Timer cancelled** by {ctx.author.mention} "
                    f"(target was {format_duration(total_seconds)})."
                )
            )
            raise
        finally:
            self.active_timers.pop(key, None)


async def setup(bot: commands.Bot):
    """Entry point for bot.load_extension('timer_cog')."""
    await bot.add_cog(TimerCog(bot))
