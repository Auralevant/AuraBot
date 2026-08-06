import discord
from discord.ext import commands
import random

# Stores every player's Pandora game
pandora_games = {}


class Pandora(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    def generate_board(self):
        """Generate 64 unique numbers from 000-999."""
        return random.sample(range(1000), 64)

    def format_board(self, board):
        """Convert the board into an 8x8 Discord code block."""

        lines = []

        # Column numbers
        lines.append("      1     2     3     4     5     6     7     8")

        row_labels = "ABCDEFGH"

        for row in range(8):

            start = row * 8
            numbers = board[start:start + 8]

            formatted = " ".join(f"{n:03}" for n in numbers)

            lines.append(f"{row_labels[row]}   {formatted}")

        return "```text\n" + "\n".join(lines) + "\n```"

    @commands.command(name="pandora")
    async def pandora(self, ctx):

        # Prevent multiple games
        if ctx.author.id in pandora_games:
            await ctx.send(
                "📦 You already have a Pandora's Box game running!"
            )
            return

        board = self.generate_board()

        pandora_games[ctx.author.id] = {
            "board": board
        }

        await ctx.send(
            "📦 **Pandora's Box**\n\n"
            "Search the board using:\n"
            "`!search ###`\n\n"
            + self.format_board(board)
        )


async def setup(bot):
    await bot.add_cog(Pandora(bot))
