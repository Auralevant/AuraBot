"""
Shape Punch — Discord ORG challenge cog
-----------------------------------------------
Single-player game. Each round shows 3 shapes, each containing the name of
a DIFFERENT shape. 6 of the 7 shapes (club, spade, heart, diamond, circle,
square, triangle) appear somewhere in the image — either as a drawn figure
or as a word inside another figure. The player has to name the ONE shape
that appears NEITHER as a figure NOR as a word.

Usage: !shapepunch  (start a 10-round game for the player who ran it)
Answer each round by just typing the shape name in the same channel.

This cog does NOT persist scores anywhere — at the end of a game it prints
the final result dict to console and you can hook `on_game_complete`
(see bottom of file) to save it into whatever storage you're already using.
"""

import asyncio
import io
import math
import os
import random
import time

import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

SHAPES = ["club", "spade", "heart", "diamond", "circle", "square", "triangle"]

ROUNDS_PER_GAME = 10
ROUND_TIMEOUT_SECONDS = 30  # counts as wrong if they don't answer in time

RED = (200, 30, 30)
BLACK = (20, 20, 20)
WHITE = (255, 255, 255)

CELL_SIZE = 300
PADDING = 30

FONT_PATHS = [
    # Bundled with this cog — put DejaVuSans-Bold.ttf in a "fonts" folder
    # next to this file so text renders identically no matter what fonts
    # (if any) happen to be installed on the host. This is checked first.
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "DejaVuSans-Bold.ttf"),
    # Fallbacks in case the bundled font is missing for some reason.
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/local/lib/python3.12/dist-packages/matplotlib/mpl-data/fonts/ttf/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def get_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ----------------------------------------------------------------------
# Shape drawing (all shapes are drawn RED, filling roughly the same area)
# ----------------------------------------------------------------------

def _draw_circle(draw, cx, cy, s):
    r = s * 0.45
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RED)


def _draw_square(draw, cx, cy, s):
    r = s * 0.42
    draw.rectangle([cx - r, cy - r, cx + r, cy + r], fill=RED)


def _draw_triangle(draw, cx, cy, s):
    r = s * 0.5
    pts = [(cx, cy - r), (cx - r * 0.95, cy + r * 0.8), (cx + r * 0.95, cy + r * 0.8)]
    draw.polygon(pts, fill=RED)


def _draw_diamond(draw, cx, cy, s):
    r = s * 0.48
    pts = [(cx, cy - r), (cx + r * 0.75, cy), (cx, cy + r), (cx - r * 0.75, cy)]
    draw.polygon(pts, fill=RED)


def _heart_curve_points(cx, cy, scale, flip=False, n=200):
    """Smooth parametric heart outline (much cleaner than stitched ellipses)."""
    pts = []
    for i in range(n):
        t = (i / n) * 2 * math.pi
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        if flip:
            y = -y
        pts.append((cx + x * scale, cy - y * scale))
    return pts


def _draw_heart(draw, cx, cy, s):
    scale = s / 34.0
    # bbox of the curve isn't symmetric around the formula's (0,0), so shift
    # so the heart's visual bounding box is centered in the cell like the
    # other shapes.
    center_y = cy - 2.54 * scale
    pts = _heart_curve_points(cx, center_y, scale, flip=False)
    draw.polygon(pts, fill=RED)


def _draw_spade(draw, cx, cy, s):
    scale = s * 0.78 / 34.0
    center_y = cy - s * 0.16
    pts = _heart_curve_points(cx, center_y, scale, flip=True)
    draw.polygon(pts, fill=RED)

    # The naive vertical flip of the heart formula leaves a small concave
    # notch between the two lobes (visible as a white gap right above the
    # stem). Patch it by filling the valley between the lobes solid red.
    n = 80
    patch_raw = []
    for i in range(n + 1):
        t = -0.7 + (1.4 * i / n)
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        patch_raw.append((x, y))
    cap = 13.5  # deeper than the lobes' own max (~11.9), guarantees overlap
    patch_pts = [(cx + patch_raw[0][0] * scale, center_y + cap * scale)]
    patch_pts += [(cx + x * scale, center_y + y * scale) for x, y in patch_raw]
    patch_pts += [(cx + patch_raw[-1][0] * scale, center_y + cap * scale)]
    draw.polygon(patch_pts, fill=RED)

    stem_w = s * 0.09
    stem_top = center_y + 10 * scale
    draw.polygon([
        (cx - stem_w, stem_top),
        (cx + stem_w, stem_top),
        (cx + stem_w * 1.9, cy + s * 0.44),
        (cx - stem_w * 1.9, cy + s * 0.44),
    ], fill=RED)


def _draw_club(draw, cx, cy, s):
    r = s * 0.24
    center_y = cy - s * 0.08
    offset = r * 0.85
    lobe_centers = [
        (cx, center_y - offset * 1.15),
        (cx - offset * 1.05, center_y + offset * 0.55),
        (cx + offset * 1.05, center_y + offset * 0.55),
    ]
    for (lx, ly) in lobe_centers:
        draw.ellipse([lx - r, ly - r, lx + r, ly + r], fill=RED)
    stem_w = s * 0.09
    draw.polygon([
        (cx - stem_w, center_y + r * 0.3),
        (cx + stem_w, center_y + r * 0.3),
        (cx + stem_w * 1.8, cy + s * 0.42),
        (cx - stem_w * 1.8, cy + s * 0.42),
    ], fill=RED)


