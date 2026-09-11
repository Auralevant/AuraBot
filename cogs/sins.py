"""
Drowning Sins - cog handling the Sins Timer + final unscramble phase.

Drop this file in your cogs folder and load it like any other cog:
    await bot.load_extension("drowning_sins")

Commands:
    !sins         - starts a run (timer begins at 75)
    !escapesins   - locks in the score, moves to the final unscramble phase
    !guess <text> - submit a guess for the unscrambled phrase (final phase only)
    !cancelsins   - cancels your own run early (utility command, optional)

Behavior:
    - Timer starts at 75 and ticks down by 1 every second.
    - Timer hitting 0 => instant loss ("drowned").
    - Saying "I SWIM FROM MY SINS" (case-insensitive) anywhere in the game
      channel adds 5 to the timer and the message is deleted immediately.
      Works in both phases.
    - If the timer ever exceeds the upper limit (150) => instant loss.
    - !escapesins locks the run and shows a scrambled version of
      "I HAVE ESCAPED FROM MY SINS" (letters scrambled per word, word order kept).
    - !guess <text> checks the answer. Spelling/letters must be correct, but
      spacing inside the guess doesn't matter (only a single space after
      "!guess" itself is required, since that's how the command splits off
      its argument) - "IHAVE ESCAPEDFROMMYSINS" and "I HAVE ESCAPED FROM MY
      SINS" are treated the same.
    - Wrong guesses do NOT cost anything (no cap penalty) - the player can
      just try again as many times as they want, as long as the timer holds.
    - Score/points aren't tracked by the bot at all - that's handled manually.
    - Fully independent per-user state, so many people can run this at once.
"""

import asyncio
import random
import re
from typing import Optional

import discord
from discord.ext import commands

PHRASE = "I HAVE ESCAPED FROM MY SINS"
SWIM_PHRASE = "I SWIM FROM MY SINS"

START_TIME = 75
TIME_INCREMENT = 5
UPPER_LIMIT = 150
EDIT_INTERVAL = 3  # seconds between routine timer message edits (avoids rate limits)


def scramble_phrase(phrase: str) -> str:
    """Keeps the word-length structure of the phrase (e.g. 1 4 7 4 2 4 for
    "I HAVE ESCAPED FROM MY SINS"), but pools ALL letters from every word
    together, shuffles that whole pool, and re-slices it back into chunks
    of those same lengths. So a letter from one word can end up in a
    completely different word, as long as the final layout still looks
    like 1 4 7 4 2 4."""
    words = phrase.split(" ")
    word_lengths = [len(w) for w in words]
    letters = list("".join(words))

    attempts = 0
    while True:
        random.shuffle(letters)
        attempts += 1
        # Try not to reproduce the original arrangement, but don't loop forever.
        if "".join(letters) != "".join(words) or attempts > 10:
            break

    scrambled_words = []
    index = 0
    for length in word_lengths:
        scrambled_words.append("".join(letters[index:index + length]))
        index += length

    return " ".join(scrambled_words)


def normalize_loose(text: str) -> str:
    """Uppercase + collapse whitespace - used for the swim phrase check."""
    return " ".join(text.strip().upper().split())


def normalize_tight(text: str) -> str:
    """Uppercase + strip everything that isn't a letter - used for the final
    guess check, since spacing/punctuation inside the guess doesn't matter,
    only spelling does."""
    return re.sub(r"[^A-Za-z]", "", text).upper()


