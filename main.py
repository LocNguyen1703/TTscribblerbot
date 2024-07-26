# python discord bot tutorial for reference:
# https://www.youtube.com/watch?v=UYJDKSah-Ww

import os
import typing

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

import discord
from dotenv import load_dotenv
from typing import Final, Sequence
from discord import Intents, Client, Message
from discord import app_commands
from discord.ext import commands, tasks
from responses import get_response

from datetime import datetime, timedelta, time

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
SCOPES = ['https://www.googleapis.com/auth/spreadsheets',
          'https://www.googleapis.com/auth/calendar']

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
        """
        I'm assuming following line is responsible for opening Google browser & authentication process,
        which is not available in a headless VM
        """
        creds = flow.run_local_server(port=0)
        # creds = flow.run_console()
    with open('token.pickle', 'wb') as token:
        pickle.dump(creds, token)

'''set up instances of Google Calendar and Google Sheets'''
# instance for Google sheets - called "sheet"
service_sheets = build('sheets', 'v4', credentials=creds)
sheet = service_sheets.spreadsheets()
# instance for Google Calendar - called "service_calendars"
# this service instance is from a class with multiple subclasses (my way of describing it)
# including an Events subclass - call service_calendars.events() to access
service_calendars = build('calendar', 'v3', credentials=creds)


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
        ["C1", "D1"],
        ["C2", "D2"],
        ["C3", "D3"],
    ]
    body = {
        'values': valuesToWrite
    }
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE1).execute()
    result2 = sheet.values().update(spreadsheetId=SPREADSHEET_ID, range=RANGE2, valueInputOption='USER_ENTERED',
                                    body=body).execute()
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
        # apparently followup class doesn't have ephemeral and delete_after parameters like interaction.response...


