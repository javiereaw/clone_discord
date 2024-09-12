import discord, logging, re, json, os, asyncio
from yaml import load, Loader
from discord.http import HTTPException
from datetime import datetime, timedelta

# Configuración del logging
# Crear un logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Crear un manejador de archivo para warnings y errores
file_handler = logging.FileHandler('warnings-message_client.log')
file_handler.setLevel(logging.WARNING)  # Solo warnings y errores
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Crear un manejador de consola para infos
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)  # Todos los niveles de info y superiores
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# Cargar configuración
settings = load(open("settings.yaml", "r"), Loader=Loader)
TOKEN = settings["client"]['token']
SERVER_ID = settings["client"]['server_id']
REGEX_FILTER = re.compile(settings["client"]['regex_filter'])
EXCLUDED_CHANNELS = settings["client"]['excluded_channels']
MESSAGE_INTERVAL = settings["client"]['message_interval']
COPIED_MESSAGES_FILE = "copied_messages.json"
PENDING_MESSAGES_FILE = "pending_messages.json"
MEMBERS_FILE = "members.json"

# Inicializar los archivos de mensajes copiados y pendientes si no existen
for file in [COPIED_MESSAGES_FILE, PENDING_MESSAGES_FILE, MEMBERS_FILE]:
    if not os.path.isfile(file):
        with open(file, 'w') as f:
            json.dump([], f)

def load_copied_messages():
    with open(COPIED_MESSAGES_FILE, 'r') as f:
        return set(json.load(f))

def save_copied_message(message_id):
    with open(COPIED_MESSAGES_FILE, 'r') as f:
        copied_messages = set(json.load(f))
    copied_messages.add(message_id)
    with open(COPIED_MESSAGES_FILE, 'w') as f:
        json.dump(list(copied_messages), f)

def load_pending_messages():
    with open(PENDING_MESSAGES_FILE, 'r') as f:
        return json.load(f)

def save_pending_message(message_data):
    with open(PENDING_MESSAGES_FILE, 'r') as f:
        pending_messages = json.load(f)
    pending_messages.append(message_data)
    with open(PENDING_MESSAGES_FILE, 'w') as f:
        json.dump(pending_messages, f)

def remove_pending_message(message_id):
    with open(PENDING_MESSAGES_FILE, 'r') as f:
        pending_messages = json.load(f)
    pending_messages = [msg for msg in pending_messages if msg['id'] != message_id]
    with open(PENDING_MESSAGES_FILE, 'w') as f:
        json.dump(pending_messages, f)

def save_members(members):
    members_data = [
        {
            'id': member.id,
            'name': member.name,
            'discriminator': member.discriminator,
            'avatar_url': str(member.avatar_url),
            'joined_at': member.joined_at.isoformat(),
            'roles': [role.id for role in member.roles]
        }
        for member in members
    ]
    with open(MEMBERS_FILE, 'w') as f:
        json.dump(members_data, f, indent=4)

client = discord.Client()

async def fetch_and_save_messages(channel):
    copied_messages = load_copied_messages()

    try:
        async for message in channel.history(limit=None, oldest_first=True):
            if message.id in copied_messages or message.channel.id in EXCLUDED_CHANNELS or REGEX_FILTER.search(message.content):
                continue

            # Obtener los archivos adjuntos (imágenes, etc.)
            attachments = [attachment.url for attachment in message.attachments]

            # Obtener los embeds del mensaje
            embeds = []
            for embed in message.embeds:
                embeds.append({
                    'title': embed.title,
                    'description': embed.description,
                    'url': embed.url,
                    'color': embed.color,
                    'timestamp': embed.timestamp.isoformat(),
                    'footer': {
                        'text': embed.footer.text,
                        'icon_url': embed.footer.icon_url
                    },
                    'image': {
                        'url': embed.image.url
                    },
                    'thumbnail': {
                        'url': embed.thumbnail.url
                    },
                    'author': {
                        'name': embed.author.name,
                        'url': embed.author.url,
                        'icon_url': embed.author.icon_url
                    },
                    'fields': [
                        {
                            'name': field.name,
                            'value': field.value,
                            'inline': field.inline
                        } for field in embed.fields
                    ]
                })

            # Guardar el mensaje en el archivo pendiente
            message_data = {
                'id': message.id,
                'content': message.content,
                'channel_id': message.channel.id,
                'channel_name': message.channel.name,
                'author_name': message.author.name,
                'author_id': message.author.id,
                'author_avatar_url': str(message.author.avatar_url),
                'timestamp': message.created_at.isoformat(),
                'attachments': attachments,
                'embeds': embeds,  # Añadir embeds
                'videos': [
                    attachment.url for attachment in message.attachments if attachment.url.endswith(('.mp4', '.mov', '.avi', '.mkv'))
                ]  # Añadir videos
            }
            save_pending_message(message_data)
            save_copied_message(message.id)
            await asyncio.sleep(MESSAGE_INTERVAL)

            # Manejo de errores de tasa
            try:
                await asyncio.sleep(MESSAGE_INTERVAL)
            except HTTPException as e:
                if e.status == 429:
                    retry_after = e.response.json().get('retry_after', 1) / 1000
                    logging.warning(f"Rate limited. Retrying after {retry_after} seconds.")
                    await asyncio.sleep(retry_after)
                else:
                    logging.error(f"HTTP error: {e}")
                    raise

    except discord.Forbidden:
        logging.warning(f"Permission denied for channel: {channel.name}")
    except discord.HTTPException as e:
        logging.error(f"Failed to fetch messages: {e}")

    await asyncio.sleep(MESSAGE_INTERVAL)

async def update_members_periodically(guild):
    while True:
        members = guild.members  # Obtener los miembros desde la caché
        save_members(members)
        await asyncio.sleep(3600)  # Esperar 1 hora antes de actualizar nuevamente

@client.event
async def on_ready():
    logging.info(f"Logged in as {client.user.name}")
    server = client.get_guild(SERVER_ID)
    
    if server:
        # Iniciar actualización periódica de miembros
        client.loop.create_task(update_members_periodically(server))

        # También podrías querer guardar mensajes
        for channel in server.text_channels:
            if channel.id not in EXCLUDED_CHANNELS:
                await fetch_and_save_messages(channel)

client.run(TOKEN)
