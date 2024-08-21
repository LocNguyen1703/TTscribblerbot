# python discord bot tutorial for reference:
# https://www.youtube.com/watch?v=UYJDKSah-Ww

import os
import typing

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
import asyncio
import functools

import discord
from dotenv import load_dotenv
from typing import Final, Sequence
from discord import Intents, Client, Message
from discord import app_commands
from discord.ext import commands, tasks
from responses import get_response

from datetime import datetime, timedelta, time, timezone
import pytz

import pickle
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.errors import HttpError  # for specific error handling in the future

# STEP 0: LOAD DISCORD BOT TOKEN FROM SOMEWHERE SAFE
load_dotenv()
TOKEN: Final[str] = os.getenv('DISCORD_TOKEN')
# for debugging
print(TOKEN)

# SERVICE_ACCOUNT_FILE = "C:\ThetaTau\TTscribblerbot\serviceaccount_auto_auth.json"  # uncomment this line when running on local machine

# load ID of my Google spreadsheet of choice and ranges of cells I want to access/edit from .env
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
RANGE1 = os.getenv('TEST_READ_RANGE')
RANGE2 = os.getenv('TEST_WRITE_RANGE')
X_RANGE = os.getenv('X_CHECK_RANGE')

# STEP 1: BOT SETUP
intents: Intents = Intents.default()
intents.message_content = True  # enables access to message content for bot
intents.members = True  # enables access to guild member's info for bot
# client: Client = Client(intents=intents)  # maybe this is a "client message" instance - to read incoming user messages

# create a "bot command" instance - I'm assuming this is used for SPECIFIC commands like "/test" that
# user types in message
bot = commands.Bot(command_prefix='/', intents=intents)

# initialize a scheduler instance - for scheduling timely messages
scheduler = AsyncIOScheduler()
# scheduler = BackgroundScheduler()

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets',
          'https://www.googleapis.com/auth/calendar']

"""
initializing everything the 1st time - Google service account will auto-authenticate without us interacting with
web browsers manually
"""
creds = credentials = service_account.Credentials.from_service_account_file(
   os.getenv('GOOGLE_APPLICATION_CREDENTIALS'), scopes=SCOPES)

# creds = service_account.Credentials.from_service_account_file(
#     SERVICE_ACCOUNT_FILE, scopes=SCOPES)

