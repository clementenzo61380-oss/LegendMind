
import discord
import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
from database import init_db

load_dotenv()

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        await init_db()
        # Liste des extensions à charger
        extensions = ['cogs.vision', 'cogs.progression', 'cogs.meta', 'cogs.guerre', 'cogs.coach', 'cogs.admin']
        for ext in extensions:
            try:
                await self.load_extension(ext)
                print(f'✅ {ext} chargé')
            except Exception as e:
                print(f'❌ Erreur sur {ext}: {e}')
        
        # SYNCHRO FORCEE
        print('⏳ Synchronisation des commandes slash...')
        synced = await self.tree.sync()
        print(f'🚀 {len(synced)} commandes synchronisées !')

bot = MyBot()

@bot.event
async def on_ready():
    print(f'✨ Connecté en tant que {bot.user}')

async def main():
    async with bot:
        await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())

# ── Entraînement automatique hebdomadaire ──────────────────────
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import subprocess

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job("cron", day_of_week="mon", hour=3, minute=0)
def weekly_training():
    print("[TRAINER] Entraînement hebdomadaire lancé...")
    subprocess.Popen(["python3", "trainer.py"])

scheduler.start()
