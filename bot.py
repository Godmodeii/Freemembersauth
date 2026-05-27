import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio
import urllib.parse
from aiohttp import web

# ─── CONFIG ────────────────────────────────────────────────
BOT_TOKEN      = "MTUwOTI3MDUxNDI5MDY1OTQ2OA.G9eh2_.BY296vvNUErFVY_sFGu5NQx33QJkGRkNt1PZEc"
CLIENT_ID      = "1509270514290659468"
CLIENT_SECRET  = "McbeQLpPTwfaY5_70vKhyCpD-qHnEr-A"
REDIRECT_URI   = "https://YOUR_APP.base44.app/callback"  # <-- update
API_BASE       = "https://discord.com/api/v10"
BASE44_API_KEY = "YOUR_BASE44_API_KEY"  # <-- get from Base44 > Settings > API
BASE44_BASE    = "https://api.base44.app/api/entities"
HEADERS        = {"api_key": BASE44_API_KEY, "Content-Type": "application/json"}

# ─── BASE44 HELPERS ─────────────────────────────────────────
async def get_tokens(session):
    async with session.get(f"{BASE44_BASE}/AuthToken", headers=HEADERS) as r:
        data = await r.json()
        return [t for t in data if t.get("status") == "active"]

async def create_job(session, guild_id, amount):
    payload = {"guild_id": guild_id, "amount": amount, "status": "running"}
    async with session.post(f"{BASE44_BASE}/PullJob", json=payload, headers=HEADERS) as r:
        return await r.json()

async def update_job(session, job_id, success, fail):
    payload = {"success_count": success, "fail_count": fail, "status": "completed"}
    async with session.patch(f"{BASE44_BASE}/PullJob/{job_id}", json=payload, headers=HEADERS) as r:
        return await r.json()

async def save_token(session, user_id, username, access_token, refresh_token):
    payload = {
        "discord_user_id": str(user_id), "username": username,
        "access_token": access_token, "refresh_token": refresh_token, "status": "active"
    }
    async with session.post(f"{BASE44_BASE}/AuthToken", json=payload, headers=HEADERS) as r:
        return await r.json()

# ─── BOT ────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

@bot.event
async def on_ready():
    await tree.sync()
    print(f"[Memberify] Online as {bot.user}")

# ─── /pull ──────────────────────────────────────────────────
@tree.command(name="pull", description="Pull backed-up members into a server")
@app_commands.describe(guild_id="Target server ID", amount="How many members to pull")
@app_commands.checks.has_permissions(administrator=True)
async def pull(interaction: discord.Interaction, guild_id: str, amount: int):
    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        tokens = await get_tokens(session)
        to_use = tokens[:amount]
        if not to_use:
            return await interaction.followup.send("No active tokens available.", ephemeral=True)
        job = await create_job(session, guild_id, len(to_use))
        job_id = job.get("id")
        await interaction.followup.send(
            f"Pulling {len(to_use)} members into {guild_id}... Job ID: {job_id}",
            ephemeral=True
        )
        success, fail = 0, 0
        for token in to_use:
            url = f"{API_BASE}/guilds/{guild_id}/members/{token['discord_user_id']}"
            bot_headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
            try:
                async with session.put(url, json={"access_token": token["access_token"]}, headers=bot_headers) as r:
                    if r.status in (200, 201, 204): success += 1
                    else: fail += 1
            except Exception: fail += 1
            await asyncio.sleep(1.2)
        await update_job(session, job_id, success, fail)
        await interaction.followup.send(f"Done! {success} joined, {fail} failed", ephemeral=True)

# ─── /tokens ────────────────────────────────────────────────
@tree.command(name="tokens", description="Show stored token count")
@app_commands.checks.has_permissions(administrator=True)
async def tokens_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    async with aiohttp.ClientSession() as session:
        all_tokens = await get_tokens(session)
    embed = discord.Embed(title="Token Stats", color=0x5865F2)
    embed.add_field(name="Active Tokens", value=str(len(all_tokens)), inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)

# ─── /authlink ──────────────────────────────────────────────
@tree.command(name="authlink", description="Get the OAuth authorization link")
async def authlink(interaction: discord.Interaction):
    scopes = "identify guilds.join"
    link = (
        f"https://discord.com/oauth2/authorize"
        f"?client_id={CLIENT_ID}&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&scope={urllib.parse.quote(scopes)}"
    )
    embed = discord.Embed(title="Authorization Link", description=f"[Click here]({link})", color=0x5865F2)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ─── /status ────────────────────────────────────────────────
@tree.command(name="status", description="Show bot status")
async def status(interaction: discord.Interaction):
    embed = discord.Embed(title="Memberify by Dujin", color=0x57F287)
    embed.add_field(name="Guilds", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)}ms", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ─── OAUTH CALLBACK SERVER ──────────────────────────────────
async def handle_callback(request):
    code = request.rel_url.query.get("code")
    if not code:
        return web.Response(text="No code.", status=400)
    async with aiohttp.ClientSession() as session:
        data = {
            "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
            "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
        }
        async with session.post(f"{API_BASE}/oauth2/token", data=data) as r:
            token_data = await r.json()
        if "access_token" not in token_data:
            return web.Response(text=f"Failed: {token_data}", status=400)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        async with session.get(f"{API_BASE}/users/@me",
                               headers={"Authorization": f"Bearer {access_token}"}) as r:
            user = await r.json()
        await save_token(session, user["id"], user["username"], access_token, refresh_token)
    return web.Response(
        text="<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
             "<h2>Authorized!</h2><p>Token saved. You can close this tab.</p></body></html>",
        content_type="text/html"
    )

async def main():
    app = web.Application()
    app.router.add_get("/callback", handle_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()
    print("[Memberify] OAuth server on :8000")
    await bot.start(BOT_TOKEN)

asyncio.run(main())
