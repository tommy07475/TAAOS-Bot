from taiga import TaigaAPI
import os
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio
import json
import requests
import output as ot

# 🧠 TAAOS (Taiga Automation Assistance Operative System)
# 
# Hello and welcome to TAAOS! 
# This is a Discord bot built to assist with daily task management within a Discord community.
# 
# The bot currently supports three core functions:
# 1. parsequota
# 2. create_card
# 3. promote
#
# ⚠️ Disclaimer:
# This bot is heavily adapted to a specific Taiga board (Taiga is a project and team management platform similar to Trello). 
# Testing it on a different Taiga setup may not work properly, as the board layout and custom fields are tailored to the original configuration.
#
# ---
#
# 🔹 parsequota
# The primary feature of TAAOS. 
# This command reads the latest message from a specified Discord channel. 
# That message contains rows formatted as:
#   "(Name) | Quota: (Value) | Activity: (Value)"
# For example:
#   "Tommy | Quota: Passed | Activity: High"
#
# The bot parses all rows, compiles them into a structured table, and iterates through each entry.
# Using this data, it communicates with the Taiga API to update the relevant user stories on a designated Taiga board.
# It locates cards matching each name and modifies various attributes based on the parsed quota and activity data.
#
# ---
#
# 🔹 create_card
# A command designed to create new Taiga cards for new members.
# It uses structured input to generate a card containing all relevant information about the person.
# The command sets the description, custom attributes, appropriate roles, and user status.
#
# ---
#
# 🔹 promote
# Used to promote users to their next rank.
# This command updates the user’s card by changing their roles, status, and adding the new tasks associated with the next level.


# Load credentials from environment
EMAIL = os.getenv("TAIGA_USERNAME") # Username, to be added in your env variables, or for a quick trial run simply replace it with EMAIL = "youremail@gmail.com"
PASSWORD = os.getenv("TAIGA_PASSWORD") # Password, same things as the Email
TAIGA_URL = "https://api.taiga.io/api/v1" #Constant, don't change, essential for JSON functions

# Bot Configuration
TOKEN = "TO REPLACE" # Discord bot token
source_channel_id = 1234567891011121314  # Channel to read last message from (placeholder id, to replace)
destination_channel_id = 1234567891011121314  # Channel to post parsed data (placeholder id, to replace)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # Access to app_commands
logging.getLogger("discord.gateway").setLevel(logging.ERROR)
ot.success("Step 1 complete - Gathering user credentials")

if not EMAIL or not PASSWORD:
    raise ValueError(ot.error("Missing TAIGA_USERNAME or TAIGA_PASSWORD environment variables"))

# Authenticate
api = TaigaAPI()
api.auth(
    username=EMAIL,
    password=PASSWORD
)
ot.success("Step 2 complete - User authenticated through the taiga API")
# Set project and column (status)
PROJECT_SLUG = "sevencuts-aegis-research-division-1" # this is the identifier of the taiga board, currently set to the main board (the bot won't just work in any board, the credentials you gave it must have access to the board you're trying to use)
if PROJECT_SLUG == "tommy07475-test":
    ot.warn("RUNNING BOT IN TEST BOARD")
elif PROJECT_SLUG == "sevencuts-aegis-research-division-1":
    ot.info("RUNNING BOT IN OFFICIAL ARD SERVER")
TARGET_STATUS_NAME = "Researcher"
SECOND_TARGET_STATUS_NAME = "Senior Researcher"
THIRD_TARGET_STATUS_NAME = "Discharging Personnel"
FOURTH_TARGET_STATUS_NAME = "Exempted Personnel"
FIFTH_TARGET_STATUS_NAME = "Assistant Researcher"

# Get project and statuses (user stories use story statuses)
project = api.projects.get_by_slug(PROJECT_SLUG)
story_statuses = project.list_user_story_statuses()
ot.success("Step 3 complete - Successfully found the project")

# Find target column/status by name
def get_target_status(TARGET_STATUS_VAR):
    target_status = next((s for s in story_statuses if s.name == TARGET_STATUS_VAR), None)
    if not target_status:
        raise ValueError(ot.error(f"Status '{TARGET_STATUS_VAR}' not found in the project's story statuses."))
    else:
        return target_status

