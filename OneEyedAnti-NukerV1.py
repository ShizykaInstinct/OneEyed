import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from collections import defaultdict
import time
import json
import os

# Настройки бота
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

# Настройки антинюка (будут загружены из файла)
THRESHOLD_BANS = 3  # Максимум банов за интервал времени
THRESHOLD_DELETIONS = 3  # Максимум удалений каналов/ролей
TIME_WINDOW = 60  # Временной интервал в секундах
LOG_CHANNEL_ID = 1375146864327917711  # ID канала для логов
WHITELIST = {1375146864327917711}  # ID пользователей в белом списке
GUILD_ID = 1340646467031007305  # ID вашего сервера
CONFIG_FILE = "config.json"  # Файл для хранения конфигурации

# Хранилище для отслеживания действий
ban_tracker = defaultdict(list)
deletion_tracker = defaultdict(list)

# Функция для загрузки конфигурации из файла
def load_config():
    global THRESHOLD_BANS, THRESHOLD_DELETIONS, TIME_WINDOW, LOG_CHANNEL_ID, WHITELIST
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                THRESHOLD_BANS = config.get('threshold_bans', THRESHOLD_BANS)
                THRESHOLD_DELETIONS = config.get('threshold_deletions', THRESHOLD_DELETIONS)
                TIME_WINDOW = config.get('time_window', TIME_WINDOW)
                LOG_CHANNEL_ID = config.get('log_channel_id', LOG_CHANNEL_ID)
                WHITELIST = set(config.get('whitelist', list(WHITELIST)))
            print(f"Конфигурация загружена: {config}")
        except Exception as e:
            print(f"Ошибка при загрузке конфигурации: {e}")
            save_config()  # Создаём файл с настройками по умолчанию
    else:
        print("Файл конфигурации не найден, создаём новый с настройками по умолчанию.")
        save_config()

# Функция для сохранения конфигурации в файл
def save_config():
    global THRESHOLD_BANS, THRESHOLD_DELETIONS, TIME_WINDOW, LOG_CHANNEL_ID, WHITELIST
    config = {
        'threshold_bans': THRESHOLD_BANS,
        'threshold_deletions': THRESHOLD_DELETIONS,
        'time_window': TIME_WINDOW,
        'log_channel_id': LOG_CHANNEL_ID,
        'whitelist': list(WHITELIST)
    }
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        print(f"Конфигурация сохранена: {config}")
    except Exception as e:
        print(f"Ошибка при сохранении конфигурации: {e}")

@bot.event
async def on_ready():
    print(f'Бот {bot.user} готов к работе!')
    # Загружаем конфигурацию при запуске
    load_config()
    try:
        # Проверка, находится ли бот на сервере
        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            print(f"Ошибка: Бот не находится на сервере с ID {GUILD_ID}. Убедитесь, что бот приглашён и GUILD_ID правильный.")
            return
        
        # Синхронизация slash-команд для конкретного сервера
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"Синхронизировано {len(synced)} slash-команд для сервера {GUILD_ID}")
    except discord.errors.Forbidden as e:
        print(f"Ошибка синхронизации: Недостаточно прав (403 Forbidden). Убедитесь, что бот имеет разрешение 'applications.commands'. Ошибка: {e}")
    except Exception as e:
        print(f"Ошибка синхронизации slash-команд: {e}")

# Обработка массовых банов
@bot.event
async def on_member_ban(guild, user):
    async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=1):
        if entry.user.id in WHITELIST or entry.user == bot.user:
            return
        
        current_time = time.time()
        ban_tracker[entry.user.id].append(current_time)
        
        # Удаляем старые записи
        ban_tracker[entry.user.id] = [t for t in ban_tracker[entry.user.id] if current_time - t < TIME_WINDOW]
        
        if len(ban_tracker[entry.user.id]) >= THRESHOLD_BANS:
            await handle_violation(guild, entry.user, f"Массовый бан ({len(ban_tracker[entry.user.id])} банов за {TIME_WINDOW} секунд)")

# Обработка удаления каналов
@bot.event
async def on_guild_channel_delete(channel):
    async for entry in channel.guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=1):
        if entry.user.id in WHITELIST or entry.user == bot.user:
            return
        
        current_time = time.time()
        deletion_tracker[entry.user.id].append(current_time)
        
        deletion_tracker[entry.user.id] = [t for t in deletion_tracker[entry.user.id] if current_time - t < TIME_WINDOW]
        
        if len(deletion_tracker[entry.user.id]) >= THRESHOLD_DELETIONS:
            await handle_violation(channel.guild, entry.user, f"Массовое удаление каналов ({len(deletion_tracker[entry.user.id])} за {TIME_WINDOW} секунд)")

