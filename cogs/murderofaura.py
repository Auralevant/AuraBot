"""
Murder Mystery Game Cog
------------------------
Requires: discord.py (or py-cord), Python 3.10+

Load this as an extension in your bot, e.g.:
    await bot.load_extension("cogs.murderofaura")

Commands:
    !files          -> posts the suspect list + statements (plain text)
    !accuse <name>  -> guess the culprit

The bolded "condition" line under each statement is just presentation /
a clue for players to reason about. It has NO effect on whether an
!accuse guess is correct -- only the `correct` flag on a suspect matters.
"""

import time
from discord.ext import commands

# ---------------------------------------------------------------------------
# 1. CASE DATA -- edit this to match your actual mystery.
#    Only the suspect with correct=True will register as the right answer.
#    "statement" and "condition" are shown to players but never checked.
# ---------------------------------------------------------------------------
SUSPECTS = [
    {
        "name": "Soul",
        "statement": "I think the killer has to be in the Spell Book Group. It had to be witchery.",
        "condition": "This statement is true if Eden won 3 competitions this season.",
        "correct": False,
    },
    {
        "name": "Release",
        "statement": "I don't think Tyler did it. He was in the Audio Room at the time.",
        "condition": "This statement is true if there was an even amount of people that won a competition this season.",
        "correct": False,
    },
    {
        "name": "Tyler",
        "statement": "I don't think anyone who bit the apple and made jury did this.",
        "condition": "This statement is false if Omega lost an HOH competition.",
        "correct": False,
    },
    {
        "name": "Aaronic",
        "statement": "I think as much Emerald cheated, I don't think she had enough time to do this.",
        "condition": "This statement is true if Flair's statement is false.",
        "correct": False,
    },
    {
        "name": "Ari",
        "statement": "Flair was busy hanging out with Production during Aura's murder.",
        "condition": "This statement is true if the Snake won a temptation competition.",
        "correct": True,  # <- the killer
    },
    {
        "name": "Krevus",
        "statement": "I think the killer is trying to pull a fast one on us. I think the killer told the truth during their statement.",
        "condition": "This statement is false if the Urn Group member(s) lied during their statement(s).",
        "correct": False,
    },
    {
        "name": "Omega",
        "statement": "Obviously it wasn't me. I was too busy taking care of Benny to bother with Aura.",
        "condition": "This statement is true if both double evictions had someone that 0 votes to save.",
        "correct": False,
    },
    {
        "name": "Goof",
        "statement": "I think it's someone from the Urn Group. They probably hid the ashes of Aura in there.",
        "condition": "This statement is true if Omega won his 5th competition before Krevus won his 2nd.",
        "correct": False,
    },
    {
        "name": "Sixx",
        "statement": "I think Soul and Release are innocent. I mean they were barely here in the first place.",
        "condition": "This statement is true if there were 12 emotions in the Perceptive Potions competition.",
        "correct": False,
    },
    {
        "name": "Hazel",
        "statement": "I think it's someone skilled enough meaning it's someone who won a competition this season.",
        "condition": "This statement is true if every non He/Him cast member told the truth in their statement.",
        "correct": False,
    },
    {
        "name": "Emerald",
        "statement": "I think it's someone that won the Veto.",
        "condition": "This is false if the most votes to evict someone for one eviction night was 11.",
        "correct": False,
    },
    {
        "name": "Flair",
        "statement": "I don't think it's someone who got eliminated in a double eviction. I mean they can clear each other.",
        "condition": "This statement is true if 4 power weeks (someone wins HOH and veto) happened so far.",
        "correct": False,
    },
]


def format_duration(seconds: float) -> str:
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


class MurderMystery(commands.Cog):
    """Handles !files and !accuse for the murder mystery game."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # per-player state, keyed by user id
        # { user_id: {"attempts": int, "started_at": float | None, "solved": bool} }
        self.player_state: dict[int, dict] = {}

    def get_state(self, user_id: int) -> dict:
        if user_id not in self.player_state:
            self.player_state[user_id] = {
                "attempts": 0,
                "started_at": None,
                "solved": False,
            }
        return self.player_state[user_id]

    @commands.command(name="files")
    async def files(self, ctx: commands.Context):
        """Show the suspect list and statements."""
        state = self.get_state(ctx.author.id)

        # Start the clock the first time they open the files (unless already solved)
        if not state["solved"] and state["started_at"] is None:
            state["started_at"] = time.monotonic()

        lines = ["**Case Files - Suspect Statements**\n"]
        for i, suspect in enumerate(SUSPECTS, start=1):
            lines.append(f"**{i}. {suspect['name']}**")
            lines.append(f"> {suspect['statement']}")
            lines.append(f"> **{suspect['condition']}**")
            lines.append("")  # blank line between suspects

        lines.append("Use `!accuse <suspect name>` to make your guess.")

        message_text = "\n".join(lines)

        # Discord messages cap at 2000 characters -- split if needed
        if len(message_text) <= 2000:
            await ctx.send(message_text)
        else:
            chunk = ""
            for line in lines:
                if len(chunk) + len(line) + 1 > 2000:
                    await ctx.send(chunk)
                    chunk = ""
                chunk += line + "\n"
            if chunk:
                await ctx.send(chunk)

    @commands.command(name="accuse")
    async def accuse(self, ctx: commands.Context, *, guess_name: str = None):
        """Guess the killer. Usage: !accuse <suspect name>"""
        state = self.get_state(ctx.author.id)

        if state["solved"]:
            await ctx.send(
                "You already solved this case! Use `!files` to review it, "
                "or start a new case."
            )
            return

        if not guess_name:
            await ctx.send("You need to name a suspect. Example: `!accuse Ari`")
            return

        match = next(
            (s for s in SUSPECTS if s["name"].lower() == guess_name.strip().lower()),
            None,
        )

        if match is None:
            await ctx.send(
                f'I don\'t recognize "{guess_name}" as a suspect. '
                f"Check `!files` for the exact names."
            )
            return

        # Make sure the clock is running even if they !accuse without !files first
        if state["started_at"] is None:
            state["started_at"] = time.monotonic()

        state["attempts"] += 1

        if not match["correct"]:
            await ctx.send(
                f"Incorrect guess! **{match['name']}** wasn't the one. "
                f"Try again. (Attempt #{state['attempts']})"
            )
            return

        # Correct guess -- stop the clock
        state["solved"] = True
        elapsed = time.monotonic() - state["started_at"]

        await ctx.send(
            f"Correct! **{match['name']}** did it.\n"
            f"It took you **{state['attempts']}** accusation"
            f"{'' if state['attempts'] == 1 else 's'} and "
            f"**{format_duration(elapsed)}** to solve the case."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MurderMystery(bot))