class SinsGame:
    def __init__(self, user: discord.abc.User, channel: discord.abc.Messageable):
        self.user = user
        self.channel = channel
        self.timer = START_TIME
        self.phase = "main"  # "main" or "final"
        self.message: Optional[discord.Message] = None
        self.task: Optional[asyncio.Task] = None
        self.scrambled: Optional[str] = None
        self.ended = False
        self.result: Optional[str] = None  # None, "won", or "lost"
        self.lock = asyncio.Lock()

    def build_embed(self, status: Optional[str] = None) -> discord.Embed:
        if self.result == "lost":
            emoji, color = "🩸", discord.Color.dark_red()
        elif self.result == "won":
            emoji, color = "✅", discord.Color.green()
        elif self.phase == "final":
            emoji, color = "🌊", discord.Color.gold()
        else:
            emoji, color = "🌊", discord.Color.blue()

        embed = discord.Embed(title=f"{emoji} Drowning Sins", color=color)
        embed.add_field(name="Timer", value=f"**{self.timer}**", inline=True)
        embed.add_field(name="Upper Limit", value=f"**{UPPER_LIMIT}**", inline=True)
        embed.add_field(
            name="Phase",
            value="Final Phrase" if self.phase == "final" else "Challenges",
            inline=True,
        )
        if self.phase == "final" and self.scrambled:
            embed.add_field(name="Unscramble this phrase", value=f"`{self.scrambled}`", inline=False)

        command_lines = ["**I SWIM FROM MY SINS** - Adds 5"]
        if self.phase == "final":
            command_lines.append("`!guess <guess>` - Guess Phrase (Capitalization and spacing doesn't matter but spelling does.)")
        else:
            command_lines.append("`!escapesins` - Enter Escape Phase")
        embed.add_field(name="Commands", value="\n".join(command_lines), inline=False)

        if status:
            embed.add_field(name="Status", value=status, inline=False)
        embed.set_footer(text=f"Player: {self.user.display_name}")
        return embed