# Build a map of Custom Field IDs to names for this project
cf_definitions = api.user_story_attributes.list(project=project.id)
cf_id_to_name = {str(cf.id): cf.name for cf in cf_definitions}

ot.success("Step 4 complete - Successfully found the target column and identified general custom attributes")

# Get user stories in the desired column
def get_stories_in_column(TARGET_STATUS_VAR):
    stories_in_column = [
        story for story in api.user_stories.list(project=project.id)
        if story.status == get_target_status(TARGET_STATUS_VAR).id
    ]
    ot.info(f"Found {len(stories_in_column)} user stories in column '{TARGET_STATUS_VAR}'")
    return stories_in_column

ot.success("Step 5 complete! - Successfully retrieved the user stories in the target column")

def update_custom_field(user_story, cf_definitions, target_name, new_value_name):
    nooptions = False
    ot.info(f"Attempting to update custom field '{target_name}' to '{new_value_name}' for story '{user_story.subject}'")

    try:
        target_name = target_name.strip().lower()

        cf = next((c for c in cf_definitions if c.name.lower() == target_name), None)
        if not cf:
            ot.error(f"Custom field '{target_name}' not found in definitions.")
            return False

        ot.success(f"Found custom field: '{cf.name}' (ID: {cf.id})")

        # Get current value of the custom field
        current_value = get_custom_attribute_value(user_story, cf_definitions, target_name)
        if current_value and str(current_value).lower() == str(new_value_name).lower():
            ot.info(f"Field '{cf.name}' is already set to '{current_value}'. Skipping update.")
            return True


        # Parse options
        options_raw = cf.extra.get("choices") if isinstance(cf.extra, dict) else cf.extra
        if not isinstance(options_raw, list):
            ot.warn(f"Custom field '{cf.name}' has no valid options format.")
            nooptions = True
            #return False

        ot.info(f"Checking if given option is valid")
        if not nooptions:
            matched = False
            for opt in options_raw:
                option_name = opt["name"] if isinstance(opt, dict) else opt

                # Check match (case-insensitive)
                if option_name.lower() == new_value_name.lower():
                    matched = True
                    ot.success("Match found")

            if not matched:
                ot.error(f"The value '{new_value_name}' does not match any valid options for '{cf.name}'.")
                return False

        # 🔄 Re-fetch the most up-to-date version of the story
        latest_story = api.user_stories.get(user_story.id)
        
        if get_custom_attribute_value(user_story, cf_definitions, "Activity") == "Inactivity Notice":
            ot.info("Skipping custom value update due to user being in Inactivity Notice.")
        else:
            custom_field_id = str(cf.id)
            latest_story.set_attribute(custom_field_id, new_value_name, 1)

        # 🔁 Confirm
        verified = api.user_stories.get(user_story.id)
        verified_values = verified.get_attributes().get("attributes_values", {})
        confirmed = verified_values.get(str(cf.id), "N/A")

        ot.info(f"Re-fetched story. Field '{cf.name}' is now: '{confirmed}'")

        return True if str(confirmed).lower() == str(new_value_name).lower() else False

    except Exception as e:
        ot.error(f"Exception occurred while updating custom field: {e}")
        return False

def add_isolated_comment(story, comment):
    try:
        # Fetch the latest version of the story
        latest = api.user_stories.get(story.id)
        version = latest.version

        headers = {
            "Authorization": f"Bearer {api.token}",
            "Content-Type": "application/json"
        }

        data = {
            "comment": comment,
            "version": version
        }

        url = f"{TAIGA_URL}/userstories/{story.id}"

        response = requests.patch(
            url,
            headers=headers,
            data=json.dumps(data)
        )

        if response.status_code in (200, 201):
            ot.success("Successfully added isolated comment.")
            return True
        else:
            ot.error(f"Failed to add comment. Status: {response.status_code}, Body: {response.text}")
            return False

    except Exception as e:
        ot.error(f"Exception occurred while posting isolated comment: {e}")
        return False
    
