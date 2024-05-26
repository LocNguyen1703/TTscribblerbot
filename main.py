# python discord bot tutorial for reference:
# https://www.youtube.com/watch?v=UYJDKSah-Ww

import os
from dotenv import load_dotenv
from typing import Final
from discord import Intents, Client, Message
from responses import get_response

import pickle
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# STEP 0: LOAD DISCORD BOT TOKEN FROM SOMEWHERE SAFE
load_dotenv()
TOKEN: Final[str] = os.getenv('DISCORD_TOKEN')
# for debugging
print(TOKEN)

# STEP 1: BOT SETUP
intents: Intents = Intents.default()
intents.message_content = True
client: Client = Client(intents=intents)


# STEP 2: MESSAGING FUNCTIONALITY
async def send_message(message: Message, user_message: str) -> None:
    if not user_message:  # if message is empty, no need to process anything
        print('(message was empty because intents were not enabled)')
        return
    if is_private := user_message[0] == '!':
        user_message = user_message[1]  # shift user_message to exclude the '!'

    try:
        response: str = get_response(user_message)
        await message.author.send(response) if is_private else await message.channel.send(response)
    # as I improve the code I should change this exception class to something as use-case-specific as posisble
    except Exception as e:
        print(e)


# STEP 3: HANDLING STARTUP FOR OUR BOT
@client.event
async def on_ready() -> None:
    print(f'{client.user} is now running!')


# STEP 4: HANDLE INCOMING MESSAGE
@client.event
async def on_message(message: Message) -> None:
    # if the message was sent by the bot itself, halt instead of keep responding & creating an infinite loop
    if message.author == client.user:
        return
    username: str = str(message.author)
    user_message: str = message.content
    channel: str = str(message.channel)

    print(f'[{channel}, {username}: "{user_message}"]')
    await send_message(message, user_message)


# STEP 5: MAIN ENTRY POINT
def main() -> None:
    client.run(token=TOKEN)


if __name__ == "__main__":
    main()
