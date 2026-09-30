# FowAscends Deobfuscator (Discord bot)

Slash command `/deobfuscate` + a `.lua` / `.luau` / `.txt` attachment. The bot runs the script in a sandboxed
Luau VM against a fake Roblox environment and replies with a readable **behaviour trace** plus a short list of
notable behaviours (webhooks, HTTP requests, loadstring, clipboard, kicks, ...). It is always started with
`--no-devirt`: trace only, only the code paths that actually ran. `/about` explains this to users.

## 1. Discord setup
1. https://discord.com/developers/applications -> **New Application** -> name it *FowAscends Deobfuscator*.
2. **Bot** tab -> **Reset Token** -> copy it (you only see it once). No privileged intents are needed.
3. **OAuth2 -> URL Generator**: scopes `bot` + `applications.commands`; permissions `Send Messages`,
   `Attach Files`, `Embed Links`. Open the URL to invite the bot.

## 2. Deploy on Railway
1. Push this folder to a **private** GitHub repo (`.env` is git-ignored; never commit the token).
2. Railway -> **New Project -> Deploy from GitHub repo**. It picks up `railway.json` and builds the `Dockerfile`
   (first build compiles Luau, a few minutes).
3. Service -> **Variables** -> add `DISCORD_TOKEN` = your bot token. Optionally `GUILD_ID` for instant command sync.
4. Deploy. Logs should show `Logged in as ...`. No port or domain is needed: it's a worker.

## Settings (all optional)
| Variable | Default | Meaning |
|---|---|---|
| `MAX_FILE_BYTES` | 2000000 | Largest accepted upload |
| `MAX_CONCURRENT` | 2 | Scripts running at once |
| `MAX_QUEUE` | 5 | Waiting requests before "busy" |
| `RUN_TIMEOUT` | 120 | Hard limit per script (s) |
| `COOLDOWN_SECONDS` | 30 | Per-user cooldown |

## Notes
- Uploaded scripts are *executed* (in Luau with a fake environment; Luau has no network or file access). The
  container runs as a non-root user; keep Railway's resource limits on.
- `deobf/` is your engine, unchanged. The header it writes into results (`base.py`, `credit_header`) credits
  **ccjvwsod**; the bot's own branding is FowAscends Deobfuscator.
- Local run: `pip install -r requirements.txt`, build Luau with `python deobf/build_luau.py` (also needs
  `luau-ast` in `deobf/bin/`), set `DISCORD_TOKEN`, `python bot.py`.
