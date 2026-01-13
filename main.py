import discord
from config import TOKEN, GUILD_IDS
from user_commands import my_ckey, change_my_name_color, add_disposable
from role_events import on_member_update
from db_commands import top_play_time
from database import db

intents = discord.Intents.default()
intents.members = True
intents.guilds = True

bot = discord.Bot(intents=intents)


@bot.event
async def on_ready():
    # Подключение к базе данных
    await db.connect()
    print('База данных подключена')

    for guild in bot.guilds:
        print(f'Бот подключен к серверу: {guild.name}')


@bot.event
async def on_close():
    """Закрытие соединения с БД при выключении бота."""
    await db.disconnect()
    print('База данных отключена')


bot.slash_command(name='my_ckey', description='Укажите ваш сикей в игре.', guild_ids=GUILD_IDS)(my_ckey)
bot.slash_command(
    name='change_my_name_color',
    description='Изменить цвет вашего имени на сайте, указав HEX-код цвета.',
    guild_ids=GUILD_IDS
)(change_my_name_color)
bot.slash_command(
    name='add_disposable',
    description='Добавить токены пользователю по его ckey.',
    guild_ids=GUILD_IDS
)(add_disposable)
bot.slash_command(
    name='top_play_time',
    description='Показать топ-10 игроков по наигранному времени.',
    guild_ids=GUILD_IDS
)(top_play_time)


bot.event(on_member_update)

bot.run(TOKEN)