# instance for Google Calendar - called "service_calendars"
# this service instance is from a class with multiple subclasses (my way of describing it)
# including an Events subclass - call service_calendars.events() to access
# we don't need to create any sub-instances like we do with Google sheets
service_calendars = build('calendar', 'v3', credentials=creds)
service_sheets = build('sheets', 'v4', credentials=creds)
# instance for Google sheets - called "sheet"
sheet = service_sheets.spreadsheets()


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
# @bot.event
# async def on_message(message: Message) -> None:
#     # if the message was sent by the bot itself, halt instead of keep responding & creating an infinite loop
#     if message.author == bot.user:
#         return
#     username: str = str(message.author)
#     user_message: str = message.content
#     channel: str = str(message.channel)
#
#     print(f'[{channel}, {username}: "{user_message}"]')
#     await send_message(message, user_message)


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
    # check to see if there's any event added - so that there's no out-of-index error when creating event_titles
    try:
        event_titles = x_check[0]
    except IndexError:
        await interaction.response.send_message("no event created - this message is only visible to you and will "
                                                "terminate in T-minus 60 seconds", ephemeral=True, delete_after=60)

    # Fetch spreadsheet metadata - for retrieving sheet_id of the sheet we're operating in
    spreadsheet = sheet.get(spreadsheetId=SPREADSHEET_ID).execute()

    # retrieve the correct sheet_id in the spreadsheet before making edit requests
    if len(spreadsheet.get('sheets', [])) == 0:  # if somehow there's no sheet created in spreadsheet
        raise ValueError("no sheet created")
    sheet_id = spreadsheet.get('sheets', [])[0]['properties']['sheetId']  # assumes 1st sheet in spreadsheet is ALWAYS
    # active_rolls

    # apparently bot times out if response command is not sent immediately after bot command is processed
    # defer() function lets bot know command is still being processed & keeps it from timing out
    # await interaction.response.defer()

    for k in range(len(x_check[1:])):
        for i in range(len(x_check[1:][k])):
            if x_check[1:][k][i] == "x":
                reason += "-missed " + event_titles[i] + " (+1)\n"
            elif x_check[1:][k][i] == "t":
                reason += "-late to " + event_titles[i] + " (+0.5)\n"

        # Create the request body to add the note to the specified cell
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': sheet_id,  # value 0 will default to the first sheet; change if needed
                    # (e.g. if sheet's name is changed)
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
        # if there's no content in request body (i.e. if no one is late to anything at all & no x's is marked)
        # there will be an HttpError 400: "must specify at least one request" - nothing to worry about
        sheet.batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body).execute()
    except Exception as e:
        print(f"An error occurred: {e}")
        await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)

    # confirm message that notes have been added
    await interaction.response.send_message(f"Notes added to cells successfully.", ephemeral=True)

    # print(notes_dict)  # for debugging
    # print(scores_dict)  # for debugging


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
    of a database, but idk if that's too complicated for this level and for maintenance..)
    
    2nd edit - (maybe) a better way: I could scan for the user's name, then look up that user's row in the sheet, 
    then recreate all the notes for that user and send that
    '''
    # fetch values from event attendance - check to see if there are any "x"
    x_fetch = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=X_RANGE).execute()
    x_check = x_fetch.get('values', [])

    NAME_RANGE = os.getenv('NAME_RANGE')
    names_fetch = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=NAME_RANGE).execute()
    names = names_fetch.get('values', [])

    SCORES_RANGE = os.getenv('SCORES_RANGE')
    scores_fetch = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=SCORES_RANGE).execute()
    scores = scores_fetch.get('values', [])

    reason: str = ""

    # get the row index of the user's name in the sheet
    row = names.index([username])  # taking into account first row of event_titles

    try:
        event_titles = x_check[0]
    except IndexError:
        await interaction.response.send_message("no event created - this message is only visible to you and will "
                                                "terminate in T-minus 60 seconds", ephemeral=True, delete_after=60)

    if len(x_check[row+1]) == 0: reason = "None added"
    else:
        for i in range(len(event_titles)):
            if x_check[row+1][i] == "x":  # row+1 takes into account mismatch caused by 1st row of event_titles
                reason += "-missed " + event_titles[i] + " (+1)\n"
            elif x_check[row+1][i] == "t":
                reason += "-late to " + event_titles[i] + " (+0.5)\n"

    good_standing_check: str = ' not' if float(scores[row][0]) < 2 else ""

    response: str = f"hey {username}! you currently have {scores[row][0]} points, which means " \
                    f"you're{good_standing_check} in bad standing!\n" \
                    f"reasons: {reason}\nif you have any questions please go annoy brother Scribe, " \
                    f"I am but a vessel of their intelligence"

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
# helper function to print message
async def print_message(message: str, file_path: str, input_channel: discord.TextChannel):
    edited = "\n\n".join(message.split("[br]"))  # "[br]" my own syntax for line breaks ("\n\n") - change if needed

    if input_channel:
        if file_path.lower() != "none":
            file = discord.File(file_path.strip('"'))  # remove quotation marks - file paths don't have ""
            await input_channel.send(edited, file=file)
        else:
            await input_channel.send(edited)


# helper function to dm message
async def print_dm(message: str, file_path: str, guild: discord.Guild, role_name: str):
    role = discord.utils.get(guild.roles, name=role_name)  # get role object from input role name
    edited = "\n\n".join(message.split("[br]"))
    # filter and put all members with same role object into a list
    members_with_roles = [member for member in guild.members if role in member.roles and not member.bot]

    for member in members_with_roles:
        try:
            if file_path.lower() != "none":
                file = discord.File(file_path.strip('"'))  # remove quotation marks - file paths don't have ""
                await member.send(edited, file=file)
            else:
                await member.send(edited)
            print("function ran successfully")  # for debugging
        except discord.Forbidden:
            print(f"Could not send DM to {member.name} (DMs might be disabled).")
        except Exception as e:
            print(f"Failed to send DM to {member.name}: {e}")


# helper function for autocompleting channel choice for messages
async def channel_name_autocomplete(interaction: discord.Interaction, current: str):
    channels = interaction.guild.text_channels
    return [
        app_commands.Choice(name=channel.name, value=channel.name)
        for channel in channels if current.lower() in channel.name.lower()
    ]


# actual scheduler function
@bot.tree.command(name='set_timely_message')
@app_commands.autocomplete(channel_name=channel_name_autocomplete)
async def setTimelyMessage(interaction: discord.Interaction, day: str, hour: str, minute: str, second: str,
                           message: str, file_path: str, channel_name: str):
    channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)

    scheduler.add_job(print_message, CronTrigger(day=None if day.lower() == "none" else day,
                                                 hour=None if hour.lower() == "none" else hour,
                                                 minute=None if minute.lower() == "none" else minute,
                                                 second=None if second.lower() == "none" else second),
                      args=[message, file_path, channel])
    await interaction.response.send_message(f'message scheduled: "{message}" with file: {file_path}. '
                                            f'Message is only visible to you and will terminate in T-minus 60 seconds',
                                            ephemeral=True, delete_after=60)
    # return NotImplementedError("no code yet...")


# STEP 4*: SPECIFIC BOT COMMAND TO SCHEDULE A ONE-TIME MESSAGE
@bot.tree.command(name='set_message')
@app_commands.autocomplete(channel_name=channel_name_autocomplete)
async def setOneTimeMessage(interaction: discord.Interaction, date_time: str, message: str, file_path: str,
                            channel_name: str):
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
    pacific = pytz.timezone('America/Los_Angeles')
    send_time = datetime.strptime(date_time, '%Y-%m-%d %H:%M')
    # send_time = send_time.replace(tzinfo=timezone.utc)  # convert to UTC time
    send_time = pacific.localize(send_time)
    # send_time = send_time.astimezone(pytz.UTC)  # Convert to UTC time

    # get channel from channel_name
    channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)

    scheduler.add_job(print_message, DateTrigger(run_date=send_time), args=[message, file_path, channel])
    await interaction.response.send_message(f'one-time message scheduled at {send_time}: "{message}", '
                                            f'with file: {file_path}. Message is only visible to you and will '
                                            f'terminate in T-minus 60 seconds', ephemeral=True, delete_after=60)


# STEP 4*: SPECIFIC BOT COMMAND TO DM MESSAGES TO USERS WITH FILTERED ROLE
@bot.tree.command(name='set_timely_dm')
async def setTimelyDM(interaction: discord.Interaction, day: str, hour: str, minute: str, second: str,
                      message: str, file_path: str, role_name: str):

    scheduler.add_job(print_dm, CronTrigger(day=None if day.lower() == "none" else day,
                                            hour=None if hour.lower() == "none" else hour,
                                            minute=None if minute.lower() == "none" else minute,
                                            second=None if second.lower() == "none" else second),
                      args=[message, file_path, interaction.guild, role_name])

    await interaction.response.send_message(f'message scheduled: "{message}" with file: {file_path}. '
                                            f'Message is only visible to you and will terminate in T-minus 60 seconds',
                                            ephemeral=True, delete_after=60)


# STEP 4*: SPECIFIC BOT COMMAND TO DM MESSAGES TO USERS WITH FILTERED ROLE
@bot.tree.command(name='set_dm')
async def setOneTimeDM(interaction: discord.Interaction, date_time: str, message: str, file_path: str,
                       role_name: str):
    pacific = pytz.timezone('America/Los_Angeles')
    send_time = datetime.strptime(date_time, '%Y-%m-%d %H:%M')
    send_time = pacific.localize(send_time)

    scheduler.add_job(print_dm, DateTrigger(run_date=send_time),
                      args=[message, file_path, interaction.guild, role_name])
    await interaction.response.send_message(f'one-time message scheduled at {send_time}: "{message}", '
                                            f'with file: {file_path}. Message is only visible to you and will '
                                            f'terminate in T-minus 60 seconds', ephemeral=True, delete_after=60)
# testing command: /set_dm date_time:2024-08-18 22:14 message:random dm - please work file_path:none role_name:random_testing_role


# helper function to send dm's about member's bad-standing status
async def print_bad_status(guild: discord.Guild):
    # fetch values from event attendance - check to see if there are any "x"
    x_fetch = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=X_RANGE).execute()
    x_check = x_fetch.get('values', [])

    NAME_RANGE = os.getenv('NAME_RANGE')
    names_fetch = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=NAME_RANGE).execute()
    names = names_fetch.get('values', [])

    SCORES_RANGE = os.getenv('SCORES_RANGE')
    scores_fetch = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=SCORES_RANGE).execute()
    scores = scores_fetch.get('values', [])

    # filter and put all members with same role object into a list
    members_lst = [member for member in guild.members if [member.display_name] in names]

    reason: str = ""
    event_titles = x_check[0]

    for member in members_lst:
        username: str = member.display_name
        row = names.index([username])

        if not x_check[row+1]: reason = "None added"
        else:
            for i in range(len(event_titles)):
                if x_check[row+1][i] == "x":  # row+1 takes into account mismatch caused by 1st row of event_titles
                    reason += "-missed " + event_titles[i] + " (+1)\n"
                elif x_check[row+1][i] == "t":
                    reason += "-late to " + event_titles[i] + " (+0.5)\n"

        good_standing_check: str = ' not' if float(scores[row][0]) < 2 else ""

        response: str = f"hey {username}! you currently have {scores[row][0]} points, which means " \
                        f"you're{good_standing_check} in bad standing!\n" \
                        f"reasons: {reason}\nif you have any questions please go annoy brother Scribe, " \
                        f"I am but a vessel of their intelligence"
        reason = ""  # reset reason for next iteration
        try:
            await member.send(response, delete_after=60)
            print("function ran successfully")  # for debugging
        except discord.Forbidden:
            print(f"Could not send DM to {member.name} (DMs might be disabled).")
        except Exception as e:
            print(f"Failed to send DM to {member.name}: {e}")


# STEP 4*: EXTRA-SPECIFIC BOT COMMAND TO SCHEDULE BAD-STANDING STATUS MESSAGES
@bot.tree.command(name='timely_bad_standing_dm')
async def timelyBadStandingDM(interaction: discord.Interaction, day: str, hour: str, minute: str, second: str):

    scheduler.add_job(print_bad_status, CronTrigger(day=None if day.lower() == "none" else day,
                                                    hour=None if hour.lower() == "none" else hour,
                                                    minute=None if minute.lower() == "none" else minute,
                                                    second=None if second.lower() == "none" else second),
                      args=[interaction.guild])

    await interaction.response.send_message(f'message scheduled. Message is only visible to you and will '
                                            f'terminate in T-minus 90 seconds', ephemeral=True, delete_after=90)


# STEP 4*: SPECIFIC BOT COMMAND TO CANCEL ALL MESSAGES
@bot.tree.command(name='cancel_all_scheduled_messages')
async def cancelAllMessages(interaction: discord.Interaction):
    scheduler.remove_all_jobs()
    await interaction.response.send_message("all scheduled messages have been canceled. Message is only visible "
                                            "to you and will terminate in T-minus 60 seconds",
                                            ephemeral=True, delete_after=60)


# STEP 4*: SPECIFIC BOT COMMAND TO SCHEDULE OTHER BOT COMMANDS
# helper function to deal with the function objects in dictionary
'''
work in progress - may have to abandon this idea
async def execute_command(coro, *args, **kwargs):
    try:
        await coro(*args, **kwargs)
    except Exception as e:
        # Handle exceptions in a way that doesn't affect the response of the command
        print(f"Error executing command: {e}")


