"""FowAscends Deobfuscator: Discord bot.

The token is read from the DISCORD_TOKEN environment variable (set it in the
Railway service's Variables tab). Nothing secret lives in the code.

Optional variables: GUILD_ID (instant command sync in one server),
MAX_FILE_BYTES, MAX_CONCURRENT, MAX_QUEUE, RUN_TIMEOUT, COOLDOWN_SECONDS.
"""
import asyncio
import gzip
import io
import logging
import os
import re
import sys
from pathlib import Path

import discord
from discord import app_commands

import runner

BRAND = "FowAscends Deobfuscator"
COLOR = 0x7C5CFF
EXTENSIONS = (".lua", ".luau", ".txt")
UPLOAD_LIMIT = 8_000_000          # stay under Discord's default upload cap


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


MAX_FILE_BYTES = env_int("MAX_FILE_BYTES", 2_000_000)
MAX_CONCURRENT = max(1, env_int("MAX_CONCURRENT", 2))
MAX_QUEUE = env_int("MAX_QUEUE", 5)
RUN_TIMEOUT = max(30, env_int("RUN_TIMEOUT", 120))
COOLDOWN = env_int("COOLDOWN_SECONDS", 30)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fowascends")

slots = asyncio.Semaphore(MAX_CONCURRENT)
waiting = 0


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())   # slash commands only: no privileged intents
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild_id = os.environ.get("GUILD_ID")
        if guild_id and guild_id.isdigit():
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        log.info("Logged in as %s (%s guilds)", self.user, len(self.guilds))
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, name="/deobfuscate"))


bot = Bot()


def clean_name(filename: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(filename).stem)[:40].strip("._") or "script"
    return stem + ".fowascends.lua"


def fmt_size(n: int) -> str:
    return "%.1f KB" % (n / 1024) if n < 1_000_000 else "%.2f MB" % (n / 1_000_000)


@bot.tree.command(name="deobfuscate",
                  description="Run a Roblox script in a sandbox and get a readable trace of what it does")
@app_commands.describe(file="The script (.lua, .luau or .txt)",
                       private="Only you can see the result (default: yes)")
@app_commands.checks.cooldown(1, COOLDOWN, key=lambda i: i.user.id)
async def deobfuscate(interaction: discord.Interaction, file: discord.Attachment, private: bool = True):
    global waiting
    if not file.filename.lower().endswith(EXTENSIONS):
        await interaction.response.send_message("Upload a `.lua`, `.luau` or `.txt` file.", ephemeral=True)
        return
    if file.size > MAX_FILE_BYTES:
        await interaction.response.send_message(
            "That file is %s; the limit is %s." % (fmt_size(file.size), fmt_size(MAX_FILE_BYTES)), ephemeral=True)
        return
    if waiting >= MAX_QUEUE:
        await interaction.response.send_message("I'm busy right now. Try again in a minute.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=private, thinking=True)
    waiting += 1
    queued = True
    try:
        data = await file.read()
        async with slots:
            waiting -= 1
            queued = False
            res = await runner.run(data, RUN_TIMEOUT)
    except Exception:   # noqa: BLE001 - never leave the user hanging
        log.exception("deobfuscate failed")
        await interaction.followup.send("Something went wrong on my side. Try again later.", ephemeral=private)
        return
    finally:
        if queued:
            waiting -= 1   # failed before getting a slot

    if not res.ok:
        embed = discord.Embed(title="Couldn't process that script", description=res.error, color=0xE5484D)
        embed.set_footer(text=BRAND)
        await interaction.followup.send(embed=embed, ephemeral=private)
        return

    body, name = res.output, clean_name(file.filename)
    if len(body) > UPLOAD_LIMIT:
        body, name = gzip.compress(body), name + ".gz"
        if len(body) > UPLOAD_LIMIT:
            await interaction.followup.send("The result is too large to upload.", ephemeral=private)
            return

    embed = discord.Embed(title=BRAND, color=COLOR)
    embed.add_field(name="Detected", value=res.obfuscator, inline=True)
    embed.add_field(name="Time", value="%.1fs" % res.seconds, inline=True)
    embed.add_field(name="Output", value=fmt_size(len(res.output)), inline=True)
    if res.hints:
        embed.add_field(name="Behaviours spotted",
                        value="\n".join("- %s (x%d)" % h for h in res.hints)[:1000], inline=False)
    else:
        embed.add_field(name="Behaviours spotted", value="Nothing from the watch list.", inline=False)
    embed.set_footer(text="Behaviour trace: only the code paths that ran are shown. "
                          "Hints are heuristics, not a verdict.")
    await interaction.followup.send(embed=embed, file=discord.File(io.BytesIO(body), filename=name),
                                    ephemeral=private)


@bot.tree.command(name="about", description="What this bot does and doesn't do")
async def about(interaction: discord.Interaction):
    embed = discord.Embed(title=BRAND, color=COLOR, description=(
        "Runs a Roblox script inside a sandboxed Luau VM with a fake Roblox environment and "
        "returns a readable trace of what it does to it (HTTP calls, webhooks, loadstring, "
        "remote events, UI, ...).\n\n"
        "- Nothing is fetched from the internet and nothing touches Roblox.\n"
        "- Only the branches that actually ran are shown.\n"
        "- Use `/deobfuscate` and attach a `.lua`, `.luau` or `.txt` file."))
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.error
async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandOnCooldown):
        msg = "Slow down: try again in %ds." % int(error.retry_after + 1)
    else:
        log.exception("command error", exc_info=error)
        msg = "Something went wrong."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


def main():
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        sys.exit("DISCORD_TOKEN is not set. In Railway: service -> Variables -> add DISCORD_TOKEN.")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
