import discord
from config import TOKEN, GUILD_IDS
from cogs.user_commands import my_ckey, change_my_name_color, add_disposable, roll
from cogs.role_events import on_member_update
from cogs.db_commands import top_play_time, top_balance
from cogs.achievements import get_reachs, set_reach
from database import db
from services.achievements_catalog import catalog

intents = discord.Intents.default()
intents.members = True
intents.guilds = True

bot = discord.Bot(intents=intents)


@bot.event
async def on_ready():
    # Подключение к базе данных
    await db.connect()
    print('База данных подключена')

    # Загрузка каталога достижений
    try:
        catalog.load()
        print(f'Каталог достижений загружен: {len(catalog.get_all())} достижений')
    except Exception as e:
        print(f'Ошибка при загрузке каталога достижений: {e}')

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
bot.slash_command(
    name='top_balance',
    description='Показать топ-10 игроков по банковскому балансу.',
    guild_ids=GUILD_IDS
)(top_balance)
bot.slash_command(
    name='roll',
    description='Бросить кубики. Формат: nd+n (например, 1d6+2 или 2d20).',
    guild_ids=GUILD_IDS
)(roll)
bot.slash_command(
    name='get_reachs',
    description='Получить список достижений игрока по его имени в SS14.',
    guild_ids=GUILD_IDS
)(get_reachs)
bot.slash_command(
    name='set_reach',
    description='Выдать достижение игроку через dropdown меню (требуются права).',
    guild_ids=GUILD_IDS
)(set_reach)


bot.event(on_member_update)

bot.run(TOKEN)