def add_isolated_status(story, status):
    try:
        og_status = get_status_from_id(story.status) #for print sillies
        # Fetch the latest version of the story
        latest = api.user_stories.get(story.id)
        version = latest.version

        headers = {
            "Authorization": f"Bearer {api.token}",
            "Content-Type": "application/json"
        }

        data = {
            "status": status,
            "version": version
        }

        url = f"{TAIGA_URL}/userstories/{story.id}"

        response = requests.patch(
            url,
            headers=headers,
            data=json.dumps(data)
        )

        if response.status_code in (200, 201):
            updated_story = api.user_stories.get(story.id)
            new_status = get_status_from_id(updated_story.status)
            ot.success(f"Successfully changed status from: {og_status} to: {new_status}")
            return True
        else:
            ot.error(f"Failed to add status. Status: {response.status_code}, Body: {response.text}")
            return False

    except Exception as e:
        ot.error(f"Exception occurred while posting isolated status: {e}")
        return False
    
def isolated_task_change(mode, story, task_name, reqinput):
    try:
        # ren renames the task
        # del deletes the task
        # sta changes the status of the task
        match mode:
            case "ren":
                task_id = get_task_id_by_name(story, task_name)
                latest = api.tasks.get(task_id)
                version = latest.version

                headers = {
                    "Authorization": f"Bearer {api.token}",
                    "Content-Type": "application/json"
                }

                data = {
                    "subject": reqinput,
                    "version": version
                }

                url = f"{TAIGA_URL}/tasks/{task_id}"

                response = requests.patch(
                    url,
                    headers=headers,
                    data=json.dumps(data)
                )

                if response.status_code in (200, 201):
                    ot.success(f"Successfully changed task subject.")
                    return True
                else:
                    ot.error(f"Failed to change subject. Status: {response.status_code}, Body: {response.text}")
                    return False
            case "del":
                task_id = get_task_id_by_name(story, task_name)

                headers = {
                    "Authorization": f"Bearer {api.token}",
                    "Content-Type": "application/json"
                }

                data = {}

                url = f"{TAIGA_URL}/tasks/{task_id}"

                response = requests.delete(
                    url,
                    headers=headers,
                    data=json.dumps(data)
                )

                if response.status_code in (200, 201):
                    ot.success(f"Successfully deleted task.")
                    return True
                elif response.status_code in (204):
                    ot.warn(f"Successfully deleted task, however server did not respond back, status code: {response.status_code}")
                else:
                    ot.error(f"Failed to delete task. Status: {response.status_code}, Body: {response.text}")
                    return False
            case "sta":
                task_id = get_task_id_by_name(story, task_name)
                latest = api.tasks.get(task_id)
                version = latest.version

                headers = {
                    "Authorization": f"Bearer {api.token}",
                    "Content-Type": "application/json"
                }

                data = {
                    "status": get_task_status_id(reqinput),
                    "version": version
                }

                url = f"{TAIGA_URL}/tasks/{task_id}"

                response = requests.patch(
                    url,
                    headers=headers,
                    data=json.dumps(data)
                )

                if response.status_code in (200, 201):
                    ot.success(f"Successfully changed task status.")
                    return True
                else:
                    ot.error(f"Failed to change task status. Status: {response.status_code}, Body: {response.text}")
                    return False
            case _:
                ot.error("Invalid mode for isolated task function.")
                return False
    except Exception as e:
        ot.error(f"Exception occurred while posting isolated status: {e}")
        return False

def get_task_id_by_name(story, task_name):
    """
    Return the ID of a task with a given name under a specific user story.
    Uses the global `api` and `project` variables.
    
    :param story: The user story object (or anything with .id)
    :param task_name: The subject (name) of the task to find
    :return: Task ID (int) or None if not found
    """
    try:
        # Fetch all tasks for this user story
        tasks = api.tasks.list(project=project.id, user_story=story.id)

        for task in tasks:
            if task.subject and task.subject.lower() == task_name.lower():
                return task.id

        # Nothing matched
        return None

    except Exception as e:
        print(f"[ FAIL ] Exception occurred while getting task ID: {e}")
        return None

def get_status_id(sname):
    try:
        story_statuses = project.list_user_story_statuses()
        for s in story_statuses:
            if s.name == sname:
                return s.id
        return None
    except Exception as e:
        ot.error(f"Execption occurred while getting status ID: {e}")
        return None

def get_status_from_id(sid):
    try:
        story_statuses = project.list_user_story_statuses()
        for s in story_statuses:
            if s.id == sid:
                return s.name
        return None
    except Exception as e:
        ot.error(f"Execption occurred while getting status ID: {e}")
        return None