@bot.tree.command(name="set_bot_function")
async def setBotFunction(interaction: discord.Interaction, day: str, hour: str, minute: str, second: str,
                         function: str):

    # add more command names below in the same format as needed
    commands_dict = {
        "note": functools.partial(execute_command, noteCommand.callback, interaction),
        "bad_standing_check": functools.partial(execute_command, badStandingCheck.callback, interaction),
        "events_check": functools.partial(execute_command, notifyEvents.callback, interaction)
    }

    input_function = commands_dict.get(function)

    if input_function is None:
        await interaction.response.send_message("your command name does not match any existing commands. "
                                                "Try another command", ephemeral=True, delete_after=60)
        return

    scheduler.add_job(input_function, CronTrigger(day=None if day.lower() == "none" else day,
                                                  hour=None if hour.lower() == "none" else hour,
                                                  minute=None if minute.lower() == "none" else minute,
                                                  second=None if second.lower() == "none" else second))

    await interaction.response.send_message(f'function scheduled: "{function}". Message is only visible to you and '
                                            f'will terminate in T-minus 60 seconds',
                                            ephemeral=True, delete_after=60)
'''


# STEP 4*: SPECIFIC BOT COMMAND TO OUTPUT A LIST OF GUIDELINES ON HOW TO USE BOT COMMANDS
@bot.tree.command(name='help')
async def guidelines(interaction: discord.Interaction):
    response: str = f'Here are some tips on how to use the bot commands\n' \
                    f'- "set_message" command: format to enter dateTime is YYYY-MM-DD HH:MM (use 24hr system)\n' \
                    f' - file_path: copy/paste path of file you want to send from your computer OR "none" for ' \
                    f'no file\n' \
                    f'- "set_timely_message" command: you can specify "none" or add a value to create a specific ' \
                    f'time you want\n' \
                    f' - second: values from 0 to 59 OR "none" - at which second message is sent EVERY MINUTE\n' \
                    f' - minute: values from 0 to 59 OR "none" - at which minute message is sent EVERY HOUR\n' \
                    f' - hour: values from 0 to 23 OR "none" - at which hour message is sent EVERY DAY\n' \
                    f' - day: values from 1 to 31 OR "none" - on which day message is sent EVERY MONTH\n' \
                    f' - file_path: copy/paste path of file you want to send from your computer OR "none" ' \
                    f'for no file\n' \
                    f'- "note" command: no input needed - for Scribe-only purposes\n' \
                    f'- "add_event" & "add_whole_day_event" commands - no input needed - for Scribe-only purposes\n' \
                    f'- "bad_standing_check" command: no input needed - bot will DM you your bad standing status\n' \
                    f'- "cancel_all_scheduled_messages" command: no input needed - NOTIFY BROTHER SCRIBE ' \
                    f'IF YOU USE IT!\n' \
                    f'- "events_check" command: - no input needed\n' \
                    f'- "test" command: no input needed - for Scribe-only purposes\n' \
                    f'refer to Brother Scribe for more instructions if needed!' \

    await interaction.response.send_message("Sure thing! check you DM's for a general guideline on how to use the bot."
                                            " This message is only available to you and will terminate in T-minus "
                                            "60 seconds", ephemeral=True, delete_after=60)
    await interaction.user.send(response)
    # return NotImplementedError("no code here yet...")


# STEP 4*: SPECIFIC BOT COMMAND TO NOTIFY EVENTS IN WEEK/MONTH
@bot.tree.command(name='events_check')
async def notifyEvents(interaction: discord.Interaction):
    now = datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
    events_result = service_calendars.events().list(calendarId='bkshlhck01pl08tgfif8qj89no@group.calendar.google.com',
                                                    timeMin=now, maxResults=29, singleEvents=True,
                                                    orderBy='startTime').execute()
    # events_result is a "response body" (kinda like the request body we created in note command)

    """
    get() function returns the specific category in the response body that we want - i.e. the items list
    google calendar API for better explanation: https://developers.google.com/calendar/api/v3/reference/events/list
    """
    events = events_result['items']  # I can either use .get() or "[]" to access categories in response body

    if not events:
        await interaction.response.send_message("no upcoming events found. This message is only visible "
                                                "to you and will terminate in T-minus 60 seconds",
                                                ephemeral=True, delete_after=60)

    # this else statement is really important - if this is not here, both response messages will be sent no matter
    # what and will result in the "message has already been responded to before" error
    else:
        event_list = []
        for event in events:
            # end = event['end']['dateTime'][11:16]  # isolate 11th-19th characters (end-time) from random formatting noise
            # start = event['start']['dateTime']  # start time
            # start = start.replace('T', ' ', 1).replace(start[16:25], '-' + end, 1)

            # apparently this method of retrieving start & end times ensures whether the event is all-day
            # or has a start & end time, the code will retrieve the according values
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))

            if 'T' in start:
                # start = start.replace('T', ' ', 1)
                start = start.replace('T', ' ', 1).replace(start[16:25], ' ', 1)  # Convert to readable format
            if 'T' in end:
                end = end[11:16]  # Extract just the time part
                # start = start.replace(start[16:25], '-' + end, 1)

            # event_list.append(f"{start} - {event['summary']}")
            event_list.append(f"{start} - {event['summary']} (Ends at {end})")

        response: str = "\n".join(event_list)
        await interaction.response.send_message(f'here are the {len(event_list)} events upcoming events: \n{response}\n'
                                                f'This message is only visible to you and will terminate in '
                                                f'T-minus 60 seconds', ephemeral=True, delete_after=60)
        print(
            len(response + 'here are the events upcoming events: \n\nThis message is only visible to you and will terminate in T-minus 60 seconds'))

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

message after some editing - taking into account whole-day events (much more understandable): 
here are the 10 events upcoming events: 
2024-08-21 - Week of Welcome  (Ends at 2024-08-26)
2024-08-25 18:00:00-07:00 - Chapter Zero (Ends at 22:00)
2024-08-26 - First Day of Classes (Ends at 2024-08-27)
2024-08-27 11:00:00-07:00 - Recruitment: Tabling (Ends at 18:00)
2024-08-29 18:00:00-07:00 - Polish Week Event & pro-devo sign language workshop (potentially Pro-devo dresscode workshop) (Ends at 20:00)
2024-08-30 18:00:00-07:00 - Alpha Delta Initiation  (Ends at 20:00)
2024-09-02 - Holiday - No Classes (Ends at 2024-09-03)
2024-09-02 19:00:00-07:00 - Formal Chapter (Ends at 21:00)
2024-09-03 17:00:00-07:00 - Recruitment: Meet-the-Bros (Ends at 19:00)
2024-09-04 17:30:00-07:00 - Recruitment: Comm-serv event (Ends at 20:00)
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
        event = service_calendars.events().insert(calendarId='bkshlhck01pl08tgfif8qj89no@group.calendar.google.com',
                                                  body=event_body).execute()
        await interaction.response.send_message(f'added event: {event}. this message is only visible to you and will '
                                                f'terminate in T-minus 60 seconds', ephemeral=True, delete_after=60)
    except Exception as e:  # do research - try to look for the exact error(s) in this situation
        await interaction.response.send_message(f'an error occurred: {e}. this message is only visible to you and will '
                                                f'terminate in T-minus 60 seconds', ephemeral=True, delete_after=60)
    # return NotImplementedError("no code here yet...")


# STEP 4*: SPECIFIC BOT COMMAND TO INSERT A WHOLE-DAY EVENT
@bot.tree.command(name="add_whole_day_event")
async def insertWholeDayEvent(interaction: discord.Interaction, title: str, location: str, description: str,
                              start_date: str, end_date: str):
    # when specifying dates, end_date is EXCLUSIVE - if start_date & end_date are only 1 day apart - event turns out
    # to be 1-day only instead of 2-day long
    event_body = {
        'summary': title,
        'location': location,
        'description': description,
        'start': {
            'date': start_date,
            'timeZone': 'America/Los_Angeles',  # time zone in Cali belongs to America/Los_Angeles instead of UTC!!
        },
        'end': {
            'date': end_date,
            'timeZone': 'America/Los_Angeles',
        },
    }
    try:
        event = service_calendars.events().insert(calendarId='bkshlhck01pl08tgfif8qj89no@group.calendar.google.com',
                                                  body=event_body).execute()
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