class DrowningSins(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games: dict[int, SinsGame] = {}

    def get_game(self, user_id: int) -> Optional[SinsGame]:
        return self.games.get(user_id)

    async def refresh_message(self, game: SinsGame, status: Optional[str] = None, mention: bool = False):
        """Posts a fresh timer message and deletes the old one, so the game
        card keeps reappearing at the bottom of the channel instead of
        getting buried while people are competing. When mention=True, the
        player is pinged outside the embed (used for game-over moments)."""
        embed = game.build_embed(status=status)
        old_message = game.message
        content = game.user.mention if mention else None
        try:
            game.message = await game.channel.send(content=content, embed=embed)
        except discord.HTTPException:
            return
        if old_message is not None:
            try:
                await old_message.delete()
            except discord.HTTPException:
                pass

    # ---------- commands ----------

    @commands.command(name="sins")
    async def start_sins(self, ctx: commands.Context):
        """Starts a new Drowning Sins run for the user."""
        if ctx.author.id in self.games:
            await ctx.send(f"{ctx.author.mention}, you already have a Drowning Sins run in progress!")
            return

        game = SinsGame(ctx.author, ctx.channel)
        self.games[ctx.author.id] = game

        game.message = await ctx.send(
            embed=game.build_embed(
                status=(
                    "Game started! Complete your challenges. Say **I SWIM FROM MY SINS** "
                    "to add 5s to your timer. Use `!escapesins` when you're ready to lock "
                    "in and face the final phrase."
                )
            )
        )

        game.task = self.bot.loop.create_task(self.run_timer(game))

    @commands.command(name="escapesins")
    async def escape_sins(self, ctx: commands.Context):
        """Locks in the score and starts the final unscramble phase."""
        game = self.get_game(ctx.author.id)
        if not game:
            await ctx.send(f"{ctx.author.mention}, you don't have an active Drowning Sins run. Start one with `!sins`.")
            return

        async with game.lock:
            if game.ended:
                return
            if game.phase == "final":
                await ctx.send(f"{ctx.author.mention}, you're already in the final phase! Use `!guess <answer>`.")
                return

            game.phase = "final"
            game.scrambled = scramble_phrase(PHRASE)

            status = (
                "🔒 Score locked in! Unscramble the phrase and submit your answer with "
                "`!guess <your answer>` before the timer runs out."
            )
            await self.refresh_message(game, status=status)

    @commands.command(name="guess")
    async def guess_sins(self, ctx: commands.Context, *, guess: str = ""):
        """Submit a guess for the unscrambled phrase (final phase only)."""
        game = self.get_game(ctx.author.id)
        if not game:
            await ctx.send(f"{ctx.author.mention}, you don't have an active Drowning Sins run.")
            return

        async with game.lock:
            if game.ended:
                return

            if game.phase != "final":
                await ctx.send(f"{ctx.author.mention}, you need to `!escapesins` before you can guess.")
                return

            if not guess:
                await ctx.send(f"{ctx.author.mention}, usage: `!guess <your answer>`")
                return

            if normalize_tight(guess) == normalize_tight(PHRASE):
                await self.end_game(
                    game,
                    won=True,
                    reason=f'You correctly unscrambled: "{PHRASE}" with **{game.timer}** seconds to spare!',
                )
                return

            # Wrong guess - no penalty, just let them know and let them try again.
            try:
                await ctx.message.add_reaction("❌")
            except discord.HTTPException:
                pass
            await self.refresh_message(game, status="❌ Wrong guess! Keep trying with `!guess <your answer>`.")

    @commands.command(name="cancelsins")
    async def cancel_sins(self, ctx: commands.Context):
        """Cancels the user's current Drowning Sins run."""
        game = self.get_game(ctx.author.id)
        if not game:
            await ctx.send(f"{ctx.author.mention}, you don't have an active run to cancel.")
            return
        game.ended = True
        if game.task and not game.task.done():
            game.task.cancel()
        self.games.pop(ctx.author.id, None)
        await ctx.send(f"{ctx.author.mention}'s Drowning Sins run has been cancelled.")

    # ---------- timer loop ----------

    async def run_timer(self, game: SinsGame):
        ticks_since_edit = 0
        try:
            while True:
                await asyncio.sleep(1)
                async with game.lock:
                    if game.ended:
                        return

                    game.timer -= 1
                    ticks_since_edit += 1

                    if game.timer <= 0:
                        await self.end_game(game, won=False, reason="The Sins Timer hit **0**. You drowned. 💀")
                        return

                    if game.timer > UPPER_LIMIT:
                        await self.end_game(
                            game,
                            won=False,
                            reason=f"Your timer exceeded the upper limit of **{UPPER_LIMIT}**. Disqualified for stalling! 🚫",
                        )
                        return

                    if ticks_since_edit >= EDIT_INTERVAL:
                        ticks_since_edit = 0
                        await self.refresh_message(game)
        except asyncio.CancelledError:
            return

    async def end_game(self, game: SinsGame, won: bool, reason: str):
        game.ended = True
        game.result = "won" if won else "lost"
        if game.task and not game.task.done():
            game.task.cancel()

        status = f"✅ **YOU ESCAPED THE SINS!**\n{reason}" if won else f"❌ **GAME OVER**\n{reason}"
        await self.refresh_message(game, status=status, mention=True)

        self.games.pop(game.user.id, None)

    # ---------- message listener (swim phrase only) ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        game = self.get_game(message.author.id)
        if not game or game.ended:
            return

        # Only react in the channel the run was started in.
        if message.channel.id != game.channel.id:
            return

        if normalize_loose(message.content) != normalize_loose(SWIM_PHRASE):
            return

        # Delete the swim-phrase message right away to keep the channel clean.
        try:
            await message.delete()
        except discord.HTTPException:
            pass

        async with game.lock:
            if game.ended:
                return

            game.timer += TIME_INCREMENT

            if game.timer > UPPER_LIMIT:
                await self.end_game(
                    game,
                    won=False,
                    reason=f"Your timer exceeded the upper limit of **{UPPER_LIMIT}**. Disqualified for stalling! 🚫",
                )
                return

            await self.refresh_message(game)


async def setup(bot: commands.Bot):
    await bot.add_cog(DrowningSins(bot))