def get_next_status_for_promo(status):
    match status:
        case "Assistant Researcher":
            return "Researcher"
        case "Researcher":
            return "Senior Researcher"
        case "Senior Researcher":
            return "Instructor"
        case "Instructor":
            return "Supervisor"
        case "Supervisor":
            return "Overwatch"
        case _:
            ot.error("Invalid input for next status promo functions, defaulting to Assistant Reseacher column.")
            return "Assistant Researcher"

def get_task_status_id(sname):
    try:
        task_statuses = api.task_statuses.list(project=project.id)
        for s in task_statuses:
            if s.name == sname:
                return s.id
        return None
    except Exception as e:
        ot.error(f"Execption occurred while getting task status ID: {e}")
        return None
        

def isolated_tag_change(mode, story, name):
    match mode:
        case "add":
            try:
                # 1. Fetch latest story
                latest = api.user_stories.get(story.id)
                version = latest.version
                existing_tags = latest.tags or []  # list of [name, color]

                # 2. Fetch project's tag definitions to find the color
                project_info = api.projects.get(project.id)
                project_tags = project_info.tags or []
                color = ""
                for t in project_tags:
                    if t[0].lower() == name.lower():
                        color = t[1] if t[1] is not None else ""
                        break

                # 3. If already present, skip
                if any(t[0].lower() == name.lower() for t in existing_tags):
                    ot.success(f"Tag '{name}' already present.")
                    return True

                # 4. Add new tag
                new_tag = [name, color]
                updated_tags = existing_tags + [new_tag]

                headers = {
                    "Authorization": f"Bearer {api.token}",
                    "Content-Type": "application/json"
                }

                data = {
                    "tags": updated_tags,
                    "version": version
                }

                url = f"{TAIGA_URL}/userstories/{story.id}"

                response = requests.patch(
                    url,
                    headers=headers,
                    data=json.dumps(data)
                )

                if response.status_code in (200, 201):
                    ot.success(f"Successfully added isolated tag '{name}' (color: {color or 'default'}).")
                    return True
                else:
                    ot.error(f"Failed to add tag. Status: {response.status_code}, Body: {response.text}")
                    return False

            except Exception as e:
                ot.error(f"Exception occurred while posting isolated tag: {e}")
                return False
        case "rem":
            try:
                # 1. Fetch latest story
                latest = api.user_stories.get(story.id)
                version = latest.version
                existing_tags = latest.tags or []  # list of [name, color]

                # 2. Filter out the tag
                updated_tags = [t for t in existing_tags if t[0].lower() != name.lower()]

                # 3. If nothing changed, skip
                if len(updated_tags) == len(existing_tags):
                    ot.success(f"Tag '{name}' not present.")
                    return True

                headers = {
                    "Authorization": f"Bearer {api.token}",
                    "Content-Type": "application/json"
                }

                data = {
                    "tags": updated_tags,
                    "version": version
                }

                url = f"{TAIGA_URL}/userstories/{story.id}"

                response = requests.patch(
                    url,
                    headers=headers,
                    data=json.dumps(data)
                )

                if response.status_code in (200, 201):
                    ot.success(f"Successfully removed isolated tag '{name}'.")
                    return True
                else:
                    ot.error(f"Failed to remove tag. Status: {response.status_code}, Body: {response.text}")
                    return False

            except Exception as e:
                ot.error(f"Exception occurred while removing isolated tag: {e}")
                return False
        case _:
            ot.error("Invalid mode for isolated tag function.")
            return False

    
'''    
def add_isolated_user(project, email):
    print("[ INFO ] Trying to add iso user")
    try:
        projectid = project.id
        roles = api.roles.list(project=project.id)
        target_role = next((r for r in roles if r.name.lower() == "ard personnel"), None)

        if not target_role:
            print("[ FAIL ] Couldn't find the targeted role.")
            return False

        headers = {
            "Authorization": f"Bearer {api.token}",
            "Content-Type": "application/json"
        }

        data = {
            "project_id": projectid,
            "bulk_membership": [{"role_id": target_role, "username": email}]
        }

        url = f"{TAIGA_URL}/memberships/bulk_create"

        response = requests.patch(
            url,
            headers=headers,
            data=json.dumps(data)
        )

        if response.status_code in (200, 201):
            print("[  OK  ] Successfully added isolated user.")
            return True
        else:
            print(f"[ FAIL ] Failed to add user. Status: {response.status_code}, Body: {response.text}")
            return False

    except Exception as e:
        print(f"[ FAIL ] Exception occurred while posting isolated comment: {e}")
        return False
'''

