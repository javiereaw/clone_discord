import discord, asyncio, websockets, json, logging
from yaml import load, Loader
from discord.ext import commands, tasks

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load settings
settings = load(open("settings.yaml", "r"), Loader=Loader)
TOKEN = settings["client"]['token']
SERVER_ID = settings["client"]['server_id']
PORT, HOST = list(settings['server']['websocket'].values())
WEBSOCKET_URI = f"ws://{HOST}:{PORT}"

bot = commands.Bot(command_prefix='>', self_bot=True)

async def get_server_structure():
    server = bot.get_guild(SERVER_ID)
    if server is None:
        logging.error("Failed to get server. The bot is not in the server or the server ID is incorrect.")
        return None
    structure = {
        "categories": [],
        "standalone_channels": []
    }
    
    # Iterar sobre las categorías y sus canales
    for category in server.categories:
        cat_data = {"name": category.name, "channels": []}
        for channel in category.channels:
            if isinstance(channel, discord.TextChannel):
                # Guardar tanto el nombre como el ID original del canal
                cat_data["channels"].append({"name": channel.name, "id": channel.id})
        structure["categories"].append(cat_data)
    
    # Canales sin categoría
    for channel in server.text_channels:
        if channel.category is None:
            structure["standalone_channels"].append({"name": channel.name, "id": channel.id})
    
    logging.info("Successfully retrieved server structure.")
    return structure

async def send_structure_to_websocket(structure):
    try:
        async with websockets.connect(WEBSOCKET_URI) as websocket:
            # Enviar la estructura del servidor, que incluye tanto IDs como nombres
            await websocket.send(json.dumps({"type": "sitemap", "data": structure}))
            logging.info("Server structure sent to websocket.")
    except Exception as e:
        logging.error(f"Error sending structure to websocket: {e}")
        
@tasks.loop(hours=1)
async def periodic_update():
    structure = await get_server_structure()
    if structure:
        await send_structure_to_websocket(structure)
    else:
        logging.warning("Failed to retrieve server structure.")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    periodic_update.start()  # Start the periodic update task

bot.run(TOKEN)