# STEP 4*: SPECIFIC BOT COMMAND TO RETURN BAD STANDING STATUS TO USER
'''
IMPORTANT NOTE: this command only works after Scribe has run the /notes command 
to set up local memory for bad standing points
'''


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
    of a database, but idk if that's too complicated for this level and for maintenance..)
    '''
    good_standing_check: str = ' not' if float(scores_dict.get(username)) < 2 else ""

    response: str = f"hey {username}! you currently have {scores_dict.get(username)} points, which means " \
                    f"you're{good_standing_check} in bad standing!\n" \
                    f"reasons: {notes_dict.get(username)}\nif you have any questions please go annoy brother Scribe, " \
                    f"I am but a vessel of his intelligence"

    try:
        # send a DM to user instead of a public message in channel with user.send()
        await interaction.user.send(response)
        await interaction.response.send_message(
            "I DM'd your status, this message is only visible to you and will terminate in T-minus 60 seconds",
            ephemeral=True, delete_after=60)
    except discord.Forbidden:
        await interaction.response.send_message(
            "I couldn't DM you the status. Please check your DM settings or annoy Brother Scribe. "
            "This message will terminate in T-minus 60 seconds",
            ephemeral=True, delete_after=60)


# STEP 4*: SPECIFIC BOT COMMAND TO SCHEDULE TIMELY MESSAGES
# separate function to print message
async def print_message(message: str, file_path: str):
    CHANNEL_ID: int = 1037860754524741634
    channel = bot.get_channel(CHANNEL_ID)

    if channel:
        if file_path.lower() != "none":
            file = discord.File(file_path.strip('"'))  # remove quotation marks
            await channel.send(message, file=file)
        else:
            await channel.send(message)


# actual scheduler function
@bot.tree.command(name='set_timely_message')
async def setTimelyMessage(interaction: discord.Interaction, day: str, hour: str, minute: str, second: str,
                           message: str, file_path: str):
    scheduler.add_job(print_message, CronTrigger(day=None if day.lower() == "none" else day,
                                                 hour=None if hour.lower() == "none" else hour,
                                                 minute=None if minute.lower() == "none" else minute,
                                                 second=None if second.lower() == "none" else second),
                      args=[message, file_path])
    await interaction.response.send_message(f'message scheduled: "{message}" with file: {file_path}. '
                                            f'Message only visible to you and terminates in T-minus 60 seconds',
                                            ephemeral=True, delete_after=60)
    # return NotImplementedError("no code yet...")


# STEP 4*: SPECIFIC BOT COMMAND TO SCHEDULE A ONE-TIME MESSAGE
@bot.tree.command(name='set_message')
async def setOneTimeMessage(interaction: discord.Interaction, date_time: str, message: str, file_path: str):
    """
    ideas:
        maybe I can use the same method as the set_timely_message command above, just after the message is sent,
        I cancel it - WITHOUT CANCELING OTHER JOBS

        - the ways jobs are kept track of is by their job_id
        - I could create a local dictionary (same way I did for all Brothers' names & their points and whatnot)
        to store each job's id and their message

        or, apparently there's a class called "DateTrigger" - similar to CronTrigger, but triggers an event at
        a certain date/time
            - apparently input formatting is: YYYY-MM-DD HH:MM
    edit:
    function now works, but will need to do full test run
        - not sure if this really schedules one-time messages or if the messages repeat every day
    """
    send_time = datetime.strptime(date_time, '%Y-%m-%d %H:%M')
    scheduler.add_job(print_message, DateTrigger(run_date=send_time), args=[message, file_path])
    await interaction.response.send_message(f'one-time message scheduled at {send_time}: "{message}", '
                                            f'with file: {file_path}. Message only visible to you and will terminate '
                                            f'in T-minus 60 seconds', ephemeral=True, delete_after=60)


# STEP 4*: SPECIFIC BOT COMMAND TO CANCEL ALL MESSAGES
@bot.tree.command(name='cancel_all_scheduled_messages')
async def cancelAllMessages(interaction: discord.Interaction):
    scheduler.remove_all_jobs()
    await interaction.response.send_message("all scheduled messages have been canceled. This message is only visible "
                                            "to you and will terminate in T-minus 60 seconds",
                                            ephemeral=True, delete_after=60)


# STEP 4*: SPECIFIC BOT COMMAND TO NOTIFY EVENTS IN WEEK/MONTH
@bot.tree.command(name='events_check')
async def notifyEvents(interaction: discord.Interaction):
    now = datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
    events_result = service_calendars.events().list(calendarId='primary', timeMin=now,
                                                    maxResults=30, singleEvents=True,
                                                    orderBy='startTime').execute()
    # events_result is a "response body" (kinda like the request body we created in note command)

    """
    get() function returns the specific category in the response body that we want - i.e. the items list
    google calendar API for better explanation: https://developers.google.com/calendar/api/v3/reference/events/list
    """
    events = events_result['items']  # I can either use .get() or "[]" to access categories in response body

    if not events: await interaction.response.send_message("no upcoming events found. This message is only visible "
                                                           "to you and will terminate in T-minus 60 seconds",
                                                           ephemeral=True, delete_after=60)
    event_list = []
    for event in events:
        end = event['end']['dateTime'][11:16]  # isolate 11th-19th characters (end-time) from random formatting noise
        start = event['start']['dateTime']
        start = start.replace('T', ' ', 1).replace(start[16:25], '-' + end, 1)
        event_list.append(f"{start} - {event['summary']}")

    response: str = "\n".join(event_list)
    await interaction.response.send_message(f'here are the {len(event_list)} events upcoming events: \n{response}\n'
                                            f'This message is only visible to you and will terminate in '
                                            f'T-minus 60 seconds', ephemeral=True, delete_after=60)
    print(len(response+'here are the events upcoming events: \n\nThis message is only visible to you and will terminate in T-minus 60 seconds'))

    """
    current message - will need to edit this for better understanding for user:
here are the 10 events upcoming events: 
2024-07-22T17:00:00-07:00 - Accelerate deep work session (5-7pm)
2024-07-23T18:00:00-07:00 - invite-only workshops/events
2024-07-24T17:00:00-07:00 - Accelerate deep work session (5-7pm)
2024-07-27T10:00:00-07:00 - Accelerate deep work session (10-12pm)
2024-07-29T17:00:00-07:00 - Accelerate deep work session (5-7pm)
2024-07-30T18:00:00-07:00 - invite-only workshops/events
2024-07-31T17:00:00-07:00 - Accelerate deep work session (5-7pm)
2024-08-03T10:00:00-07:00 - Accelerate deep work session (10-12pm)
2024-08-05T17:00:00-07:00 - Accelerate deep work session (5-7pm)
2024-08-06T18:00:00-07:00 - invite-only workshops/events
This message is only visible to you and will terminate in T-minus 60 seconds

message after some editing (much more understandable): 
here are the 28 events upcoming events: 
2024-07-23 10:00-11:00 - random example event title
2024-07-23 18:00-20:00 - invite-only workshops/events
2024-07-24 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-07-27 10:00-12:00 - Accelerate deep work session (10-12pm)
2024-07-29 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-07-30 18:00-20:00 - invite-only workshops/events
2024-07-31 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-08-03 10:00-12:00 - Accelerate deep work session (10-12pm)
2024-08-05 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-08-06 18:00-20:00 - invite-only workshops/events
2024-08-07 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-08-08 18:00-19:00 - Regional Conference Meeting III - Lambda Delta
2024-08-08 18:00-19:00 - Regionals meeting
2024-08-10 10:00-12:00 - Accelerate deep work session (10-12pm)
2024-08-12 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-08-13 18:00-20:00 - invite-only workshops/events
2024-08-14 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-08-17 10:00-12:00 - Accelerate deep work session (10-12pm)
2024-08-19 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-08-20 18:00-20:00 - invite-only workshops/events
2024-08-21 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-08-24 10:00-12:00 - Accelerate deep work session (10-12pm)
2024-08-26 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-08-27 18:00-20:00 - invite-only workshops/events
2024-08-28 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-08-31 10:00-12:00 - Accelerate deep work session (10-12pm)
2024-09-02 17:00-19:00 - Accelerate deep work session (5-7pm)
2024-09-03 18:00-20:00 - invite-only workshops/events
This message is only visible to you and will terminate in T-minus 60 seconds
    """


# STEP 4*: SPECIFIC BOT COMMAND TO INSERT AN EVENT/MULTIPLE EVENTS
# idea: have a comment similar to add notes command where I can add multiple notes at the same time
@bot.tree.command(name="add_event")
async def insertEvent(interaction: discord.Interaction, title: str, location: str, description: str,
                      start_datetime: str, end_datetime: str):
    """
    how to format input string events (how do I want user to type in events to add):
        - maybe read in a .txt file that includes multiple events to add? or a string
            - downside of using string is user probably won't be able to add multiple events
        - what if we specified input parameter as a list? result - error: "unsupported type _"...

    - I guess let's start with the 1st step: adding a single event
    - input format:
        - we can have multiple parameters for a single event: summary, location, datetime, timezone, etc.
            - e.g. insertEvent(interaction, event_summary: str, location: str, datetime: str, timezone: str, etc.)
        - or, we can have a single string containing all that info in an established order
            - e.g. insertEvent(interaction: discord.Interaction, event: str)

    example input format:
                  title  location   description       start_datetime         end_datetime
    !add_events 'Meeting,Office,Discuss Q2 targets,2024-07-02T10:00:00,2024-07-02T11:00:00';

    test command:
    /add_event title:random example event title location:mah house description:parteh time!! start_datetime:2024-07-23T10:00:00 end_datetime:2024-07-23T11:00:00

    next step: a command to add multiple events in a single request
    how to format input parameters and unpack said input: 1st idea
        - have multiple parameters for a single event (summary, location, datetime, etc.)
        - each of those params takes in a long string of inputs for multiple events
            - e.g. summary: eventtitle1, eventtitle2; location: location1, location2, etc.

        - then, to unpack input we can do something like this:

        a = "h e l l o"
        b = "w o r l d"
        c = "d a i l y"
        d = "w o r d l e"

        a_lst, b_lst, c_lst, d_lst = a.split(), b.split(), c.split(), d.split() - one line gets 4 different lists
    """
    # unlike note command above, I don't need to defer interaction (yet) cause this command can execute
    # quick enough without causing timeout - I'm guessing once I go to add multiple events in a command I'll have to
    # defer interaction...
    event_body = {
        'summary': title,
        'location': location,
        'description': description,
        'start': {
            'dateTime': start_datetime,
            'timeZone': 'America/Los_Angeles',  # time zone in Cali belongs to America/Los_Angeles instead of UTC!!
        },
        'end': {
            'dateTime': end_datetime,
            'timeZone': 'America/Los_Angeles',
        },
    }
    try:
        event = service_calendars.events().insert(calendarId='primary', body=event_body).execute()
        await interaction.response.send_message(f'added event: {event}. this message is only visible to you and will '
                                                f'terminate in T-minus 60 seconds', ephemeral=True, delete_after=60)
    except Exception as e:  # do research - try to look for the exact error(s) in this situation
        await interaction.response.send_message(f'an error occurred: {e}. this message is only visible to you and will '
                                                f'terminate in T-minus 60 seconds', ephemeral=True, delete_after=60)
    # return NotImplementedError("no code here yet...")


# STEP 5: MAIN ENTRY POINT
def main() -> None:
    bot.run(token=TOKEN)
    # client.run(token=TOKEN)


if __name__ == "__main__":
    main()
