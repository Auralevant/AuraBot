import discord
from discord.ext import commands
import random

# Stores active Pandora games
pandora_games = {}


class Pandora(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    def generate_board(self):
        """Generate 36 unique numbers from 0000-9999."""
        return random.sample(range(10000), 49)

    def generate_jewels(self, board):
        """Randomly place 4 jewels on the board."""

        # Pick 4 unique board numbers
        jewel_numbers = random.sample(board, 4)

        # Generate 4 unique random letters
        letters = random.sample("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 4)

        # Assign each jewel a letter
        jewels = dict(zip(jewel_numbers, letters))

        # Shuffle the letters to create the unlock code
        code_letters = letters.copy()
        random.shuffle(code_letters)
        code = "".join(code_letters)

        return jewels, code

    def format_board(self, board):
        """Display the board as a 6x6 grid."""

        rows = []

        for row in range(6):
            start = row * 6
            numbers = board[start:start + 6]

            rows.append(" ".join(f"{number:04}" for number in numbers))

        return "```text\n" + "\n".join(rows) + "\n```"

    @commands.command(name="pandora")
    async def pandora(self, ctx):

        # Prevent multiple games
        if ctx.author.id in pandora_games:
            await ctx.send(
                "📦 You already have a Pandora's Box game running!"
            )
            return

        board = self.generate_board()

        jewels, code = self.generate_jewels(board)

        pandora_games[ctx.author.id] = {
            "board": board,
            "jewels": jewels,
            "searched": set(),
            "letters_found": [],
            "code": code,
            "attempts": 0
        }

        await ctx.send(
            "📦 **Pandora's Box**\n\n"
            "Search the grid using:\n"
            "`!search ####`\n\n"
            + self.format_board(board)
        )

    @commands.command(name="search")
    async def search(self, ctx, number: int):

        # Make sure the player has a game running
        if ctx.author.id not in pandora_games:
            await ctx.send("❌ You don't have an active Pandora's Box game.")
            return

        game = pandora_games[ctx.author.id]

        # Make sure the number exists on the board
        if number not in game["board"]:
            await ctx.send("❌ That number is not on your Pandora board.")
            return

        # Prevent duplicate searches
        if number in game["searched"]:
            await ctx.send("⚠️ You've already searched that number.")
            return

        # Record the search
        game["searched"].add(number)

        # Empty location
        if number not in game["jewels"]:
            await ctx.send("Nothing was hidden there...")
            return

        # Jewel found!
        letter = game["jewels"][number]
        game["letters_found"].append(letter)

        found = " ".join(game["letters_found"])

        await ctx.send(
            f"💎 **You found a jewel!**\n\n"
            f"Letter Found: **{letter}**\n\n"
            f"Letters Collected:\n{found}"
        )

        # All four letters found
        if len(game["letters_found"]) == 4:
            await ctx.send(
                "🔓 You have found all four letters!\n\n"
                "Use `!unlock ABCD` to attempt opening Pandora's Box."
            )

    @commands.command(name="unlock")
    async def unlock(self, ctx, guess: str):

        # Make sure the player has a game running
        if ctx.author.id not in pandora_games:
            await ctx.send("❌ You don't have an active Pandora's Box game.")
            return

        game = pandora_games[ctx.author.id]

        # Make sure all letters have been found first
        if len(game["letters_found"]) < 4:
            await ctx.send(
                "❌ You haven't found all four letters yet!"
            )
            return

        guess = guess.upper()

        # Must be exactly 4 letters
        if len(guess) != 4 or not guess.isalpha():
            await ctx.send(
                "❌ Your guess must be exactly 4 letters.\n"
                "Example: `!unlock ABCD`"
            )
            return

        # Correct code
        if guess == game["code"]:

            await ctx.send(
                "🎉 **Pandora's Box has opened!**\n\n"
                f"🔓 Correct Code: **{game['code']}**"
            )

            # Remove completed game
            pandora_games.pop(ctx.author.id)

            return

        # Wrong code
        await ctx.send(
            "❌ The box remains sealed..."
        )


async def setup(bot):
    await bot.add_cog(Pandora(bot))