@bot.event
async def on_guild_role_delete(role):
    async for entry in role.guild.audit_logs(action=discord.AuditLogAction.role_delete, limit=1):
        if entry.user.id in WHITELIST or entry.user == bot.user:
            return
        
        current_time = time.time()
        deletion_tracker[entry.user.id].append(current_time)
        
        deletion_tracker[entry.user.id] = [t for t in deletion_tracker[entry.user.id] if current_time - t < TIME_WINDOW]
        
        if len(deletion_tracker[entry.user.id]) >= THRESHOLD_DELETIONS:
            await handle_violation(role.guild, entry.user, f"Массовое удаление ролей ({len(deletion_tracker[entry.user.id])} за {TIME_WINDOW} секунд)")

async def handle_violation(guild, user, reason):
    try:
        await guild.ban(user, reason=reason)
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"Пользователь {user.mention} ({user.id}) забанен за: {reason}")
    except discord.Forbidden:
        print(f"Ошибка: Нет прав для бана {user.name}")
    except Exception as e:
        print(f"Ошибка при обработке нарушения: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def whitelist(ctx, user: discord.User):
    global WHITELIST
    WHITELIST.add(user.id)
    save_config()  
    await ctx.send(f"Пользователь {user.mention} добавлен в белый список.")

@bot.command()
@commands.has_permissions(administrator=True)
async def remove_whitelist(ctx, user: discord.User):
    global WHITELIST
    if user.id in WHITELIST:
        WHITELIST.remove(user.id)
        save_config()  
        await ctx.send(f"Пользователь {user.mention} удалён из белого списка.")
    else:
        await ctx.send(f"Пользователь {user.mention} не находится в белом списке.")

class ConfigModal(discord.ui.Modal, title="Настройка Антинюкера"):
    ban_threshold = discord.ui.TextInput(
        label="Порог банов",
        default=str(THRESHOLD_BANS),
        placeholder="Введите количество банов для срабатывания",
        required=True
    )
    deletion_threshold = discord.ui.TextInput(
        label="Порог удалений",
        default=str(THRESHOLD_DELETIONS),
        placeholder="Введите количество удалений для срабатывания",
        required=True
    )
    time_window = discord.ui.TextInput(
        label="Временной интервал (сек)",
        default=str(TIME_WINDOW),
        placeholder="Введите интервал в секундах",
        required=True
    )
    log_channel = discord.ui.TextInput(
        label="ID канала логов",
        default=str(LOG_CHANNEL_ID),
        placeholder="Введите ID канала для логов",
        required=True
    )
    whitelist_ids = discord.ui.TextInput(
        label="Управление whitelist (ID: +/-/)",
        default=", ".join(str(id) for id in WHITELIST),
        placeholder="Пример: +123456789,-987654321",
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        global THRESHOLD_BANS, THRESHOLD_DELETIONS, TIME_WINDOW, LOG_CHANNEL_ID, WHITELIST
        try:
            new_ban_threshold = int(self.ban_threshold.value)
            new_deletion_threshold = int(self.deletion_threshold.value)
            new_time_window = int(self.time_window.value)
            new_log_channel = int(self.log_channel.value)

            if new_ban_threshold <= 0 or new_deletion_threshold <= 0 or new_time_window <= 0:
                await interaction.response.send_message("Ошибка: Значения должны быть больше 0!", ephemeral=True)
                return

            # Проверка существования канала
            channel = bot.get_channel(new_log_channel)
            if not channel:
                await interaction.response.send_message("Ошибка: Указанный канал логов не существует!", ephemeral=True)
                return

            # Обновление настроек
            THRESHOLD_BANS = new_ban_threshold
            THRESHOLD_DELETIONS = new_deletion_threshold
            TIME_WINDOW = new_time_window
            LOG_CHANNEL_ID = new_log_channel

            # Обработка управления белым списком
            if self.whitelist_ids.value:
                try:
                    add_ids = set()
                    remove_ids = set()
                    for item in self.whitelist_ids.value.split(','):
                        item = item.strip()
                        if item.startswith('+'):
                            add_ids.add(int(item[1:].strip()))
                        elif item.startswith('-'):
                            remove_ids.add(int(item[1:].strip()))
                    WHITELIST.update(add_ids)
                    WHITELIST.difference_update(remove_ids)
                except ValueError:
                    await interaction.response.send_message("Ошибка: ID должны быть числами, используйте + для добавления, - для удаления!", ephemeral=True)
                    return

            # Сохраняем обновлённую конфигурацию
            save_config()

            # Отправка подтверждения
            response = (
                "✅ **Конфигурация обновлена!**\n"
                f"Порог банов: {THRESHOLD_BANS} за {TIME_WINDOW} секунд\n"
                f"Порог удалений: {THRESHOLD_DELETIONS} за {TIME_WINDOW} секунд\n"
                f"Канал логов: <#{LOG_CHANNEL_ID}>\n"
                f"Белый список: {', '.join(str(id) for id in WHITELIST) or 'Пусто'}"
            )
            await interaction.response.send_message(response, ephemeral=True)

        except ValueError:
            await interaction.response.send_message("Ошибка: Введите числовые значения для порогов, интервала и ID канала!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Ошибка при обновлении настроек: {e}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.response.send_message("Произошла ошибка при обработке формы!", ephemeral=True)

# Slash-команда для настройки конфигурации
@app_commands.command(name="nuke_config", description="Настройка параметров антинюкера")
@app_commands.checks.has_permissions(administrator=True)
async def nuke_config(interaction: discord.Interaction):
    await interaction.response.send_modal(ConfigModal())

# Регистрация slash-команды для конкретного сервера
bot.tree.add_command(nuke_config, guild=discord.Object(id=GUILD_ID))

# Временная команда для проверки и удаления slash-команд с тестированием
@app_commands.command(name="cleanup_commands", description="Проверяет и удаляет лишние slash-команды, тестируя их работоспособность")
@app_commands.checks.has_permissions(administrator=True)
async def cleanup_commands(interaction: discord.Interaction, command_name: str = "nuke_config"):
    await interaction.response.defer(ephemeral=True)
    try:
        # Получение списка команд для сервера
        guild = discord.Object(id=GUILD_ID)
        commands = await bot.tree.fetch_commands(guild=guild)
        
        # Фильтрация команд с именем command_name
        target_commands = [cmd for cmd in commands if cmd.name == command_name]
        
        if not target_commands:
            await interaction.followup.send(f"Команды с именем '{command_name}' не найдены на сервере.", ephemeral=True)
            return
        response = f"Найдено {len(target_commands)} команд с именем '{command_name}':\n"
        working_commands = []
        broken_commands = []
        
        for cmd in target_commands:
            response += f"- ID: {cmd.id}, Имя: {cmd.name}, Описание: {cmd.description}\n"
            try:
                test_interaction = interaction
                test_interaction.command = cmd
                await nuke_config(test_interaction)
                response += f"  Команда с ID {cmd.id} работает (модальное окно открывается).\n"
                working_commands.append(cmd)
            except Exception as e:
                response += f"  Команда с ID {cmd.id} НЕ работает. Ошибка: {e}\n"
                broken_commands.append(cmd)
        if broken_commands:
            for cmd in broken_commands:
                await bot.http.delete_guild_command(bot.user.id, GUILD_ID, cmd.id)
                response += f"Удалена неработающая команда с ID: {cmd.id}\n"
        else:
            response += "Все команды работают. Удаление не требуется.\n"
        
        if len(working_commands) == 0:
            bot.tree.clear_commands(guild=guild)
            bot.tree.add_command(nuke_config, guild=guild)
            synced = await bot.tree.sync(guild=guild)
            response += f"Пересинхронизировано {len(synced)} команд. Рабочая команда '/nuke_config' восстановлена.\n"
        else:
            response += f"Оставлено {len(working_commands)} рабочих команд.\n"
        await interaction.followup.send(response, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Ошибка при очистке команд: {e}", ephemeral=True)

bot.tree.add_command(cleanup_commands, guild=discord.Object(id=GUILD_ID))

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("Ошибка: У вас нет прав администратора!", ephemeral=True)
    else:
        await interaction.response.send_message(f"Произошла ошибка: {error}", ephemeral=True)

bot.run('MTM3NTEzMTY2OTA2NTEwOTU1NA.GYgEx6.YfMzL46_S-jGR5lGnjNBSsejRFFKHMT-cvromY')