SHAPE_FUNCS = {
    "circle": _draw_circle,
    "square": _draw_square,
    "triangle": _draw_triangle,
    "diamond": _draw_diamond,
    "heart": _draw_heart,
    "spade": _draw_spade,
    "club": _draw_club,
}


def render_cell(figure_shape: str, word: str) -> Image.Image:
    img = Image.new("RGB", (CELL_SIZE, CELL_SIZE), WHITE)
    draw = ImageDraw.Draw(img)
    cx, cy = CELL_SIZE // 2, CELL_SIZE // 2
    SHAPE_FUNCS[figure_shape](draw, cx, cy, CELL_SIZE * 0.85)

    text = word.upper()
    max_text_width = CELL_SIZE * 0.85
    font_size = int(CELL_SIZE * 0.26)
    font = get_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    # Shrink to fit for longer words (e.g. "TRIANGLE", "DIAMOND") so nothing
    # ever runs off the edge of the cell.
    while tw > max_text_width and font_size > 10:
        font_size -= 2
        font = get_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx, ty = cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]
    # Plain black text, no white halo/background — just solid black on red.
    draw.text((tx, ty), text, font=font, fill=BLACK)
    return img


def render_round_image(pairs: list[tuple[str, str]]) -> io.BytesIO:
    """pairs: list of (figure_shape, word) tuples, length 3."""
    width = CELL_SIZE * 3 + PADDING * 4
    height = CELL_SIZE + PADDING * 2
    canvas = Image.new("RGB", (width, height), WHITE)
    for i, (figure_shape, word) in enumerate(pairs):
        cell = render_cell(figure_shape, word)
        x = PADDING + i * (CELL_SIZE + PADDING)
        canvas.paste(cell, (x, PADDING))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ----------------------------------------------------------------------
# Round generation
# ----------------------------------------------------------------------

def generate_round() -> tuple[list[tuple[str, str]], str]:
    """
    Returns (pairs, answer) where pairs is a list of 3 (figure_shape, word)
    tuples and answer is the shape name that appears NEITHER as a figure
    NOR as a word.
    """
    shuffled = SHAPES[:]
    random.shuffle(shuffled)

    answer = shuffled[0]
    remaining = shuffled[1:]  # 6 shapes

    figures = remaining[:3]
    words = remaining[3:]
    random.shuffle(words)  # random bijection figures -> words

    pairs = list(zip(figures, words))
    random.shuffle(pairs)  # randomize display order too
    return pairs, answer


# ----------------------------------------------------------------------
# Cog
# ----------------------------------------------------------------------

class ShapePunch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: set[int] = set()  # user_ids currently mid-game

    @commands.command(name="shapepunch")
    async def shapepunch(self, ctx: commands.Context):
        if ctx.author.id in self.active_games:
            await ctx.send(f"{ctx.author.mention} you're already mid-game — finish that one first!")
            return

        self.active_games.add(ctx.author.id)
        try:
            await self.run_game(ctx)
        finally:
            self.active_games.discard(ctx.author.id)

    async def run_game(self, ctx: commands.Context):
        await ctx.send(
            f"🥊 **Shape Punch** — {ctx.author.mention}, get ready!\n"
            f"Each round shows 3 shapes, each with another shape's name inside it. "
            f"6 of the 7 shapes will appear (by figure or by word) — type the **one that's missing**.\n"
            f"{ROUNDS_PER_GAME} rounds. You have {ROUND_TIMEOUT_SECONDS}s per round. Round 1 coming up..."
        )
        await asyncio.sleep(2)

        correct_count = 0
        start_time = time.perf_counter()

        for round_num in range(1, ROUNDS_PER_GAME + 1):
            pairs, answer = generate_round()
            image_buf = render_round_image(pairs)
            file = discord.File(fp=image_buf, filename="round.png")

            await ctx.send(
                f"**Round {round_num}/{ROUNDS_PER_GAME}** — which shape is missing?",
                file=file,
            )

            def check(m: discord.Message):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            try:
                msg = await self.bot.wait_for("message", check=check, timeout=ROUND_TIMEOUT_SECONDS)
                guess = msg.content.strip().lower()
            except asyncio.TimeoutError:
                await ctx.send(f"⏱️ Time's up! The answer was **{answer.upper()}**.")
                continue

            if guess == answer:
                correct_count += 1
                await ctx.send(f"✅ Correct! It was **{answer.upper()}**.")
            else:
                await ctx.send(f"❌ Wrong. The answer was **{answer.upper()}**.")

        total_time = time.perf_counter() - start_time

        result = {
            "user_id": ctx.author.id,
            "username": str(ctx.author),
            "score": correct_count,
            "total_rounds": ROUNDS_PER_GAME,
            "time_seconds": round(total_time, 2),
        }

        embed = discord.Embed(
            title="🥊 Shape Punch — Results",
            color=discord.Color.red(),
        )
        embed.add_field(name="Player", value=ctx.author.mention, inline=True)
        embed.add_field(name="Score", value=f"{correct_count}/{ROUNDS_PER_GAME}", inline=True)
        embed.add_field(name="Time", value=f"{total_time:.2f}s", inline=True)
        await ctx.send(embed=embed)

        # Hook point: save `result` into your own storage/leaderboard system here.
        self.bot.dispatch("shape_punch_complete", result)
        print(f"[ShapePunch] game complete: {result}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ShapePunch(bot))