def add_isolated_user(project, user_id, role_id):
    ot.info("Adding user to project")
    try:
        api.memberships.create(
            project=project.id,
            user=user_id,
            role=role_id
        )
        ot.success("Successfully added user to project.")
        return True
    except Exception as e:
        ot.error(f"Exception occurred while adding user: {e}")
        return False

def get_custom_attribute_value(user_story, cf_definitions, target_name): 
    try:
        target_name = target_name.strip().lower()

        # Find the custom field definition by name
        cf = next((c for c in cf_definitions if c.name.lower() == target_name), None)
        if not cf:
            ot.error(f"Custom field '{target_name}' not found in definitions.")
            return None

        # Get the field ID (as string) and look it up in the user story's custom attributes
        custom_field_id = str(cf.id)
        current_values = user_story.get_attributes().get("attributes_values", {})

        # Return the current value for that custom field
        current_value = current_values.get(custom_field_id)
        return current_value

    except Exception as e:
        ot.error(f"Exception occurred while retrieving custom field value: {e}")
        return None


def check_if_reached_4_strikes(user_story, cf_definitions, target_name):
    try:
        if get_custom_attribute_value(user_story, cf_definitions, target_name) == "4 | 4 Weeks Inactive":
            return True
        else:
            return False
    except Exception as e:
        ot.error(f"Exception occurred while retrieving custom field value: {e}")
        return None    

def get_next_strike(number):
    if number == "1":
        return "2 | 2 Weeks Inactive"
    elif number == "2":
        return "3 | 3 Weeks Inactive"
    elif number == "3":
        return "4 | 4 Weeks Inactive"
    else:
        return "1 | 1 Week Inactive"
    

def strike_to_number(strike):
    if strike == "1 | 1 Week Inactive":
        return "1"
    elif strike == "2 | 2 Weeks Inactive":
        return "2"
    elif strike == "3 | 3 Weeks Inactive":
        return "3"
    elif strike == "4 | 4 Weeks Inactive":
        return "4"
    else:
        return "0"

def process_user(story, user_input, PR_Result, Actual_Activity):
        try:
            try:
                # Convert string to date object
                input_date = datetime.strptime(user_input, "%Y-%m-%d").date()

                # Add 7 days
                new_date = input_date + timedelta(days=7)
            except ValueError:
                ot.warn("Invalid date format. Please use YYYY-MM-DD.")

            if PR_Result == "Failed":
                Activity = get_custom_attribute_value(story, cf_definitions, "Activity Strikes")
                Activity = strike_to_number(Activity)
                Actual_Activity_When_Fail = Actual_Activity
                success2 = update_custom_field(story, cf_definitions, "Activity Strikes", get_next_strike(Activity))
                if not success2:
                    ot.error("Update failed.")
                else:
                    ot.success("Successfully updated the custom attribute, CHECK TAIGA FOR CONFIRMATION")
                Actual_Activity = Activity+" -> "+(strike_to_number(get_custom_attribute_value(story, cf_definitions, "Activity Strikes")))
                comment_text = "**\[L-2\] Researcher Performance Review**\n\n"+str(input_date)+" - "+str(new_date)+"\n"+"PR Review: "+PR_Result+"\n"+"Activity Strikes: "+Actual_Activity
                success2 = update_custom_field(story, cf_definitions, "Activity", Actual_Activity_When_Fail)
                if not success2:
                    ot.error("Update failed.")
                else:
                    ot.success("Successfully updated the custom attribute, CHECK TAIGA FOR CONFIRMATION")
            else:
                comment_text = "**\[L-2\] Researcher Performance Review**\n\n"+str(input_date)+" - "+str(new_date)+"\n"+"PR Review: "+PR_Result+"\n"+"Activity: "+Actual_Activity
                success2 = update_custom_field(story, cf_definitions, "Activity", Actual_Activity)
                if not success2:
                    ot.error("Update failed.")
                else:
                    ot.success("Successfully updated the custom attribute, CHECK TAIGA FOR CONFIRMATION")

            if comment_text:
                add_isolated_comment(story, comment_text)
                ot.success("Comment added.")
                return True
            else:
                ot.info("Skipped.")
                return False
        except Exception as ex:
            ot.error(f"Unexpected exception: {ex}")
        return False

