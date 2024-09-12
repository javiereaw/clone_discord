import asyncio, websockets, discord, logging, aiohttp, json
from discord.ext import commands
from yaml import load, Loader
from json import load as j_load, dump as j_dump, loads
from resilient_caller import resilient_call, update_session_proxy 
from random import choice

# Define logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Disable logging for discord
discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.WARNING)

# Load settings
settings = load(open("settings.yaml", "r"), Loader=Loader)
TOKEN = settings["server"]['token']
SERVER_ID = settings["server"]['server_id']
INTERVAL = settings["server"]['interval']
WEBHOOK_NAME = settings["server"]['webhook_name']
PORT, HOST = list(settings['server']['websocket'].values())
PROXIES = open("proxies.txt", "r").read().splitlines()
bot = commands.Bot(command_prefix='>', self_bot=True)

@resilient_call()
async def send_webhook_to_discord(webhook_url: str, webhook_data: dict):
    # Send async request to discord webhook
    logging.info(f"Sending data to webhook: {webhook_url}")
    async with aiohttp.ClientSession() as session:
        if len(PROXIES) > 0:
            update_session_proxy(session, choice(PROXIES))
            logging.info(f"Using proxy for webhook: {choice(PROXIES)}")
        async with session.post(webhook_url, json=webhook_data) as response:
            result = await response.text()
            logging.info(f"Webhook response: {response.status} - {result}")
            return result

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user.name} ({bot.user.id})")

async def update_server_structure(sitemap: dict, sitemap_file: str):
    server = bot.get_guild(SERVER_ID)
    if server is None:
        logging.error("Failed to find the server. Check SERVER_ID in settings.{SERVER_ID}")
        return
    try:
        with open(sitemap_file, "r") as infile:
            updated_sitemap = j_load(infile)
    except FileNotFoundError:
        logging.warning(f"{sitemap_file} not found, creating a new one.")
        updated_sitemap = {"categories": [], "standalone_channels": []}
    if updated_sitemap == sitemap:
        logging.info("No updates required for the sitemap.")
        return
    
    logging.info("Updating server structure...")

    for cat_data in sitemap["categories"]:
        # Verificar si la categoría ya existe en el sitemap
        existing_category = next((cat for cat in updated_sitemap["categories"] if cat["name"] == cat_data["name"]), None)
        
        if existing_category is None:
            category = discord.utils.get(server.categories, name=cat_data["name"])
            if category is None:
                category = await server.create_category(cat_data["name"])
                logging.info(f"Category created: {cat_data['name']}")
            await asyncio.sleep(INTERVAL)
            
            updated_channels = []
            
            for channel_data in cat_data["channels"]:
                # Verificar si 'original_id' está presente
                if 'original_id' not in channel_data:
                    logging.error(f"'original_id' not found in channel_data: {channel_data}")
                    continue  # O puedes manejar el error de otra forma
                channel = discord.utils.get(category.channels, name=channel_data["name"])
                if channel is None:
                    channel = await server.create_text_channel(channel_data["name"], category=category)
                    webhook = await channel.create_webhook(name=WEBHOOK_NAME)
                    updated_channels.append({"name": channel.name, "original_id": channel_data["original_id"], "cloned_id": channel.id, "webhook": webhook.url})
                    logging.info(f"Channel created: {channel_data['name']} in category {cat_data['name']}")
                    await asyncio.sleep(INTERVAL)
                else:
                    webhook = None
                    webhooks = await channel.webhooks()
                    for hook in webhooks:
                        if hook.name == WEBHOOK_NAME:
                            webhook = hook
                            break
                    if webhook is None:
                        webhook = await channel.create_webhook(name=WEBHOOK_NAME)
                    updated_channels.append({"name": channel.name, "original_id": channel_data["original_id"],"cloned_id": channel.id, "webhook": webhook.url})
                    logging.debug(f"Channel already exists: {channel_data['name']} in category {cat_data['name']}")
                await asyncio.sleep(INTERVAL)
            
            updated_sitemap["categories"].append({"name": category.name, "channels": updated_channels})
        else:
            logging.debug(f"Category already exists: {cat_data['name']}")

        await save_sitemap_to_file(updated_sitemap, sitemap_file)

    for channel_data in sitemap["standalone_channels"]:
        # Verificar si 'original_id' está presente
        if 'original_id' not in channel_data:
            logging.error(f"'original_id' not found in standalone channel_data: {channel_data}")
            continue  # O puedes manejar el error de otra forma
        # Verificar si el canal ya existe en el sitemap
        existing_channel = next((chan for chan in updated_sitemap["standalone_channels"] if chan["name"] == channel_data["name"]), None)
        
        if existing_channel is None:
            channel = discord.utils.get(server.text_channels, name=channel_data["name"], category=None)
            if channel is None:
                channel = await server.create_text_channel(channel_data["name"])
                webhook = await channel.create_webhook(name=WEBHOOK_NAME)
                updated_sitemap["standalone_channels"].append({"name": channel.name, "original_id": channel_data["original_id"], "cloned_id": channel.id, "webhook": webhook.url})
                logging.info(f"Standalone channel created: {channel_data['name']}")
                await asyncio.sleep(INTERVAL)
            else:
                webhook = None
                webhooks = await channel.webhooks()
                for hook in webhooks:
                    if hook.name == WEBHOOK_NAME:
                        webhook = hook
                        break
                if webhook is None:
                    webhook = await channel.create_webhook(name=WEBHOOK_NAME)
                updated_sitemap["standalone_channels"].append({"name": channel.name, "original_id": channel_data["original_id"], "cloned_id": channel.id, "webhook": webhook.url})
                logging.debug(f"Standalone channel already exists: {channel_data['name']}")
        else:
            logging.debug(f"Standalone channel already exists in the sitemap: {channel_data['name']}")

        await save_sitemap_to_file(updated_sitemap, sitemap_file)
        await asyncio.sleep(INTERVAL)
    logging.info("Server structure updated.")
    return updated_sitemap

