"""
Ptero Towers — a Squid Game "Glass Bridge" style luck game cog.

Drop this file into your cogs folder and load it like your other cogs
(e.g. `await bot.load_extension("ptero_towers")`).

Requirements:
    discord.py >= 2.0 (uses app_commands + discord.ui.View/Button)
    Your bot must already be syncing its command tree somewhere, since this
    cog registers a slash command (/pterotowers).

Game rules:
    - 15 levels. Each level has two boxes: Left and Right.
    - One side is safe, the other sends you back to level 1 (ground floor).
    - The safe side for each level is decided randomly ONCE per game and
      does not change for the rest of that game — so if the player messes
      up, the layout is still the same and they have to remember it.
    - The bot does NOT show the player which levels they got right/wrong
      from a previous attempt at that level once they restart — the
      display simply resets to the ground floor. They have to memorize it
      themselves.
    - Timer starts the instant they run the command and stops the instant
      they touch the top of level 15.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import discord
from discord.ext import commands

LEVELS = 15

# ---- Visual customization -------------------------------------------------
EMOJI_UNKNOWN = "▫️"      # a level not yet reached
EMOJI_PENDING = "❔"      # the level the player is currently choosing on
EMOJI_STANDING = "🧍"     # marks which side the player is standing on
EMOJI_EMPTY = "⬛"        # the side of a cleared level the player did NOT step on
EMOJI_FLAG = "🏁"
EMOJI_FALL = "💥"
COLOR_CLIMBING = discord.Color.blurple()
COLOR_FALL = discord.Color.red()
COLOR_WIN = discord.Color.gold()
COLOR_GAVE_UP = discord.Color.dark_grey()


def format_elapsed(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    if minutes:
        return f"{minutes}m {secs:.2f}s"
    return f"{secs:.2f}s"


@dataclass
class GameState:
    user_id: int
    layout: list[str]           # 'L' or 'R' safe side per level, index 0 = level 1
    current_level: int = 0      # number of levels successfully cleared (0-15)
    falls: int = 0
    start_time: float = field(default_factory=time.monotonic)
    finished: bool = False


class PteroTowersView(discord.ui.View):
    def __init__(self, cog: "PteroTowers", state: GameState, member: discord.Member | discord.User):
        super().__init__(timeout=180)  # auto-expire if they abandon the game
        self.cog = cog
        self.state = state
        self.member = member

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message(
                "This isn't your climb — start your own with `/pterotowers`.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        self.cog.active_games.pop(self.member.id, None)
        for item in self.children:
            item.disabled = True
        # Best effort — message may have been deleted, ignore failures.
        try:
            if self.message:
                embed = self.cog.build_embed(self.state, status="timeout")
                await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass

    def _disable_all(self):
        for item in self.children:
            item.disabled = True

    async def _end_game(self, interaction: discord.Interaction, status: str):
        self.state.finished = True
        self._disable_all()
        self.cog.active_games.pop(self.member.id, None)
        embed = self.cog.build_embed(self.state, status=status)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def _handle_choice(self, interaction: discord.Interaction, side: str):
        state = self.state
        safe_side = state.layout[state.current_level]

        if side == safe_side:
            state.current_level += 1
            if state.current_level == LEVELS:
                await self._end_game(interaction, status="win")
                return
            embed = self.cog.build_embed(state, status="climbing")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            state.falls += 1
            state.current_level = 0
            embed = self.cog.build_embed(state, status="fell")
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⬅️ Left", style=discord.ButtonStyle.primary)
    async def left(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_choice(interaction, "L")

    @discord.ui.button(label="Right ➡️", style=discord.ButtonStyle.primary)
    async def right(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_choice(interaction, "R")

    @discord.ui.button(label="🏳️ Give Up", style=discord.ButtonStyle.secondary, row=1)
    async def give_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._end_game(interaction, status="gave_up")


class PteroTowers(commands.Cog):
    """A Squid Game glass-bridge style luck game."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: dict[int, bool] = {}

    def render_tower(self, state: GameState) -> str:
        """Builds the live ASCII climbing wall, top level first."""
        lines = [f"        {EMOJI_FLAG} TOP {EMOJI_FLAG}"]
        for level_index in range(LEVELS - 1, -1, -1):
            level_num = level_index + 1
            safe_side = state.layout[level_index]

            if level_index < state.current_level:
                # Already cleared this level in the CURRENT run.
                left = EMOJI_STANDING if safe_side == "L" else EMOJI_EMPTY
                right = EMOJI_STANDING if safe_side == "R" else EMOJI_EMPTY
            elif level_index == state.current_level and not state.finished:
                # The level they're currently deciding on.
                left = EMOJI_PENDING
                right = EMOJI_PENDING
            else:
                # Not reached yet.
                left = EMOJI_UNKNOWN
                right = EMOJI_UNKNOWN

            marker = " ←you" if (level_index == state.current_level and not state.finished) else ""
            lines.append(f"Lvl {level_num:>2} | {left}  {right} |{marker}")
        lines.append("       [ START ]")
        return "```\n" + "\n".join(lines) + "\n```"

    def build_embed(self, state: GameState, status: str) -> discord.Embed:
        elapsed = time.monotonic() - state.start_time

        if status == "win":
            title = "🏆 Ptero Towers — Cleared!"
            color = COLOR_WIN
            desc = (
                f"You reached the top of all **{LEVELS}** levels!\n"
                f"⏱️ Final time: **{format_elapsed(elapsed)}**\n"
                f"💥 Falls: **{state.falls}**"
            )
        elif status == "fell":
            title = f"{EMOJI_FALL} Ptero Towers — You fell!"
            color = COLOR_FALL
            desc = (
                f"Wrong side. Back to the ground floor you go.\n"
                f"⏱️ Time so far: **{format_elapsed(elapsed)}** (still running)\n"
                f"💥 Falls: **{state.falls}**"
            )
        elif status == "gave_up":
            title = "🏳️ Ptero Towers — Gave up"
            color = COLOR_GAVE_UP
            desc = (
                f"You bailed at level **{state.current_level}/{LEVELS}**.\n"
                f"⏱️ Time: **{format_elapsed(elapsed)}**\n"
                f"💥 Falls: **{state.falls}**"
            )
        elif status == "timeout":
            title = "⌛ Ptero Towers — Game expired"
            color = COLOR_GAVE_UP
            desc = "You took too long to make a move. Run `/pterotowers` to try again."
        else:  # "climbing"
            title = "🪜 Ptero Towers"
            color = COLOR_CLIMBING
            desc = (
                f"Level **{state.current_level}/{LEVELS}** cleared. Pick a side to continue.\n"
                f"⏱️ Time so far: **{format_elapsed(elapsed)}**"
            )

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.add_field(name="Tower", value=self.render_tower(state), inline=False)
        embed.set_footer(text="One side is safe, one isn't. Remember your steps — the board won't.")
        return embed

    @commands.hybrid_command(
        name="pterotowers",
        description="Climb Ptero Towers — pick left or right at each of 15 levels. One side is always safe.",
    )
    async def pterotowers(self, ctx: commands.Context):
        # Works both as a prefix command (!pterotowers) and a slash command
        # (/pterotowers), since it's a hybrid command.
        if self.active_games.get(ctx.author.id):
            await ctx.send(
                "You're already mid-climb! Finish or give up on your current game first.",
                ephemeral=True,
            )
            return

        layout = [random.choice(["L", "R"]) for _ in range(LEVELS)]
        state = GameState(user_id=ctx.author.id, layout=layout)
        self.active_games[ctx.author.id] = True

        view = PteroTowersView(self, state, ctx.author)
        embed = self.build_embed(state, status="climbing")

        message = await ctx.send(embed=embed, view=view)
        view.message = message


async def setup(bot: commands.Bot):
    await bot.add_cog(PteroTowers(bot))