# START OF BOT SHENANINGANS

@bot.event
async def on_ready():
    ot.core(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await tree.sync()
        ot.core(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        ot.error(f"Failed to sync commands: {e}")

@tree.command(name="parsequota", description="Parse quota data and match to user stories.")
@app_commands.describe(date_string="Date to use in format YYYY-MM-DD")
async def parse_quota(interaction: discord.Interaction, date_string: str):
    await interaction.response.send_message("✅ Running quota match...", ephemeral=True)

    source_channel = bot.get_channel(source_channel_id)
    destination_channel = bot.get_channel(destination_channel_id)

    if not source_channel or not destination_channel:
        await interaction.followup.send("Channel IDs are invalid.", ephemeral=True)
        return

    # === Step 1: Read quota report ===
    messages = [msg async for msg in source_channel.history(limit=1)]
    if not messages:
        await destination_channel.send("No quota report message found.")
        return

    last_message = messages[0].content.strip()
    lines = last_message.split('\n')
    library = []

    for line in lines:
        try:
            parts = [p.strip() for p in line.split('|')]
            name = parts[0]
            quota = parts[1].split(':')[1].strip()
            activity = parts[2].split(':')[1].strip()
            library.append([name, quota, activity])
        except (IndexError, ValueError):
            continue  # Skip malformed lines

    # === Step 2: Try matching in multiple columns ===
    taiga_mismatches = []
    google_mismatches = []
    ac_strikes = []

    status_order = [
        TARGET_STATUS_NAME,
        SECOND_TARGET_STATUS_NAME,
        THIRD_TARGET_STATUS_NAME,
        FOURTH_TARGET_STATUS_NAME,
        FIFTH_TARGET_STATUS_NAME
    ]

    for status_name in status_order:
        # Reset TAIGA mismatches for each pass, but keep library only for unmatched ones
        taiga_mismatches.clear()
        google_mismatches.clear()

        for story in get_stories_in_column(status_name):
            story_name = story.subject
            match = None
            for row in library:
                if row[0] == story_name:
                    match = row
                    break

            if match:
                PR_Result = match[1]
                Actual_Activity = match[2]
                success = await asyncio.to_thread(process_user, story, date_string, PR_Result, Actual_Activity)
                if not success:
                    ot.error(f"Failed processing {story_name}")
                library.remove(match)
                if check_if_reached_4_strikes(story, cf_definitions, "Activity Strikes"):
                    ac_strikes.append(story_name+" Has reached 4 activity strikes"+"\n")
            else:
                taiga_mismatches.append(story_name)

        # Anything left in library after this pass = Google mismatch
        for leftover in library:
            google_mismatches.append(leftover[0])

        # If no Google mismatches remain, stop early
        if not google_mismatches:
            break

    # === Step 3: Prepare final report ===
    report_lines = []

    if google_mismatches:
        for name in google_mismatches:
            report_lines.append(f"Couldn't find any matches for {name} [GOOGLE]")
    
    if ac_strikes:
        for strike in ac_strikes:
            report_lines.append(strike)

    final_report = "Quota Import Report:\n" + "\n".join(report_lines) if report_lines else "Quota Import Report:\nAll matches successful."
    await destination_channel.send(final_report)
    ot.info("End of command")

# ------------------------------ WORK IN PROGRESS ------------------------------

class CardInfoModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Create New Taiga Card")

        # First input: Card Details
        self.card_details = discord.ui.TextInput(
            label="Card Details",
            style=discord.TextStyle.paragraph,
            placeholder="Paste the user details block here...",
            required=True
        )
        self.add_item(self.card_details)

        # Second input: Division
        self.division = discord.ui.TextInput(
            label="Command Mode",
            style=discord.TextStyle.short,
            placeholder="Type AOA, ARD, or AAST, anything else will result in the function not executing.",
            required=True,
            max_length=4
        )
        self.add_item(self.division)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)  # Prevents timeout

        details = self.card_details.value
        mode = self.division.value.strip()

        # Parse the pasted details
        details_lines = self.card_details.value.splitlines()

        roblox_name = ""
        taiga_name = ""
        timezone = ""
        email = ""
        contract = ""
        account_link = ""
        security_link = ""
        join_date = datetime.today().strftime("%d/%m/%Y")  # DD/MM/YYYY format

        for line in details_lines:
            line = line.strip()
            if line.lower().startswith("roblox:"):
                roblox_name = line.split(":", 1)[1].strip()
            elif line.lower().startswith("taiga:"):
                taiga_name = line.split(":", 1)[1].strip()
            elif line.lower().startswith("timezone:"):
                timezone = line.split(":", 1)[1].strip()
            elif line.lower().startswith("email:"):
                email = line.split(":", 1)[1].strip()
            elif line.lower().startswith("contract:"):
                contract = line.split(":", 1)[1].strip()
            elif line.lower().startswith("roblox account link:"):
                account_link = line.split(":", 1)[1].strip()
            elif line.startswith("http") and "discord.com/channels" in line:
                security_link = line

        # Fill the HTML description
        description_html = f"""<b>User Profile</b>
----------------

<hr>

<h4>User Details</h4>
Roblox: {roblox_name}
Taiga: @{taiga_name}
Timezone: {timezone}
Email: {email}
Contract: {contract}
Roblox Account Link: {account_link}
Join Date: {join_date} <br>

<hr>

<h3>Security</h3>
{security_link} <br>

<h3>Enforcement</h3>
No Enforcement Actions.<br>

<h3>Inactivity Notices</h3>
No Inactivity Notices.<br>
"""

        try:
            # 1️⃣ Create the card
            new_story = api.user_stories.create(
                project=project.id,
                subject=roblox_name,  # Card name from Roblox field
                description=description_html
            )


            # 2️⃣ Add the "Education Program" task
            api.tasks.create(
                project=project.id,
                user_story=new_story.id,
                status = get_task_status_id("Incomplete"),
                subject="Education Program"
            )

            api.tasks.create(
                project=project.id,
                user_story=new_story.id,
                status = get_task_status_id("Incomplete"),
                subject="Current Rank: Assistant Researcher"
            )

            # 3️⃣ Add the "assistant researcher" tag
            updated_tags = list(new_story.tags) if new_story.tags else []
            if "assistant researcher" not in [t.lower() for t in updated_tags]:
                isolated_tag_change("add", new_story, "assistant researcher")
            if "divisional trialing" not in [t.lower() for t in updated_tags]:
                isolated_tag_change("add", new_story, "division trialing")
            
            new_story = api.user_stories.get(new_story.id)

            update_custom_field(new_story, cf_definitions, "Timezone", timezone)
            update_custom_field(new_story, cf_definitions, "Divisional Status", "Personnel")
            update_custom_field(new_story, cf_definitions, "Divisional Strikes", "0")
            update_custom_field(new_story, cf_definitions, "Activity Strikes", "0")

            await interaction.followup.send(
                f"Card '{roblox_name}' created successfully with Education Program task and tag.",
                ephemeral=True
            )

        except Exception as e:
            await interaction.followup.send(f"Failed to create card: {e}", ephemeral=True)


@tree.command(name="create_card", description="Create a new Taiga card with preset description from pasted details.")
async def create_card(interaction: discord.Interaction):
    await interaction.response.send_modal(CardInfoModal())

# ------------------------------ HEAVELY WORK IN PROGRESS ------------------------------

@tree.command(name="add_member", description="Add a member to the Taiga project by email.")
@app_commands.describe(email="The email of the Taiga user to add")
async def add_member(interaction: discord.Interaction, email: str):
    await interaction.response.defer(ephemeral=True)  # respond immediately
    print("[ INFO ] Started function")

    try:
        # 1️⃣ Lookup user by email in a background thread
        print("[ INFO ] Looking up user")
        user_matches = await asyncio.to_thread(api.users.list)
        print("[ INFO ] Found")
        if not user_matches:
            await interaction.followup.send(
                f"[ FAIL ] No Taiga account found with email: {email}. Check for typos.",
                ephemeral=True
            )
            return

        print("[ INFO ] Found Email")
        user = user_matches[0]

        # 2️⃣ Check if already a member
        print("[ INFO ] Checking if already member")
        memberships = await asyncio.to_thread(api.memberships.list, project=project.id)
        print("[ INFO ] Found")
        if any(m.user == user.id for m in memberships):
            await interaction.followup.send(
                f"[ INFO ] {user.full_name_display} ({email}) is already a member of the project.",
                ephemeral=True
            )
            return

        print("[ INFO ] Checked if already member")
        # 3️⃣ Get "ARD Personnel" role
        print("[ INFO ] Getting role")
        roles = await asyncio.to_thread(api.roles.list, project=project.id)
        print("[ INFO ] Found")
        target_role = next((r for r in roles if r.name.lower() == "ard personnel"), None)

        if not target_role:
            await interaction.followup.send(
                "[ FAIL ] Role 'ARD Personnel' not found in project roles.",
                ephemeral=True
            )
            return

        # 4️⃣ Add the user
        print("[ INFO ] Adding iso user")
        await asyncio.to_thread(add_isolated_user, project, user.id, target_role.id)
        print("[ INFO ] Done")

        await interaction.followup.send(
            f"[  OK  ] {user.full_name_display} ({email}) has been added to the project as 'ARD Personnel'.",
            ephemeral=True
        )

    except Exception as e:
        await interaction.followup.send(
            f"[ FAIL ] Could not add member: {e}",
            ephemeral=True
        )

@tree.command(name="promote", description="promote a user on taiga")
@app_commands.describe(name="Insert the name of the target card.")
async def parse_quota(interaction: discord.Interaction, name: str):
    try:
        await interaction.response.send_message("✅ Promoting user...", ephemeral=True)
        status_order = [
            "Assistant Researcher",
            "Researcher",
            "Senior Researcher",
            "Instructor",
            "Supervisor",
        ]

        for status_name in status_order:
            match = None
            for story in get_stories_in_column(status_name):
                story_name = story.subject
                if story_name == name:
                    match = story

                if match:
                    break
            
            if match:
                ot.success("User card found.")
                break
            else:
                ot.error(f"User card not found in: {status_name}")

        currentStatusId = match.status
        currentStatusName = get_status_from_id(currentStatusId)
        newStatusName = get_next_status_for_promo(currentStatusName)
        newStatusId = get_status_id(newStatusName)

        if currentStatusId:
            add_isolated_status(match, newStatusId)
        else:
            ot.error("Status ID not found.")

        match newStatusName:
            case "Researcher":
                isolated_task_change("ren", match, "Current Rank: Assistant Researcher", "Current Rank: Researcher")
                isolated_task_change("sta", match, "Education Program", "Complete")
                api.tasks.create(
                    project=project.id,
                    user_story=match.id,
                    status = get_task_status_id("Incomplete"),
                    subject="Researcher Advancement Program"
                )
                ot.success('Successfully created task "Researcher Advancement Program"')
                isolated_tag_change("rem", match, "assistant researcher")
                isolated_tag_change("rem", match, "divisional trialing")
                isolated_tag_change("add", match, "researcher")
            case "Senior Researcher":
                isolated_task_change("ren", match, "Current Rank: Researcher", "Current Rank: Senior Researcher")
                isolated_task_change("sta", match, "Researcher Advancement Program", "Complete")
                api.tasks.create(
                    project=project.id,
                    user_story=match.id,
                    status = get_task_status_id("Incomplete"),
                    subject="Instructor Training Program"
                )
                ot.success('Successfully created task "Instructor Training Program"')
                isolated_tag_change("rem", match, "researcher")
                isolated_tag_change("add", match, "senior researcher")
            case "Instructor":
                isolated_task_change("ren", match, "Current Rank: Senior Researcher", "Current Rank: Instructor")
                isolated_task_change("sta", match, "Instructor Training Program", "Complete")
                isolated_tag_change("rem", match, "senior researcher")
                isolated_tag_change("add", match, "instructor")
            case "Supervisor":
                isolated_task_change("ren", match, "Current Rank: Instructor", "Current Rank: Supervisor")
                isolated_tag_change("rem", match, "instructor")
                isolated_tag_change("add", match, "supervisor")
            case _:
                ot.error("Invalid status name recieved in promote function, no action taken.")
            


    except Exception as e:
        ot.error(f"An unexpected error occurred while executing promote command: {e}")     



# END OF BOT SHENANIGANS
if __name__ == "__main__":


    bot.run(TOKEN)