async def save_sitemap_to_file(sitemap, filename="final.json"):
    logging.info(f"Saving sitemap to {filename}")
    with open(filename, "w") as outfile:
        j_dump(sitemap, outfile, indent=4)
    logging.info(f"Sitemap saved successfully to {filename}")

def compare_sitemaps(old_sitemap, new_sitemap):
    removed_channels = []
    title_changes = []

    # Compare category channels
    for old_cat in old_sitemap["categories"]:
        new_cat = next((cat for cat in new_sitemap["categories"] if cat["name"] == old_cat["name"]), None)
        if new_cat is None:
            removed_channels.extend(old_cat["channels"])
        else:
            for old_channel in old_cat["channels"]:
                new_channel = next((chan for chan in new_cat["channels"] if chan["cloned_id"] == old_channel["cloned_id"]), None)
                if new_channel is None:
                    removed_channels.append(old_channel)
                elif new_channel["name"] != old_channel["name"]:
                    title_changes.append({"type": "channel", "old": old_channel, "new": new_channel})

            # Check for category title changes
            if old_cat["name"] != new_cat["name"]:
                title_changes.append({"type": "category", "old": old_cat, "new": new_cat})

    # Compare standalone channels
    for old_channel in old_sitemap["standalone_channels"]:
        new_channel = next((chan for chan in new_sitemap["standalone_channels"] if chan["cloned_id"] == old_channel["cloned_id"]), None)
        if new_channel is None:
            removed_channels.append(old_channel)
        elif new_channel["name"] != old_channel["name"]:
            title_changes.append({"type": "channel", "old": old_channel, "new": new_channel})

    return removed_channels, title_changes

async def websocket_handler(websocket, path):
    sitemap_file = "final.json"
    try:
        with open(sitemap_file, "r") as infile:
            old_sitemap = j_load(infile)
            logging.info(f"Loaded existing sitemap from {sitemap_file}")
    except FileNotFoundError:
        logging.warning(f"{sitemap_file} not found, starting with an empty sitemap.")
        old_sitemap = None

    async for message in websocket:
        data = loads(message)
        if data["type"] == "sitemap":
            logging.info("Sitemap received")
            updated_sitemap = await update_server_structure(data["data"], sitemap_file)
            if updated_sitemap is not None:
                await save_sitemap_to_file(updated_sitemap, sitemap_file)

            if old_sitemap is not None:
                removed_channels, title_changes = compare_sitemaps(old_sitemap, updated_sitemap)
                if removed_channels:
                    logging.info("Removed channels: %s", removed_channels)
                if title_changes:
                    logging.info("Title changes:%s", title_changes)
                if not removed_channels and not title_changes:
                    logging.info("Nothing changed")

            old_sitemap = updated_sitemap
        elif data["type"] == "ping":
            logging.info("Ping received")
        else:
            logging.warning(f"Unknown message type received from websocket: {data['type']}")

start_server = websockets.serve(websocket_handler, HOST, PORT)
logging.info(f"Starting websocket server on ws://{HOST}:{PORT}")
bot.loop.run_until_complete(start_server)
bot.run(TOKEN)