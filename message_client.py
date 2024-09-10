import discord
import logging
import re
from yaml import load, Loader
from time import sleep
import asyncio
from discord.http import HTTPException
import json
import os

# Configuración del logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar configuración
settings = load(open("settings.yaml", "r"), Loader=Loader)
TOKEN = settings["client"]['token']
SERVER_ID = settings["client"]['server_id']
REGEX_FILTER = re.compile(settings["client"]['regex_filter'])
EXCLUDED_CHANNELS = settings["client"]['excluded_channels']
MESSAGE_INTERVAL = settings["client"]['message_interval']
COPIED_MESSAGES_FILE = "copied_messages.json"
PENDING_MESSAGES_FILE = "pending_messages.json"

# Inicializar los archivos de mensajes copiados y pendientes si no existen
for file in [COPIED_MESSAGES_FILE, PENDING_MESSAGES_FILE]:
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

client = discord.Client()

async def fetch_and_send_messages(channel):
    copied_messages = load_copied_messages()
    pending_messages = load_pending_messages()
    
    # Convertir los mensajes pendientes en un diccionario para acceso rápido
    pending_messages_dict = {msg['id']: msg for msg in pending_messages}
    
    try:
        async for message in channel.history(limit=None, oldest_first=True):
            if message.id in copied_messages or message.channel.id in EXCLUDED_CHANNELS or REGEX_FILTER.search(message.content):
                continue

            # Aquí deberías guardar el mensaje en el archivo pendiente
            message_data = {
                'id': message.id,
                'content': message.content,
                'channel_id': message.channel.id,
                'channel_name': message.channel.name,
                'author_name': message.author.name,
                'timestamp': message.created_at.isoformat()
            }
            save_pending_message(message_data)

            # Preservar la fecha y hora original del mensaje en un embed
            embed = discord.Embed(description=message.content, timestamp=message.created_at)
            embed.set_author(name=message.author.name, icon_url=message.author.avatar_url)

            # Aquí deberías enviar el embed al canal destino
            # Ejemplo: await destination_channel.send(embed=embed)

            # Guardar el ID del mensaje copiado
            save_copied_message(message.id)

            # Manejo de errores de tasa
            try:
                await asyncio.sleep(MESSAGE_INTERVAL)  # Espera el intervalo antes de copiar el siguiente mensaje
            except HTTPException as e:
                if e.status == 429:  # Error de límite de tasa
                    retry_after = e.response.json().get('retry_after', 1) / 1000  # Tiempo en segundos para reintentar
                    logging.warning(f"Rate limited. Retrying after {retry_after} seconds.")
                    await asyncio.sleep(retry_after)
                else:
                    logging.error(f"HTTP error: {e}")
                    raise

    except discord.Forbidden:
        logging.warning(f"Permission denied for channel: {channel.name}")
    except discord.HTTPException as e:
        logging.error(f"Failed to fetch messages: {e}")

def load_sitemap():
    with open("final.json", 'r') as f:
        return json.load(f)
    
async def process_pending_messages():
    pending_messages = load_pending_messages()
    sitemap = load_sitemap()  # Cargar el final.json

    for message_data in pending_messages:
        original_channel_id = message_data['channel_id']
        cloned_channel_id = None

        # Buscar el canal clonado correspondiente
        for category in sitemap["categories"]:
            for channel in category["channels"]:
                if channel["original_id"] == original_channel_id:
                    cloned_channel_id = channel["cloned_id"]
                    break

        # Buscar en los canales sin categoría si no está en las categorías
        if cloned_channel_id is None:
            for channel in sitemap["standalone_channels"]:
                if channel["original_id"] == original_channel_id:
                    cloned_channel_id = channel["cloned_id"]
                    break

        # Si encontramos el canal clonado, enviamos el mensaje
        if cloned_channel_id:
            channel = client.get_channel(cloned_channel_id)
            if channel:
                try:
                    embed = discord.Embed(description=message_data['content'], timestamp=discord.utils.snowflake_time(message_data['id']))
                    embed.set_author(name=message_data['author_name'])
                    await channel.send(embed=embed)
                    logging.info(f"Message re-sent to {channel.name}: {message_data['content']}")
                    remove_pending_message(message_data['id'])
                except Exception as e:
                    logging.error(f"Failed to resend message {message_data['id']}: {e}")
                    continue
        else:
            logging.warning(f"Cloned channel not found for original channel ID {original_channel_id}")


@client.event
async def on_ready():
    logging.info(f"Logged in as {client.user.name}")
    server = client.get_guild(SERVER_ID)

    if server:
        for channel in server.text_channels:
            if channel.id not in EXCLUDED_CHANNELS:
                await fetch_and_send_messages(channel)

    # Procesar mensajes pendientes
    await process_pending_messages()

client.run(TOKEN)
