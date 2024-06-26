# python discord bot tutorial for reference:
# https://www.youtube.com/watch?v=UYJDKSah-Ww

import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import discord
from dotenv import load_dotenv
from typing import Final
from discord import Intents, Client, Message
from discord import app_commands
from discord.ext import commands, tasks
from responses import get_response

from datetime import datetime, timedelta

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
X_RANGE = os.getenv('X_CHECK_RANGE')

# STEP 1: BOT SETUP
intents: Intents = Intents.default()
intents.message_content = True
# client: Client = Client(intents=intents)  # maybe this is a "client message" instance - to read incoming user messages

# create a "bot command" instance - I'm assuming this is used for SPECIFIC commands like "/test" that
# user types in message
bot = commands.Bot(command_prefix='/', intents=intents)

# initialize a scheduler instance - for scheduling timely messages
scheduler = AsyncIOScheduler()

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
@bot.event
async def on_ready() -> None:
    print(f'{bot.user} is now running!')
    try:
        synced = await bot.tree.sync()
        print(f"synced {len(synced)} command(s)")
        scheduler.start()
    except Exception as e:
        print(e)


# STEP 4: HANDLE INCOMING MESSAGE
@bot.event
async def on_message(message: Message) -> None:
    # if the message was sent by the bot itself, halt instead of keep responding & creating an infinite loop
    if message.author == bot.user:
        return
    username: str = str(message.author)
    user_message: str = message.content
    channel: str = str(message.channel)

    print(f'[{channel}, {username}: "{user_message}"]')
    await send_message(message, user_message)


# STEP 4*: SPECIFIC BOT COMMAND TO ACCESS & PRINT GOOGLE SHEET CONTENT
# could've made the bot to recognize any message for this functionality as well but tutorial I found only had
# Google Sheet API integration in bot command form
@bot.tree.command(name='test')
async def testCommand(interaction: discord.Interaction):
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
        response_message = []
        for row in values:
            # Print columns A and E, which correspond to indices 0 and 4.
            print('%s, %s' % (row[0], row[1]))
            response_message.append(f'{row[0]}, {row[1]}')
        await interaction.response.send_message("\n".join(i for i in response_message))

# a dictionary to store all notes
notes_dict = {}
scores_dict = {}


# STEP 4*: SPECIFIC BOT COMMAND TO ADD NOTES TO CELLS
@bot.tree.command(name='note')
async def noteCommand(interaction: discord.Interaction):
    rowIndex: int = 1
    columnIndex: int = 1

    # fetch values from event attendance - check to see if there are any "x"
    x_fetch = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=X_RANGE).execute()
    x_check = x_fetch.get('values', [])

    NAME_RANGE = os.getenv('NAME_RANGE')
    names_fetch = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=NAME_RANGE).execute()
    names = names_fetch.get('values', [])

    SCORES_RANGE = os.getenv('SCORES_RANGE')
    scores_fetch = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=SCORES_RANGE).execute()
    scores = scores_fetch.get('values', [])

    # "reason" string to hold bad standing reasons to add to cells' notes
    reason: str = ""

    # list of requests to hold all cell update requests
    requests = []

    # add reason for every "x" found
    event_titles = x_check[0]
    # access specific row & column of cell i want to add notes in

    # clear dictionaries before re-updating
    scores_dict.clear()
    notes_dict.clear()
    try:
        # apparently bot times out if response command is not sent immediately after bot command is processed
        # defer() function lets bot know command is still being processed & keeps it from timing out
        await interaction.response.defer()

        for k in range(len(x_check[1:])):
            for i in range(len(x_check[1:][k])):
                if x_check[1:][k][i] == "x":
                    reason += "-missed " + event_titles[i] + " (+1)\n"
                elif x_check[1:][k][i] == "t":
                    reason += "-late to " + event_titles[i] + " (+0.5)\n"

            # update notes dictionary
            notes_dict.update({names[k][0]: reason if reason else "None added"})
            scores_dict.update({names[k][0]: scores[k][0]})

            # Create the request body to add the note to the specified cell
            requests.append({
                'updateCells': {
                    'range': {
                        'sheetId': 0,  # Default to the first sheet; change if needed
                        'startRowIndex': rowIndex,  # Convert A1 notation to row index (0-based)
                        'endRowIndex': rowIndex + 1,  # One row
                        'startColumnIndex': columnIndex,  # Convert column letter to index (0-based)
                        'endColumnIndex': columnIndex + 1  # One column
                    },
                    'rows': [{
                        'values': [{
                            'note': reason if reason else ''  # this cleans note if the 'x''s are somehow deleted
                        }]
                    }],
                    'fields': 'note'
                }
            })

            rowIndex += 1
            reason = ""

        # Execute the batch update request
        body = {
            'requests': requests
        }

        try:
            response = sheet.batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body).execute()
        except Exception as e:
            print(f"An error occurred: {e}")
            await interaction.followup.send(f"An error occurred: {e}")

        # confirm message that notes have been added
        await interaction.followup.send(f"Notes added to cells successfully.")

        print(notes_dict)
        print(scores_dict)

    except Exception as e:
        print(f"An error occurred: {e}")
        await interaction.followup.send(f"An error occurred: {e}")


# STEP 4*: SPECIFIC BOT COMMAND TO RETURN BAD STANDING STATUS TO USER
@bot.tree.command(name='bad_standing_check')
async def badStandingCheck(interaction: discord.Interaction):
    username: str = interaction.user.display_name

    '''
    thought: instead of having a middle-man (creating notes THEN fetch notes back THEN reply to user message)
    --> why not create note directly then send (i.e. instead of creating notes for all members create notes for the 
    1 member asking then send it)
    this way --> i can create like a global dictionary outside to store all notes, then update the dict weekly with 
    the note command, then members can use this command to quickly fetch their notes
    
    edit: i now got it to work, but is there a better way so that i don't have to use global vars? (i.e. i'm thinking 
    of a database, but idk if that's too complicated for this level..)
    '''
    good_standing_check: str = ' not' if float(scores_dict.get(username)) < 2 else ""

    response: str = f"hey {username}! you currently have {scores_dict.get(username)} points, which means " \
                    f"you're{good_standing_check} in bad standing!\n" \
                    f"reasons: {notes_dict.get(username)}\nif you have any questions please go annoy brother Scribe, " \
                    f"I'm just relaying what he wrote down"

    await interaction.response.send_message(response)


# STEP 4*: SPECIFIC BOT COMMAND TO SCHEDULE TIMELY MESSAGES
# separate function to print message
async def print_message(message: str):
    CHANNEL_ID = 1037860754524741634
    channel = bot.get_channel(CHANNEL_ID)

    if channel: await channel.send(message)


# actual scheduler function
@bot.tree.command(name='set_timely_message')
async def setTimelyMessage(interaction: discord.Interaction, day: str, hour: str, minute: str, second: str, message: str):
    scheduler.add_job(print_message, CronTrigger(day=None if day.lower() == "none" else day,
                                                 hour=None if hour.lower() == "none" else hour,
                                                 minute=None if minute.lower() == "none" else minute,
                                                 second= None if second.lower() == "none" else second), args=[message])
    await interaction.response.send_message(f'message scheduled: "{message}"')
    # return NotImplementedError("no code yet...")


# STEP 5: MAIN ENTRY POINT
def main() -> None:
    bot.run(token=TOKEN)
    # client.run(token=TOKEN)


if __name__ == "__main__":
    main()
