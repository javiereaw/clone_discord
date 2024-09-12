import asyncio, discord, logging, json, os, datetime, aiohttp
from yaml import load, Loader
from discord.ext import commands

# Configuración del logging
# Crear un logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Crear un manejador de archivo para warnings y errores
file_handler = logging.FileHandler('warnings-message_server.log')
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
TOKEN = settings["server"]['token']
SERVER_ID = settings["server"]['server_id']
INTERVAL = settings["server"]['interval']
COPIED_MESSAGES_FILE = "copied_messages.json"
PENDING_MESSAGES_FILE = "pending_messages.json"
SENT_MESSAGES_FILE = "sent_messages.json"


# Inicializar el bot
bot = commands.Bot(command_prefix='>', self_bot=True)

def load_sitemap():
    with open("final.json", 'r') as f:
        return json.load(f)

def load_pending_messages():
    with open(PENDING_MESSAGES_FILE, 'r') as f:
        return json.load(f)

def remove_pending_message(message_id):
    with open(PENDING_MESSAGES_FILE, 'r') as f:
        pending_messages = json.load(f)
    pending_messages = [msg for msg in pending_messages if msg['id'] != message_id]
    with open(PENDING_MESSAGES_FILE, 'w') as f:
        json.dump(pending_messages, f)

def load_sent_messages():
    if os.path.exists(SENT_MESSAGES_FILE):
        with open(SENT_MESSAGES_FILE, 'r') as f:
            return json.load(f)
    return []

def save_sent_message(message_id):
    sent_messages = load_sent_messages()
    sent_messages.append(message_id)
    with open(SENT_MESSAGES_FILE, 'w') as f:
        json.dump(sent_messages, f)

async def send_message_via_webhook(webhook_url, content, author_name, author_avatar_url, timestamp, message_id, attachments=None, embeds=None, videos=None):
    async with aiohttp.ClientSession() as session:
        payload = {
            "username": author_name,
            "avatar_url": author_avatar_url,
            "content": content,
            "embeds": [{
                "footer": {
                    "text": f"Sent at {timestamp}"
                }
            }]
        }

        # Enviar las imágenes como archivos adjuntos reales
        form_data = aiohttp.FormData()
        form_data.add_field('payload_json', json.dumps(payload))  # Añadir el contenido del payload como JSON

        if attachments:
            for attachment in attachments:
                async with session.get(attachment) as resp:
                    if resp.status == 200:
                        file_data = await resp.read()
                        # Obtener el nombre del archivo desde la URL
                        file_name = attachment.split("/")[-1].split("?")[0]
                        # Añadir el archivo al formulario de datos
                        form_data.add_field('file', file_data, filename=file_name, content_type=resp.headers['Content-Type'])

        # Añadir videos al payload si es necesario
        if videos:
            payload["videos"] = [{"url": video} for video in videos]

        # Enviar la solicitud POST con el formulario de datos
        async with session.post(webhook_url, data=form_data) as response:
            if response.status == 204:
                logging.info("Message sent successfully via webhook.")
            else:
                logging.error(f"Failed to send message via webhook: {response.status} - {await response.text()}")


async def process_pending_messages():
    pending_messages = load_pending_messages()
    sitemap = load_sitemap()
    sent_messages = load_sent_messages()  # Cargar los mensajes enviados


    # Crear un diccionario para mapear IDs de canales originales a clonados
    channel_map = {}
    for category in sitemap.get("categories", []):
        for channel in category.get("channels", []):
            channel_map[channel["original_id"]] = {
                "cloned_id": channel["cloned_id"],
                "webhook": channel.get("webhook")
            }
    for channel in sitemap.get("standalone_channels", []):
        channel_map[channel["original_id"]] = {
            "cloned_id": channel["cloned_id"],
            "webhook": channel.get("webhook")
        }

    for message_data in pending_messages:
        message_id = message_data['id']
        
        # Verificar si el mensaje ya ha sido enviado
        if message_id in sent_messages:
            logging.info(f"Message with ID {message_id} has already been sent. Skipping.")
            continue

        original_channel_id = message_data['channel_id']
        channel_info = channel_map.get(original_channel_id)

        if channel_info:
            cloned_channel_id = channel_info['cloned_id']
            webhook_url = channel_info['webhook']
            if webhook_url:
                try:
                    # Obtener y limpiar el contenido del mensaje
                    content = message_data['content'].strip()
                    logging.info(f"Message content loaded: {content}")

                    # Obtener el nombre del autor
                    author_name = message_data['author_name']
                    author_id = message_data['author_id']
                    author_avatar_url = message_data.get('author_avatar_url', '')
                    logging.info(f"Message author loaded: {author_name} (ID: {author_id})")

                    # Obtener y convertir el timestamp
                    timestamp = message_data['timestamp']
                    logging.info(f"Message timestamp loaded: {timestamp}")

                    # Convertir timestamp a formato de texto
                    timestamp_dt = datetime.datetime.fromisoformat(timestamp[:-1])  # Eliminar 'Z' si está presente
                    timestamp_str = timestamp_dt.strftime('%Y-%m-%d %H:%M:%S')
                    logging.info(f"Converted timestamp to datetime: {timestamp_str}")

                    # Obtener archivos adjuntos
                    attachments = message_data.get('attachments', [])
                    logging.info(f"Message attachments loaded: {attachments}")

                    # Obtener embeds
                    embeds = message_data.get('embeds', [])
                    logging.info(f"Message embeds loaded: {embeds}")

                    # Obtener videos
                    videos = message_data.get('videos', [])
                    logging.info(f"Message videos loaded: {videos}")

                    # Enviar mensaje usando el webhook
                    if content:  # Si el contenido no está vacío
                        await send_message_via_webhook(webhook_url, content, author_name, author_avatar_url, timestamp_str, message_id, attachments, embeds, videos)
                        logging.info(f"Message re-sent via webhook: {content}")

                        # Guardar el ID del mensaje como enviado
                        save_sent_message(message_id)
                    else:
                        logging.warning(f"Message with ID {message_data['id']} has empty content.")

                    # Después de enviar el mensaje, elimina de la lista de pendientes
                    remove_pending_message(message_id)
                except Exception as e:
                    logging.error(f"Failed to resend message {message_data['id']}: {e}")
            else:
                logging.warning(f"No webhook URL found for cloned channel ID {cloned_channel_id}")
        else:
            logging.warning(f"Cloned channel not found for original channel ID {original_channel_id}")

        await asyncio.sleep(INTERVAL)


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user.name}")
    server = bot.get_guild(SERVER_ID)

    if server:
        while True:
            logging.info("Processing pending messages.")
            await process_pending_messages()
            logging.info(f"Waiting for {INTERVAL*6} seconds before processing again.")
            await asyncio.sleep(INTERVAL*6)  # Espera de 60 segundos (1 minuto) entre procesos de mensajes

bot.run(TOKEN)
