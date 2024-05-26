# python discord bot tutorial for reference:
# https://www.youtube.com/watch?v=UYJDKSah-Ww

import os
from dotenv import load_dotenv
from typing import Final
from discord import Intents, Client, Message
from discord.ext import commands
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

# load ID of my google spreadsheet of choice and ranges of cells I want to access/edit from .env
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
RANGE1 = os.getenv('TEST_READ_RANGE')
RANGE2 = os.getenv('TEST_WRITE_RANGE')

# STEP 1: BOT SETUP
intents: Intents = Intents.default()
intents.message_content = True
client: Client = Client(intents=intents)

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# STEP 4*: TESTING GOOGLE SHEETS API FUNCTIONS
# "initialize Google authentication" - still NOT sure why I need this part
creds = None
if os.path.exists('token.pickle'):
    with open('token.pickle', 'rb') as token:
        creds = pickle.load(token)
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
    with open('token.pickle', 'wb') as token:
        pickle.dump(creds, token)
service = build('sheets', 'v4', credentials=creds)
sheet = service.spreadsheets()

# create a "bot command" instance - I'm assuming this is used for SPECIFIC commands like "!test" that
# user types in message
bot = commands.Bot(command_prefix='!')


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


@bot.command(name='test')
async def testCommand(ctx):
    valuesToWrite = [
        [ "C1","D1" ],
        [ "C2","D2" ],
        [ "C3","D3" ],
    ]
    body = {
        'values': valuesToWrite
    }
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE1).execute()
    result2 = sheet.values().update(spreadsheetId=SPREADSHEET_ID, range=RANGE2, valueInputOption='USER_ENTERED', body=body).execute()
    values = result.get('values', [])

    if not values:
        print('No data found.')
    else:
        print('Name, Major:')
        for row in values:
            # Print columns A and E, which correspond to indices 0 and 4.
            print('%s, %s' % (row[0], row[1]))
            await ctx.send(f"{row[0]} {row[1]}")


# STEP 5: MAIN ENTRY POINT
def main() -> None:
    client.run(token=TOKEN)


if __name__ == "__main__":
    main()
