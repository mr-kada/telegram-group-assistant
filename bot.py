from telethon import TelegramClient, events, Button, types, functions, errors
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsAdmins
from telethon.tl.types import ChannelParticipantCreator
from telethon.tl.types import ChannelParticipantAdmin
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.types import ChannelParticipantsBanned
from telethon.tl.functions.messages import ExportChatInviteRequest
from telethon.tl.types import User, Channel
from telethon.tl.functions.messages import HideChatJoinRequestRequest
from telethon.tl.types import PeerChannel
from telethon.tl.types import PeerChat
from telethon.tl.types import InputMessagePinned

import json, asyncio, re, pytz, sqlite3, os, string, random, math, time
from datetime import datetime, timedelta
from collections import defaultdict


from myfatoorah_payApi import check_invoice_status_myfatoorah, create_invoice_myfatoorah


# pip install telethon
# pip install pytz
# apt install sqlite3


# Configure bot details
configs = json.load(open('config.json', encoding='utf-8'))


api_id = 1724716
api_hash = '00b2d8f59c12c1b9a4bc63b70b461b2f'
bot_token = configs["BOT_TOKEN"]


bot = TelegramClient('bot_session', api_id, api_hash).start(bot_token=bot_token)


# Configs
OWNER_ID = 691459768 # 7616544351


# Groups JSONs
groups_database = json.load(open('groups_database.json', encoding='utf-8'))
groups_manager = json.load(open('groups_manager.json', encoding='utf-8'))
bot_configs = json.load(open('bot_configs.json', encoding='utf-8'))


# CONNECT TO DATABASE
database = sqlite3.connect('database.db')
cursor = database.cursor()


# Create a lock to prevent simultaneous access
lock1 = asyncio.Lock()
lock2 = asyncio.Lock()
lock3 = asyncio.Lock()


# Define items per page
page_data = {}
PAGE_SIZE = 5
ITEMS_PER_PAGE = 2


# Store message timestamps and settings per group
group_message_times = defaultdict(lambda: defaultdict(list))
group_settings_antiflood = defaultdict(lambda: {'max_messages': 3, 'time_window': 5})


user_join_times = {}
LEAVE_TIME_THRESHOLD = 10  

group_join_settings = {}
group_join_times = {}

RUN_ONE_TIME = False


###########################################################################
async def DeleteEvent(event):
    try:
        await event.delete()
    except:pass


async def SaveJsonGroupsData(data):
    global groups_database

    async with lock1:
        with open('groups_database.json', mode='w', encoding='utf-8') as JsonFile:
            json.dump(data, JsonFile, ensure_ascii=False, indent=4)

        groups_database = data


async def SaveJsonGroupsManager(data):
    global groups_manager

    async with lock2:
        with open('groups_manager.json', mode='w', encoding='utf-8') as JsonFile:
            json.dump(data, JsonFile, ensure_ascii=False, indent=4)

        groups_manager = data


async def SaveJsonBotConfigs(data):
    global bot_configs

    async with lock3:
        with open('bot_configs.json', mode='w', encoding='utf-8') as JsonFile:
            json.dump(data, JsonFile, ensure_ascii=False, indent=4)

    bot_configs = data


async def set_bot_commands():
    try:
        commands = [
            types.BotCommand(command="start", description="Start the bot"),
            types.BotCommand(command="help", description="Show help"),
            types.BotCommand(command="settings", description="Group Settings"),
            types.BotCommand(command="developer", description="Bot Developer")
        ]

        await bot(functions.bots.SetBotCommandsRequest(
            commands=commands,
            scope=types.BotCommandScopeDefault(),
            lang_code='en'
        ))
    
    except:pass


async def GetGroupAdmins(event):
    group_ownerID, group_admins = None, []

    try:
        participants = await bot(GetParticipantsRequest(
            event.chat_id, ChannelParticipantsAdmins(), offset=0, limit=0, hash=0
        ))
                
        group_ownerID, group_admins = None, []
        for participant in participants.participants:
            if isinstance(participant, ChannelParticipantCreator):
                group_ownerID = participant.user_id
            elif isinstance(participant, ChannelParticipantAdmin):
                group_admins.append(participant.user_id)
    except Exception as error:print(f'Get Group Admins (ERROR) : {error}')
    
    return group_ownerID, group_admins


async def get_current_time_in_timezone(timezone: str):
    try:
        tz = pytz.timezone(timezone)
        current_time = datetime.now(tz)
    except pytz.UnknownTimeZoneError:
        current_time = datetime.now()  # Fallback to system time (without timezone)
    
    return current_time.strftime('%Y-%m-%d %H:%M:%S')


async def check_user_vip(event, user_id):
    is_vip = cursor.execute(f'SELECT is_vip FROM bot_users WHERE user_id = {user_id}').fetchone()
    is_vip = is_vip[0]

    if is_vip:
        vip_datetime = datetime.strptime(str(is_vip), '%Y-%m-%d %H:%M:%S')
        current_datetime = datetime.now()

        # Check if VIP is expired
        if current_datetime > vip_datetime:
            await event.respond('❕ __اشتراكك لقد انتهى, أنت الان في العضوية المجانية__')
            cursor.execute(f'UPDATE bot_users SET is_vip = NULL WHERE user_id = {user_id}')
            database.commit()

    is_vip = cursor.execute(f'SELECT is_vip FROM bot_users WHERE user_id = {user_id}').fetchone()
    is_vip = is_vip[0]

    if is_vip:return True
    else:return False


def get_group_settings(chat_id):
    if chat_id not in group_join_settings:
        group_join_settings[chat_id] = {"max_joins": 5, "time_window": 10}
    return group_join_settings[chat_id]


async def set_group_join_settings(chat_id, max_joins, time_window):
    group_join_settings[chat_id] = {"max_joins": max_joins, "time_window": time_window}


async def get_first_message(group_id, user_id):
    try:
        async for message in bot.iter_messages(group_id, from_user=user_id, reverse=True):
            if message:
                return message

        return None
    except Exception as error:
        return None

############################################################################

@bot.on(events.NewMessage(pattern='/start'))
async def BotStart(event, callback=False):

    await set_bot_commands()

    # if asks to open settings in private
    # if callback == False:
    #     check_args = str(event.message.message).split(' ')
    #     if len(check_args) >= 2 and check_args[1].startswith('OpenGroupSettings_'):
    #         target_group_id = check_args[1].replace('OpenGroupSettings_', '')

    #         group_ownerID, group_admins = await GetGroupAdmins(event)
    #         CoFounders, Admins = [], []

    #         if str(group_ownerID) in groups_database:
    #             if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
    #                 group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
    #                 CoFounders = group_data["co_founders"]
    #                 Admins = group_data["admins"]

    #         if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
    #             return

    #         # if str(event.sender_id) in groups_database:
    #             # if str(target_group_id) in groups_database[str(event.sender_id)]["groups"]:

    #         try:
    #             participant = await bot(GetParticipantRequest(int(target_group_id), 'me'))
    #             if isinstance(participant.participant, ChannelParticipantCreator):
    #                 return await ShowGroupSettings(event, group_ID=target_group_id)
    #             elif isinstance(participant.participant, ChannelParticipantAdmin):
    #                 return await ShowGroupSettings(event, group_ID=target_group_id)
    #             else:
    #                 return await event.respond("**لإدارة الإعدادات، يجب تعييني كمسؤول.**")    
    #         except Exception as error:
    #             return await event.respond("**لإدارة الإعدادات، يجب تعييني كمسؤول.**")    

    # else:
    #     await DeleteEvent(event)

    # if it's a group
    if event.is_group:
        if event.sender_id == None:
            return
        
        group_ownerID, group_admins = await GetGroupAdmins(event)

        if event.sender_id != group_ownerID:
            return

        WelcomeGroup_buttons = [
            [Button.url("📢 اشترك في قناتي", "https://t.me/iGroupHelp")]
        ]
        WelcomeGroup_MSG = f'''
شكراً لإضافتي إلى مجموعتك! 😊

لا تنسَ تعييني كمسؤول في المجموعة، وإلا فلن أتمكن من الرد على الأوامر.

ابدأ محادثة معي بشكل خاص حتى أتمكن من إرسال رسائل الخطأ هناك دون إزعاج هذه الدردشة! 🚀
'''
        
        await event.respond(WelcomeGroup_MSG, buttons=WelcomeGroup_buttons, link_preview=False)

        SettingGroup_buttons = [
            [
                Button.inline("🇸🇦 اللغات", b"languages"),
                Button.inline("⚙️ اعدادات", b"groupSettings")
            ]
        ]
        SettingGroup_MSG = f'''لإعدادي، استخدم أمر /settings أو اضغط على الزر أدناه.'''
        
        await event.respond(SettingGroup_MSG, buttons=SettingGroup_buttons, link_preview=False)

        # add group to database
        if str(event.sender_id) not in groups_database:
            groups_database[str(event.sender_id)] = {}
            groups_database[str(event.sender_id)]["groups"] = {}
            
        if str(event.chat_id) not in groups_database[str(event.sender_id)]["groups"]:
            group_url = ""
            try:
                group_DATA = await bot.get_entity(event.chat_id)
                if group_DATA.username:
                    group_url = f"https://t.me/{group_DATA.username}"
                else:
                    try:
                        invite = await bot(ExportChatInviteRequest(event.chat_id))
                        group_url = invite.link
                    except Exception as error:pass
            except Exception as error:pass
            
            groups_database[str(event.sender_id)]["groups"][str(event.chat_id)] = {
                "id": event.chat_id,
                "creator_id": group_ownerID,
                "co_founders": [],
                "admins": group_admins,
                "moderators": [],
                "cleaners": [],
                "muters": [],
                "helpers": [],
                "free_users": [],
                "rules": {
                    "text": None,
                    "media": None,
                    "buttons": []
                },
                "welcome_message": {
                    "is_active": False,
                    "mode": "every_join",
                    "delete_last_message": False,
                    "text": None,
                    "media": None,
                    "buttons": []
                },
                "goodbye_message": {
                    "is_active": False,
                    "send_in_private": False,
                    "delete_last_message": False,
                    "text": None,
                    "media": None,
                    "buttons": []
                },
                "captcha": {
                    "is_active": False,
                    "penalty": "Mute",
                    "mode": "Button",
                    "timer": 3,
                    "delete_service_message": False,
                    "mode_open": False,
                    "timer_open": False,
                    "penalty_open": False,
                    "editMessage_open": False,
                    "captcha_modes": {
                        "Button": {
                            "text": "{MENTION}، تحقق خلال {TIMER} دقيقة لتتمكن من الكتابة في المجموعة 👇🏻",
                            "button_text": "أزل كتم الصوت عني",
                            "description": "سيحتاج المستخدم إلى الضغط على زر بسيط ليتم إزالة كتم الصوت عنه.."
                        }
                    }
                },
                "adminTag": {
                    "send_to": "✖️ NoBody",
                    "tag_founder": True,
                    "tag_admins": False,
                    "admins_to_tag": []
                },
                "allowed_media": {
                    "duration": None,
                    "story": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "photo": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "video": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "album": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "gif": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "voice": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "audio": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "sticker": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "animatedStickers": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "animatedGames": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "animatedEmoji": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "premiumEmoji": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "files": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "games": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "contacts": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "polls": {
                        "penalty": "Off",
                        "delete_msg": False
                    },
                    "payments": {
                        "penalty": "Off",
                        "delete_msg": False
                    }
                },
                "warned_users": {},
                "warn_system": {
                    "is_active": False,
                    "max_warns": 3,
                    "punishment": "Mute",
                    "duration": None
                },
                "tag_alert": {
                    "is_active": False
                },
                "approval_mode": {
                    "is_active": False
                },
                "antispam": {
                    "penalty": "Warn",
                    "delete_msg": False,
                    "username_antispam": False,
                    "bots_antispam": False,
                    "forwarding_penalty": "Off",
                    "forwarding_delete_msg": False,
                    "forwarding_channels": True,
                    "forwarding_groups": True,
                    "forwarding_users": True,
                    "forwarding_bots": True,
                    "quate_penalty": "Off",
                    "quate_delete_msg": False,
                    "quate_channels": True,
                    "quate_groups": True,
                    "quate_users": True,
                    "quate_bots": True,
                    "total_links_penalty": "Off",
                    "total_links_delete_msg": False
                },
                "antiflood": {
                    "penalty": "Off",
                    "delete_msg": False,
                    "messages_target": 2,
                    "interval_time": 5
                },
                "alphabets": {
                    "penalty": "Off",
                    "delete_msg": False,
                    "watchArabic": False,
                    "watchCyrillic": False,
                    "watchChinese": False,
                    "watchLatin": False
                },
                "checks": {
                    "check_at_the_join": False,
                    "delete_msg": False,
                    "obligation_surname": "Off",
                    "obligation_username": "Off",
                    "obligation_profile_picture": "Off",
                    "obligation_channel_obligation": "Off",
                    "obligation_obligation_to_add": "Off",
                    "block_arabic_name": "Off",
                    "block_chinese_name": "Off",
                    "block_russian_name": "Off",
                    "block_spam_name": "Off"
                },
                "blocks": {
                    "blacklist": {
                        "penalty": "Ban"
                    },
                    "bot_block": {
                        "is_active": False,
                        "penalty": "Off"
                    },
                    "join_block": {
                        "penalty": "Off",
                        "delete_join_msg": False
                    },
                    "leave_block": {
                        "penalty": "Off"
                    },
                    "joinLeave_block": {
                        "penalty": "Off",
                        "delete_service_msg": False,
                        "delete_welcome_msg": False
                    },
                    "multiplejoins_block": {
                        "penalty": "Off",
                        "users_count": 5,
                        "time": 3
                    }
                },
                "porn": {
                    "penalty": "Off",
                    "delete_msg": False
                },
                "night_mode": {
                    "is_active": False,
                    "delete_medias": True,
                    "global_silence": False,
                    "send_advices": True,
                    "timeSlot_start": 23,
                    "timeSlot_end": 7,
                    "timezone": None
                },
                "link": {
                    "is_active": False,
                    "url": group_url # Make it url of this group
                },
                "banned_words": {
                    "penalty": "Off",
                    "delete_msg": True,
                    "banned_words_list": []
                },
                "masked_users": {
                    "is_active": False,
                    "delete_msg": False
                },
                "discussion_group": {
                    "is_active": False,
                    "delete_msg": False,
                    "remove_from_pin": False,
                    "from_pin_active": False,
                    "first_comment": False,
                    "text": None,
                    "media": None,
                    "buttons": []
                },
                "message_length": {
                    "penalty": "Off",
                    "delete_msg": False,
                    "min_length": None,
                    "max_length": None,
                    "min_length_open": False,
                    "max_length_open": False
                },
                "group_satistics": {
                    "users": {}
                }
            }

            await SaveJsonGroupsData(groups_database)

        return

    # register user in database
    # CHECK IF USER ALREADY IN DATABASE
    user_data = cursor.execute(f'SELECT * FROM bot_users WHERE user_id = {event.chat_id}').fetchone()

    if user_data == None:
        refferal_from_id = None

        # NEW USER
        cursor.execute(
            """
            INSERT INTO bot_users 
            (user_id, balance, is_vip, refferal_from, added_date, banned, firstname, lastname)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.chat_id, 0.0, None, refferal_from_id,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'), None, None, None
            )
        )
        database.commit()

    # LOGIN - NOTIFY OWNER
    if bot_configs["is_notify_login_enabled"]:
        try:
            user_entity = await bot.get_entity(event.chat_id)
            await bot.send_message(OWNER_ID, f'''
__🚨 تم دخول شخص جديد للبوت الخاص بك :
                        
الاسم: {user_entity.first_name}
المعرف: @{user_entity.username}
ID: `{user_entity.id}`
__''')
        except Exception as error:pass


    user_profile = await bot.get_entity(event.chat_id)
    bot_data = await bot.get_me()

    WelcomeBot_buttons = [
        [
            Button.url("➕ أضفني في مجموعتك ➕", f"https://t.me/{bot_data.username}?startgroup=true"), # change_info+delete_messages+ban_users+invite_users+pin_messages+manage_call
        ],
        [
            # Button.url("👥 Group", "https://t.me/iGroupHelp/9"),
            # Button.url("Channel 📢", "https://t.me/iGroupHelp/9"),
        ],
        [
            # Button.inline("🔧 Support", b"support"),
            # Button.inline("Information 💬", b"information"),
        ],
        [
            Button.inline('👤 ملفي الشخصي', 'show_profile'),
            Button.inline('🔧 تواصل مع الدعم', 'contact_support')
        ],
        [
            Button.inline('⭐ العضوية المدفوعة', 'buy_vip') # VIP Subscription
        ],
        [
            Button.inline("🇸🇦 اللغات 🇸🇦", b"languages")
        ]
    ]

    if event.chat_id == OWNER_ID or event.chat_id == 978571497:
        WelcomeBot_buttons.append([Button.inline('🛠️ لوحة المشرف', 'adminPanel')])
    

    WelcomeBot_MSG = f'''
👋🏻 مرحبًا {user_profile.first_name}!
بوت **حماية المجموعات** هو الأداة الأكثر اكتمالًا لمساعدتك في إدارة مجموعاتك بسهولة وأمان!

👉🏻 أضفني إلى مجموعة سوبر وقم بترقيتي كمسؤول لأتمكن من العمل!

❓ **ما هي الأوامر؟**
اضغط على /help لعرض جميع الأوامر وطريقة استخدامها!
اضغط على /settings لعرض جميع مجموعاته التي يحميها البوت!
'''
    await event.respond(WelcomeBot_MSG, link_preview=False, buttons=WelcomeBot_buttons)


# User Cancel Action
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"UserCancelAction")))
async def UserCancelAction(event):

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await BotStart(event, callback=True)

    except Exception as error:pass


# CONTACT SUPPORT
@bot.on(events.CallbackQuery(data='contact_support'))
async def ContactSupport(event):

    maintenance_mode = bot_configs.get('is_bot_in_maintenance_mode')
    if event.chat_id != OWNER_ID and event.chat_id not in bot_configs.get('admins') and maintenance_mode:
        await event.respond('__البوت معطل حاليا, سنعود قريبا 😊__')
        return
    
    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [[Button.inline('❌ الغاء التذكرة', 'UserCancelAction')]]
            await conv.send_message('📧 __أرسل رسالة التي تريد ارسالها للدعم:__', buttons=buttons)
            the_message = await conv.get_response()

        reply_buttons = [[Button.inline('✍🏻 ارسال رد', f'ownerReply_{event.chat_id}')]]
        try:
            await bot.forward_messages(entity=OWNER_ID, messages=the_message)
            await bot.send_message(entity=OWNER_ID, message='✍🏻 للرد على هذه الرسالة اضغط هنا:', buttons=reply_buttons)
        except:pass
        await event.respond('❕ __تم ارسال الرسالة, سوف تتلقى رد في أقرب وقت__')
    
    except Exception as error:print(error)
    await BotStart(event, callback=True)


# REPLY ON MESSAGE
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'ownerReply_')))
async def OwnerReply(event):

    user_id = int(str(event.data.decode()).replace('ownerReply_', '').strip())
    try:
        async with bot.conversation(event.chat_id, timeout=120) as conv:
            buttons = [[Button.inline('❌ الغاء التذكرة', 'UserCancelAction')]]
            await conv.send_message('📧 __أرسل رسالة التي تريد ارسالها:__', buttons=buttons)
            the_message = await conv.get_response()

        try:
            await bot.send_message(entity=user_id, message=the_message)
        except:pass

        buttons = [[Button.inline('🔙 رجوع للقائمة الرئيسية', 'UserCancelAction')]]
        await event.respond('✅ __تم ارسال الرسالة, بنجاح__', buttons=buttons)
    
    except:pass



# SHOW PROFILE
@bot.on(events.CallbackQuery(data='show_profile'))
async def ShowProfile(event):

    maintenance_mode = bot_configs.get('is_bot_in_maintenance_mode')
    if event.chat_id != OWNER_ID and event.chat_id not in bot_configs.get('admins') and maintenance_mode:
        await event.respond('__البوت معطل حاليا, سنعود قريبا 😊__')
        return
    
    await DeleteEvent(event)

    user_data = cursor.execute(f"SELECT * FROM bot_users WHERE user_id = {event.chat_id}")
    user_data = cursor.fetchone()

    if user_data[5] == 'YES':
        await event.respond('__تم حظرك من استخدام خدمات هذا البوت__')
        return

    balance, joined_date = user_data[1], user_data[4]

    if not user_data[2]:
        subscription_active = 'مجانية'
        subscription_date = 'غير مشترك'
        subscription_expires = 'غير مشترك'
    else:
        subscription_active = 'مدفوعة'
        subscription_date = user_data[2]

        expire_time = datetime.strptime(str(user_data[2]), "%Y-%m-%d %H:%M:%S")
        current_time = datetime.now()

        time_remaining = expire_time - current_time
        days = time_remaining.days

        hours, remainder = divmod(time_remaining.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        subscription_expires = f'{days} يوم، {hours} ساعة، {minutes} دقيقة'

    groups_added_count = 0
    if str(event.chat_id) in groups_database:
        groups_added_count = len(groups_database[str(event.chat_id)]["groups"])

    buttons = [
        [Button.inline('🔙 رجوع للقائمة الرئيسية', 'UserCancelAction')]
    ]

    await event.respond(f'''__
✨ **تفاصيل حسابك**

🆔 آيدي: `{event.chat_id}`
💰 رصيدك: {round(float(balance), 2)}$

⭐ العضوية: {subscription_active}
📆 تاريخ انتهاء العضوية: {subscription_date}
⏳ المدة المتبقية لانتهاء العضوية: {subscription_expires}

📅 تاريخ انضمامك للبوت: {joined_date}
📢 عدد المجموعات المضافة : {groups_added_count}
__''', buttons=buttons)



#############################
# ADMIN PANEL
@bot.on(events.CallbackQuery(data='adminPanel'))
async def BotAdminPanel(event):

    await DeleteEvent(event)
    notify_login_text = "إشعار الدخول ✅" if bot_configs["is_notify_login_enabled"] else "إشعار الدخول ❌"
    
    buttons = [
        [Button.inline(notify_login_text, b'toggle_notify_login')],
        [Button.inline('💳 خطط الاشتراكات', 'vip_show'), Button.inline('🎁 عروض و خصومات', 'discounts_show')],
        # [Button.inline('📌 الاشتراك الاجباري', 'first_join'), Button.inline('📉 عمليات التحميل', 'daily_limits_show')],
        # [Button.inline('🛠️ انشاء أزرار للاشهار', 'ad_buttons')],
        [Button.inline('📢 اذاعة لجميع المستخدمين', 'broadcast')],
        [Button.inline('📢 اذاعة لجميع مجموعات الحماية 📣', 'groups_broadcast')],
        [Button.inline('💰 اضافة/حذف رصيد', 'editUser_price'), Button.inline('🔎 بحث عن عميل', 'getUser_byID')],
        # [Button.inline('🎁 تعديل جائزة رابط الدعوة', 'editLink_price')],
        # [Button.inline("⚙️ إعدادات البوت", b'settings_section')],
        [Button.inline("👤 قسم الأدمنية", b'SectionAdmin')],
        [Button.inline('📊 احصائيات متقدمة', 'all_statistics')],
        # [Button.inline('🏷 أكثر الخدمات طلبا', 'most_services_needed')],
        # [Button.inline('🕵️‍♂️ اخر عمليات التحميل', 'last_download'), Button.inline('🏆 أكثر من قام بالتحميل', 'most_download')],
        [Button.inline('🔙 رجوع للقائمة الرئيسية', 'backToAdminMenu')]
    ]

    await event.respond(f'''__
👋 مرحبًا بك في لوحة المشرف!
                        
🎯 اختر الأمر الذي ترغب في تنفيذه من القائمة أدناه.
__''', buttons=buttons)
    

# back To Admin Menu
@bot.on(events.CallbackQuery(data=b"backToAdminMenu"))
async def backToAdminMenu(event):

    await DeleteEvent(event), await BotStart(event, callback=True)


# back To Help Menu
@bot.on(events.CallbackQuery(data=b"backToHelpMenu"))
async def backToHelpMenu(event):

    await DeleteEvent(event), await HelpCommand(event)


# back To Pro Guides Menu
@bot.on(events.CallbackQuery(data=b"backToProGuidesMenu"))
async def backToProGuidesMenu(event):

    await DeleteEvent(event), await ProGuides(event)



# back To Users Roles Menu
@bot.on(events.CallbackQuery(data=b"backToUsersRolesMenu"))
async def backToUsersRolesMenu(event):

    await DeleteEvent(event), await UsersRoles(event)


# BACK TO OFFER
@bot.on(events.CallbackQuery(data='back_to_offer'))
async def BackToOffer(event):
    await DeleteEvent(event), await discounts_show(event)



# BACK TO STATISTICS
@bot.on(events.CallbackQuery(data='back_to_statistics'))
async def BackToStatistics(event):
    await DeleteEvent(event), await AllStatistics(event)


# BACK TO Admin Section
@bot.on(events.CallbackQuery(data='back_to_admin_section'))
async def BackToAdminSection(event):
    await DeleteEvent(event), await AdminSection(event)



# Enabled/Disabled Notify Login
@bot.on(events.CallbackQuery(data='toggle_notify_login'))
async def ToggleNotifyLogin(event):
    global bot_configs

    # Toggle the notification setting
    is_enabled = not bot_configs.get("is_notify_login_enabled", False)
    bot_configs["is_notify_login_enabled"] = is_enabled

    # Save updated configuration
    await SaveJsonBotConfigs(bot_configs)

    # Send a response message to the user
    status_message = "تم تفعيل إشعار الدخول!" if is_enabled else "تم تعطيل إشعار الدخول!"
    await event.answer(status_message), await BotAdminPanel(event)


#####################################


# Groups BROADCAST
@bot.on(events.CallbackQuery(data='groups_broadcast')) 
async def GroupsBroadCast(event):

    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return

    # if event.chat_id == OWNER_ID or event.chat_id == 978571497 or event.chat_id in admins_list:
    await event.answer('🥽 جاري تجهيز الاذاعة')

    async with bot.conversation(event.chat_id) as conv:
        await conv.send_message('__أرسل الرسالة :__')
        the_message = await conv.get_response()
        
    notice_admin = await event.reply(f"__جاري الارسال...__")

    # users = cursor.execute(f"SELECT * FROM bot_users")
    # users = cursor.fetchall()

    group_ids = []
    for user_data in groups_database.values():
        group_ids.extend(user_data.get("groups", {}).keys())

    success, fails = 0, 0
    for group_id in group_ids:
        try:
            if int(group_id) != OWNER_ID:
                send_to__user = await bot.send_message(entity=int(group_id), message=the_message)
                success += 1
            else:
                success += 1
        except:
            # cursor.execute(f"UPDATE bot_users SET banned = 'YES' WHERE user_id = {int(group_id)}")
            fails += 1
    
    # bot_users = cursor.execute("SELECT * FROM bot_users WHERE banned = 'YES'")
    # bot_users = cursor.fetchall()

    notice_admin = await event.reply(f"""__
📊 تمت الإذاعة بنجاح تام 

✅ تم الإرسال إلى: {success}
❌ فشل في الإرسال: {fails}
📈 نسبة نجاح الاذاعة : {round((success / len(group_ids)) * 100, 2)}%
__""")



#####################################


# BROADCAST
@bot.on(events.CallbackQuery(data='broadcast')) 
async def BroadCast(event):

    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return

    # if event.chat_id == OWNER_ID or event.chat_id == 978571497 or event.chat_id in admins_list:
    await event.answer('🥽 جاري تجهيز الاذاعة')

    async with bot.conversation(event.chat_id) as conv:
        await conv.send_message('__أرسل الرسالة :__')
        the_message = await conv.get_response()
        
    notice_admin = await event.reply(f"__جاري الارسال...__")
    users = cursor.execute(f"SELECT * FROM bot_users")
    users = cursor.fetchall()
    success, fails = 0, 0
    for user in users:
        try:
            if int(user[0]) != OWNER_ID:
                send_to__user = await bot.send_message(entity=int(user[0]), message=the_message)
                success += 1
            else:
                success += 1
        except:
            cursor.execute(f"UPDATE bot_users SET banned = 'YES' WHERE user_id = {int(user[0])}")
            fails += 1
    
    bot_users = cursor.execute("SELECT * FROM bot_users WHERE banned = 'YES'")
    bot_users = cursor.fetchall()

    notice_admin = await event.reply(f"""__
📊 تمت الإذاعة بنجاح تام 

👥 المستخدمون المستهدفون الذين شاهدوا الرساله: غير معروف
✅ تم الإرسال إلى: {success}
🚫 الاعضاء المحظورين: {len(bot_users)}
❌ فشل في الإرسال لهم بسبب الحظر : {fails}
📈 نسبة نجاح الاذاعة : {round((success / len(users)) * 100, 2)}%
__""")



#####################################

# Edit User Price
@bot.on(events.CallbackQuery(data='editUser_price')) 
async def EditUserPrice(event):

    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return

    await DeleteEvent(event)
    if event.chat_id == OWNER_ID or event.chat_id == 978571497:
        try:
            async with bot.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message('__أرسل ايدي الشخص الذي تريد اضافة/حذف الرصيد له:__')
                user_id = (await conv.get_response()).message
                
                await conv.send_message('__أرسل الرصيد بالدولار ( لحذف رصيد أرسل الرقم بالسالب ):__')
                price_in_dollar = (await conv.get_response()).message
                
            try:
                user_data = cursor.execute(f"SELECT * FROM bot_users WHERE user_id = {user_id}")
                user_data = cursor.fetchone()
                if user_data != None:
                    new_balance = round((float(user_data[1]) + float(price_in_dollar)), 2)
                    cursor.execute(f"UPDATE bot_users SET balance = {new_balance} WHERE user_id = {user_id}")

                    try:
                        notice_user = await bot.send_message(entity=int(user_id), message=f'__تم ارسال لك رصيد من مشرف البوت : **{price_in_dollar}$**__')
                    except:pass

                    buttons = [[Button.inline('🔙 رجوع', 'adminPanel')]]
                    notice_admin = await event.reply("__تم التنفيذ بنجاح__", buttons=buttons)
                    database.commit()

            except Exception as error:
                notice_user = await event.reply(str(error))

        except Exception as error:print(error)


#####################################

# Admin Section
@bot.on(events.CallbackQuery(data='SectionAdmin')) 
async def AdminSection(event):

    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return

    await DeleteEvent(event)
    buttons = [
        [Button.inline('➕ اضافة مشرف', 'add_admin'), Button.inline('➖ حذف مشرف', 'delete_admin')],
        [Button.inline('🔙 رجوع', 'adminPanel')]
    ]

    await event.respond(f'''__
✨ يمكنك اضافة أو حذف المشرفين من هنا بكل سهولة!

عدد المشرفين : {len(admins_list)}
__''', buttons=buttons)


# Add Admin
@bot.on(events.CallbackQuery(data='add_admin'))
async def AddAdmin(event):

    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return
    
    await DeleteEvent(event)
    try:
        async with bot.conversation(event.chat_id, timeout=120) as conv:
            await conv.send_message('__أرسل رابط أو معرف أو ايدي الشخص:__')
            admin_info = (await conv.get_response()).message

        try:
            if str(admin_info).isdigit():
                user_entity = await bot.get_entity(int(admin_info))
            else:
                user_entity = await bot.get_entity(str(admin_info))
            admin_id = user_entity.id
        except:user_entity, admin_id = None, None

        # ADD ADMIN
        if user_entity == None:
            await event.respond('__المعرف خاطئ أو الشخص لم يقم بارسال /start في بوت__')
        else:
            bot_configs['admins'].append(admin_id)
            await SaveJsonBotConfigs(bot_configs)

    except:pass
    await AdminSection(event)


# Delete Admin
@bot.on(events.CallbackQuery(data='delete_admin'))
async def DeleteAdmin(event):

    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return
    
    await DeleteEvent(event)

    buttons = []
    for admin_id in admins_list:
        try:
            user_entity = await bot.get_entity(admin_id)
            name = user_entity.first_name
            username = f'( @{user_entity.username} )' if user_entity.username != None else ''
        except:
            name, username = admin_id, ''

        buttons.append([Button.inline(f'❌ {name} {username}', f'deleteAdminID_{admin_id}')])

    buttons.append([Button.inline('🔙 رجوع', 'back_to_admin_section')])
    await event.respond('__اضغط على زر المشرف لحذفه من مشرفين البوت:__', buttons=buttons)


# Delete Admin ID
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'deleteAdminID_')))
async def DeleteAdminID(event):
    
    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return
    
    admin_id = int(str(event.data.decode()).replace('deleteAdminID_', '').strip())

    # DELETE ADMIN
    bot_configs['admins'].remove(admin_id)
    await SaveJsonBotConfigs(bot_configs)
    
    await DeleteAdmin(event)



#####################################
# GET USRES BY OFFSET
def get_users(offset, limit):
    cursor.execute("SELECT * FROM bot_users LIMIT ? OFFSET ?", (limit, offset))
    return cursor.fetchall()


# STATISTICS
@bot.on(events.CallbackQuery(data='all_statistics')) 
async def AllStatistics(event):
    
    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return

    await DeleteEvent(event)

    user_data = cursor.execute(f"SELECT * FROM bot_users")
    user_data = cursor.fetchall()

    user_data_banned = cursor.execute(f"SELECT * FROM bot_users WHERE banned = 'YES'")
    user_data_banned = cursor.fetchall()

    user_data_not_banned = cursor.execute(f"SELECT * FROM bot_users WHERE banned IS NULL")
    user_data_not_banned = cursor.fetchall()


    today = datetime.now()
    today_formatted = today.strftime("%Y-%m-%d")

    cursor.execute("SELECT * FROM bot_users WHERE DATE(added_date) = ?", (today_formatted,))
    date_users_today = cursor.fetchall()

    # cursor.execute("SELECT * FROM bot_users WHERE DATE(last_download_date) = ?", (today_formatted,))
    # date_users_today_search_today = cursor.fetchall()

    cursor.execute("SELECT * FROM subscription_history WHERE DATE(paid_subscription_at) = ?", (today_formatted,))
    paid_subscription_today = cursor.fetchall()


    today_users_subscription = 0
    for sub in paid_subscription_today:
        today_users_subscription += float(sub[7])

    # today_msg = len(date_users_today_search_today)
    # for msg in date_users_today_search_today:
    #     today_msg += int(msg[5])


    yesterday = today - timedelta(days=1)
    yesterday_formatted = yesterday.strftime("%Y-%m-%d")
    
    cursor.execute("SELECT * FROM bot_users WHERE DATE(added_date) = ?", (yesterday_formatted,))
    date_users_yesterday = cursor.fetchall()

    # cursor.execute("SELECT * FROM bot_users WHERE DATE(last_download_date) = ?", (yesterday_formatted,))
    # date_users_today_search_yesterday = cursor.fetchall()

    cursor.execute("SELECT * FROM subscription_history WHERE DATE(paid_subscription_at) = ?", (yesterday_formatted,))
    paid_subscription_yesterday = cursor.fetchall()

    yesterday_users_subscription = 0
    for sub in paid_subscription_yesterday:
        yesterday_users_subscription += float(sub[7])

    # yesterday_msg = len(date_users_today_search_yesterday)
    # for msg in date_users_today_search_yesterday:
    #     yesterday_msg += int(msg[5])


    # Get current month
    current_month = today.strftime("%Y-%m")

    # Get users who joined in the current month
    # cursor.execute("SELECT * FROM bot_users WHERE DATE_FORMAT(added_date, '%Y-%m') = ?", (current_month,))
    cursor.execute("SELECT * FROM bot_users WHERE strftime('%Y-%m', added_date) = ?", (current_month,))
    date_users_current_month = cursor.fetchall()

    # Get previous month
    previous_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    # Get users who joined in the previous month
    # cursor.execute("SELECT * FROM bot_users WHERE DATE_FORMAT(added_date, '%Y-%m') = ?", (previous_month,))
    cursor.execute("SELECT * FROM bot_users WHERE strftime('%Y-%m', added_date) = ?", (previous_month,))
    date_users_previous_month = cursor.fetchall()
 

    if event.chat_id not in page_data:
        page_data[event.chat_id] = 0

    users = get_users(page_data[event.chat_id], PAGE_SIZE)

    cursor.execute("SELECT COUNT(*) FROM bot_users")
    total_users = cursor.fetchone()[0]
    total_pages = math.ceil(total_users / PAGE_SIZE)
    current_page = (page_data[event.chat_id] // PAGE_SIZE) + 1


    buttons = [[Button.inline('🔎 بحث عن مستخدم', 'getUser_byID')]]

    for user in users:
        try:
            get_user_data = await bot.get_entity(int(user[0]))
            if get_user_data.username == None:
                username = ''
            else:
                username = f'( @{get_user_data.username} )'

            if user[6] == None:
                first_name = get_user_data.first_name
                last_name = get_user_data.last_name

                cursor.execute(
                    "UPDATE bot_users SET firstname = ?, lastname = ? WHERE user_id = ?",
                    (first_name, last_name, int(user[0]))
                )
                database.commit()

                if last_name == None:
                    firstlast_name = f'{first_name}'
                else:
                    firstlast_name = f'{first_name} {last_name}'

            else:
                if user[7] == None:
                    firstlast_name = f'{user[6]}'
                else:
                    firstlast_name = f'{user[6]} {user[7]}'

            buttons.append([Button.inline(f'{firstlast_name} {username}', f'getUserInfoID_{user[0]}')])
        except Exception as error:print (error)

    buttons.append([Button.inline("الصفحة السابقة »", data='previous_users'), Button.inline("« الصفحة التالية", data='next_users')])

    buttons.append([Button.inline('🔙 رجوع', 'adminPanel')])

    channels_list = cursor.execute('SELECT * FROM join_channels')
    channels_list = cursor.fetchall()

    # - 👥 المستخدمون الفعّالين: {len(date_users_today_search_today)}
    # - ✉️ الرسائل: {today_msg}

    # - 👥 المستخدمون الفعّالين: {len(date_users_today_search_yesterday)}
    # - ✉️ الرسائل: {yesterday_msg}

    total_users = len(groups_database)
    total_groups = sum(len(user_data.get("groups", {})) for user_data in groups_database.values())


    await event.respond(f'''
📊 مرحبًا بك في قسم الإحصائيات 📊

المستخدمون:
- 👥 العدد الإجمالي للمستخدمين: {len(user_data)}
- 👤 عدد المستخدمين في الخاص: {len(user_data_not_banned)}
- 👥 عدد القنوات والمجموعات: {len(channels_list)}
- 🚫 عدد المحظورين: {len(user_data_banned)}

📅 الفعّالين:
اليوم ({today_formatted}):
- 👥 المستخدمون الجدد: {len(date_users_today)}
- 💰 ربحية الاشتراكات: {today_users_subscription}$

الأمس ({yesterday_formatted}):
- 👥 المستخدمون الجدد: {len(date_users_yesterday)}
- 💰 ربحية الاشتراكات: {yesterday_users_subscription}$

👥 عدد الأشخاص الذين أضافوا مجموعات: {total_users}
🛡️ إجمالي المجموعات المضافة للحماية: {total_groups}


📅 المستخدمون الجدد:
- عدد المستخدمين الجدد خلال الشهر الحالي: {len(date_users_current_month)}
- عدد المستخدمين الجدد خلال الشهر الماضي: {len(date_users_previous_month)}


الصفحة: {current_page}/{total_pages}
''', buttons=buttons)



# Previous Users
@bot.on(events.CallbackQuery(data='previous_users')) 
async def PreviousUsers(event):
    user_id = event.chat_id

    # Initialize user's page if not set
    if user_id not in page_data:
        page_data[user_id] = 0

    # Adjust offset based on button
    if page_data[user_id] > 0:
        page_data[user_id] -= PAGE_SIZE

    await AllStatistics(event)



# Next Users
@bot.on(events.CallbackQuery(data='next_users')) 
async def NextUsers(event):
    user_id = event.chat_id

    # Initialize user's page if not set
    if user_id not in page_data:
        page_data[user_id] = 0

    # Adjust offset based on button
    page_data[user_id] += PAGE_SIZE

    # Fetch the users
    offset = page_data[user_id]
    users = get_users(offset, PAGE_SIZE)

    if not users:
        # If no more users, reset the page
        page_data[user_id] -= PAGE_SIZE
        await event.answer("لا يوجد المزيد")
        return
    
    await AllStatistics(event)



# Get User by ID
@bot.on(events.CallbackQuery(data='getUser_byID')) 
async def GetUserbyID(event):
    
    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return

    await DeleteEvent(event)
    if event.chat_id == OWNER_ID or event.chat_id == 978571497 or event.chat_id in admins_list:
        try:
            async with bot.conversation(event.chat_id, timeout=120) as conv:
                await conv.send_message('__أرسل ايدي الشخص لعرض معلوماته:__')
                user_id = (await conv.get_response()).message
            
            if str(user_id).isdigit():
                await GetUserByID_(event, passed_user_id=user_id)
            else:
                await event.reply('__ايدي يجب أن يكون رقما!__')

        except:pass


# GET USER BY ID
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'getUserInfoID_')))
async def GetUserByID_(event, passed_user_id=None):

    await DeleteEvent(event)
    if passed_user_id == None:
        user_id = int(str(event.data.decode()).split('_')[1])
    else:
        user_id = passed_user_id

    try:
        # bot_settings_data = cursor.execute('SELECT * FROM bot_settings WHERE setting_id = 1')
        # bot_settings_data = cursor.fetchone()

        user_data = cursor.execute(f"SELECT * FROM bot_users WHERE user_id = {int(user_id)}")
        user_data = cursor.fetchone()

        # search_history_data = cursor.execute(f"SELECT * FROM download_history WHERE download_by = {int(user_id)}")
        # search_history_data = cursor.fetchall()
        
        balance, added_date = user_data[1], user_data[4]
        banned = user_data[5]
        # last_search_date = user_data[7]

        if user_data[7] == None:
            firstlast_name = f'{user_data[6]}'
        else:
            firstlast_name = f'{user_data[6]} {user_data[7]}'

        if user_data[3] == None:
            refferal_from = 'لا أحد'
        else:
            refferal_from = f'[اضغط لزيارة المستخدم](tg://user?id={user_data[3]})'
        
        if not user_data[2]:
            # limit = f'{user_data[5]}/{bot_settings_data[1]}'
            subscription_active = 'مجانية'
            subscription_date = 'غير مشترك'
            subscription_expires = 'غير مشترك'
        else:
            # limit = f'غير محدود'
            subscription_active = 'مدفوعة'
            subscription_date = user_data[2]

            expire_time = datetime.strptime(str(user_data[2]), "%Y-%m-%d %H:%M:%S")
            current_time = datetime.now()

            time_remaining = expire_time - current_time
            days = time_remaining.days

            hours, remainder = divmod(time_remaining.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            subscription_expires = f'{days} يوم، {hours} ساعة، {minutes} دقيقة'

        if banned == None:
            banned_text = '🚫 حظر'
        else:
            banned_text = '🔓 فك حظر'
        
        try:
            get_user_data = await bot.get_entity(int(user_id))
            if get_user_data.username == None:
                url = f'tg://user?id={get_user_data.id}'
            else:
                url = f'https://t.me/{get_user_data.username}'
        except:url = f'tg://user?id={int(user_id)}'

        buttons = [
            [Button.url('💬 فتح محادثة', url), Button.inline('✏️ تعديل', f'OwnerEdit_{user_id}')],
            [
                # Button.inline('🔎 سجل التحميل', f'getSearchHistory_{user_id}'),
                Button.inline('💳 سجل اشتراكات', f'getSubscription_{user_id}')
            ],
            [Button.inline(banned_text, f'CheckBan_{user_id}'), Button.inline('🗑️ حذف', f'DeleteUser_{user_id}')],
            [Button.inline('🔄 تحديث', f'reffresh_{user_id}')],
            [Button.inline('🔙 رجوع', 'back_to_statistics')]
        ]

        total_groups = 0
        if str(event.chat_id) in groups_database:
            total_groups = len(groups_database[str(event.chat_id)]["groups"])

        notice_user = await event.reply(f'''__
✨ **تفاصيل العميل**

🆔 رقم المستخدم: {user_id}
👨🏻‍💻 اسم الكامل : {firstlast_name}
💰 الرصيد: {balance}$

📅 تاريخ الانضمام: {added_date}
🔗 الإحالة من: {refferal_from}

🏷️ نوع العضوية: {subscription_active}
📆 تاريخ انتهاء العضوية: {subscription_date}
⏳ المدة المتبقية لانتهاء العضوية: {subscription_expires}

🛡️ إجمالي المجموعات المضافة للحماية: {total_groups}
__''', buttons=buttons)

#         🔍 محاولات التحميل اليومية المتبقية: {limit}
#         ⏱️ تاريخ آخر تحميل: {last_search_date}
#         🔍 اجمالي عدد عمليات التحميل: {len(search_history_data)}

    except Exception as error:
        notice_user = await event.reply(str(error))



# Delete User
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'DeleteUser_')))
async def GetUserByID_DeleteUser(event):

    await DeleteEvent(event)
    user_id = int(str(event.data.decode()).split('_')[1])
    buttons = [
        [Button.inline('🗑️ تأكيد و حذف المستخدم', f'ConfirmDeleteUser_{user_id}')],
        [Button.inline('🔙 رجوع', f'getUserInfoID_{user_id}')]
    ]

    await event.respond(f'''__
هل أنت متأكد من حذف هذا المستخدم, سيتم حذف جميع معلوماته بالكامل
__''', buttons=buttons)



# Confirm Delete User
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'ConfirmDeleteUser_')))
async def GetUserByID_ConfirmDeleteUser(event):

    await DeleteEvent(event)
    user_id = int(str(event.data.decode()).split('_')[1])

    cursor.execute(f'DELETE FROM bot_users WHERE user_id = {int(user_id)}')
    database.commit()

    buttons = [
        [Button.inline('🔙 رجوع', 'adminPanel')]
    ]

    await event.respond('__تم حذف المستخدم و كامل معلوماته في البوت__', buttons=buttons)


# Reffresh
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'reffresh_')))
async def GetUserByID_reffresh(event):

    user_id = int(str(event.data.decode()).split('_')[1])
    await GetUserByID_(event, passed_user_id=user_id)



# Check Ban/Unban
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'CheckBan_')))
async def GetUserByID_CheckBan(event):

    user_id = int(str(event.data.decode()).split('_')[1])
    cursor.execute("SELECT banned FROM bot_users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()

    if result is None:
        await event.answer('المستخدم غير موجود')
        return

    current_status = result[0]
    if current_status is not None:
        cursor.execute("UPDATE bot_users SET banned = NULL WHERE user_id = ?", (user_id,))
        await event.answer('تم فك حظر المستخدم')
    else:
        cursor.execute("UPDATE bot_users SET banned = 'YES' WHERE user_id = ?", (user_id,))
        await event.answer('تم حظر المستخدم')
    
    database.commit()
    await GetUserByID_(event, passed_user_id=user_id)


# Get Subscription
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'getSubscription_')))
async def GetSubscription(event):
    
    user_id = int(str(event.data.decode()).replace('getSubscription_', '').strip())
    subscription_history = cursor.execute(f'SELECT * FROM subscription_history WHERE user_id = {user_id}')
    subscription_history = cursor.fetchall()

    if len(subscription_history) == 0:
        header_info = f'''# تقرير شامل على اشتراكات العميل

ايدي العميل : {user_id}
اجمالي عدد الاشتراكات : {len(subscription_history)}

--------------------------------------------
لا يوجد اشتراكات
--------------------------------------------
'''
    else:
        header_info = f'''# تقرير شامل على اشتراكات العميل

ايدي العميل : {user_id}
اجمالي عدد الاشتراكات : {len(subscription_history)}


--------------------------------------------
'''
        
        for item in subscription_history:
            header_info += f'''رقم الفاتورة : {item[2]}
رابط الفاتورة : {item[3]}

تم دفع الفاتورة بتاريخ : {item[4]}
تاريخ انتهاء الاشتراك : {item[5]}

عدد أشهر الاشتراك : {item[6]}
سعر الاشتراك : {item[7]}$
--------------------------------------------'''


    filepath = ''.join(random.choices(string.ascii_letters + string.digits, k=8)) + '.txt'
    with open(filepath, "w", encoding='utf-8 ') as file:
        file.write(header_info)

    last_3 = '**💳📜 سجل الاشتراكات (📥 حمل الملف لتصفح السجل بالكامل) 📄**\n\n'
    for idx, item in enumerate(subscription_history):
        if idx == 3:
            break

        last_3 += f'''__🧾 **رقم الفاتورة**: {item[2]}
🔗 **رابط الفاتورة**: {item[3]}
📅 **تم دفع الفاتورة بتاريخ**: {item[4]}
⏳ **تاريخ انتهاء الاشتراك**: {item[5]}
📆 **عدد أشهر الاشتراك**: {item[6]}
💰 **سعر الاشتراك**: {item[7]}$__

'''

    await bot.send_message(event.chat_id, file=filepath, message=last_3)

    try:
        os.remove(filepath)
    except:pass



# Get Search History
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'getSearchHistory_')))
async def GetSearchHistory(event):
    
    # await DeleteEvent(event)
    user_id = int(str(event.data.decode()).replace('getSearchHistory_', '').strip())
    search_history = cursor.execute(f'SELECT * FROM download_history WHERE download_by = {user_id}')
    search_history = cursor.fetchall()

    if len(search_history) == 0:
        header_info = f'''# تقرير شامل على عمليات التحميل

ايدي العميل : {user_id}
اجمالي عمليات التحميل : {len(search_history)}

--------------------------------------------
لا يوجد عمليات تحميل
--------------------------------------------
'''
    else:
        header_info = f'''# تقرير شامل على عمليات التحميل

ايدي العميل : {user_id}
اجمالي عمليات التحميل : {len(search_history)}

--------------------------------------------
'''
        
        for item in search_history:
            header_info += f'''
رابط التحميل : {item[3]}
نوع التحميل : {item[2]}
تاريخ التحميل : {item[4]}
--------------------------------------------'''


    filepath = ''.join(random.choices(string.ascii_letters + string.digits, k=8)) + '.txt'
    with open(filepath, "w", encoding='utf-8 ') as file:
        file.write(header_info)

    last_3 = '**🔍📜 سجل التحميل (📥 حمل الملف لتصفح السجل بالكامل) 📄**\n\n'
    for idx, item in enumerate(search_history):
        if idx == 3:
            break

        last_3 += f'''__🔎 **رابط التحميل**: {item[3]}
📂 **نوع التحميل**: {item[2]}
📅 **تاريخ التحميل**: {item[4]}__

'''

    await bot.send_message(event.chat_id, file=filepath, message=last_3)

    try:
        os.remove(filepath)
    except:pass


# Owner Edit User
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'OwnerEdit_')))
async def GetUserByID_OwnerEdit(event, passed_user_id=None, extra_msg=''):

    await DeleteEvent(event)
    if passed_user_id == None:
        user_id = int(str(event.data.decode()).split('_')[1])
    else:
        user_id = passed_user_id

    buttons = [
        [Button.inline('✏️ الاسم الأول', f'OwnerEditName1_{user_id}'), Button.inline('✏️ الاسم الأخير', f'OwnerEditName2_{user_id}')],
        [Button.inline('🔙 رجوع', f'getUserInfoID_{user_id}')]
    ]

    await event.respond(f'''__
يمكنك تعديل اسم الأول و الأخير للمستخدم:

{extra_msg}
__''', buttons=buttons)



# EDIT NAME 1
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'OwnerEditName1_')))
async def GetUserByID_OwnerEditName1(event):

    await DeleteEvent(event)
    user_id = int(str(event.data.decode()).split('_')[1])

    try:
        async with bot.conversation(event.chat_id, timeout=120) as conv:
            await conv.send_message('__أرسل الاسم الأول لتحديثه:__')
            first_name = (await conv.get_response()).message

        cursor.execute("UPDATE bot_users SET firstname = ? WHERE user_id = ?", (first_name, user_id,))
        database.commit()

        await GetUserByID_OwnerEdit(event, passed_user_id=user_id, extra_msg='__✅ تم تعديل الاسم الأول للمستخدم بنجاح__')
    
    except:await GetUserByID_(event, passed_user_id=user_id)


# EDIT NAME 2
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'OwnerEditName2_')))
async def GetUserByID_OwnerEditName2(event):

    await DeleteEvent(event)
    user_id = int(str(event.data.decode()).split('_')[1])

    try:
        async with bot.conversation(event.chat_id, timeout=120) as conv:
            await conv.send_message('__أرسل الاسم الأخير لتحديثه:__')
            first_name = (await conv.get_response()).message

        cursor.execute("UPDATE bot_users SET lastname = ? WHERE user_id = ?", (first_name, user_id,))
        database.commit()

        await GetUserByID_OwnerEdit(event, passed_user_id=user_id, extra_msg='__✅ تم تعديل الاسم الأخير للمستخدم بنجاح__')
    
    except:await GetUserByID_(event, passed_user_id=user_id)



#####################################

# Discounts Show
@bot.on(events.CallbackQuery(data='discounts_show')) 
async def discounts_show(event):

    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return

    await DeleteEvent(event)

    limited_offer = cursor.execute('SELECT * FROM limited_offer')
    limited_offer = cursor.fetchall()

    limited_offer_active = cursor.execute("SELECT * FROM limited_offer WHERE status = 'active'")
    limited_offer_active = cursor.fetchall()

    limited_offer_users = 0
    for offer in limited_offer:
        limited_offer_users += int(offer[8])


    last_offer = ''
    if len(limited_offer_active) != 0:
        offer_data = limited_offer_active[-1]

        target_date = datetime.strptime(str(offer_data[6]), "%Y-%m-%d %H:%M:%S")
        current_time = datetime.now()

        # Calculate the time difference
        time_difference = target_date - current_time

        if time_difference.total_seconds() > 0:
            remaining_days = time_difference.days
            remaining_seconds = time_difference.seconds
            remaining_hours = remaining_seconds // 3600
            remaining_minutes = (remaining_seconds % 3600) // 60
            remains = f'{remaining_days} يوم, {remaining_hours} ساعة, {remaining_minutes} ثانية'
        else:
            remains = 'العرض انتهى'
            cursor.execute(f"UPDATE limited_offer SET status = 'unactive' WHERE id = {offer_data[0]}")
            database.commit()

        last_offer = f'''🏷️ اسم العرض: {offer_data[1]}
🔢 كود العرض: {offer_data[2]}
💸 قيمة الخصم: {offer_data[3]}%

⏳ المدة: {offer_data[4]} يوم
📅 ينتهي بعد: {remains}'''
    
    else:
        last_offer = 'لا يوجد أي عروض'


    limited_offer_unactive = cursor.execute("SELECT * FROM limited_offer WHERE status = 'unactive'")
    limited_offer_unactive = cursor.fetchall()


    buttons = [
        [Button.inline('📊 إحصائيات العروض', 'offers_statistics')],
        [
            Button.inline(f'✅ الخطط النشيطة ({len(limited_offer_active)})', 'activeOffers'), 
            Button.inline(f'❌ الخطط غير النشيطة ({len(limited_offer_unactive)})', 'unactiveOffers')
        ],
        [Button.inline('➕ اضافة عرض', 'add_limited_offer')],
        [Button.inline('🔙 رجوع', 'adminPanel')]
    ]

    await event.respond(f'''__
🔧 **إدارة العروض و الخصومات**  

📊 **إحصائيات عامة**  
📋 إجمالي العروض: {len(limited_offer)}
✅ العروض النشيطة: {len(limited_offer_active)}
❌ العروض المنتهية : {len(limited_offer_unactive)}
👥 إجمالي الاستخدامات: {limited_offer_users}


🔥 **احدث العروض النشيطة**
--------------------------------
{last_offer}
--------------------------------
__''', buttons=buttons)




@bot.on(events.CallbackQuery(data='offers_statistics'))
async def offers_statistics(event):
    # Start with the first page
    await show_offers_page(event, current_page=0)



@bot.on(events.CallbackQuery(data=re.compile(r'OffersUsagePage_(\d+)')))
async def paginate_offers(event):
    # Extract the current page from callback data
    current_page = int(event.data_match.group(1))
    await show_offers_page(event, current_page)



async def show_offers_page(event, current_page):

    # Calculate offset for pagination
    offset = current_page * ITEMS_PER_PAGE

    # Fetch offers from the database
    cursor.execute(
        "SELECT * FROM limited_offer LIMIT ? OFFSET ?", (ITEMS_PER_PAGE, offset)
    )
    limited_offers = cursor.fetchall()

    if len(limited_offers) == 0:
        await event.answer('لا توجد عروض لعرضها', alert=True)
        return


    await DeleteEvent(event)

    # Create the message with offers
    offer_msg = '**📊 إحصائيات العروض**\n\n'
    for offer in limited_offers:
        offer_name, usage_count = offer[1], offer[8]
        offer_msg += f'''__🏷️ اسم العرض: {offer_name}
👥 عدد المستخدمين : {usage_count}__

'''

    # Fetch total number of offers for pagination controls
    cursor.execute("SELECT COUNT(*) FROM limited_offer")
    total_offers = cursor.fetchone()[0]

    # Calculate total pages
    total_pages = (total_offers + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    offer_msg += f'\n📄 الصفحة: {current_page + 1}/{total_pages}'

    # Ensure "back" and "next" buttons are always visible
    buttons = [
        [
            Button.inline('السابق »', f'OffersUsagePage_{max(0, current_page - 1)}'),
            Button.inline('« التالي', f'OffersUsagePage_{min(total_pages - 1, current_page + 1)}'),
        ],
        [Button.inline('🔙 Back', 'back_to_offer')]
    ]

    # Add buttons to the message
    await event.respond(offer_msg, buttons=buttons)



# Show all VIP subscriptions with Pagination
@bot.on(events.CallbackQuery(data='activeOffers'))
async def activeOffers(event):

    cursor.execute("SELECT * FROM limited_offer WHERE status = 'active'")
    limited_offers = cursor.fetchall()

    # Get the first subscription based on the id or show the first if none selected
    if len(limited_offers) == 0:
        await event.answer('لا توجد عروض لعرضها', alert=True)
    else:
        first_sub = limited_offers[0]
        item = first_sub
        await display_limited_offers(event, item[0], is_status=True, status_type='active')



# Show all VIP subscriptions with Pagination
@bot.on(events.CallbackQuery(data='unactiveOffers'))
async def unactiveOffers(event):

    cursor.execute("SELECT * FROM limited_offer WHERE status = 'unactive'")
    limited_offers = cursor.fetchall()

    # Get the first subscription based on the id or show the first if none selected
    if len(limited_offers) == 0:
        await event.answer('لا توجد عروض لعرضها', alert=True)
    else:
        first_sub = limited_offers[0]
        item = first_sub
        await display_limited_offers(event, item[0], is_status=True, status_type='unactive')



# Function to display a specific VIP subscription
async def display_limited_offers(event, sub_id, is_status=False, status_type=''):

    await DeleteEvent(event)
    cursor = database.cursor()

    # Query to get the specific subscription by id
    if is_status == False:
        cursor.execute('SELECT * FROM limited_offer WHERE id = ?', (sub_id,))
        item = cursor.fetchone()
    else:
        cursor.execute('SELECT * FROM limited_offer WHERE id = ? AND status = ?', (sub_id, status_type,))
        item = cursor.fetchone()

    if item:
        if item[7] == 'active':
            status = 'نشيطة ✅'
        else:
            status = 'غير نشيطة ❌'
        
        target_date = datetime.strptime(str(item[6]), "%Y-%m-%d %H:%M:%S")
        current_time = datetime.now()

        # Calculate the time difference
        time_difference = target_date - current_time
        if time_difference.total_seconds() > 0:
            remaining_days = time_difference.days
            remaining_seconds = time_difference.seconds
            remaining_hours = remaining_seconds // 3600
            remaining_minutes = (remaining_seconds % 3600) // 60
            remains = f'{remaining_days} يوم, {remaining_hours} ساعة, {remaining_minutes} ثانية'
        else:
            remains = 'العرض انتهى'
            cursor.execute(f"UPDATE limited_offer SET status = 'unactive' WHERE id = {item[0]}")
            database.commit()

        if item[7] == 'unactive':
            remains = 'العرض انتهى'


        item_display = f'''🏷️ اسم العرض: {item[1]}
🔢 كود العرض: {item[2]}
💸 قيمة الخصم: {item[3]}%

⏳ المدة: {item[4]} يوم
📅 ينتهي بعد: {remains}

👥 عدد المستخدمين : {item[8]}
'''
        

        # Prepare the buttons for Next and Previous navigation
        buttons = [
            # [Button.inline('🛠 تعديل السعر', f'VipEditPrice_{item[0]}'), Button.inline('📅 تعديل الشهور', f'VipEditMonth_{item[0]}')]
        ]

        if item[7] == 'active':
            buttons.append([Button.inline('❌ انهاء العرض', f'StopOffer_{item[0]}')])
        else:
            buttons.append([Button.inline('❌ العرض منتهي', '')])

        nextback_buttons = []

        # Get Previous Item (if exists)
        if is_status == False:
            cursor.execute('SELECT id FROM limited_offer WHERE id < ? ORDER BY id DESC LIMIT 1', (item[0],))
            prev_item = cursor.fetchone()

            if prev_item:
                nextback_buttons.append(Button.inline('السابق »', data=f'prevOffer_{prev_item[0]}'))
            else:
                nextback_buttons.append(Button.inline('السابق »', data=f'prevOffer_none'))

        else:
            cursor.execute('SELECT id FROM limited_offer WHERE status = ? AND id < ? ORDER BY id DESC LIMIT 1', (status_type, item[0]))
            prev_item = cursor.fetchone()

            if prev_item:
                nextback_buttons.append(Button.inline('السابق »', data=f'prevOffer{status_type}_{prev_item[0]}'))
            else:
                nextback_buttons.append(Button.inline('السابق »', data=f'prevOffer{status_type}_none'))

        # Get Next Item (if exists)
        if is_status == False:
            cursor.execute('SELECT id FROM limited_offer WHERE id > ? ORDER BY id ASC LIMIT 1', (item[0],))
            next_item = cursor.fetchone()

            if next_item:
                nextback_buttons.append(Button.inline('« التالي', data=f'nextOffer_{next_item[0]}'))
            else:
                nextback_buttons.append(Button.inline('« التالي', data=f'nextOffer_none'))
        else:
            cursor.execute('SELECT id FROM limited_offer WHERE status = ? AND id > ? ORDER BY id ASC LIMIT 1', (status_type, item[0]))
            next_item = cursor.fetchone()

            if next_item:
                nextback_buttons.append(Button.inline('« التالي', data=f'nextOffer{status_type}_{next_item[0]}'))
            else:
                nextback_buttons.append(Button.inline('« التالي', data=f'nextOffer{status_type}_none'))


        buttons.append(nextback_buttons)

        # Back to main menu button
        buttons.append([Button.inline('🔙 رجوع', data='back_to_offer')])

        # Send the current item with navigation buttons
        await event.respond(f"__📋 العرض\n\n{item_display}\n\n🔽 اختر ما تريد:__", buttons=buttons)
    else:
        await event.respond("العرض غير موجود")



# Stop Offer
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'StopOffer_')))
async def StopOffer(event):

    try:
        sub_id = int(event.data.decode().split('_')[1])
        cursor.execute(f"UPDATE limited_offer SET status = 'unactive' WHERE id = {sub_id}")
        database.commit()
        await display_limited_offers(event, sub_id)
    except:await event.answer('لا يوجد هذا العرض', alert=True)



# Handle "Next" button press to show the next subscription
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'nextOffer_')))
async def next_item_offer(event):

    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_limited_offers(event, sub_id)
    except:await event.answer('لا مزيد من العروض', alert=True)



# Handle "Previous" button press to show the previous subscription
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'prevOffer_')))
async def prev_item_offer(event):

    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_limited_offers(event, sub_id)
    except:await event.answer('لا مزيد من العروض', alert=True)



@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'nextOfferactive_')))
async def next_item2_offer(event):
    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_limited_offers(event, sub_id, is_status=True, status_type='active')
    except Exception as e:
        await event.answer('لا مزيد من العروض', alert=True)



@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'prevOfferactive_')))
async def prev_item2_offer(event):
    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_limited_offers(event, sub_id, is_status=True, status_type='active')
    except Exception as e:
        await event.answer('لا مزيد من العروض', alert=True)


@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'nextOfferunactive_')))
async def next_item3_offer(event):
    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_limited_offers(event, sub_id, is_status=True, status_type='unactive')
    except Exception as e:
        await event.answer('لا مزيد من العروض', alert=True)


@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'prevOfferunactive_')))
async def prev_item3_offer(event):
    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_limited_offers(event, sub_id, is_status=True, status_type='unactive')
    except Exception as e:
        await event.answer('لا مزيد من العروض', alert=True)


# Add Limited Offer
@bot.on(events.CallbackQuery(data='add_limited_offer'))
async def add_limited_offer(event):

    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return

    await DeleteEvent(event)
    try:
        async with bot.conversation(event.chat_id, timeout=120) as conv:
            await conv.send_message('__أرسل اسم العرض:__')
            offer_name = (await conv.get_response()).message

            await conv.send_message('__أرسل كود العرض:__')
            offer_code = (await conv.get_response()).message

            await conv.send_message('__أرسل قيمة العرض:__')
            offer_reduce = (await conv.get_response()).message

            await conv.send_message('__أرسل مدة العرض بالأيام:__')
            offer_days = (await conv.get_response()).message

        if str(offer_days).isdigit():
            try:
                reduce = float(offer_reduce)
            except:
                await event.respond('__قيمة العرض يجب أن يكون رقما!__')
                return
            
            current_datetime = datetime.now()
            future_datetime = current_datetime + timedelta(days=int(offer_days))
            future_datetime = future_datetime.replace(microsecond=0)
            
            # ADD OFFER
            insert_query = """
                INSERT INTO limited_offer (
                    offer_name, offer_code, reduce, valid_days, created_at, end_at, status, usage_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """

            values = (
                offer_name,
                offer_code,
                reduce,
                int(offer_days),
                current_datetime.replace(microsecond=0),
                future_datetime,
                'active',
                0,
            )
            
            cursor.execute(insert_query, values)
            database.commit()

        else:
            await event.respond('__الأيام يجب أن يكون رقما!__')

    except:pass
    await discounts_show(event)



#####################################
# VIP show
@bot.on(events.CallbackQuery(data='vip_show')) 
async def VIP_SHOW(event):

    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return

    vip_subscription = cursor.execute('SELECT * FROM vip_subscription')
    vip_subscription = cursor.fetchall()

    vip_subscription_active = cursor.execute("SELECT * FROM vip_subscription WHERE status = 'active'")
    vip_subscription_active = cursor.fetchall()

    vip_subscription_unactive = cursor.execute("SELECT * FROM vip_subscription WHERE status = 'unactive'")
    vip_subscription_unactive = cursor.fetchall()

    vip_bot_users = cursor.execute("SELECT * FROM bot_users WHERE is_vip IS NOT NULL")
    vip_bot_users = cursor.fetchall()

    await DeleteEvent(event)

    buttons = [
        [Button.inline('📋 عرض جميع الخطط', 'show_all_vip_sub')],
        [Button.inline(f'✅ الخطط النشيطة ({len(vip_subscription_active)})', 'activeVIP'), Button.inline(f'❌ الخطط غير النشيطة ({len(vip_subscription_unactive)})', 'unactiveVIP')],
        [Button.inline('➕ اضافة خطة جديدة', 'add_vip_sub')],
        [Button.inline('🔙 رجوع', 'adminPanel')]
    ]


    await event.respond(f'''__
🔧 **إدارة خطط الاشتراك**  

📊 **إحصائيات عامة**  
📋 إجمالي الخطط: {len(vip_subscription)}
✅ الخطط النشطة: {len(vip_subscription_active)}
❌ الخطط غير النشطة: {len(vip_subscription_unactive)}
👥 إجمالي المشتركين النشطين: {len(vip_bot_users)}


🔽 **اختر ما تريد عرضه:**
__''', buttons=buttons)


# Show all VIP subscriptions with Pagination
@bot.on(events.CallbackQuery(data='activeVIP'))
async def activeVIP(event):

    cursor.execute("SELECT * FROM vip_subscription WHERE status = 'active'")
    vip_subscription = cursor.fetchall()

    # Get the first subscription based on the id or show the first if none selected
    if len(vip_subscription) == 0:
        await event.answer('لا توجد خطط لعرضها', alert=True)
    else:
        first_sub = vip_subscription[0]
        item = first_sub
        await display_vip_subscription(event, item[0], is_status=True, status_type='active')


# Show all VIP subscriptions with Pagination
@bot.on(events.CallbackQuery(data='unactiveVIP'))
async def unactiveVIP(event):

    cursor.execute("SELECT * FROM vip_subscription WHERE status = 'unactive'")
    vip_subscription = cursor.fetchall()

    # Get the first subscription based on the id or show the first if none selected
    if len(vip_subscription) == 0:
        await event.answer('لا توجد خطط لعرضها', alert=True)
    else:
        first_sub = vip_subscription[0]
        item = first_sub
        await display_vip_subscription(event, item[0], is_status=True, status_type='unactive')


# Show all VIP subscriptions with Pagination
@bot.on(events.CallbackQuery(data='show_all_vip_sub'))
async def show_all_vip_sub(event):

    cursor.execute('SELECT * FROM vip_subscription')
    vip_subscription = cursor.fetchall()

    # Get the first subscription based on the id or show the first if none selected
    if len(vip_subscription) == 0:
        await event.answer('لا توجد خطط لعرضها', alert=True)
    else:
        first_sub = vip_subscription[0]
        item = first_sub
        await display_vip_subscription(event, item[0])


# Function to display a specific VIP subscription
async def display_vip_subscription(event, sub_id, is_status=False, status_type=''):

    await DeleteEvent(event)
    cursor = database.cursor()

    # Query to get the specific subscription by id
    if is_status == False:
        cursor.execute('SELECT * FROM vip_subscription WHERE id = ?', (sub_id,))
        item = cursor.fetchone()
    else:
        cursor.execute('SELECT * FROM vip_subscription WHERE id = ? AND status = ?', (sub_id, status_type,))
        item = cursor.fetchone()

    if item:
        if item[3] == 'active':
            status = 'نشيطة ✅'
        else:
            status = 'غير نشيطة ❌'

        item_display = f"""
📅 حالة الخطة : {status}
💰 سعر الاشتراك: {item[1]}$
⏳ المدة الاشتراك بالشهر: {item[2]}
"""

        # Prepare the buttons for Next and Previous navigation
        buttons = [[
            Button.inline('🛠 تعديل السعر', f'VipEditPrice_{item[0]}'), 
            Button.inline('📅 تعديل الشهور', f'VipEditMonth_{item[0]}')
        ]]

        if item[3] == 'active':
            buttons.append([Button.inline('❌ ايقاف تنشيط الخطة', f'VipActive_{item[0]}')])
        else:
            buttons.append([Button.inline('✅ اعادة تنشيط الخطة', f'VipUnActive_{item[0]}')])

        nextback_buttons = []

        # Get Previous Item (if exists)
        if is_status == False:
            cursor.execute('SELECT id FROM vip_subscription WHERE id < ? ORDER BY id DESC LIMIT 1', (item[0],))
            prev_item = cursor.fetchone()

            if prev_item:
                nextback_buttons.append(Button.inline('السابق »', data=f'prevSub_{prev_item[0]}'))
            else:
                nextback_buttons.append(Button.inline('السابق »', data=f'prevSub_none'))

        else:
            cursor.execute('SELECT id FROM vip_subscription WHERE status = ? AND id < ? ORDER BY id DESC LIMIT 1', (status_type, item[0]))
            prev_item = cursor.fetchone()

            if prev_item:
                nextback_buttons.append(Button.inline('السابق »', data=f'prevSub{status_type}_{prev_item[0]}'))
            else:
                nextback_buttons.append(Button.inline('السابق »', data=f'prevSub{status_type}_none'))

        # Get Next Item (if exists)
        if is_status == False:
            cursor.execute('SELECT id FROM vip_subscription WHERE id > ? ORDER BY id ASC LIMIT 1', (item[0],))
            next_item = cursor.fetchone()

            if next_item:
                nextback_buttons.append(Button.inline('« التالي', data=f'nextSub_{next_item[0]}'))
            else:
                nextback_buttons.append(Button.inline('« التالي', data=f'nextSub_none'))
        else:
            cursor.execute('SELECT id FROM vip_subscription WHERE status = ? AND id > ? ORDER BY id ASC LIMIT 1', (status_type, item[0]))
            next_item = cursor.fetchone()

            if next_item:
                nextback_buttons.append(Button.inline('« التالي', data=f'nextSub{status_type}_{next_item[0]}'))
            else:
                nextback_buttons.append(Button.inline('« التالي', data=f'nextSub{status_type}_none'))


        buttons.append(nextback_buttons)

        # Back to main menu button
        buttons.append([Button.inline('🔙 رجوع', data='back_to_sub')])

        # Send the current item with navigation buttons
        await event.respond(f"__📋 الخطة\n{item_display}\n\n🔽 اختر ما تريد:__", buttons=buttons)
    else:
        await event.respond("لا توجد خطة اشتراك بهذا الرقم.")


# BACK TO SUB
@bot.on(events.CallbackQuery(data='back_to_sub'))
async def BackToSub(event):
    await DeleteEvent(event), await VIP_SHOW(event)


# Handle "Next" button press to show the next subscription
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'nextSub_')))
async def next_item(event):

    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_vip_subscription(event, sub_id)
    except:await event.answer('لا مزيد من الخطط', alert=True)


# Handle "Previous" button press to show the previous subscription
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'prevSub_')))
async def prev_item(event):

    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_vip_subscription(event, sub_id)
    except:await event.answer('لا مزيد من الخطط', alert=True)


@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'nextSubactive_')))
async def next_item2(event):
    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_vip_subscription(event, sub_id, is_status=True, status_type='active')
    except Exception as e:
        await event.answer('لا مزيد من الخطط', alert=True)


@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'prevSubactive_')))
async def prev_item2(event):
    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_vip_subscription(event, sub_id, is_status=True, status_type='active')
    except Exception as e:
        await event.answer('لا مزيد من الخطط', alert=True)


@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'nextSubunactive_')))
async def next_item3(event):
    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_vip_subscription(event, sub_id, is_status=True, status_type='unactive')
    except Exception as e:
        await event.answer('لا مزيد من الخطط', alert=True)


@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'prevSubunactive_')))
async def prev_item3(event):
    try:
        sub_id = int(event.data.decode().split('_')[1])
        await display_vip_subscription(event, sub_id, is_status=True, status_type='unactive')
    except Exception as e:
        await event.answer('لا مزيد من الخطط', alert=True)


# VipActive_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'VipActive_')))
async def VipActive_(event):

    try:
        sub_id = int(event.data.decode().split('_')[1])
        cursor.execute(f"UPDATE vip_subscription SET status = 'unactive' WHERE id = {sub_id}")
        database.commit()
        await display_vip_subscription(event, sub_id)
    except:await event.answer('لا توجد هذه الخطة', alert=True)


# VipUnActive_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'VipUnActive_')))
async def VipUnActive_(event):

    try:
        sub_id = int(event.data.decode().split('_')[1])
        cursor.execute(f"UPDATE vip_subscription SET status = 'active' WHERE id = {sub_id}")
        database.commit()
        await display_vip_subscription(event, sub_id)
    except:await event.answer('لا توجد هذه الخطة', alert=True)


# Add Vip Sub
@bot.on(events.CallbackQuery(data='add_vip_sub'))
async def add_vip_sub(event):

    admins_list = bot_configs.get('admins')
    if event.chat_id not in admins_list and event.chat_id != OWNER_ID:
        return

    await DeleteEvent(event)
    try:
        async with bot.conversation(event.chat_id, timeout=120) as conv:
            await conv.send_message('__أرسل عدد أشهر الخطة:__')
            months = (await conv.get_response()).message

            await conv.send_message('__أرسل السعر الخطة:__')
            price = (await conv.get_response()).message

        if str(months).isdigit():
            try:
                price = float(price)
            except:
                await event.respond('__السعر يجب أن يكون رقما!__')
                return
            
            # ADD VIP SUB
            insert_sql = f"INSERT INTO vip_subscription (price, months, status) VALUES ({float(price)}, {int(months)}, 'active');"
            cursor.execute(insert_sql)
            database.commit()

        else:
            await event.respond('الأشهر يجب أن يكون رقما!__')

    except:pass
    await VIP_SHOW(event)


# Vip Edit Price
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'VipEditPrice_')))
async def VipEditPrice(event):

    await DeleteEvent(event)
    sub_id = int(event.data.decode().split('_')[1])
    try:
        async with bot.conversation(event.chat_id, timeout=120) as conv:
            await conv.send_message('__أرسل السعر الجديد:__')
            new_price = (await conv.get_response()).message

        try:
            new_price = float(new_price)
            cursor.execute(f"UPDATE vip_subscription SET price = {new_price} WHERE id = {sub_id}")
            database.commit()

            await display_vip_subscription(event, sub_id)
        except:
            await event.respond('__السعر يجب أن يكون رقما!__')

    except:pass


# Vip Edit Month
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'VipEditMonth_')))
async def VipEditMonth(event):

    await DeleteEvent(event)
    sub_id = int(event.data.decode().split('_')[1])
    try:
        async with bot.conversation(event.chat_id, timeout=120) as conv:
            await conv.send_message('__أرسل المدة الجديد بالشهور:__')
            new_month = (await conv.get_response()).message

        if str(new_month).isdigit():
            cursor.execute(f"UPDATE vip_subscription SET months = {new_month} WHERE id = {sub_id}")
            database.commit()

            await display_vip_subscription(event, sub_id)
        else:
            await event.respond('الشهور يجب أن يكون رقما!__')

    except:pass


# BUY VIP
@bot.on(events.CallbackQuery(data='buy_vip'))
async def BuyVIP(event):
    
    maintenance_mode = bot_configs.get('is_bot_in_maintenance_mode')
    if event.chat_id != OWNER_ID and event.chat_id not in bot_configs.get('admins') and maintenance_mode:
        await event.respond('__البوت معطل حاليا, سنعود قريبا 😊__')
        return
            
    await DeleteEvent(event)

    user_data = cursor.execute(f'SELECT * FROM bot_users WHERE user_id = {event.chat_id}')
    user_data = cursor.fetchone()

    if user_data[5] == 'YES':
        await event.respond('__تم حظرك من استخدام خدمات هذا البوت__')
        return

    vip_subscription = cursor.execute("SELECT * FROM vip_subscription WHERE status = 'active'")
    vip_subscription  = cursor.fetchall()

    buttons = []

    for sub in vip_subscription:
        buttons.append([Button.inline(f'اشتراك مدفوع لـ {sub[2]} أشهر ({sub[1]}$)', f'PreCreateInvoice_{sub[2]}_{sub[1]}')])

    buttons.append([Button.inline('🔙 رجوع للقائمة الرئيسية', 'backToAdminMenu')])

    await event.respond(f'''__
✨ اشترك في العضوية المدفوعة للحصول على جميع مميزات البوت خلال مدة اشتراكك
__''', buttons=buttons)



# PRE-BUY VIP
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'PreCreateInvoice_')))
async def PreCreateInvoice(event):

    await DeleteEvent(event)
    months, price_in_dollar = str(event.data.decode()).replace('PreCreateInvoice_', '').split('_')

    user_data = cursor.execute(f"SELECT * FROM bot_users WHERE user_id = {event.chat_id}")
    user_data = cursor.fetchone()

    buttons = [
        [Button.inline(f'🎁 استخدم خصم', f'Discount_{months}_{price_in_dollar}')],
        [Button.inline(f'💳 دفع بواسطة رصيدي', f'PayInstant_{months}_{price_in_dollar}')],
        [Button.inline(f'🧾 دفع بواسطة فاتورة', f'CreateInvoice_{months}_{price_in_dollar}')],
        [Button.inline('🔙 رجوع للقائمة الرئيسية', 'backToAdminMenu')]
    ]

    gen_msg = await event.reply(f'''__
💳 اختر طريقة الدفع، يمكنك الدفع بواسطة رصيدك في البوت أو عن طريق فاتورة:  

💵 **رصيدك الحالي**: {user_data[1]}$  
💰 **سعر الاشتراك**: {price_in_dollar}$  
📆 **مدة الاشتراك بالشهر**: {months}
__''', buttons=buttons)



# DISCOUNT
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'Discount_')))
async def RedeemDiscount(event):

    await DeleteEvent(event)
    months, price_in_dollar = str(event.data.decode()).replace('Discount_', '').split('_')

    update_msg, coupon_used = '', False
    try:
        async with bot.conversation(event.chat_id, timeout=120) as conv:
            await conv.send_message('__أرسل كود الخصم:__')
            code = (await conv.get_response()).message

        offer_data = cursor.execute(f"SELECT * FROM limited_offer WHERE offer_code = '{code}'")
        offer_data = cursor.fetchone()

        if offer_data == None:
            update_msg = '‼ كود الخصم الذي أرسلته غير موجود!'
        else:
            if offer_data[7] == 'unactive':
                update_msg = '‼ كود الخصم الذي أرسلت لم يعد صالحا'
            else:
                target_date = datetime.strptime(str(offer_data[6]), "%Y-%m-%d %H:%M:%S")
                current_time = datetime.now()

                # Calculate the time difference
                time_difference = target_date - current_time
                if time_difference.total_seconds() > 0:
                    price_in_dollar = float(price_in_dollar) * (1 - float(offer_data[3]) / 100)
                    update_msg = f'✅ تم تطبيق الخصم بنجاح, الخصم {offer_data[3]}%'
                    coupon_used = True

                    cursor.execute(f"UPDATE limited_offer SET usage_count = {int(offer_data[8]) + 1} WHERE id = {offer_data[0]}")
                    database.commit()
                else:
                    update_msg = '‼ كود الخصم الذي أرسلت لم يعد صالحا'
                    cursor.execute(f"UPDATE limited_offer SET status = 'unactive' WHERE id = {offer_data[0]}")
                    database.commit()

    except Exception as error:pass

    user_data = cursor.execute(f"SELECT * FROM bot_users WHERE user_id = {event.chat_id}")
    user_data = cursor.fetchone()

    buttons = []

    if coupon_used == False:
        buttons.append([Button.inline(f'🎁 استخدم خصم', f'Discount_{months}_{price_in_dollar}')])
    
    buttons.append([Button.inline(f'💳 دفع بواسطة رصيدي', f'PayInstant_{months}_{price_in_dollar}')])
    buttons.append([Button.inline(f'🧾 دفع بواسطة فاتورة', f'CreateInvoice_{months}_{price_in_dollar}')])
    buttons.append([Button.inline('🔙 رجوع للقائمة الرئيسية', 'backToAdminMenu')])


    gen_msg = await event.reply(f'''__
💳 اختر طريقة الدفع، يمكنك الدفع بواسطة رصيدك في البوت أو عن طريق فاتورة:  

💵 **رصيدك الحالي**: {user_data[1]}$  
💰 **سعر الاشتراك**: {price_in_dollar}$  
📆 **مدة الاشتراك بالشهر**: {months}

{update_msg}
__''', buttons=buttons)




@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'PayInstant_')))
async def CreateInvoice(event):

    await DeleteEvent(event)
    gen_msg = await event.reply('__جاري التحقق...__')

    months, price_in_dollar = str(event.data.decode()).replace('PayInstant_', '').split('_')

    user_data = cursor.execute(f"SELECT * FROM bot_users WHERE user_id = {event.chat_id}")
    user_data = cursor.fetchone()

    user_balance = float(user_data[1])
    if user_balance >= float(price_in_dollar):
        # take user balance
        new_balance = user_balance - float(price_in_dollar)

        is_vip = user_data[2]
        if is_vip is None:
            new_vip_time = datetime.now() + timedelta(days=int(months) * 30)
        else:
            current_vip_time = datetime.strptime(str(is_vip), "%Y-%m-%d %H:%M:%S")
            new_vip_time = current_vip_time + timedelta(days=int(months) * 30)

        # Format the datetime back to string / # Update the database
        new_vip_time_str = new_vip_time.strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE bot_users SET is_vip = ?, balance = ? WHERE user_id = ?",
            (new_vip_time_str, new_balance, event.chat_id,)
        )
        database.commit()

        notice_user = await event.reply(
            message=f'''__
🎉 شكرًا لك على دفعتك!

لقد تم دفع فاتورتك بنجاح، تم ترقية حسابك. نقدر سرعة استجابتك!
__''', buttons=[[Button.inline('🔙 رجوع للقائمة الرئيسية', 'backToAdminMenu')]])
        
        # Add To History
        user_id = event.chat_id
        invoice_id = 'تم الدفع بواسطة رصيد البوت'
        invoice_link = 'تم الدفع بواسطة رصيد البوت'
        paid_subscription_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subscription_ends = new_vip_time_str
        subscription_months = months
        subscription_price = price_in_dollar

        insert_query = """
            INSERT INTO subscription_history (
                user_id,
                invoice_id,
                invoice_link,
                paid_subscription_at,
                subscription_ends,
                subscription_months,
                subscription_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """
        cursor.execute(insert_query, (user_id, invoice_id, invoice_link, paid_subscription_at, subscription_ends, subscription_months, subscription_price))
        database.commit()

        
        try:
            notice_admin = await bot.send_message(
                entity=OWNER_ID,
                message=f'''__
تم دفع الفاتورة بنجاح ✅

👤 **ايدي المستخدم**: {event.chat_id}  
💳 **رقم الفاتورة**: تم الدفع بواسطة رصيد البوت  

📅 **العضوية بالشهر**: {months}  
💵 **السعر**: {price_in_dollar}$  
__''')
        except:pass


    else:
        await event.respond('__رصيدك غير كافي, يرجى الدفع بواسطة فاتورة__', 
            buttons=[[Button.inline('🔙 رجوع للقائمة الرئيسية', 'backToAdminMenu')]])

    await DeleteEvent(gen_msg)

    

@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'CreateInvoice_')))
async def CreateInvoice(event):

    await DeleteEvent(event)
    gen_msg = await event.reply('__جاري توليد فاتورتك. الرجاء الانتظار قليلاً...__')

    months, price_in_dollar = str(event.data.decode()).replace('CreateInvoice_', '').split('_')
    amount_inSAR = float(price_in_dollar) * 3.76 # FROM USD TO SAR

    invoice = await create_invoice_myfatoorah(amount_inSAR, event.chat_id)
    await event.reply(f'''__
✅ فاتورتك جاهزة!

رقم الفاتورة: {invoice[0]}
رابط الفاتورة: [اضغط لدفع فاتورتك]({invoice[1]})

عند إكمال دفع ( ${price_in_dollar} ), سيتم ترقية عضوية حسابك فورًا. يرجى الدفع خلال ساعة، شكرًا لك!
__''', buttons=[
            [Button.url('دفع فاتورتي', invoice[1])],
            [Button.inline('🔙 رجوع للقائمة الرئيسية', 'backToAdminMenu')]])
    

    await DeleteEvent(gen_msg)
    try:
        notice_admin = await bot.send_message(
            entity=OWNER_ID,
            message=f'''__
مستخدم أنشأ فاتورة 🧾

👤 **ايدي المستخدم**: {event.chat_id}  
💳 **رقم الفاتورة**: {invoice[0]}  
🔗 **رابط الدفع**: {invoice[1]}

📅 **العضوية بالشهر**: {months}  
💵 **السعر**: ${price_in_dollar}  
__''')
    except Exception as error:pass

    counter = 0
    while True:
        check_paid = await check_invoice_status_myfatoorah(invoice[0])
        if check_paid[0] == False:
            await asyncio.sleep(120)
            counter += 120
        else:
            user_data = cursor.execute(f"SELECT * FROM bot_users WHERE user_id = {event.chat_id}")
            user_data = cursor.fetchone()
            is_vip = user_data[2]
            if is_vip is None:
                new_vip_time = datetime.now() + timedelta(days=int(months) * 30)
            else:
                current_vip_time = datetime.strptime(str(is_vip), "%Y-%m-%d %H:%M:%S")
                new_vip_time = current_vip_time + timedelta(days=int(months) * 30)

            # Format the datetime back to string / # Update the database
            new_vip_time_str = new_vip_time.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "UPDATE bot_users SET is_vip = ? WHERE user_id = ?",
                (new_vip_time_str, event.chat_id,)
            )
            database.commit()

            notice_user = await event.reply(
                message=f'''__
🎉 شكرًا لك على دفعتك!

لقد تم دفع فاتورتك بنجاح، تم ترقية حسابك. نقدر سرعة استجابتك!
__''', buttons=[[Button.inline('🔙 رجوع للقائمة الرئيسية', 'backToAdminMenu')]])
            

            # Add To History
            user_id = event.chat_id
            invoice_id = invoice[0]
            invoice_link = invoice[1]
            paid_subscription_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            subscription_ends = new_vip_time_str
            subscription_months = months
            subscription_price = price_in_dollar

            insert_query = """
                INSERT INTO subscription_history (
                    user_id,
                    invoice_id,
                    invoice_link,
                    paid_subscription_at,
                    subscription_ends,
                    subscription_months,
                    subscription_price
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """
            cursor.execute(insert_query, (user_id, invoice_id, invoice_link, paid_subscription_at, subscription_ends, subscription_months, subscription_price))
            database.commit()

            
            try:
                notice_admin = await bot.send_message(
                    entity=OWNER_ID,
                    message=f'''__
تم دفع الفاتورة بنجاح ✅

👤 **ايدي المستخدم**: {event.chat_id}  
💳 **رقم الفاتورة**: {invoice[0]}

📅 **العضوية بالشهر**: {months}  
💵 **السعر**: {price_in_dollar}$  

__''')
            except:pass

            break
        
        if counter >= 3600:
            await event.reply(f'''__
⏰ مرت ساعة واحدة دون الدفع.

إذا كنت لا تزال ترغب في الاشتراك, يرجى إنشاء فاتورة جديدة لمتابعة معاملتك.
__''', buttons=[[Button.inline('🔙 رجوع للقائمة الرئيسية', 'backToAdminMenu')]])
            break




###############################################################################
###############################################################################
# Back To Setting Menu
@bot.on(events.CallbackQuery(data=b"back_to_setting_menu"))
async def BackToSettingMenu(event):

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    if event.is_group:
        await DeleteEvent(event)

        SettingGroup_buttons = [
            [
                Button.inline("🇸🇦 اللغات", b"languages"),
                Button.inline("⚙️ اعدادات", b"groupSettings")
            ]
        ]
        SettingGroup_MSG = f'''لإعدادي، استخدم أمر /settings أو اضغط على الزر أدناه.'''
        
        await event.respond(SettingGroup_MSG, buttons=SettingGroup_buttons, link_preview=False)
    else:
        await BotStart(event, callback=True)


# Back To Group Setting Menu
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"BackToGroupSettingMenu_")))
async def BackToGroupSettingMenu(event):

    target_group_id = int(str(event.data.decode()).replace('BackToGroupSettingMenu_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    await ShowGroupSettings(event, group_ID=target_group_id)
    

# Back To Block List Menu
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"BackToBlockListMenu_")))
async def BackToBlockListMenu(event):

    target_group_id = int(str(event.data.decode()).replace('BackToBlockListMenu_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    await Blocks(event, group_ID=target_group_id)


# Back To Multiple Joins Menu
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"BackToMultipleJoinsMenu_")))
async def BackToMultipleJoinsMenu(event):

    target_group_id = int(str(event.data.decode()).replace('BackToMultipleJoinsMenu_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    await MultipleJoinBlockBlocks(event, group_ID=target_group_id)


# Back To Anti-Spam Menu
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"BackToAntiSpamMenu_")))
async def BackToAntiSpamMenu(event):

    target_group_id = int(str(event.data.decode()).replace('BackToAntiSpamMenu_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    await AntiSpam(event, group_ID=target_group_id)


# Back To Anti-Flood Menu
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"BackToAntiFloodMenu_")))
async def BackToAntiFloodMenu(event):

    target_group_id = int(str(event.data.decode()).replace('BackToAntiFloodMenu_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    await AntiFlood(event, group_ID=target_group_id)



# Back To Night Mode Menu
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"BackToNightModeMenu_")))
async def BackToNightModeMenu(event):

    target_group_id = int(str(event.data.decode()).replace('BackToNightModeMenu_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    await NightMode(event, group_ID=target_group_id)


# Delete This Message
@bot.on(events.CallbackQuery(data=b"delete_this_message"))
async def DeleteThisMessage(event):

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    # if event.is_private:
    #     group_ownerID = await find_group_creator(target_group_id, groups_database)

    #     CoFounders, Admins = [], []
    #     if str(group_ownerID) in groups_database:
    #         if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
    #             group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
    #             CoFounders = group_data["co_founders"]
    #             Admins = group_data["admins"]
        
    #     if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
    #         return
        
    await DeleteEvent(event)


# Developer
@bot.on(events.NewMessage(pattern='/developer'))
async def BotDevloper(event):
    
    await event.reply('This bot was developed by @zkada')


# Help Command
@bot.on(events.NewMessage(pattern='/help'))
async def HelpCommand(event):

    if event.is_group:
        return

    buttons = [
        [
            Button.inline('💁🏻‍♂️ الأوامر الأساسية', 'BasicCommands'),
            Button.inline('🙋🏻‍♂️ الأوامر المتقدمة', 'AdvancedCommands')
        ],
        [
            Button.inline('🕵🏻‍♂️ للمحترفين', 'ProCommands'),
            Button.inline('💆🏻‍♂️ دليل المحترفين', 'ProGuides')
        ],
        [
            Button.inline('🔙 الرجوع', 'backToAdminMenu')
        ]
    ]

    await event.reply('🎉 مرحبًا بك في قائمة المساعدة!', buttons=buttons)


# Basic Commands
@bot.on(events.CallbackQuery(data=b'BasicCommands'))
async def BasicCommands(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [[Button.inline('🔙 الرجوع', 'backToHelpMenu')]]

    await event.respond('''
**الأوامر الأساسية**

👮🏻 متاحة للمديرين و المشرفين
🕵🏻 متاحة المديرين

👮🏻 /reload – يقوم بتحديث قائمة المديرين وامتيازاتهم.

🕵🏻 /settings – يتيح لك إدارة جميع إعدادات البوت في المجموعة.

👮🏻 /ban – يحظر المستخدم من المجموعة نهائيًا، مما يمنعه من الانضمام مرة أخرى باستخدام رابط المجموعة.

👮🏻 /mute – يضع المستخدم في وضع القراءة فقط، حيث يمكنه رؤية الرسائل لكنه لا يستطيع إرسال أي رسائل.

👮🏻 /kick – يطرد المستخدم من المجموعة، لكنه يمكنه العودة مرة أخرى باستخدام رابط المجموعة.

👮🏻 /unban – يزيل المستخدم من القائمة السوداء، مما يسمح له بالانضمام مرة أخرى باستخدام رابط المجموعة.

👮🏻 /info – يعرض معلومات عن المستخدم.
👮🏻 /infopvt – نفس وظيفة /info لكن يتم إرسال المعلومات في الدردشة الخاصة.

◽️ /staff – يعرض القائمة الكاملة لأعضاء طاقم إدارة المجموعة.
''', buttons=buttons)


# Advanced Commands
@bot.on(events.CallbackQuery(data=b'AdvancedCommands'))
async def AdvancedCommands(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [[Button.inline('🔙 الرجوع', 'backToHelpMenu')]]

    await event.respond('''
**الأوامر المتقدمة**

🕵🏻 متاحة المديرين
👮🏻 متاحة للمديرين و المشرفين
🛃 متاحة للمديرين والمنظفين

إدارة التحذيرات
👮🏻 /warn – يضيف تحذيرًا للمستخدم.
👮🏻 /unwarn – يزيل تحذيرًا من المستخدم.
👮🏻 /warns – يتيح لك عرض وإدارة تحذيرات المستخدمين.
🕵🏻 /delwarn – يحذف الرسالة ويضيف تحذيرًا للمستخدم.

🛃 /del – يحذف الرسالة المحددة.

🕵🏻 /send – يسمح بإرسال منشور باستخدام HTML عبر البوت في المجموعة.
➡️ مثال: /send مرحبًا بالعالم!
''', buttons=buttons)
    
    # 🛃 /logdel – يحذف الرسالة المحددة ويرسلها إلى قناة السجلات.
    # ◽️ /me – يرسل في الدردشة الخاصة معلومات المستخدم، معلومات المجموعة، التحذيرات المستلمة، قوانين المجموعة، قائمة الكلمات المحظورة...
    # 👮🏻 /intervention – يتيح لك طلب تدخل أحد أعضاء الدعم الرسمي للروبوت، والذي سينضم إلى المجموعة في أقرب وقت ممكن.



# Pro Commands
@bot.on(events.CallbackQuery(data=b'ProCommands'))
async def ProCommands(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [[Button.inline('🔙 الرجوع', 'backToHelpMenu')]]

    await event.respond('''
**الأوامر المتقدمة للمحترفين**

👥 متاحة لجميع المستخدمين
👮🏻 متاحة للمديرين و المشرفين
🕵🏻 متاحة المديرين

إدارة الروابط والرسائل
👥 /geturl – بالرد على رسالة واستخدام هذا الأمر، ستحصل على رابط مباشر يُشير إلى تلك الرسالة.

إدارة الرسائل المثبتة
🕵🏻 /pin [الرسالة] – يرسل الرسالة عبر البوت ويقوم بتثبيتها.
🕵🏻 /pin – يثبّت الرسالة التي تم الرد عليها.
🕵🏻 /editpin [الرسالة] – يعدّل الرسالة المثبتة الحالية (إذا تم إرسالها عبر البوت).
🕵🏻 /delpin – يزيل الرسالة المثبتة.
🕵🏻 /repin – يزيل ويعيد تثبيت الرسالة المثبتة الحالية مع إشعار!
👥 /pinned – يعرض الرسالة المثبتة الحالية.

إدارة الأعضاء والإحصائيات
🕵🏻 /list – يرسل في الدردشة الخاصة قائمة بأعضاء المجموعة مع عدد الرسائل التي أرسلوها.
🕵🏻 /list roles – يرسل في الدردشة الخاصة قائمة بجميع الأدوار الخاصة الممنوحة للمستخدمين.
''', buttons=buttons)

    # 🕵🏻 /inactives [الأيام] – يرسل في الدردشة الخاصة قائمة بالمستخدمين الذين لم يرسلوا أي رسالة خلال [عدد الأيام] الماضية، مع إمكانية معاقبتهم.
    # 🕵🏻 /graphic – يرسل رسمًا بيانيًا يُظهر تطور عدد أعضاء المجموعة.
    # 🕵🏻 /trend – يرسل إحصائيات نمو المجموعة.


# Pro Guides
@bot.on(events.CallbackQuery(data=b'ProGuides'))
async def ProGuides(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [
        [
            # Button.inline('👷🏻 إعداد موظفين المجموعة', 'BasicCommands'),
            Button.inline('🎩 أدوار المستخدمين', 'usersRoles')
        ],
        [
            Button.inline('🔙 الرجوع', 'backToHelpMenu')
        ]
    ]

    await event.respond('''
**دليل المحترفين**
                        
في هذا القسم، ستجد مجموعة من الأدلة المخصصة للوظائف المتقدمة جدًا لمساعدة المجموعات.
                        
⚠️ يُوصى باستخدامها فقط إذا كنت على دراية كاملة بما تفعله، واتباع التعليمات بدقة.
''', buttons=buttons)


# Users Roles
@bot.on(events.CallbackQuery(data=b'usersRoles'))
async def UsersRoles(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [
        [
            Button.inline('👑 المؤسس', 'userRoleFounder'),
            Button.inline('⚜️ الشريك المؤسس', 'userRoleCoFounder')
        ],
        [
            Button.inline('👮🏻‍♀️ المدير', 'userRoleAdmin'),
            Button.inline('👷🏻 المشرف', 'userRoleModerator')
        ],
        [
            Button.inline('🛂 منظف الدردشة', 'userRoleCleaner'),
            Button.inline('🙊 كاتم', 'userRoleMuter')
        ],
        [
            Button.inline('⛑ مساعد', 'userRoleHelper'),
            Button.inline('🔓 بدون قيود', 'userRoleFree')
        ],
        [
            Button.inline('🔙 الرجوع', 'backToProGuidesMenu')
        ]
    ]

    await event.respond('''
**أدوار المستخدمين**
                        
استخدم لوحة المفاتيح المدمجة لاكتشاف قوة هذه الأدوار!

لإضافة أو إزالة دور من المستخدم، يمكنك استخدام الأوامر المتوفرة في تبويبات الأدوار
''', buttons=buttons)


# User Role Founder
@bot.on(events.CallbackQuery(data=b'userRoleFounder'))
async def UserRoleFounder(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [[Button.inline('🔙 الرجوع', 'backToUsersRolesMenu')]]
    await event.respond('''
👑 **المؤسس**
                        
المؤسس هو منشئ المجموعة، وله جميع الصلاحيات من تيليجرام والبوت
➕ يظهر أولاً في قائمة الموظفين
➕ يمكنهم إدارة الشركاء المؤسسين، المشرفين، المساعدين، والمستخدمين بدون قيود
➕ يمكنهم إدارة جميع المستخدمين، بما في ذلك المدراء

يمكن تغيير المؤسس مباشرة باستخدام نظام تيليجرام.
''', buttons=buttons)


# User Role Co-Founder
@bot.on(events.CallbackQuery(data=b'userRoleCoFounder'))
async def UserRoleCoFounder(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [[Button.inline('🔙 الرجوع', 'backToUsersRolesMenu')]]
    await event.respond('''
⚜️ **الشريك المؤسس**
                        
هم المدراء الذين لديهم صلاحيات إضافية
➕ يظهرون في قائمة الموظفين
➕ يمكنهم تعيين شركاء مؤسسين، مشرفين، مساعدين، ومستخدمين بدون قيود ويمكنهم حظرهم

الأوامر: /cofounder و /uncofounder
''', buttons=buttons)


# User Role Admin
@bot.on(events.CallbackQuery(data=b'userRoleAdmin'))
async def UserRoleAdmin(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [[Button.inline('🔙 الرجوع', 'backToUsersRolesMenu')]]
    await event.respond('''
👮 **المديرين**
                        
➕ يظهرون في قائمة الموظفين
➕ يمكنهم إدارة إعدادات المجموعة /settings
➕ يمكنهم إدارة المستخدمين (من خلال Telegram أو باستخدام أوامر مثل /ban)، إذا كان لديهم إذن "حظر المستخدمين"
➕ يمكنهم حذف الرسائل (من خلال Telegram أو باستخدام أوامر مثل /del و /logdel)، إذا كان لديهم إذن "حذف الرسائل"
➕ يمكنهم إدارة الرسائل المثبتة (من خلال Telegram أو باستخدام أوامر مثل /pin)، إذا كان لديهم إذن "تثبيت الرسائل"

هناك طريقتان لإضافتهم/إزالتهم:
• باستخدام الأوامر /admin و /unadmin
• تعيينهم من خلال لوحة المسؤولين في مجموعة Telegram ثم استخدام /reload في المجموعة
''', buttons=buttons)


# User Role Moderator
@bot.on(events.CallbackQuery(data=b'userRoleModerator'))
async def UserRoleModerator(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [[Button.inline('🔙 الرجوع', 'backToUsersRolesMenu')]]
    await event.respond('''
👷🏻‍♂️ **المشرفين**
                        
➕ يظهرون في قائمة الموظفين
➕ يمكنهم استخدام جميع أوامر الإدارة من البوت (حظر، طرد، رفع الحظر، معلومات، معلومات خاصة، كتم، رفع الكتم)
➕ هم مستخدمون بدون قيود
➖ لا يمكنهم حذف الرسائل

الأوامر: /mod و /unmod
''', buttons=buttons)


# User Role Cleaner
@bot.on(events.CallbackQuery(data=b'userRoleCleaner'))
async def UserRoleCleaner(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [[Button.inline('🔙 الرجوع', 'backToUsersRolesMenu')]]
    await event.respond('''
🛃 **منظف الدردشة**
                        
➕ يظهرون في قائمة الموظفين
➕ يمكنهم حذف الرسائل باستخدام /del
➖ لا يمكنهم إدارة المستخدمين
➖ لا يعتبرون مستخدمين بدون قيود

الأوامر: /cleaner و /uncleaner
''', buttons=buttons)

    #أو /logdel


# User Role Muter
@bot.on(events.CallbackQuery(data=b'userRoleMuter'))
async def UserRoleMuter(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [[Button.inline('🔙 الرجوع', 'backToUsersRolesMenu')]]
    await event.respond('''
🙊 **المكتم**
                        
➕ يمكنهم كتم ورفع الكتم عن المستخدمين باستخدام أوامر البوت
➕ يعتبرون مستخدمين بدون قيود
➖ لا يمكنهم حظر أو رفع الحظر أو طرد المستخدمين
➖ لا يمكنهم حذف الرسائل

الأوامر: /muter و /unmuter
''', buttons=buttons)


# User Role Helper
@bot.on(events.CallbackQuery(data=b'userRoleHelper'))
async def UserRoleHelper(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [[Button.inline('🔙 الرجوع', 'backToUsersRolesMenu')]]
    await event.respond('''
⛑ **مساعد**
                        
➕ يظهرون في قائمة الموظفين
➖ ليس لديهم أي صلاحيات
➖ ليسوا مستخدمين بدون قيود

الأوامر: /helper و /unhelper
''', buttons=buttons)


# User Role Free
@bot.on(events.CallbackQuery(data=b'userRoleFree'))
async def UserRoleFree(event):

    if event.is_group:
        return

    await DeleteEvent(event)
    buttons = [[Button.inline('🔙 الرجوع', 'backToUsersRolesMenu')]]
    await event.respond('''
🔓 **مستخدمون بدون قيود**
                        
➕ يتجاهلهم البوت بالنسبة للعقوبات التلقائية مثل مكافحة سبام، مكافحة الرسائل المكررة، حظر الوسائط، الصمت العام...

الأوامر: /free و /unfree
''', buttons=buttons)




# Cofounder User Command
@bot.on(events.NewMessage(pattern='/cofounder'))
async def CofounderUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["co_founders"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id
        
        if user_id not in CoFounders:
            targetGroupSettings.append(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم اضافة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# UnCofounder User Command
@bot.on(events.NewMessage(pattern='/uncofounder'))
async def UnCofounderUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["co_founders"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id

        if user_id in CoFounders:
            targetGroupSettings.remove(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم ازالة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# Admin User Command
@bot.on(events.NewMessage(pattern='/admin'))
async def AdminUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["admins"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id
        
        if user_id not in Admins:
            targetGroupSettings.append(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم اضافة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# UnAdmin User Command
@bot.on(events.NewMessage(pattern='/unadmin'))
async def UnAdminUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["admins"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id

        if user_id in Admins:
            targetGroupSettings.remove(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم ازالة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# Mod User Command
@bot.on(events.NewMessage(pattern='/mod'))
async def ModUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["moderators"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id
        
        if user_id not in Moderators:
            targetGroupSettings.append(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم اضافة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# UnMod User Command
@bot.on(events.NewMessage(pattern='/unmod'))
async def UnModUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["moderators"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id

        if user_id in Moderators:
            targetGroupSettings.remove(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم ازالة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# Cleaner User Command
@bot.on(events.NewMessage(pattern='/cleaner'))
async def CleanerUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["cleaners"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id
        
        if user_id not in Cleaners:
            targetGroupSettings.append(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم اضافة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# UnCleaner User Command
@bot.on(events.NewMessage(pattern='/uncleaner'))
async def UnCleanerUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["cleaners"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id

        if user_id in Cleaners:
            targetGroupSettings.remove(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم ازالة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# Muter User Command
@bot.on(events.NewMessage(pattern='/muter'))
async def MuterUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["muters"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id
        
        if user_id not in Muters:
            targetGroupSettings.append(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم اضافة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# UnMuter User Command
@bot.on(events.NewMessage(pattern='/unmuter'))
async def UnMuterUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["muters"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id

        if user_id in Muters:
            targetGroupSettings.remove(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم ازالة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# Helper User Command
@bot.on(events.NewMessage(pattern='/helper'))
async def HelperUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["helpers"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id
        
        if user_id not in Helpers:
            targetGroupSettings.append(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم اضافة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# UnHelper User Command
@bot.on(events.NewMessage(pattern='/unhelper'))
async def UnHelperUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["helpers"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id

        if user_id in Helpers:
            targetGroupSettings.remove(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم ازالة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# Free User Command
@bot.on(events.NewMessage(pattern='/free'))
async def FreeUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["free_users"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id
        
        if user_id not in FreeUsers:
            targetGroupSettings.append(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم اضافة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')


# UnFree User Command
@bot.on(events.NewMessage(pattern='/unfree'))
async def UnFreeUserCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders:
            return

    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["free_users"]
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        user_id = reply_msg.sender_id

        if user_id in FreeUsers:
            targetGroupSettings.remove(user_id)

        await SaveJsonGroupsData(groups_database)
        await event.reply('✅ تم ازالة المستخدم')
    else:
        await event.reply('❕ قم بالرد على المستخدم')



# List Roles Command
@bot.on(events.NewMessage(pattern='/list roles'))
async def ListRolesCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.message.message != '/list roles':
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]
                FreeUsers = group_data["free_users"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    
    Staff_MSG = f'**الأدوار الخاصة**\n\n'

    if len(CoFounders) != 0:
        Staff_MSG += '⚜️ **الشريك المؤسس**\n'
    for user_id in CoFounders:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    if len(Admins) != 0:
        Staff_MSG += '\n👮🏼 **مديرين**\n'
    for user_id in Admins:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    if len(Moderators) != 0:
        Staff_MSG += '\n👷🏻‍♂️ **المشرفين**\n'
    for user_id in Moderators:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    if len(Cleaners) != 0:
        Staff_MSG += '\n🛃 **منظف الدردشة**\n'
    for user_id in Cleaners:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    if len(Muters) != 0:
        Staff_MSG += '\n🙊 **المكتم**\n'
    for user_id in Muters:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    if len(Helpers) != 0:
        Staff_MSG += '\n⛑ **مساعد**\n'
    for user_id in Helpers:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    if len(FreeUsers) != 0:
        Staff_MSG += '\n🔓 **مستخدمون بدون قيود**\n'
    for user_id in FreeUsers:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    

    bot_data = await bot.get_me()
    buttons = [[Button.url('عرض في الخاص', f'https://t.me/{bot_data.username}')]]

    await bot.send_message(event.sender_id, Staff_MSG)
    MSG = await event.respond("📩 تم إرسال القائمة في الدردشة الخاصة.", buttons=buttons)

    await asyncio.sleep(30)
    await DeleteEvent(MSG)
        



# List Command
@bot.on(events.NewMessage(pattern='/list'))
async def ListCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.message.message != '/list':
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    # Print the results
    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
    result = "📊 Message Count in Group:\n\n"
    for user_id in targetGroupSettings["group_satistics"]["users"]:
        user = targetGroupSettings["group_satistics"]["users"][str(user_id)]
        result += f'[{user["messages_count"]}] {user["full_name"]} [{user_id}]\n'
    
    file_path = f'temp/list_{event.chat_id}_stats.txt'
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(result)

    bot_data = await bot.get_me()
    buttons = [[Button.url('عرض في الخاص', f'https://t.me/{bot_data.username}')]]

    await bot.send_message(event.sender_id, file=file_path)
    MSG = await event.respond("📩 تم إرسال القائمة في الدردشة الخاصة.", buttons=buttons)

    try:
        os.remove(file_path)
    except:pass

    await asyncio.sleep(30)
    await DeleteEvent(MSG)


# Pinned Command
@bot.on(events.NewMessage(pattern='/pinned'))
async def PinnedCommand(event):

    if event.is_private or event.sender_id == None:
        return

    # pinned message
    pinned_msg = await bot.get_messages(event.chat_id, ids=InputMessagePinned())
    if pinned_msg:
        await event.reply(pinned_msg.text)


# Re Pin Command
@bot.on(events.NewMessage(pattern='/repin'))
async def RePinCommand(event):

    if event.is_private or event.sender_id == None or event.message.message == '/pinned':
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    # re pin
    pinned_msg = await bot.get_messages(event.chat_id, ids=InputMessagePinned())

    try:
        await bot.pin_message(event.chat_id, pinned_msg, notify=True)
        await event.respond('**تم اعادة تثبت الرسالة**')
    except Exception as error:
        await event.respond('⚠️ **لم يتم العثور على رسالة مثبتة**')
    

# Del Pin Command
@bot.on(events.NewMessage(pattern='/delpin'))
async def DelPinCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    # delete pinned message
    pinned_msg = await bot.get_messages(event.chat_id, ids=InputMessagePinned())
    
    try:
        await bot.delete_messages(event.chat_id, message_ids=pinned_msg.id)
        await event.respond('**تم حذف الرسالة المثبتة**')
    except Exception as error:
        await event.respond('⚠️ **لم يتم العثور على رسالة مثبتة**')


# Edit Pin Command
@bot.on(events.NewMessage(pattern='/editpin'))
async def EditPinCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    # edit pin
    pinned_msg = await bot.get_messages(event.chat_id, ids=InputMessagePinned())
    pinned_MSG = str(event.message.message).replace('/editpin', '').strip()
    if pinned_MSG != '':
        try:
            await bot.edit_message(event.chat_id, pinned_msg.id, pinned_MSG)
        except Exception as error:
            await event.reply("⚠️ الرسالة المثبتة حاليًا ليست من قِبل البوت. يرجى تثبيت رسالة باستخدام /pin أولًا.")


# Pin Command
@bot.on(events.NewMessage(pattern='/pin'))
async def PinCommand(event):

    if event.is_private or event.sender_id == None or event.message.message == '/pinned':
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    # show warn
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        await bot.pin_message(event.chat_id, reply_msg, notify=True)

    else:
        pin_MSG = str(event.message.message).replace('/pin', '').strip()
        if pin_MSG != '':
            message = await bot.send_message(event.chat_id, pin_MSG)
            await bot.pin_message(event.chat_id, message, notify=True)



# Show Message link
@bot.on(events.NewMessage(pattern="/geturl"))
async def ShowMessageLink(event):

    if event.is_private:
        return

    # show warn
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        group_data = await bot.get_entity(event.chat_id)

        if group_data.username:
            message_url = f't.me/{group_data.username}/{reply_msg.id}'
        else:
            message_url = f't.me/c/{group_data.id}/{reply_msg.id}'
        
        await event.reply(f'🔗 **رابط الرسالة:** {message_url}')
    else:
        await event.reply('❕ قم بالرد على الرسالة!')
    

# Reset Warn Command
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'resetWarns_')))
async def ResetWarnCommand(event):

    user_id = int(str(event.data.decode()).replace('resetWarns_', ''))

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

    # increase Warn
    await DeleteEvent(event)
    await ChangeWarn(event, group_ownerID, user_id, onlyShow=True, reset=True)


# Increase Warn Command
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'increaseWarn_')))
async def IncreaseWarnCommand(event):

    user_id = int(str(event.data.decode()).replace('increaseWarn_', ''))

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

    # increase Warn
    await DeleteEvent(event)
    await ChangeWarn(event, group_ownerID, user_id, onlyShow=True, increase=True)


# Decrease Warn Command
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'decreaseWarn_')))
async def DecreaseWarnCommand(event):

    user_id = int(str(event.data.decode()).replace('decreaseWarn_', ''))

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

    # decrease Warn
    await DeleteEvent(event)
    await ChangeWarn(event, group_ownerID, user_id, onlyShow=True, decrease=True)


# Warns Command
@bot.on(events.NewMessage(pattern='/warns'))
async def WarnsCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

    # show warn
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        await ChangeWarn(event, group_ownerID, reply_msg.sender_id, onlyShow=True)
    else:
        await event.reply('❕ قم بالرد على الرسالة!')


# Delete Warn Command
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'WarnCancel_')))
async def DeleteWarnCommand(event):

    user_id = int(str(event.data.decode()).replace('WarnCancel_', ''))

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

    # delete warn
    await DeleteEvent(event)
    await ChangeWarn(event, group_ownerID, user_id, onlyShow=False, decrease=True)


# UnWarn Command
@bot.on(events.NewMessage(pattern='/unwarn'))
async def UnWarnCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

    # delete warn
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        await ChangeWarn(event, group_ownerID, reply_msg.sender_id, onlyShow=False, decrease=True)
    else:
        await event.reply('❕ قم بالرد على الرسالة!')


# Warn Command
@bot.on(events.NewMessage(pattern='/warn'))
async def WarnCommand(event):

    if event.is_private or event.sender_id == None or event.message.message == '/warns':
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

    # add warn
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        await TakePenaltyAction(reply_msg, group_ownerID, 'Warn', None, 'تلقى تحذير')
    else:
        await event.reply('❕ قم بالرد على الرسالة!')


# Del Warn Command
@bot.on(events.NewMessage(pattern='/delwarn'))
async def DelWarnCommand(event):

    if event.is_private or event.sender_id == None or event.message.message == '/warns':
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    # delete & add warn
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        await TakePenaltyAction(reply_msg, group_ownerID, 'Warn', True, 'تلقى تحذير')
    else:
        await event.reply('❕ قم بالرد على الرسالة!')


# Send Command
@bot.on(events.NewMessage(pattern='/send'))
async def SendCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await event.respond(str(event.message.message).replace('/send', ''), parse_mode='HTML')


# Del Command
@bot.on(events.NewMessage(pattern='/del'))
async def DelCommand(event):

    if event.is_private or event.sender_id == None or event.message.message == '/delwarn' or event.message.message == '/delpin':
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Cleaners:
            return

    if event.is_reply:
        try:
            await bot.delete_messages(event.chat_id, message_ids=event.reply_to_msg_id)
        except Exception as error:pass
    else:
        await event.reply('❕ قم بالرد على الرسالة!')


# Staff Command
@bot.on(events.NewMessage(pattern='/staff'))
async def StaffCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        Cleaners, Muters, Helpers = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Cleaners = group_data["cleaners"]
                Muters = group_data["muters"]
                Helpers = group_data["helpers"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

    user_data = await bot.get_entity(int(group_ownerID))
    Staff_MSG = f'''**موظفين المجموعة**

👑 **مؤسس المجموعة**
⤿ [{user_data.first_name}](tg://user?id={group_ownerID})
'''

    if len(CoFounders) != 0:
        Staff_MSG += '⚜️ **الشريك المؤسس**\n'
    for user_id in CoFounders:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    if len(Admins) != 0:
        Staff_MSG += '\n👮🏼 **مديرين**\n'
    for user_id in Admins:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    if len(Moderators) != 0:
        Staff_MSG += '\n👷🏻‍♂️ **المشرفين**\n'
    for user_id in Moderators:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    if len(Cleaners) != 0:
        Staff_MSG += '\n🛃 **منظف الدردشة**\n'
    for user_id in Cleaners:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    if len(Muters) != 0:
        Staff_MSG += '\n🙊 **المكتم**\n'
    for user_id in Muters:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    if len(Helpers) != 0:
        Staff_MSG += '\n⛑ **مساعد**\n'
    for user_id in Helpers:
        user_data = await bot.get_entity(int(user_id))
        Staff_MSG += f"⤿ {f'@{user_data.username}' if user_data.username else f'[{user_data.first_name}](tg://user?id={user_id})'}\n"
    
    await event.respond(Staff_MSG)


# kick Command
@bot.on(events.NewMessage(pattern='/kick'))
async def KickCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

        # Kick
        if event.is_reply:
            reply_msg = await event.get_reply_message()
            await bot.edit_permissions(event.chat_id, reply_msg.sender_id, view_messages=False)
            await bot.edit_permissions(event.chat_id, reply_msg.sender_id)
            
            MSG = await event.reply('🚷 **تم طرد المستخدم**')

        else:
            await event.reply('❕ قم بالرد على المستخدم!')


# Mute Command
@bot.on(events.NewMessage(pattern='/mute'))
async def MuteCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Muters = group_data["muters"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators and event.sender_id not in Muters:
            return

        # Mute
        if event.is_reply:
            reply_msg = await event.get_reply_message()
            await bot.edit_permissions(event.chat_id, reply_msg.sender_id, send_messages=False)
            
            MSG = await event.reply(
                '🚷 **تم كتم المستخدم**',
                buttons=[
                    [Button.inline('✅ رفع الكتم', f'DoUnMute_{event.chat_id}_{reply_msg.sender_id}')]
                ]
            )

        else:
            await event.reply('❕ قم بالرد على المستخدم!')


# Ban Command
@bot.on(events.NewMessage(pattern='/ban'))
async def BanCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

        # ban
        if event.is_reply:
            reply_msg = await event.get_reply_message()
            await bot.edit_permissions(event.chat_id, reply_msg.sender_id, view_messages=None)
            
            MSG = await event.reply(
                '🚷 **تم حظر المستخدم**',
                buttons=[
                    [Button.inline('✅ رفع الحظر', f'DoUnban_{event.chat_id}_{reply_msg.sender_id}')]
                ]
            )

        else:
            await event.reply('❕ قم بالرد على المستخدم!')


# UnBan Command
@bot.on(events.NewMessage(pattern='/unban'))
async def UnBanCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

        # ban
        if event.is_reply:
            reply_msg = await event.get_reply_message()
            await bot.edit_permissions(event.chat_id, reply_msg.sender_id, send_messages=True)
            await event.reply('✅ تم رفع الحظر على المستخدم')

        else:
            await event.reply('❕ قم بالرد على المستخدم!')


# Do Unban
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'DoUnban_')))
async def DoUnban(event):

    chat_id, user_id = str(event.data.decode()).replace('DoUnban_', '').split('_')

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

    await DeleteEvent(event)
    await bot.edit_permissions(int(chat_id), int(user_id), send_messages=True)
    await event.reply('✅ تم رفع الحظر على المستخدم')



# Do UnMute
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'DoUnMute_')))
async def DoUnMute(event):

    chat_id, user_id = str(event.data.decode()).replace('DoUnMute_', '').split('_')

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]
                Muters = group_data["muters"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators and event.sender_id not in Muters:
            return

    await DeleteEvent(event)
    await bot.edit_permissions(int(chat_id), int(user_id), send_messages=True)
    await event.reply('✅ تم رفع الكتم على المستخدم')


# Info Command
@bot.on(events.NewMessage(pattern='/info'))
async def InfoCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

        if event.is_reply:
            reply_msg = await event.get_reply_message()
            user_data = await bot.get_entity(reply_msg.sender_id)

            user_id = user_data.id
            first_name = user_data.first_name
            last_name = user_data.last_name if user_data.last_name else ""
            username = f"@{user_data.username}" if user_data.username else ""
            status = "مستخدم عادي"

            user_warns = group_data["warned_users"][str(event.chat_id)]["warn_count"] if str(event.chat_id) in group_data["warned_users"] else "0"
            warns = f'{user_warns}/{group_data["warn_system"]["max_warns"]}'

            # first_msg = await get_first_message(event.chat_id, user_id)
            # join_date = ''
            # if first_msg:
            #     join_date = first_msg.date.strftime('%d/%m/%Y %H:%M')
            # ⤵️ Join: {join_date}

            language = user_data.lang_code

            info_message = f"""
🆔 المعرف: {user_id}
👱 الاسم: {first_name}  
👪 اللقب: {last_name}  
🌐 اسم المستخدم: {username}  
👀 الحالة: {status}  
❕ التحذيرات: {warns}  
🇸🇦 اللغة: {language}
"""

            
            if event.message.message == '/infopvt':
                bot_data = await bot.get_me()
                await bot.send_message(event.sender_id, info_message)
                MSG = await event.reply(
                    '✅ **تم ارسال المعلومات في الدردشة الخاصة**',
                    buttons=[
                        [Button.url('📄 عرض المعلومات', f'https://t.me/{bot_data.username}')]
                    ]
                )

                await asyncio.sleep(30)
                await DeleteEvent(MSG)
            else:
                await event.reply(info_message)

        else:
            await event.reply('❕ قم بالرد على المستخدم!')


# Reload Command
@bot.on(events.NewMessage(pattern='/reload'))
async def ReloadCommand(event):

    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins, Moderators = [], [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
                Moderators = group_data["moderators"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins and event.sender_id not in Moderators:
            return

        groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["admins"] = group_admins
        await SaveJsonGroupsData(groups_database)

        await event.reply('✅ **تم تحديث قائمة المديرين**')


# Settings Command
@bot.on(events.NewMessage(pattern='/settings'))
async def SettingsCommand(event):

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    if event.is_group:
        try:
            bot_data = await bot.get_me()
            participant = await bot(GetParticipantRequest(event.chat_id, bot_data.id))

            if isinstance(participant.participant, ChannelParticipantCreator):
                return await GroupSettings(event)
            elif isinstance(participant.participant, ChannelParticipantAdmin):
                return await GroupSettings(event)
            else:
                return await event.respond("**لإدارة الإعدادات، يجب تعييني كمسؤول.**")

        except Exception as error:
            print(f"⚠️ Settings Command : {error}")
            return await event.respond("**لإدارة الإعدادات، يجب تعييني كمسؤول.**")

    buttons = []
    target_groups = {}
    if str(event.chat_id) in groups_database:
        target_groups = groups_database[str(event.chat_id)]["groups"]

    for group in target_groups:
        target_group_data = target_groups[group]
        try:
            group_data = await bot.get_entity(target_group_data.get("id"))
            buttons.append([Button.inline(str(group_data.title), f'showGroupSettings_{target_group_data.get("id")}')])
        
        except Exception as error:print(f'⚠️ Settings Command ( PRIVATE ) : {error}')

    Settings_MSG = '''
⚙️ إعدادات المجموعة
👉🏻 اختر المجموعة التي تريد تعديل إعداداتها.

إذا لم تظهر مجموعة أنت مسؤول فيها هنا:
• أرسل /reload في المجموعة ثم حاول مرة أخرى.
• أرسل /settings في المجموعة ثم اضغط على "فتح في الخاص".
'''

    buttons.append([Button.inline("🔙 الرجوع", b"back_to_setting_menu")])
    await event.respond(Settings_MSG, buttons=buttons)


# Group Settings
@bot.on(events.CallbackQuery(data=b"groupSettings"))
async def GroupSettings(event):
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return await event.reply('''
⚠️ ليس لديك الصلاحيات لتنفيذ هذه العملية  

💡 إذا كنت تعتقد عكس ذلك، استخدم /reload وحاول مرة أخرى
''')
        
        
    await DeleteEvent(event)
    bot_data = await bot.get_me()
    msg = '**أين تريد فتح قائمة الإعدادات؟**'
    buttons = [
        # [Button.inline("👥 Open here", b"openSettings")],
        [Button.inline("👥 افتح في الدردشة الخاصة.", "sendSettingsToPrivate")] # f"http://t.me/{bot_data.username}?start=OpenGroupSettings_{event.chat_id}")]
    ]

    await event.respond(msg, buttons=buttons)


# Open Settings
@bot.on(events.CallbackQuery(data=b"openSettings"))
async def OpenSettings(event):
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    # if event.is_private:
    #     group_ownerID = await find_group_creator(target_group_id, groups_database)

    #     CoFounders, Admins = [], []
    #     if str(group_ownerID) in groups_database:
    #         if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
    #             group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
    #             CoFounders = group_data["co_founders"]
    #             Admins = group_data["admins"]
        
    #     if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
    #         return

    await ShowGroupSettings(event, group_ID=event.chat_id)


# Send Settings To Private
@bot.on(events.CallbackQuery(data=b"sendSettingsToPrivate"))
async def SendSettingsToPrivate(event):
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    await DeleteEvent(event)
    bot_data = await bot.get_me()
    buttons = [[Button.url('🔧 توجه للخاص لعرض الاعدادات', f'https://t.me/{bot_data.username}')]]
    open_buttons = [[Button.inline('⚙️ طلب فتح الإعدادات', f'OpenGroupSettingsNow_{event.chat_id}')]]

    await bot.send_message(event.sender_id, '🔒 انقر هنا لطلب فتح القائمة بشكل آمن', buttons=open_buttons)
    SettingsMSG = await event.reply('✅ تم إرسال الإعدادات بنجاح!', buttons=buttons)

    await asyncio.sleep(30)
    await DeleteEvent(SettingsMSG)


# Open Group Settings Now
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"OpenGroupSettingsNow_")))
async def OpenGroupSettingsNow(event):

    target_group_id = int(str(event.data.decode()).replace('OpenGroupSettingsNow_', ''))
    await ShowGroupSettings(event, group_ID=target_group_id)


# Function to find the creator of a group by group ID
async def find_group_creator(target_group_id, user_data):
    for user_id, user_info in user_data.items():
        groups = user_info.get("groups", {})
        for group_id, group_info in groups.items():
            if group_id == str(target_group_id):
                return group_info.get("creator_id", None)

    return None


# Show Group Settings
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showGroupSettings_")))
async def ShowGroupSettings(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('showGroupSettings_', ''))
    else:
        target_group_id = int(group_ID)

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return


    await DeleteEvent(event)
    group_data = await bot.get_entity(target_group_id)
    
    ChangeLang_MSG = f'''
**الاعدادات**
المجموعة: `{group_data.title}`

اختر أحد الإعدادات التي تريد تغييرها.
'''
    buttons = [
        [Button.inline("📜 القوانين", f"regulation_{target_group_id}"), Button.inline("🛡 مكافحة السبام", f"antiSpam_{target_group_id}")],
        [Button.inline("💬 رسالة الترحيب", f"welcome_{target_group_id}"), Button.inline("🚫 الرسائل المتكررة", f"antiFlood_{target_group_id}")],
        [Button.inline("👋 رسالة الوداع", f"goodbye_{target_group_id}"), Button.inline("🔠 الأبجديات", f"alphabets_{target_group_id}")],
        [Button.inline("🧠 الكابتشا", f"captcha_{target_group_id}"), Button.inline("📝 فحوصات", f"checks_{target_group_id}")],
        [Button.inline("🆘 @Admin", f"admin_{target_group_id}"), Button.inline("🔒 القيود", f"blocks_{target_group_id}")],
        [Button.inline("🖼 الميديا", f"media_{target_group_id}"), Button.inline("🔞 الاباحية", f"porn_{target_group_id}")],
        [Button.inline("⚠ التحذير", f"warns_{target_group_id}"), Button.inline("🌙 الوضع الليلي", f"nightMode_{target_group_id}")],
        [
            Button.inline("🔔 تنبيه", f"tag_{target_group_id}"),
            Button.inline("🗳 وضع القبول", f"approvalMode_{target_group_id}"),
            Button.inline("🔗 الرابط", f"link_{target_group_id}")
        ],
        # [Button.inline("🗑 Deleting Messages", b"deleting_messages")],
        [
            # Button.inline("🇸🇦 اللغة", b"languages"),
            Button.inline("✅ اغلاق", b"delete_this_message"),
            Button.inline("➡️ التالي", f"nextList_{target_group_id}")
        ]
    ]

    await event.respond(ChangeLang_MSG, buttons=buttons)



# Show Group Settings Next List
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"nextList_")))
async def ShowGroupSettingsNextList(event):

    target_group_id = int(str(event.data.decode()).replace('nextList_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return


    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    
    await DeleteEvent(event)
    group_data = await bot.get_entity(target_group_id)
    
    ChangeLang_MSG = f'''
**الاعدادات**
المجموعة: `{group_data.title}`

اختر أحد الإعدادات التي تريد تغييرها.
'''
    buttons = [
        # [Button.inline("📂 Topic", b"topic")],
        [Button.inline("🔤 الكلمات المحظورة", f"bannedWords_{target_group_id}")],
        [Button.inline("⏰ Recurring messages", b"recurring_messages")],
        [Button.inline("👥 إدارة الأعضاء", f"membersManagement_{target_group_id}")],
        [
            Button.inline("😷 المستخدمين المخفيين", f"maskedUsers_{target_group_id}"),
            Button.inline("📣 مجموعة النقاش", f"discussionGroup_{target_group_id}")
        ],
        # [Button.inline("📟 Personal Commands", b"personal_commands")],
        # [Button.inline("🧙‍♂️ Magic Stickers & GIFs", b"magic_stickers_gifs")],
        [Button.inline("✏️ طول الرسالة", f"messageLength_{target_group_id}")],
        [Button.inline("📢 إدارة القنوات", b"channelsManagement")],
        # [Button.inline("⚙️ Permissions", b"permissions"), Button.inline("🔍 Log Channel", b"log_channel")], 

        # [Button.inline("🔤 الكلمات المحظورة", f"bannedWords_{target_group_id}")],
        # [Button.inline("⏰ الرسائل المتكررة", b"recurring_messages")],
        # [Button.inline("👥 إدارة الأعضاء", f"membersManagement_{target_group_id}")],
        # [Button.inline("😷 المستخدمون المخفيون", f"maskedUsers_{target_group_id}")],
        # [Button.inline("📣 مجموعة النقاش", f"discussionGroup_{target_group_id}")],
        # [Button.inline("📟 الأوامر الشخصية", b"personal_commands")],
        # [Button.inline("🧙‍♂️ الملصقات والصور المتحركة السحرية", b"magic_stickers_gifs")],
        # [Button.inline("✏️ طول الرسالة", f"messageLength_{target_group_id}")],
        # [Button.inline("📢 إدارة القنوات", b"channels_management")],
        # [Button.inline("⚙️ الصلاحيات", b"permissions"), Button.inline("🔍 قناة السجلات", b"log_channel")],
        
        [
            Button.inline("⬅️ الرجوع", f"showGroupSettings_{target_group_id}"),
            Button.inline("✅ اغلاق", b"delete_this_message"),
            # Button.inline("🇸🇦 اللغة", b"languages"),
        ]
    ]

    await event.respond(ChangeLang_MSG, buttons=buttons)



# Change Language
@bot.on(events.CallbackQuery(data=b"languages"))
async def ChangeLanguage(event):
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    # if event.is_private:
    #     group_ownerID = await find_group_creator(target_group_id, groups_database)

    #     CoFounders, Admins = [], []
    #     if str(group_ownerID) in groups_database:
    #         if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
    #             group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
    #             CoFounders = group_data["co_founders"]
    #             Admins = group_data["admins"]
        
    #     if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
    #         return

    await DeleteEvent(event)
    ChangeLang_MSG = '🇸🇦 اختر لغتك.'
    buttons = [
        [Button.inline("🇸🇦 العربية", b"changeLang_ar")],
        [Button.inline("🔙 الرجوع", b"back_to_setting_menu")]
    ]

    await event.respond(ChangeLang_MSG, buttons=buttons)


# Change Language
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'changeLang_')))
async def ChangeLanguage(event):
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    # if event.is_private:
    #     group_ownerID = await find_group_creator(target_group_id, groups_database)

    #     CoFounders, Admins = [], []
    #     if str(group_ownerID) in groups_database:
    #         if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
    #             group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
    #             CoFounders = group_data["co_founders"]
    #             Admins = group_data["admins"]
        
    #     if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
    #         return
    
    await DeleteEvent(event)
    buttons = [
        [Button.inline("🔙 الرجوع", b"back_to_setting_menu")]
    ]
    await event.respond("حسنًا، من الآن فصاعدًا سأتحدث العربية 🇸🇦", buttons=buttons)


# Show Group Rule
@bot.on(events.NewMessage(pattern="/rules"))
async def GroupRules(event):

    target_group_id = event.chat_id
    if event.is_private:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

    rules_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["text"]
    rules_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["media"]
    rules_urlButtons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["buttons"]
    
    if not rules_text and not rules_media and not rules_urlButtons:
        return

    await DeleteEvent(event)
    row_btn, buttons = [], []
    for row in rules_urlButtons:
        for button in row:
            row_btn.append(Button.url(button.get('text'), button.get('url')))
        buttons.append(row_btn)
        row_btn = []

    msg_text = f'📜 **قوانين المجموعة**\n\n{rules_text}'
    if not buttons:
        buttons = None
    
    await event.respond(msg_text, file=rules_media, buttons=buttons)


# Show Group link
@bot.on(events.NewMessage(pattern="/link"))
async def GroupRules(event):

    target_group_id = event.chat_id
    if event.is_private:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

    is_active = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["link"]["is_active"]
    url = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["link"]["url"]
 
    if is_active:
        msg_text = f'🔗 **رابط المجموعة:** {url}'
        await event.respond(msg_text)
        



####################################################################

# regulation
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"regulation_")))
async def Regulation(event):

    target_group_id = int(str(event.data.decode()).replace('regulation_', ''))
    

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        

    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return


    await DeleteEvent(event)
    MSG = '''
📜 **قوانين المجموعة**

من خلال هذه القائمة، يمكنك إدارة قوانين المجموعة التي ستظهر عند استخدام الأمر /rules.

'''
    # لتعديل من يمكنه استخدام أمر /rules، انتقل إلى قسم "صلاحيات الأوامر".

    buttons = [
        [Button.inline("✍🏻 تخصيص الرسالة", f"customizeMessage_{target_group_id}")],
        [Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")]
    ]

    await event.respond(MSG, buttons=buttons)



# Customize Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"customizeMessage_")))
async def CustomizeMessage(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('customizeMessage_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    rules_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["text"]
    rules_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["media"]
    rules_buttons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["buttons"]
    
    MSG = f'''📜 القوانين

📄 النص {'✅' if rules_text else '❌'}
📸 الميديا {'✅' if rules_media else '❌'}
🔠 الأزرار {'✅' if len(rules_buttons) != 0 else '❌'}

👉🏻 استخدم الأزرار أدناه لاختيار ما تريد تعيينه.
'''

    buttons = [
        [Button.inline("📄 النص", f"editRuleText_{target_group_id}"), Button.inline("👀 عرض", f"showRuleText_{target_group_id}")],
        [Button.inline("📸 الميديا", f"editRuleMedia_{target_group_id}"), Button.inline("👀 عرض", f"showRuleMedia_{target_group_id}")],
        [Button.inline("🔠 الأزرار", f"editRuleUrlButtons_{target_group_id}"), Button.inline("👀 عرض", f"showRuleUrlButtons_{target_group_id}")],
        [Button.inline("👀 عرض كامل", f"showRuleAll_{target_group_id}")],
        [Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")]
    ]

    await event.respond(MSG, buttons=buttons)



# Edit Rule Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editRuleText_")))
async def EditRuleText(event):

    target_group_id = int(str(event.data.decode()).replace('editRuleText_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الرسالة', f'removeRulesText_{target_group_id}')],
                [Button.inline('❌ الغاء', f'cancel_{target_group_id}')]
            ]

            await conv.send_message('''👉🏻 أرسل الآن الرسالة التي تريد تعيينها.''', buttons=buttons)
            the_message = (await conv.get_response()).message

        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["text"] = str(the_message)
        await SaveJsonGroupsData(groups_database)
        await CustomizeMessage(event, target_group_id)

    except Exception as error:pass



# Remove Rule Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeRulesText_")))
async def RemoveRuleText(event):

    target_group_id = int(str(event.data.decode()).replace('removeRulesText_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return


    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["text"] = None
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeMessage(event, group_ID=target_group_id)

    except Exception as error:pass


# Cancel Conversation
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"cancel_")))
async def CancelConversation(event):

    target_group_id = int(str(event.data.decode()).replace('cancel_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeMessage(event, group_ID=target_group_id)

    except Exception as error:pass



# Edit Rule Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editRuleMedia_")))
async def EditRuleMedia(event):

    target_group_id = int(str(event.data.decode()).replace('editRuleMedia_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الميديا', f'removeRulesMedia_{target_group_id}')],
                [Button.inline('❌ Cancel', f'cancel_{target_group_id}')]
            ]

            await conv.send_message('''👉🏻 أرسل الآن الوسائط (الصور، الفيديوهات، الملصقات...) التي تريد تعيينها.''', buttons=buttons)
            the_message = await conv.get_response()

        media_path = await the_message.download_media('rules_media/')

        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["media"] = media_path
        await SaveJsonGroupsData(groups_database)
        await CustomizeMessage(event, target_group_id)

    except Exception as error:pass



# Remove Rules Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeRulesMedia_")))
async def RemoveRulesMedia(event):

    target_group_id = int(str(event.data.decode()).replace('removeRulesMedia_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["media"] = None
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeMessage(event, group_ID=target_group_id)

    except Exception as error:pass



# Edit Rule Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editRuleUrlButtons_")))
async def EditRuleUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('editRuleUrlButtons_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الأزرار', f'removeRulesUrlButtons_{target_group_id}')],
                [Button.inline('❌ Cancel', f'cancel_{target_group_id}')]
            ]

            await conv.send_message('''
👉🏻 الآن أرسل قائمة الأزرار التي تريد إدراجها في لوحة المفاتيح المدمجة، مع النصوص والروابط، باستخدام هذا التنسيق:
                                    
`Button text - link.com`
`Button text - link.net`

• إذا كنت ترغب في تعيين زرين في نفس السطر، افصل بينهما بـ **&&**.  
• عند تعيين القواعد كـ **رابط**، سيؤدي الزر إلى توجيه المستخدمين إلى قواعد المجموعة، إذا تم تعيينها باستخدام البوت.
                                    
مثال:
`Group - https://t.me/username && Channel - google.com`
''', buttons=buttons, link_preview=False)
            the_message = (await conv.get_response()).message

        if not all('-' in line for line in the_message.split('\n') if line.strip()):
            buttons = [[Button.inline('❌ الغاء', f'cancel_{target_group_id}')]]
            await event.respond("تنسيق لوحة المفاتيح المدمجة غير صحيح. حاول مرة أخرى", buttons=buttons)
            return
        
        list_buttons = []
        for line in the_message.split('\n'):
            buttons = []
            for btn in line.split('&&'):
                parts = btn.strip().split(' - ')
                if len(parts) == 2:
                    text, url = parts
                    buttons.append({"text": text.strip(), "url": url.strip()})
            if buttons:
                list_buttons.append(buttons)
        
        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["buttons"] = list_buttons
        
        row_btn, test_buttons = [], []
        for row in list_buttons:
            for button in row:
                row_btn.append(Button.url(button.get('text'), button.get('url')))
            test_buttons.append(row_btn)
            row_btn = []
            
        test_buttons.append([Button.inline("🔙 الرجوع", f"customizeMessage_{target_group_id}")])

        try:
            test_msg = await event.respond('الأزرار الحالية', buttons=test_buttons)
            await DeleteEvent(test_msg)
        
        except Exception as error:
            buttons = [[Button.inline('❌ الغاء', f'cancel_{target_group_id}')]]
            await event.respond("تنسيق لوحة المفاتيح المدمجة غير صحيح. حاول مرة أخرى", buttons=buttons)
            return
        
        await SaveJsonGroupsData(groups_database)
        await CustomizeMessage(event, target_group_id)

    except Exception as error:pass


# Remove Rules Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeRulesUrlButtons_")))
async def RemoveRulesUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('removeRulesUrlButtons_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["buttons"] = []
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeMessage(event, group_ID=target_group_id)

    except Exception as error:pass


# Show Rule Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showRuleText_")))
async def ShowRuleText(event):

    target_group_id = int(str(event.data.decode()).replace('showRuleText_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    buttons = [
        [Button.inline("🔙 الرجوع", f"customizeMessage_{target_group_id}")]
    ]

    rules_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["text"]
    
    if rules_text:
        await DeleteEvent(event)
        await event.respond(rules_text, buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)



# Show Rule Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showRuleMedia_")))
async def ShowRuleMedia(event):

    target_group_id = int(str(event.data.decode()).replace('showRuleMedia_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    buttons = [
        [Button.inline("🔙 الرجوع", f"customizeMessage_{target_group_id}")]
    ]

    rules_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["media"]
    
    if rules_media:
        await DeleteEvent(event)
        await event.respond(file=rules_media, buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)



# Show Rule Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showRuleUrlButtons_")))
async def ShowRuleUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('showRuleUrlButtons_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    rules_urlButtons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["buttons"]
    
    if rules_urlButtons:
        await DeleteEvent(event)
        row_btn, buttons = [], []
        for row in rules_urlButtons:
            for button in row:
                row_btn.append(Button.url(button.get('text'), button.get('url')))
            buttons.append(row_btn)
            row_btn = []
            
        buttons.append([Button.inline("🔙 الرجوع", f"customizeMessage_{target_group_id}")])
        await event.respond('الأزرار الحالية', buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)



# Show Rule All
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showRuleAll_")))
async def ShowRuleAll(event):

    target_group_id = int(str(event.data.decode()).replace('showRuleAll_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    rules_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["text"]
    rules_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["media"]
    rules_urlButtons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["rules"]["buttons"]
    
    if not rules_text and not rules_media and not rules_urlButtons:
        await event.answer('لم تقم بتعيينها بعد', alert=True)
        return

    await DeleteEvent(event)
    row_btn, buttons = [], []
    for row in rules_urlButtons:
        for button in row:
            row_btn.append(Button.url(button.get('text'), button.get('url')))
        buttons.append(row_btn)
        row_btn = []
        
    buttons.append([Button.inline("🔙 الرجوع", f"customizeMessage_{target_group_id}")])
    
    msg_text = f'📜 **قوانين المجموعة**\n\n{rules_text}'
    await event.respond(msg_text, file=rules_media, buttons=buttons)


###############################################################################

# welcome_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"welcome_")))
async def WelcomeMessage(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('welcome_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    welcomeMessageSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]

    MSG = f'''
💬 **رسالة الترحيب**

من خلال هذه القائمة، يمكنك تعيين رسالة ترحيب ستُرسل عندما ينضم شخص إلى المجموعة.

الحالة: {'مفعل ✅' if welcomeMessageSettings['is_active'] else 'معطل  ❌'}
الوضع: إرسال رسالة الترحيب {'في كل مرة ينضم فيها المستخدمون إلى المجموعة' if welcomeMessageSettings['mode'] == 'every_join' else 'فقط عند الانضمام الأول للمستخدم إلى المجموعة'}
'''

    buttons = [
        [
            Button.inline("✖️ ايقاف", f"TurnOffWelcomeMessage_{target_group_id}"),
            Button.inline("✔️ تشغيل", f"TurnOnWelcomeMessage_{target_group_id}")
        ],
        [Button.inline("✍🏻 تخصيص الرسالة", f"customizeWelcomeMessage_{target_group_id}")],
        [
            Button.inline("🔔 إرسال دائمًا", f"Mode1WelcomeMessage_{target_group_id}"),
            Button.inline("1️⃣ إرسال عند الانضمام الأول", f"Mode2WelcomeMessage_{target_group_id}")
        ],
        [Button.inline(f"♻️ حذف الرسالة الأخيرة {'✔️' if welcomeMessageSettings['delete_last_message'] else '✖️'}", f"DeleteWelcomeMessage_{target_group_id}")],
        [Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")]
    ]

    await event.respond(MSG, buttons=buttons)


# Turn Off Welcome Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOffWelcomeMessage_")))
async def TurnOffWelcomeMessage(event):

    target_group_id = int(str(event.data.decode()).replace('TurnOffWelcomeMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    welcomeMessageSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]
    welcomeMessageSettings["is_active"] = False

    await SaveJsonGroupsData(groups_database)
    await WelcomeMessage(event, group_ID=target_group_id)


# Turn On Welcome Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOnWelcomeMessage_")))
async def TurnOnWelcomeMessage(event):

    target_group_id = int(str(event.data.decode()).replace('TurnOnWelcomeMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    welcomeMessageSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]
    welcomeMessageSettings["is_active"] = True

    await SaveJsonGroupsData(groups_database)
    await WelcomeMessage(event, group_ID=target_group_id)


# Delete Welcome Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteWelcomeMessage_")))
async def DeleteWelcomeMessage(event):

    target_group_id = int(str(event.data.decode()).replace('DeleteWelcomeMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    welcomeMessageSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]
    welcomeMessageSettings["delete_last_message"] = not welcomeMessageSettings["delete_last_message"]

    await SaveJsonGroupsData(groups_database)
    await WelcomeMessage(event, group_ID=target_group_id)


# Mode Welcome Message - every_join
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"Mode1WelcomeMessage_")))
async def Mode1WelcomeMessage(event):

    target_group_id = int(str(event.data.decode()).replace('Mode1WelcomeMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    welcomeMessageSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]
    welcomeMessageSettings["mode"] = 'every_join'

    await SaveJsonGroupsData(groups_database)
    await WelcomeMessage(event, group_ID=target_group_id)


# Mode Welcome Message - first_join
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"Mode2WelcomeMessage_")))
async def Mode2WelcomeMessage(event):

    target_group_id = int(str(event.data.decode()).replace('Mode2WelcomeMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    welcomeMessageSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]
    welcomeMessageSettings["mode"] = 'first_join'

    await SaveJsonGroupsData(groups_database)
    await WelcomeMessage(event, group_ID=target_group_id)


# Customize Welcome Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"customizeWelcomeMessage_")))
async def CustomizeWelcomeMessage(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('customizeWelcomeMessage_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    WelcomeMessage_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["text"]
    WelcomeMessage_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["media"]
    WelcomeMessage_buttons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["buttons"]
    
    MSG = f'''💬 **رسالة الترحيب**

📄 النص {'✅' if WelcomeMessage_text else '❌'}
📸 الميديا {'✅' if WelcomeMessage_media else '❌'}
🔠 الأزرار {'✅' if len(WelcomeMessage_buttons) != 0 else '❌'}

👉🏻 استخدم الأزرار أدناه لاختيار ما تريد تعيينه.
'''

    buttons = [
        [Button.inline("📄 النص", f"editWelcomeMessageText_{target_group_id}"), Button.inline("👀 عرض", f"showWelcomeMessageText_{target_group_id}")],
        [Button.inline("📸 الميديا", f"editWelcomeMessageMedia_{target_group_id}"), Button.inline("👀 عرض", f"showWelcomeMessageMedia_{target_group_id}")],
        [Button.inline("🔠 الأزرار", f"editWelcomeMessageUrlButtons_{target_group_id}"), Button.inline("👀 عرض", f"showWelcomeMessageUrlButtons_{target_group_id}")],
        [Button.inline("👀 عرض كامل", f"showWelcomeMessageAll_{target_group_id}")],
        [Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")]
    ]

    await event.respond(MSG, buttons=buttons)


# Edit Welcome Message Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editWelcomeMessageText_")))
async def EditWelcomeMessageText(event):

    target_group_id = int(str(event.data.decode()).replace('editWelcomeMessageText_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الرسالة', f'removeWelcomeMessageText_{target_group_id}')],
                [Button.inline('❌ الغاء', f'cancel2_{target_group_id}')]
            ]

            await conv.send_message('''👉🏻 أرسل الآن الرسالة التي تريد تعيينها.''', buttons=buttons)
            the_message = (await conv.get_response()).message

        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["text"] = str(the_message)
        await SaveJsonGroupsData(groups_database)
        await CustomizeWelcomeMessage(event, target_group_id)

    except Exception as error:pass


# Remove Welcome Message Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeWelcomeMessageText_")))
async def RemoveWelcomeMessageText(event):

    target_group_id = int(str(event.data.decode()).replace('removeWelcomeMessageText_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["text"] = None
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeWelcomeMessage(event, group_ID=target_group_id)

    except Exception as error:pass


# Cancel Conversation 2
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"cancel2_")))
async def CancelConversation2(event):

    target_group_id = int(str(event.data.decode()).replace('cancel2_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeWelcomeMessage(event, group_ID=target_group_id)

    except Exception as error:pass



# Edit Welcome Message Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editWelcomeMessageMedia_")))
async def EditWelcomeMessageMedia(event):

    target_group_id = int(str(event.data.decode()).replace('editWelcomeMessageMedia_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الميديا', f'removeWelcomeMessageMedia_{target_group_id}')],
                [Button.inline('❌ الغاء', f'cancel2_{target_group_id}')]
            ]

            await conv.send_message('''👉🏻 أرسل الآن الوسائط (الصور، الفيديوهات، الملصقات...) التي تريد تعيينها.''', buttons=buttons)
            the_message = await conv.get_response()

        media_path = await the_message.download_media('welcomeMessage_media/')

        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["media"] = media_path
        await SaveJsonGroupsData(groups_database)
        await CustomizeWelcomeMessage(event, target_group_id)

    except Exception as error:pass


# Remove Welcome Message Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeWelcomeMessageMedia_")))
async def RemoveWelcomeMessageMedia(event):

    target_group_id = int(str(event.data.decode()).replace('removeWelcomeMessageMedia_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["media"] = None
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeWelcomeMessage(event, group_ID=target_group_id)

    except Exception as error:pass


# Edit Welcome Message Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editWelcomeMessageUrlButtons_")))
async def EditWelcomeMessageUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('editWelcomeMessageUrlButtons_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الأزرار', f'removeWelcomeMessageUrlButtons_{target_group_id}')],
                [Button.inline('❌ الغاء', f'cancel2_{target_group_id}')]
            ]

            await conv.send_message('''
👉🏻 الآن أرسل قائمة الأزرار التي تريد إدراجها في لوحة المفاتيح المدمجة، مع النصوص والروابط، باستخدام هذا التنسيق:

`Button text - link.com`
`Button text - link.net`

• إذا كنت ترغب في تعيين زرين في نفس السطر، افصل بينهما بـ &&.
• عند تعيين القواعد كـ رابط، سيؤدي الزر إلى توجيه المستخدمين إلى قواعد المجموعة، إذا تم تعيينها باستخدام البوت.
                                    
مثال:
`Group - https://t.me/username && Channel - google.com`
''', buttons=buttons, link_preview=False)
            the_message = (await conv.get_response()).message

        if not all('-' in line for line in the_message.split('\n') if line.strip()):
            buttons = [[Button.inline('❌ الغاء', f'cancel2_{target_group_id}')]]
            await event.respond("تنسيق لوحة المفاتيح المدمجة غير صحيح. حاول مرة أخرى.", buttons=buttons)
            return
        
        list_buttons = []
        for line in the_message.split('\n'):
            buttons = []
            for btn in line.split('&&'):
                parts = btn.strip().split(' - ')
                if len(parts) == 2:
                    text, url = parts
                    buttons.append({"text": text.strip(), "url": url.strip()})
            if buttons:
                list_buttons.append(buttons)
        
        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["buttons"] = list_buttons
        
        row_btn, test_buttons = [], []
        for row in list_buttons:
            for button in row:
                row_btn.append(Button.url(button.get('text'), button.get('url')))
            test_buttons.append(row_btn)
            row_btn = []
            
        test_buttons.append([Button.inline("🔙 الرجوع", f"customizeWelcomeMessage_{target_group_id}")])

        try:
            test_msg = await event.respond('الأزرار المضافة حاليا', buttons=test_buttons)
            await DeleteEvent(test_msg)
        
        except Exception as error:
            buttons = [[Button.inline('❌ الغاء', f'cancel2_{target_group_id}')]]
            await event.respond("تنسيق لوحة المفاتيح المدمجة غير صحيح. حاول مرة أخرى.", buttons=buttons)
            return
        
        await SaveJsonGroupsData(groups_database)
        await CustomizeWelcomeMessage(event, target_group_id)

    except Exception as error:pass


# Remove Welcome Message Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeWelcomeMessageUrlButtons_")))
async def RemoveWelcomeMessageUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('removeWelcomeMessageUrlButtons_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["buttons"] = []
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeWelcomeMessage(event, group_ID=target_group_id)

    except Exception as error:pass


# Show Welcome Message Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showWelcomeMessageText_")))
async def ShowWelcomeMessageText(event):

    target_group_id = int(str(event.data.decode()).replace('showWelcomeMessageText_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    buttons = [
        [Button.inline("🔙 الرجوع", f"customizeWelcomeMessage_{target_group_id}")]
    ]

    welcomeMessage_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["text"]
    
    if welcomeMessage_text:
        await DeleteEvent(event)
        await event.respond(welcomeMessage_text, buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)



# Show Welcome Message Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showWelcomeMessageMedia_")))
async def ShowWelcomeMessageMedia(event):

    target_group_id = int(str(event.data.decode()).replace('showWelcomeMessageMedia_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    buttons = [
        [Button.inline("🔙 الرجوع", f"customizeWelcomeMessage_{target_group_id}")]
    ]

    WelcomeMessage_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["media"]
    
    if WelcomeMessage_media:
        await DeleteEvent(event)
        await event.respond(file=WelcomeMessage_media, buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)


# Show Welcome Message Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showWelcomeMessageUrlButtons_")))
async def ShowWelcomeMessageUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('showWelcomeMessageUrlButtons_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    WelcomeMessage_urlButtons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["buttons"]
    
    if WelcomeMessage_urlButtons:
        await DeleteEvent(event)
        row_btn, buttons = [], []
        for row in WelcomeMessage_urlButtons:
            for button in row:
                row_btn.append(Button.url(button.get('text'), button.get('url')))
            buttons.append(row_btn)
            row_btn = []
            
        buttons.append([Button.inline("🔙 الرجوع", f"customizeWelcomeMessage_{target_group_id}")])
        await event.respond('الأزرار المضافة حاليا', buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)



# Show Welcome Message All
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showWelcomeMessageAll_")))
async def ShowWelcomeMessageAll(event):

    target_group_id = int(str(event.data.decode()).replace('showWelcomeMessageAll_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    welcomeMessage_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["text"]
    welcomeMessage_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["media"]
    welcomeMessage_urlButtons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["welcome_message"]["buttons"]
    
    if not welcomeMessage_text and not welcomeMessage_media and not welcomeMessage_urlButtons:
        await event.answer('لم تقم بتعيينها بعد', alert=True)
        return

    await DeleteEvent(event)
    row_btn, buttons = [], []
    for row in welcomeMessage_urlButtons:
        for button in row:
            row_btn.append(Button.url(button.get('text'), button.get('url')))
        buttons.append(row_btn)
        row_btn = []
        
    buttons.append([Button.inline("🔙 الرجوع", f"customizeWelcomeMessage_{target_group_id}")])
    
    msg_text = f'💬 **رسالة الترحيب**\n\n{welcomeMessage_text}'
    await event.respond(msg_text, file=welcomeMessage_media, buttons=buttons)


###############################################################################

# goodbye_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"goodbye_")))
async def GoodbyeMessage(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('goodbye_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    GoodbyeMessageSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]

    MSG = f'''
👋🏻 **رسالة الوداع**

من خلال هذه القائمة، يمكنك تعيين رسالة وداع ستُرسل عندما يغادر شخص ما المجموعة.

{'⚠️ الرسالة ستُرسل فقط للمستخدمين الذين بدأوا هذا البوت في الدردشة الخاصة.' if GoodbyeMessageSettings['send_in_private'] else ''}

الحالة: {'مفعل ✅' if GoodbyeMessageSettings['is_active'] else 'معطل  ❌'}
'''

    buttons = [
        [
            Button.inline("✖️ ايقاف", f"TurnOffGoodbyeMessage_{target_group_id}"),
            Button.inline("✔️ تشغيل", f"TurnOnGoodbyeMessage_{target_group_id}")
        ],
        [Button.inline("✍🏻 تخصيص الرسالة", f"customizeGoodbyeMessage_{target_group_id}")],
        [Button.inline(f"💌 إرسال في الدردشة الخاصة {'✔️' if GoodbyeMessageSettings['send_in_private'] else '✖️'}", f"SetPrivateGoodbyeMessage_{target_group_id}")],
        [Button.inline(f"♻️ حذف الرسالة الأخيرة {'✔️' if GoodbyeMessageSettings['delete_last_message'] else '✖️'}", f"DeleteGoodbyeMessage_{target_group_id}")],
        [Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")]
    ]

    await event.respond(MSG, buttons=buttons)


# Turn Off Goodbye Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOffGoodbyeMessage_")))
async def TurnOffGoodbyeMessage(event):

    target_group_id = int(str(event.data.decode()).replace('TurnOffGoodbyeMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    GoodbyeMessageSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]
    GoodbyeMessageSettings["is_active"] = False

    await SaveJsonGroupsData(groups_database)
    await GoodbyeMessage(event, group_ID=target_group_id)


# Turn On Goodbye Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOnGoodbyeMessage_")))
async def TurnOnGoodbyeMessage(event):

    target_group_id = int(str(event.data.decode()).replace('TurnOnGoodbyeMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    GoodbyeMessageSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]
    GoodbyeMessageSettings["is_active"] = True

    await SaveJsonGroupsData(groups_database)
    await GoodbyeMessage(event, group_ID=target_group_id)


# Delete Goodbye Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteGoodbyeMessage_")))
async def DeleteGoodbyeMessage(event):

    target_group_id = int(str(event.data.decode()).replace('DeleteGoodbyeMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    GoodbyeMessageSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]
    GoodbyeMessageSettings["delete_last_message"] = not GoodbyeMessageSettings["delete_last_message"]

    await SaveJsonGroupsData(groups_database)
    await GoodbyeMessage(event, group_ID=target_group_id)


# Set Private Goodbye Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"SetPrivateGoodbyeMessage_")))
async def SetPrivateGoodbyeMessage(event):

    target_group_id = int(str(event.data.decode()).replace('SetPrivateGoodbyeMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    GoodbyeMessageSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]
    GoodbyeMessageSettings["send_in_private"] = not GoodbyeMessageSettings["send_in_private"]

    await SaveJsonGroupsData(groups_database)
    await GoodbyeMessage(event, group_ID=target_group_id)


# Customize Goodbye Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"customizeGoodbyeMessage_")))
async def CustomizeGoodbyeMessage(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('customizeGoodbyeMessage_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    GoodbyeMessage_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["text"]
    GoodbyeMessage_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["media"]
    GoodbyeMessage_buttons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["buttons"]
    
    MSG = f'''👋🏻 **رسالة الوداع**

📄 النص {'✅' if GoodbyeMessage_text else '❌'}
📸 الميديا {'✅' if GoodbyeMessage_media else '❌'}
🔠 الأزرار {'✅' if len(GoodbyeMessage_buttons) != 0 else '❌'}

👉🏻 استخدم الأزرار أدناه لاختيار ما تريد تعيينه.
'''

    buttons = [
        [Button.inline("📄 النص", f"editGoodbyeMessageText_{target_group_id}"), Button.inline("👀 عرض", f"showGoodbyeMessageText_{target_group_id}")],
        [Button.inline("📸 الميديا", f"editGoodbyeMessageMedia_{target_group_id}"), Button.inline("👀 عرض", f"showGoodbyeMessageMedia_{target_group_id}")],
        [Button.inline("🔠 الأزرار", f"editGoodbyeMessageUrlButtons_{target_group_id}"), Button.inline("👀 عرض", f"showGoodbyeMessageUrlButtons_{target_group_id}")],
        [Button.inline("👀 عرض كامل", f"showGoodbyeMessageAll_{target_group_id}")],
        [Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")]
    ]

    await event.respond(MSG, buttons=buttons)


# Edit Goodbye Message Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editGoodbyeMessageText_")))
async def EditGoodbyeMessageText(event):

    target_group_id = int(str(event.data.decode()).replace('editGoodbyeMessageText_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الرسالة', f'removeGoodbyeMessageText_{target_group_id}')],
                [Button.inline('❌ الغاء', f'cancel3_{target_group_id}')]
            ]

            await conv.send_message('''👉🏻 أرسل الآن الرسالة التي تريد تعيينها.''', buttons=buttons)
            the_message = (await conv.get_response()).message

        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["text"] = str(the_message)
        await SaveJsonGroupsData(groups_database)
        await CustomizeGoodbyeMessage(event, target_group_id)

    except Exception as error:pass


# Remove Goodbye Message Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeGoodbyeMessageText_")))
async def RemoveGoodbyeMessageText(event):

    target_group_id = int(str(event.data.decode()).replace('removeGoodbyeMessageText_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["text"] = None
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeGoodbyeMessage(event, group_ID=target_group_id)

    except Exception as error:pass


# Cancel Conversation 3
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"cancel3_")))
async def CancelConversation3(event):

    target_group_id = int(str(event.data.decode()).replace('cancel3_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeGoodbyeMessage(event, group_ID=target_group_id)

    except Exception as error:pass


# Edit Goodbye Message Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editGoodbyeMessageMedia_")))
async def EditGoodbyeMessageMedia(event):

    target_group_id = int(str(event.data.decode()).replace('editGoodbyeMessageMedia_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الميديا', f'removeGoodbyeMessageMedia_{target_group_id}')],
                [Button.inline('❌ الغاء', f'cancel3_{target_group_id}')]
            ]

            await conv.send_message('''👉🏻 أرسل الآن الوسائط (الصور، الفيديوهات، الملصقات...) التي تريد تعيينها.''', buttons=buttons)
            the_message = await conv.get_response()

        media_path = await the_message.download_media('GoodbyeMessage_media/')

        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["media"] = media_path
        await SaveJsonGroupsData(groups_database)
        await CustomizeGoodbyeMessage(event, target_group_id)

    except Exception as error:pass


# Remove Goodbye Message Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeGoodbyeMessageMedia_")))
async def RemoveGoodbyeMessageMedia(event):

    target_group_id = int(str(event.data.decode()).replace('removeGoodbyeMessageMedia_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["media"] = None
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeGoodbyeMessage(event, group_ID=target_group_id)

    except Exception as error:pass


# Edit Goodbye Message Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editGoodbyeMessageUrlButtons_")))
async def EditGoodbyeMessageUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('editGoodbyeMessageUrlButtons_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الأزرار', f'removeGoodbyeMessageUrlButtons_{target_group_id}')],
                [Button.inline('❌ الغاء', f'cancel3_{target_group_id}')]
            ]

            await conv.send_message('''
👉🏻 الآن أرسل قائمة الأزرار التي تريد إدراجها في لوحة المفاتيح المدمجة، مع النصوص والروابط، باستخدام هذا التنسيق:

`Button text - link.com`
`Button text - link.net`

• إذا كنت ترغب في تعيين زرين في نفس السطر، افصل بينهما بـ **&&**.  
• عند تعيين القواعد كـ **رابط**، سيؤدي الزر إلى توجيه المستخدمين إلى قواعد المجموعة، إذا تم تعيينها باستخدام البوت.

مثال:
`Group - https://t.me/username && Channel - google.com`
''', buttons=buttons, link_preview=False)
            the_message = (await conv.get_response()).message

        if not all('-' in line for line in the_message.split('\n') if line.strip()):
            buttons = [[Button.inline('❌ الغاء', f'cancel3_{target_group_id}')]]
            await event.respond("تنسيق لوحة المفاتيح المدمجة غير صحيح. حاول مرة أخرى.", buttons=buttons)
            return
        
        list_buttons = []
        for line in the_message.split('\n'):
            buttons = []
            for btn in line.split('&&'):
                parts = btn.strip().split(' - ')
                if len(parts) == 2:
                    text, url = parts
                    buttons.append({"text": text.strip(), "url": url.strip()})
            if buttons:
                list_buttons.append(buttons)
        
        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["buttons"] = list_buttons
        
        row_btn, test_buttons = [], []
        for row in list_buttons:
            for button in row:
                row_btn.append(Button.url(button.get('text'), button.get('url')))
            test_buttons.append(row_btn)
            row_btn = []
            
        test_buttons.append([Button.inline("🔙 الرجوع", f"customizeGoodbyeMessage_{target_group_id}")])

        try:
            test_msg = await event.respond('الأزرار المضافة حاليا', buttons=test_buttons)
            await DeleteEvent(test_msg)
        
        except Exception as error:
            buttons = [[Button.inline('❌ الغاء', f'cancel3_{target_group_id}')]]
            await event.respond("تنسيق لوحة المفاتيح المدمجة غير صحيح. حاول مرة أخرى.", buttons=buttons)
            return
        
        await SaveJsonGroupsData(groups_database)
        await CustomizeGoodbyeMessage(event, target_group_id)

    except Exception as error:pass


# Remove Goodbye Message Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeGoodbyeMessageUrlButtons_")))
async def RemoveGoodbyeMessageUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('removeGoodbyeMessageUrlButtons_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["buttons"] = []
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeGoodbyeMessage(event, group_ID=target_group_id)

    except Exception as error:pass


# Show Goodbye Message Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showGoodbyeMessageText_")))
async def ShowGoodbyeMessageText(event):

    target_group_id = int(str(event.data.decode()).replace('showGoodbyeMessageText_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    buttons = [
        [Button.inline("🔙 الرجوع", f"customizeGoodbyeMessage_{target_group_id}")]
    ]

    GoodbyeMessage_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["text"]
    
    if GoodbyeMessage_text:
        await DeleteEvent(event)
        await event.respond(GoodbyeMessage_text, buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)


# Show Goodbye Message Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showGoodbyeMessageMedia_")))
async def ShowGoodbyeMessageMedia(event):

    target_group_id = int(str(event.data.decode()).replace('showGoodbyeMessageMedia_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    buttons = [
        [Button.inline("🔙 الرجوع", f"customizeGoodbyeMessage_{target_group_id}")]
    ]

    GoodbyeMessage_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["media"]
    
    if GoodbyeMessage_media:
        await DeleteEvent(event)
        await event.respond(file=GoodbyeMessage_media, buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)


# Show Goodbye Message Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showGoodbyeMessageUrlButtons_")))
async def ShowGoodbyeMessageUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('showGoodbyeMessageUrlButtons_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    GoodbyeMessage_urlButtons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["buttons"]
    
    if GoodbyeMessage_urlButtons:
        await DeleteEvent(event)
        row_btn, buttons = [], []
        for row in GoodbyeMessage_urlButtons:
            for button in row:
                row_btn.append(Button.url(button.get('text'), button.get('url')))
            buttons.append(row_btn)
            row_btn = []
            
        buttons.append([Button.inline("🔙 الرجوع", f"customizeGoodbyeMessage_{target_group_id}")])
        await event.respond('الأزرار المضافة حاليا', buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)


# Show Goodbye Message All
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showGoodbyeMessageAll_")))
async def ShowGoodbyeMessageAll(event):

    target_group_id = int(str(event.data.decode()).replace('showGoodbyeMessageAll_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    GoodbyeMessage_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["text"]
    GoodbyeMessage_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["media"]
    GoodbyeMessage_urlButtons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["goodbye_message"]["buttons"]
    
    if not GoodbyeMessage_text and not GoodbyeMessage_media and not GoodbyeMessage_urlButtons:
        await event.answer('لم تقم بتعيينها بعد', alert=True)
        return

    await DeleteEvent(event)
    row_btn, buttons = [], []
    for row in GoodbyeMessage_urlButtons:
        for button in row:
            row_btn.append(Button.url(button.get('text'), button.get('url')))
        buttons.append(row_btn)
        row_btn = []
        
    buttons.append([Button.inline("🔙 الرجوع", f"customizeGoodbyeMessage_{target_group_id}")])
    
    msg_text = f'👋🏻 **رسالة الوداع**\n\n{GoodbyeMessage_text}'
    await event.respond(msg_text, file=GoodbyeMessage_media, buttons=buttons)



###############################################################################

# captcha_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"captcha_")))
async def Captcha(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('captcha_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
    
    MSG = f'''
🧠 **التحقق البشري** (Captcha)

عند تفعيل التحقق البشري، لن يتمكن المستخدم من إرسال الرسائل عندما يدخل المجموعة حتى يؤكد أنه ليس روبوتًا.

🕑 يمكنك أيضًا تحديد عقوبة أدناه لأولئك الذين لم يحلوا التحقق في الوقت المحدد، وإذا كنت ترغب في مسح رسالة الخدمة في حالة الفشل.

الحالة: {'مفعل ✅' if CaptchaSettings['is_active'] else 'معطل  ❌'}
'''
    
    if CaptchaSettings['is_active']:
        MSG += f'''🕒 الوقت: {CaptchaSettings['timer']} دقائق
⛔️ العقاب: {CaptchaSettings['penalty']}
🗂 الوضع: {CaptchaSettings['mode']}
🗑 حذف رسالة الخدمة: {'نعم' if CaptchaSettings['delete_service_message'] else 'لا'}
'''
    #  └ {CaptchaSettings['captcha_modes'][CaptchaSettings['mode']]['description']}

    button_text = '✅ تشغيل' if not CaptchaSettings['is_active'] else '❌ ايقاف ❌'

    buttons = [
        [Button.inline(button_text, f"TurnOffCaptcha_{target_group_id}")]
    ]

    if CaptchaSettings['is_active']:
        buttons.append([Button.inline("🗂 الوضع 🗂", f"OpenModeCaptch_{target_group_id}")])
        if CaptchaSettings['mode_open']:
            buttons.append([Button.inline("✅ زر تحقق", f"captcha_{target_group_id}")])

        buttons.append([Button.inline("🕔 الوقت 🕔", f"OpenTimerCaptch_{target_group_id}")])
        if CaptchaSettings['timer_open']:
            buttons.append([
                Button.inline(f"1 {'✅' if CaptchaSettings['timer'] == 1 else ''}", f"setCaptchaTimer_1_{target_group_id}"),
                Button.inline(f"2 {'✅' if CaptchaSettings['timer'] == 2 else ''}", f"setCaptchaTimer_2_{target_group_id}"),
                Button.inline(f"3 {'✅' if CaptchaSettings['timer'] == 3 else ''}", f"setCaptchaTimer_3_{target_group_id}"),
                Button.inline(f"5 {'✅' if CaptchaSettings['timer'] == 5 else ''}", f"setCaptchaTimer_5_{target_group_id}")
            ])
            buttons.append([
                Button.inline(f"10 {'✅' if CaptchaSettings['timer'] == 10 else ''}", f"setCaptchaTimer_10_{target_group_id}"),
                Button.inline(f"15 {'✅' if CaptchaSettings['timer'] == 15 else ''}", f"setCaptchaTimer_15_{target_group_id}"),
                Button.inline(f"20 {'✅' if CaptchaSettings['timer'] == 20 else ''}", f"setCaptchaTimer_20_{target_group_id}"),
                Button.inline(f"30 {'✅' if CaptchaSettings['timer'] == 30 else ''}", f"setCaptchaTimer_30_{target_group_id}")
            ])

        buttons.append([Button.inline("⛔️ العقاب ⛔️", f"OpenPenaltyCaptch_{target_group_id}")])
        if CaptchaSettings['penalty_open']:
            buttons.append([
                Button.inline(f"🚷 حظر {'✅' if CaptchaSettings['penalty'] == 'Ban' else ''}", f"setCaptchaPenalty_Ban_{target_group_id}")
            ])
            buttons.append([
                Button.inline(f"🔇 كتم {'✅' if CaptchaSettings['penalty'] == 'Mute' else ''}", f"setCaptchaPenalty_Mute_{target_group_id}"),
                Button.inline(f"❗️ طرد {'✅' if CaptchaSettings['penalty'] == 'Kick' else ''}", f"setCaptchaPenalty_Kick_{target_group_id}")
            ])

        buttons.append([Button.inline("✍🏻 تخصيص الرسالة ✍🏻", f"OpenEditMsgCaptch_{target_group_id}")])
        if CaptchaSettings['editMessage_open']:
            buttons.append([
                Button.inline("📄 النص", f"editTextCaptchaMessage_{target_group_id}"),
                Button.inline("👀 عرض", f"showTextCaptchaMessage_{target_group_id}")
            ])
            buttons.append([
                Button.inline("🔤 نص الزر", f"editButtonTextCaptchaMessage_{target_group_id}"),
                Button.inline("👀 عرض", f"showButtonTextCaptchaMessage_{target_group_id}")
            ])
        
        buttons.append([Button.inline(f"🗑 حذف رسالة الخدمة {'✔️' if CaptchaSettings['delete_service_message'] else '✖️'}", f"DeleteCaptchaServiceMessage_{target_group_id}")])

 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)



# Open Edit Message Captcha
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"OpenEditMsgCaptch_")))
async def OpenEditMsgCaptch(event):

    target_group_id = int(str(event.data.decode()).replace('OpenEditMsgCaptch_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
    CaptchaSettings["editMessage_open"] = not CaptchaSettings["editMessage_open"]

    await SaveJsonGroupsData(groups_database)
    await Captcha(event, group_ID=target_group_id)


# Open Penalty Captcha
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"OpenPenaltyCaptch_")))
async def OpenPenaltyCaptch(event):

    target_group_id = int(str(event.data.decode()).replace('OpenPenaltyCaptch_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
    CaptchaSettings["penalty_open"] = not CaptchaSettings["penalty_open"]

    await SaveJsonGroupsData(groups_database)
    await Captcha(event, group_ID=target_group_id)


# Open Timer Captcha
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"OpenTimerCaptch_")))
async def OpenTimerCaptch(event):

    target_group_id = int(str(event.data.decode()).replace('OpenTimerCaptch_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
    CaptchaSettings["timer_open"] = not CaptchaSettings["timer_open"]

    await SaveJsonGroupsData(groups_database)
    await Captcha(event, group_ID=target_group_id)


# Open Mode Captcha
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"OpenModeCaptch_")))
async def OpenModeCaptch(event):

    target_group_id = int(str(event.data.decode()).replace('OpenModeCaptch_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
    CaptchaSettings["mode_open"] = not CaptchaSettings["mode_open"]

    await SaveJsonGroupsData(groups_database)
    await Captcha(event, group_ID=target_group_id)


# Turn Off Captcha
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOffCaptcha_")))
async def TurnOffCaptcha(event):

    target_group_id = int(str(event.data.decode()).replace('TurnOffCaptcha_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
    CaptchaSettings["is_active"] = not CaptchaSettings["is_active"]

    await SaveJsonGroupsData(groups_database)
    await Captcha(event, group_ID=target_group_id)


# Set Captcha Timer
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setCaptchaTimer_")))
async def setCaptchaTimer(event):

    new_timer, target_group_id = (str(event.data.decode()).replace('setCaptchaTimer_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
    CaptchaSettings["timer"] = int(new_timer)

    await SaveJsonGroupsData(groups_database)
    await Captcha(event, group_ID=target_group_id)


# Set Captcha Penelty
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setCaptchaPenalty_")))
async def SetCaptchaPenalty(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setCaptchaPenalty_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
    CaptchaSettings["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await Captcha(event, group_ID=target_group_id)


# Delete Captcha Service Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteCaptchaServiceMessage_")))
async def DeleteCaptchaServiceMessage(event):

    target_group_id = int(str(event.data.decode()).replace('DeleteCaptchaServiceMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
    CaptchaSettings["delete_service_message"] = not CaptchaSettings["delete_service_message"]

    await SaveJsonGroupsData(groups_database)
    await Captcha(event, group_ID=target_group_id)



# Edit Text Captcha Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editTextCaptchaMessage_")))
async def EditTextCaptchaMessage(event):

    target_group_id = int(str(event.data.decode()).replace('editTextCaptchaMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('❌ الغاء', f'cancel4_{target_group_id}')]
            ]

            await conv.send_message('''
أرسل الآن الرسالة الخاصة بالتحقق البشري (Captcha)!

يمكنك استخدام:
• {MENTION} = رابط إلى ملف المستخدم الشخصي 
• {TIMER} = الوقت المحدد للتحقق

👇🏻 أرسل الرسالة التي تريد تعيينها للتحقق البشري.
''', buttons=buttons)
            the_message = (await conv.get_response()).message

        if the_message != '':
            CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
            CaptchaSettings["captcha_modes"][CaptchaSettings["mode"]]["text"] = str(the_message) # set text for a current mode

            await SaveJsonGroupsData(groups_database)

        await Captcha(event, target_group_id)

    except Exception as error:pass


# Edit Button Text Captcha Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editButtonTextCaptchaMessage_")))
async def EditButtonTextCaptchaMessage(event):

    target_group_id = int(str(event.data.decode()).replace('editButtonTextCaptchaMessage_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('❌ الغاء', f'cancel4_{target_group_id}')]
            ]

            await conv.send_message('''
🧠 **التحقق البشري** (Captcha)

👉🏻 أرسل الآن النص الذي سيظهر على الزر الذي يجب على المستخدمين الضغط عليه لحل التحقق البشري.
''', buttons=buttons)
            the_message = (await conv.get_response()).message

        if the_message != '':
            CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
            CaptchaSettings["captcha_modes"][CaptchaSettings["mode"]]["button_text"] = str(the_message) # set button text for a current mode

            await SaveJsonGroupsData(groups_database)
        
        await Captcha(event, target_group_id)

    except Exception as error:pass


# Cancel Conversation 4
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"cancel4_")))
async def CancelConversation4(event):

    target_group_id = int(str(event.data.decode()).replace('cancel4_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await Captcha(event, group_ID=target_group_id)

    except Exception as error:pass


# Show Text Captcha Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showTextCaptchaMessage_")))
async def showTextCaptchaMessage(event):

    target_group_id = int(str(event.data.decode()).replace('showTextCaptchaMessage_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    buttons = [
        [Button.inline("🔙 الرجوع", f"captcha_{target_group_id}")]
    ]

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
    CaptchaText = CaptchaSettings["captcha_modes"][CaptchaSettings["mode"]]["text"]
    
    if CaptchaText:
        await DeleteEvent(event)
        await event.respond(CaptchaText, buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)



# Show Button Text Captcha Message
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showButtonTextCaptchaMessage_")))
async def ShowButtonTextCaptchaMessage(event):

    target_group_id = int(str(event.data.decode()).replace('showButtonTextCaptchaMessage_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    buttons = [
        [Button.inline("🔙 الرجوع", f"captcha_{target_group_id}")]
    ]

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["captcha"]
    CaptchaText = CaptchaSettings["captcha_modes"][CaptchaSettings["mode"]]["button_text"]
    
    if CaptchaText:
        await DeleteEvent(event)
        await event.respond(CaptchaText, buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)


# verify captcha - user request unmute
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b'VerifyCaptcha_')))
async def UserRequestVerifyCaptcha(event):
    
    user_id, target_group_id = (str(event.data.decode()).replace('VerifyCaptcha_', '')).split('_')
    
    if event.sender_id == int(user_id):
        if str(user_id) in groups_manager["pending_verify"]:
            await bot.edit_permissions(int(target_group_id), int(user_id), send_messages=True)

            del groups_manager["pending_verify"][str(user_id)]
            await SaveJsonGroupsManager(groups_manager)

            await event.answer('✅ أحسنت، لقد حللت التحقق البشري بنجاح، يمكنك الآن الكتابة في المجموعة.', alert=True)

            await DeleteEvent(event)



#############################################################################
 
# admin_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"admin_")))
async def AdminTag(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('admin_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    AdminTagSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["adminTag"]

    MSG = f'''
🆘 **أمر @admin**

@admin هو أمر متاح للمستخدمين لجذب انتباه موظفي المجموعة، على سبيل المثال إذا كان أحد المستخدمين لا يحترم قواعد المجموعة.

من خلال هذه القائمة، يمكنك تعيين المكان الذي تريد أن تُرسل إليه التقارير التي يقدمها المستخدمون

إرسال إلى: {AdminTagSettings["send_to"]}
'''
    
    buttons = [
        [
            Button.inline("✖️ لا أحد", f"NobodyAdminTag_{target_group_id}"),
            Button.inline("👑 المؤسس", f"FounderAdminTag_{target_group_id}")
        ],
        [Button.inline("👥 طاقم المجموعة", f"StaffGroupAdminTag_{target_group_id}")],
        # [Button.inline(f"🔔 وضع إشارة على المؤسس {'✅' if AdminTagSettings['tag_founder'] else '❌'}", f"setTagFounderAdminTag_{target_group_id}")],
        # [Button.inline(f"🔔 Tag Admins {'✅' if AdminTagSettings['tag_admins'] else '❌'}", f"setTagAdminsAdminTag_{target_group_id}")]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Nobody Admin Tag
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"NobodyAdminTag_")))
async def NobodyAdminTag(event):

    target_group_id = int(str(event.data.decode()).replace('NobodyAdminTag_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AdminTagSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["adminTag"]
    AdminTagSettings["send_to"] = "✖️ NoBody"

    await SaveJsonGroupsData(groups_database)
    await AdminTag(event, group_ID=target_group_id)


# Founder Admin Tag
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"FounderAdminTag_")))
async def FounderAdminTag(event):

    target_group_id = int(str(event.data.decode()).replace('FounderAdminTag_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AdminTagSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["adminTag"]
    AdminTagSettings["send_to"] = "👑 Founder"

    await SaveJsonGroupsData(groups_database)
    await AdminTag(event, group_ID=target_group_id)


# Staff Group Admin Tag
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"StaffGroupAdminTag_")))
async def StaffGroupAdminTag(event):

    target_group_id = int(str(event.data.decode()).replace('StaffGroupAdminTag_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AdminTagSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["adminTag"]
    AdminTagSettings["send_to"] = "👥 Staff Group"

    await SaveJsonGroupsData(groups_database)
    await AdminTag(event, group_ID=target_group_id)


# Set Tag Founder Admin Tag
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setTagFounderAdminTag_")))
async def SetTagFounderAdminTag(event):

    target_group_id = int(str(event.data.decode()).replace('setTagFounderAdminTag_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    CaptchaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["adminTag"]
    CaptchaSettings["tag_founder"] = not CaptchaSettings["tag_founder"]

    await SaveJsonGroupsData(groups_database)
    await AdminTag(event, group_ID=target_group_id)


#############################################################################
 
# media_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"media_")))
async def AllowedMedia(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('media_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    AllowedMediaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["allowed_media"]
    penaltyList = {
        "Off": "☑️",
        "Warn": "❕",
        "Kick": "❗️",
        "Mute": "🔇",
        "Ban": "🚷"
    }

    MSG = f'''
📸 حظر الوسائط

❕ = تحذير | ❗️ = طرد
🔇 = كتم | 🚷 = حظر
🗑 = حذف
☑️ = معطل
______________________________

📸 الصور = {penaltyList[AllowedMediaSettings["photo"]["penalty"]]} {AllowedMediaSettings["photo"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["photo"]["delete_msg"] else ''}
🎞 الفيديوهات = {penaltyList[AllowedMediaSettings["video"]["penalty"]]} {AllowedMediaSettings["video"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["video"]["delete_msg"] else ''}
🎥 صور GIF = {penaltyList[AllowedMediaSettings["gif"]["penalty"]]} {AllowedMediaSettings["gif"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["gif"]["delete_msg"] else ''}
🎤 الرسائل الصوتية = {penaltyList[AllowedMediaSettings["voice"]["penalty"]]} {AllowedMediaSettings["voice"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["voice"]["delete_msg"] else ''}
🎧 الصوتيات = {penaltyList[AllowedMediaSettings["audio"]["penalty"]]} {AllowedMediaSettings["audio"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["audio"]["delete_msg"] else ''}
🃏 الملصقات = {penaltyList[AllowedMediaSettings["sticker"]["penalty"]]} {AllowedMediaSettings["sticker"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["sticker"]["delete_msg"] else ''}
'''
    
    # 📲 Story = {penaltyList[AllowedMediaSettings["story"]["penalty"]]} {AllowedMediaSettings["story"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["story"]["delete_msg"] else ''}
    # 🖼 الألبومات = {penaltyList[AllowedMediaSettings["album"]["penalty"]]} {AllowedMediaSettings["album"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["album"]["delete_msg"] else ''}
    # 🎲 Animated Games = {penaltyList[AllowedMediaSettings["animatedGames"]["penalty"]]} {AllowedMediaSettings["animatedGames"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["animatedGames"]["delete_msg"] else ''}
    # 😀 Animated Emoji = {penaltyList[AllowedMediaSettings["animatedEmoji"]["penalty"]]} {AllowedMediaSettings["animatedEmoji"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["animatedEmoji"]["delete_msg"] else ''}
    # 👾 Premium Emoji = {penaltyList[AllowedMediaSettings["premiumEmoji"]["penalty"]]} {AllowedMediaSettings["premiumEmoji"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["premiumEmoji"]["delete_msg"] else ''}
    # 📍 الموقع = ☑️ معطل
    # 🆎 العاصمة = ☑️ معطل
    # 🤖 بوت مدمج = ☑️ معطل
    # 🗯 التلميحات = ☑️ معطل
    # 🌌 وسائط التلميحات = ☑️ معطل
    # 👁‍🗨 الفيديو المستدير = ☑️ معطل
    # 🎁 العروض = ☑️ معطل


    buttons = [
        # [
        #     Button.inline("📲", "showThis"),
        #     Button.inline("☑️", f"setPenaltyAllowedMedia_story_Off_{target_group_id}"),
        #     Button.inline("❕", f"setPenaltyAllowedMedia_story_Warn_{target_group_id}"),
        #     Button.inline("❗️", f"setPenaltyAllowedMedia_story_Kick_{target_group_id}"),
        #     Button.inline("🔇", f"setPenaltyAllowedMedia_story_Mute_{target_group_id}"),
        #     Button.inline("🚷", f"setPenaltyAllowedMedia_story_Ban_{target_group_id}"),
        #     Button.inline("🗑", f"setDeletionAllowedMedia_story_Delete_{target_group_id}")
        # ],
        [
            Button.inline("📸", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_photo_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_photo_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_photo_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_photo_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_photo_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_photo_Delete_{target_group_id}")
        ],
        [
            Button.inline("🎞", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_video_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_video_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_video_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_video_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_video_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_video_Delete_{target_group_id}")
        ],
        # [
        #     Button.inline("🖼", "showThis"),
        #     Button.inline("☑️", f"setPenaltyAllowedMedia_album_Off_{target_group_id}"),
        #     Button.inline("❕", f"setPenaltyAllowedMedia_album_Warn_{target_group_id}"),
        #     Button.inline("❗️", f"setPenaltyAllowedMedia_album_Kick_{target_group_id}"),
        #     Button.inline("🔇", f"setPenaltyAllowedMedia_album_Mute_{target_group_id}"),
        #     Button.inline("🚷", f"setPenaltyAllowedMedia_album_Ban_{target_group_id}"),
        #     Button.inline("🗑", f"setDeletionAllowedMedia_album_Delete_{target_group_id}")
        # ],
        [
            Button.inline("🎥", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_gif_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_gif_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_gif_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_gif_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_gif_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_gif_Delete_{target_group_id}")
        ],
        [
            Button.inline("🎤", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_voice_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_voice_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_voice_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_voice_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_voice_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_voice_Delete_{target_group_id}")
        ],
        [
            Button.inline("🎧", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_audio_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_audio_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_audio_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_audio_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_audio_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_audio_Delete_{target_group_id}")
        ],
        [
            Button.inline("🃏", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_sticker_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_sticker_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_sticker_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_sticker_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_sticker_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_sticker_Delete_{target_group_id}")
        ],
        # [
        #     Button.inline("🎭", "showThis"),
        #     Button.inline("☑️", f"setPenaltyAllowedMedia_animatedStickers_Off_{target_group_id}"),
        #     Button.inline("❕", f"setPenaltyAllowedMedia_animatedStickers_Warn_{target_group_id}"),
        #     Button.inline("❗️", f"setPenaltyAllowedMedia_animatedStickers_Kick_{target_group_id}"),
        #     Button.inline("🔇", f"setPenaltyAllowedMedia_animatedStickers_Mute_{target_group_id}"),
        #     Button.inline("🚷", f"setPenaltyAllowedMedia_animatedStickers_Ban_{target_group_id}"),
        #     Button.inline("🗑", f"setDeletionAllowedMedia_animatedStickers_Delete_{target_group_id}")
        # ],
        # [
        #     Button.inline("🎲", "showThis"),
        #     Button.inline("☑️", f"setPenaltyAllowedMedia_animatedGames_Off_{target_group_id}"),
        #     Button.inline("❕", f"setPenaltyAllowedMedia_animatedGames_Warn_{target_group_id}"),
        #     Button.inline("❗️", f"setPenaltyAllowedMedia_animatedGames_Kick_{target_group_id}"),
        #     Button.inline("🔇", f"setPenaltyAllowedMedia_animatedGames_Mute_{target_group_id}"),
        #     Button.inline("🚷", f"setPenaltyAllowedMedia_animatedGames_Ban_{target_group_id}"),
        #     Button.inline("🗑", f"setDeletionAllowedMedia_animatedGames_Delete_{target_group_id}")
        # ],
        # [
        #     Button.inline("😀", "showThis"),
        #     Button.inline("☑️", f"setPenaltyAllowedMedia_animatedEmoji_Off_{target_group_id}"),
        #     Button.inline("❕", f"setPenaltyAllowedMedia_animatedEmoji_Warn_{target_group_id}"),
        #     Button.inline("❗️", f"setPenaltyAllowedMedia_animatedEmoji_Kick_{target_group_id}"),
        #     Button.inline("🔇", f"setPenaltyAllowedMedia_animatedEmoji_Mute_{target_group_id}"),
        #     Button.inline("🚷", f"setPenaltyAllowedMedia_animatedEmoji_Ban_{target_group_id}"),
        #     Button.inline("🗑", f"setDeletionAllowedMedia_animatedEmoji_Delete_{target_group_id}")
        # ],
        # [
        #     Button.inline("👾", "showThis"),
        #     Button.inline("☑️", f"setPenaltyAllowedMedia_premiumEmoji_Off_{target_group_id}"),
        #     Button.inline("❕", f"setPenaltyAllowedMedia_premiumEmoji_Warn_{target_group_id}"),
        #     Button.inline("❗️", f"setPenaltyAllowedMedia_premiumEmoji_Kick_{target_group_id}"),
        #     Button.inline("🔇", f"setPenaltyAllowedMedia_premiumEmoji_Mute_{target_group_id}"),
        #     Button.inline("🚷", f"setPenaltyAllowedMedia_premiumEmoji_Ban_{target_group_id}"),
        #     Button.inline("🗑", f"setDeletionAllowedMedia_premiumEmoji_Delete_{target_group_id}")
        # ]
    ]
 
    # Button.inline("🔇 🕧 🚷", f"setDurationAllowedMedia__{target_group_id}"),
    buttons.append([
        Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}"),
        Button.inline("➡️ التالي", f"mediaNext_{target_group_id}")
    ])

    await event.respond(MSG, buttons=buttons, parse_mode="HTML")


@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"mediaNext_")))
async def AllowedMediaNext(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('mediaNext_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    AllowedMediaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["allowed_media"]
    penaltyList = {
        "Off": "☑️",
        "Warn": "❕",
        "Kick": "❗️",
        "Mute": "🔇",
        "Ban": "🚷"
    }

    MSG = f'''
📸 حظر الوسائط

❕ = تحذير | ❗️ = طرد
🔇 = كتم | 🚷 = حظر
🗑 = حذف
☑️ = معطل
______________________________

🎭 الملصقات المتحركة = {penaltyList[AllowedMediaSettings["animatedStickers"]["penalty"]]} {AllowedMediaSettings["animatedStickers"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["animatedStickers"]["delete_msg"] else ''}
💾 الملفات = {penaltyList[AllowedMediaSettings["files"]["penalty"]]} {AllowedMediaSettings["files"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["files"]["delete_msg"] else ''}
🎮 الألعاب = {penaltyList[AllowedMediaSettings["games"]["penalty"]]} {AllowedMediaSettings["games"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["games"]["delete_msg"] else ''}
🏷 جهات الاتصال = {penaltyList[AllowedMediaSettings["contacts"]["penalty"]]} {AllowedMediaSettings["contacts"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["contacts"]["delete_msg"] else ''}
📊 الاستطلاعات = {penaltyList[AllowedMediaSettings["polls"]["penalty"]]} {AllowedMediaSettings["polls"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["polls"]["delete_msg"] else ''}
💶 المدفوعات ={penaltyList[AllowedMediaSettings["payments"]["penalty"]]} {AllowedMediaSettings["payments"]["penalty"]} {'+ 🗑' if AllowedMediaSettings["payments"]["delete_msg"] else ''}
'''
    

    buttons = [
        [
            Button.inline("🎭", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_animatedStickers_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_animatedStickers_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_animatedStickers_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_animatedStickers_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_animatedStickers_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_animatedStickers_Delete_{target_group_id}")
        ],
        [
            Button.inline("💾", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_files_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_files_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_files_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_files_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_files_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_files_Delete_{target_group_id}")
        ],
        [
            Button.inline("🎮", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_games_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_games_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_games_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_games_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_games_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_games_Delete_{target_group_id}")
        ],
        [
            Button.inline("🏷", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_contacts_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_contacts_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_contacts_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_contacts_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_contacts_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_contacts_Delete_{target_group_id}")
        ],
        [
            Button.inline("📊", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_polls_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_polls_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_polls_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_polls_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_polls_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_polls_Delete_{target_group_id}")
        ],
        [
            Button.inline("💶", "showThis"),
            Button.inline("☑️", f"setPenaltyAllowedMedia_payments_Off_{target_group_id}"),
            Button.inline("❕", f"setPenaltyAllowedMedia_payments_Warn_{target_group_id}"),
            Button.inline("❗️", f"setPenaltyAllowedMedia_payments_Kick_{target_group_id}"),
            Button.inline("🔇", f"setPenaltyAllowedMedia_payments_Mute_{target_group_id}"),
            Button.inline("🚷", f"setPenaltyAllowedMedia_payments_Ban_{target_group_id}"),
            Button.inline("🗑", f"setDeletionAllowedMedia_payments_Delete_{target_group_id}")
        ]
    ]
 
    # Button.inline("🔇 🕧 🚷", f"setDurationAllowedMedia__{target_group_id}"),
    buttons.append([
        # Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}"),
        Button.inline("⬅️ العودة", f"media_{target_group_id}")
    ])

    await event.respond(MSG, buttons=buttons, parse_mode="HTML")





# Set Penalty Allowed Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setPenaltyAllowedMedia_")))
async def SetPenaltyAllowedMedia(event):

    target_media, penalty, target_group_id = (str(event.data.decode()).replace('setPenaltyAllowedMedia_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AllowedMediaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["allowed_media"]
    AllowedMediaSettings[target_media]["penalty"] = penalty

    await SaveJsonGroupsData(groups_database)
    await AllowedMedia(event, group_ID=target_group_id)



# Set Deletion Allowed Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setDeletionAllowedMedia_")))
async def SetDeletionAllowedMedia(event):

    target_media, penalty, target_group_id = (str(event.data.decode()).replace('setDeletionAllowedMedia_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AllowedMediaSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["allowed_media"]
    AllowedMediaSettings[target_media]["delete_msg"] = not AllowedMediaSettings[target_media]["delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await AllowedMedia(event, group_ID=target_group_id)



#############################################################################

# warns_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"warns_")))
async def WarnsSystem(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('warns_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    WarnSystemSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["warn_system"]

    MSG = f'''
❗️ **تحذيرات المستخدمين**

نظام التحذيرات يسمح لك بإعطاء تحذيرات للمستخدمين بسبب السلوك الغير لائق في المجموعة، قبل معاقبتهم فعلاً.

من هذه القائمة يمكنك تعيين:
• العقوبة للمستخدمين الذين يتجاوزون الحد الأقصى لعدد التحذيرات المسموح بها
• الحد الأقصى لعدد التحذيرات المسموح بها

العقوبة: {WarnSystemSettings["punishment"]}
الحد الأقصى للتحذيرات المسموح بها: {WarnSystemSettings["max_warns"]}
'''
    
    button_text = '✅ تفعيل' if not WarnSystemSettings['is_active'] else '❌ ايقاف ❌'

    buttons = [
        [
            Button.inline(button_text, f"setWarnSystem_{target_group_id}")
        ]
    ]

    if WarnSystemSettings['is_active']:
        # buttons.append([Button.inline("📄 Warned List", f"WarnedListWarnSystem_{target_group_id}")])
        buttons.append([Button.inline(f"🔇 كتم {'✅' if WarnSystemSettings['punishment'] == 'Mute' else ''}", f"setWarnSystemPenalty_Mute_{target_group_id}")])
        buttons.append([
            Button.inline(f"❗️ طرد {'✅' if WarnSystemSettings['punishment'] == 'Kick' else ''}", f"setWarnSystemPenalty_Kick_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if WarnSystemSettings['punishment'] == 'Ban' else ''}", f"setWarnSystemPenalty_Ban_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"2 {'✅' if WarnSystemSettings['max_warns'] == 2 else ''}", f"setWarnSystemMaxWarns_2_{target_group_id}"),
            Button.inline(f"3 {'✅' if WarnSystemSettings['max_warns'] == 3 else ''}", f"setWarnSystemMaxWarns_3_{target_group_id}"),
            Button.inline(f"4 {'✅' if WarnSystemSettings['max_warns'] == 4 else ''}", f"setWarnSystemMaxWarns_4_{target_group_id}"),
            Button.inline(f"5 {'✅' if WarnSystemSettings['max_warns'] == 5 else ''}", f"setWarnSystemMaxWarns_5_{target_group_id}"),
            Button.inline(f"6 {'✅' if WarnSystemSettings['max_warns'] == 6 else ''}", f"setWarnSystemMaxWarns_6_{target_group_id}")
        ])
    
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)



# Set Warn System
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setWarnSystem_")))
async def SetWarnSystem(event):

    target_group_id = str(event.data.decode()).replace('setWarnSystem_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    WarnSystemSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["warn_system"]
    WarnSystemSettings["is_active"] = not WarnSystemSettings["is_active"]

    await SaveJsonGroupsData(groups_database)
    await WarnsSystem(event, group_ID=target_group_id)



# Set Warn System Penalty
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setWarnSystemPenalty_")))
async def SetWarnSystemPenalty(event):

    penalty, target_group_id = (str(event.data.decode()).replace('setWarnSystemPenalty_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    WarnSystemSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["warn_system"]
    WarnSystemSettings["punishment"] = penalty

    await SaveJsonGroupsData(groups_database)
    await WarnsSystem(event, group_ID=target_group_id)



# Set Warn System Max Warns
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setWarnSystemMaxWarns_")))
async def SetWarnSystemMaxWarns(event):

    maxWarns, target_group_id = (str(event.data.decode()).replace('setWarnSystemMaxWarns_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    WarnSystemSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["warn_system"]
    WarnSystemSettings["max_warns"] = int(maxWarns)

    await SaveJsonGroupsData(groups_database)
    await WarnsSystem(event, group_ID=target_group_id)



#############################################################################

# tag_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"tag_")))
async def TagAlert(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('tag_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    bot_data = await bot.get_me()

    # Check Paid Service & User VIP
    if bot_configs["tag_alert_paid"]:
        is_vip = await check_user_vip(event, event.sender_id)
        if is_vip == False:
            buttons = [
                [Button.inline('💳 شراء العضوية المدفوعة ⭐️', 'buy_vip')],
                [Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")]
            ]
            await event.respond(f'''
🛎 **تنبيه التاغ**

عند الإشارة إلى المستخدم، سيتم إرسال تنبيه خاص له لإعلامه.

سيتم إرسال الإشعارات عبر @{bot_data.username} (للمستخدمين الذين بدأوا البوت).

🔰 **متاح فقط لـ المستخدمين المميزين**
''', buttons=buttons)
            return
    ################################# End VIP Check

    TagAlertSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["tag_alert"]

    MSG = f'''
🛎 **تنبيه التاغ**

عند الإشارة إلى المستخدم، سيتم إرسال تنبيه خاص له لإعلامه.

سيتم إرسال الإشعارات عبر @{bot_data.username} (للمستخدمين الذين بدأوا البوت).


الحالة: {'✔️ مفعل' if TagAlertSettings['is_active'] else '✖️ معطل'}
'''

    button_text = '✅ تفعيل' if not TagAlertSettings['is_active'] else '❌ ايقاف ❌'
    buttons = [
        [
            Button.inline(button_text, f"activePersonalTagAlert_{target_group_id}")
        ]
    ]

    # if TagAlertSettings['is_active']:
    #     # buttons.append([Button.inline("📄 Warned List", f"WarnedListWarnSystem_{target_group_id}")])
    #     pass
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Active Personal Tag Alert
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"activePersonalTagAlert_")))
async def ActivePersonalTagAlert(event):

    target_group_id = int(str(event.data.decode()).replace('activePersonalTagAlert_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    TagAlertSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["tag_alert"]
    TagAlertSettings["is_active"] = not TagAlertSettings["is_active"]

    await SaveJsonGroupsData(groups_database)
    await TagAlert(event, group_ID=target_group_id)


#############################################################################

# approvalMode_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"approvalMode_")))
async def ApprovalMode(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('approvalMode_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return


    await DeleteEvent(event)
    ApprovalModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["approval_mode"]

    MSG = f'''
📬 **وضع الموافقة**

من خلال هذه القائمة يمكنك تحديد ما إذا كنت تريد تفويض إدارة الموافقات في المجموعة إلى البوت، للمستخدمين الذين يطلبون الانضمام عبر الرابط مع الموافقة.

🧠 بما أن كابتشا غير مفعلة، إذا قمت بتمكين الموافقة التلقائية، سيتم قبول المستخدمين تلقائيًا في المجموعة بمجرد تقديم طلبهم (ما لم يتم تفعيل فحص آخر).

👥 إذا انضم مستخدم عبر رابط لا يتطلب الموافقة، ستتم الإجراءات بشكل عادي في المجموعة.


💡 الحالة: {'مفعل ✔️' if ApprovalModeSettings['is_active'] else 'معطل ✖️'}
'''
    
    buttons = [
        [
            Button.inline("🔒 وضع الموافقة التلقائية ⤵️", f"AutoApprovalMode_{target_group_id}")
        ],
        [
            Button.inline("✖️ ايقاف", f"TurnOffApprovalMode_{target_group_id}"),
            Button.inline("✔️ تشغيل", f"TurnOnApprovalMode_{target_group_id}")
        ],
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Turn Off Approval Mode
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOffApprovalMode_")))
async def TurnOffApprovalMode(event):

    target_group_id = int(str(event.data.decode()).replace('TurnOffApprovalMode_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    ApprovalModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["approval_mode"]
    ApprovalModeSettings["is_active"] = False

    await SaveJsonGroupsData(groups_database)
    await ApprovalMode(event, group_ID=target_group_id)


# Turn On Approval Mode
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOnApprovalMode_")))
async def TurnOnApprovalMode(event):

    target_group_id = int(str(event.data.decode()).replace('TurnOnApprovalMode_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    ApprovalModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["approval_mode"]
    ApprovalModeSettings["is_active"] = True

    await SaveJsonGroupsData(groups_database)
    await ApprovalMode(event, group_ID=target_group_id)



#############################################################################

# antiSpam_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"antiSpam_")))
async def AntiSpam(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('antiSpam_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    MSG = f'''
📨 **مكافحة السبام**

من خلال هذا القائمة، يمكنك حماية مجموعتك من الروابط غير الضرورية، وإعادة التوجيه، والاقتباسات.
'''
    
    buttons = [
        [
            Button.inline("📘 روابط تيليجرام", f"TelegramLinksAntiSpam_{target_group_id}")
        ],
        [
            Button.inline("📩 إعادة التوجيه", f"ForwardingAntiSpam_{target_group_id}"),
            Button.inline("💭 الاقتباس", f"QuateAntiSpam_{target_group_id}")
        ],
        [
            Button.inline("🔗 حظر جميع الروابط", f"TotalLinksBlockAntiSpam_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Telegram Links Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TelegramLinksAntiSpam_")))
async def TelegramLinksAntiSpam(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('TelegramLinksAntiSpam_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]

    MSG = f'''
📘 **روابط تيليجرام**

من خلال هذا القائمة، يمكنك تعيين عقوبة للمستخدمين الذين يرسلون رسائل تحتوي على روابط تيليجرام.

🎯 مكافحة معرفات المستخدمين: المعرفات تعتبر سبام
🤖 مكافحة روابط البوتات: روابط البوتات تعتبر سبام

العقاب: {AntiSpamSettings["penalty"]}
حذف الرسالة: {'نعم ✔️' if AntiSpamSettings["delete_msg"] else 'لا ✖️'}
'''
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if AntiSpamSettings['penalty'] == 'Off' else ''}", f"setAntiSpamPenalty_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if AntiSpamSettings['penalty'] == 'Warn' else ''}", f"setAntiSpamPenalty_Warn_{target_group_id}"),
            Button.inline(f"❗️ طرد {'✅' if AntiSpamSettings['penalty'] == 'Kick' else ''}", f"setAntiSpamPenalty_Kick_{target_group_id}")
        ],
        [
            Button.inline(f"🔇 كتم {'✅' if AntiSpamSettings['penalty'] == 'Mute' else ''}", f"setAntiSpamPenalty_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if AntiSpamSettings['penalty'] == 'Ban' else ''}", f"setAntiSpamPenalty_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"🗑 حذف الرسالة {'✔️' if AntiSpamSettings['delete_msg'] else '✖️'}", f"DeleteMsgAntiSpam_{target_group_id}")
        ],
        [
            Button.inline(f"🎯 المعرفات سبام {'✔️' if AntiSpamSettings['username_antispam'] else '✖️'}", f"UsernameAntiSpam_{target_group_id}")
        ],
        [
            Button.inline(f"🤖 روابط البوتات سبام {'✔️' if AntiSpamSettings['bots_antispam'] else '✖️'}", f"BotsAntiSpam_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToAntiSpamMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Set Anti-Spam Penalty
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setAntiSpamPenalty_")))
async def SetAntiSpamPenalty(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setAntiSpamPenalty_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await TelegramLinksAntiSpam(event, group_ID=target_group_id)


# Delete Msg Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMsgAntiSpam_")))
async def DeleteMsgAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('DeleteMsgAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["delete_msg"] = not AntiSpamSettings["delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await TelegramLinksAntiSpam(event, group_ID=target_group_id)


# Username Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"UsernameAntiSpam_")))
async def UsernameAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('UsernameAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["username_antispam"] = not AntiSpamSettings["username_antispam"]

    await SaveJsonGroupsData(groups_database)
    await TelegramLinksAntiSpam(event, group_ID=target_group_id)


# Bots Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"BotsAntiSpam_")))
async def BotsAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('BotsAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["bots_antispam"] = not AntiSpamSettings["bots_antispam"]

    await SaveJsonGroupsData(groups_database)
    await TelegramLinksAntiSpam(event, group_ID=target_group_id)


# Forwarding Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"ForwardingAntiSpam_")))
async def ForwardingAntiSpam(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('ForwardingAntiSpam_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]

    MSG = f'''
📩 **إعادة التوجيه**  

اختر العقوبة للمستخدمين الذين يقومون بإعادة توجيه الرسائل في المجموعة.  


📣 مشاركة من القنوات
 └ {AntiSpamSettings["forwarding_penalty"] if AntiSpamSettings["forwarding_channels"] else 'Off'}
👥 المجموعات
 └ {AntiSpamSettings["forwarding_penalty"] if AntiSpamSettings["forwarding_groups"] else 'Off'}
👤 المستخدمين
 └ {AntiSpamSettings["forwarding_penalty"] if AntiSpamSettings["forwarding_users"] else 'Off'}
🤖 البوتات
 └ {AntiSpamSettings["forwarding_penalty"] if AntiSpamSettings["forwarding_bots"] else 'Off'}
 
العقاب: {AntiSpamSettings["forwarding_penalty"]}
حذف الرسالة: {'نعم ✔️' if AntiSpamSettings["forwarding_delete_msg"] else 'لا ✖️'}
'''
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if AntiSpamSettings['forwarding_penalty'] == 'Off' else ''}", f"setForwardingAntiSpamPenalty_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if AntiSpamSettings['forwarding_penalty'] == 'Warn' else ''}", f"setForwardingAntiSpamPenalty_Warn_{target_group_id}"),
            Button.inline(f"❗️ طرد {'✅' if AntiSpamSettings['forwarding_penalty'] == 'Kick' else ''}", f"setForwardingAntiSpamPenalty_Kick_{target_group_id}")
        ],
        [
            Button.inline(f"🔇 كتم {'✅' if AntiSpamSettings['forwarding_penalty'] == 'Mute' else ''}", f"setForwardingAntiSpamPenalty_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if AntiSpamSettings['forwarding_penalty'] == 'Ban' else ''}", f"setForwardingAntiSpamPenalty_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"🗑 حذف الرسالة {'✔️' if AntiSpamSettings['forwarding_delete_msg'] else '✖️'}", f"DeleteMsgForwardingAntiSpam_{target_group_id}")
        ],
        [
            Button.inline(f"📣 القنوات {'✔️' if AntiSpamSettings['forwarding_channels'] else '✖️'}", f"ChannelsForwardingAntiSpam_{target_group_id}"),
            Button.inline(f"👥 المجموعات {'✔️' if AntiSpamSettings['forwarding_groups'] else '✖️'}", f"GroupsForwardingAntiSpam_{target_group_id}")
        ],
        [
            Button.inline(f"👤 المستخدمين {'✔️' if AntiSpamSettings['forwarding_users'] else '✖️'}", f"UsersForwardingAntiSpam_{target_group_id}"),
            Button.inline(f"🤖 البوتات {'✔️' if AntiSpamSettings['forwarding_bots'] else '✖️'}", f"BotsForwardingAntiSpam_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToAntiSpamMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Set Forwarding Anti-Spam Penalty
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setForwardingAntiSpamPenalty_")))
async def SetForwardingAntiSpamPenalty(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setForwardingAntiSpamPenalty_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["forwarding_penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await ForwardingAntiSpam(event, group_ID=target_group_id)


# Delete Msg Forwarding Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMsgForwardingAntiSpam_")))
async def DeleteMsgForwardingAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('DeleteMsgForwardingAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["forwarding_delete_msg"] = not AntiSpamSettings["forwarding_delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await ForwardingAntiSpam(event, group_ID=target_group_id)


# Channels Forwarding Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"ChannelsForwardingAntiSpam_")))
async def ChannelsForwardingAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('ChannelsForwardingAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["forwarding_channels"] = not AntiSpamSettings["forwarding_channels"]

    await SaveJsonGroupsData(groups_database)
    await ForwardingAntiSpam(event, group_ID=target_group_id)


# Groups Forwarding Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"GroupsForwardingAntiSpam_")))
async def GroupsForwardingAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('GroupsForwardingAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["forwarding_groups"] = not AntiSpamSettings["forwarding_groups"]

    await SaveJsonGroupsData(groups_database)
    await ForwardingAntiSpam(event, group_ID=target_group_id)


# Users Forwarding Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"UsersForwardingAntiSpam_")))
async def UsersForwardingAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('UsersForwardingAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["forwarding_users"] = not AntiSpamSettings["forwarding_users"]

    await SaveJsonGroupsData(groups_database)
    await ForwardingAntiSpam(event, group_ID=target_group_id)


# bots Forwarding Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"BotsForwardingAntiSpam_")))
async def BotsForwardingAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('BotsForwardingAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["forwarding_bots"] = not AntiSpamSettings["forwarding_bots"]

    await SaveJsonGroupsData(groups_database)
    await ForwardingAntiSpam(event, group_ID=target_group_id)


# Quate Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"QuateAntiSpam_")))
async def QuateAntiSpam(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('QuateAntiSpam_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]

    MSG = f'''
💭 **الاقتباس**

اختر العقوبة للمستخدمين الذين يرسلون رسائل تحتوي على اقتباسات من محادثات خارجية.


📣 اقتباس من القنوات
 └ {AntiSpamSettings["quate_penalty"] if AntiSpamSettings["quate_channels"] else 'Off'}
👥 المجموعات
 └ {AntiSpamSettings["quate_penalty"] if AntiSpamSettings["quate_groups"] else 'Off'}
👤 المستخدمين
 └ {AntiSpamSettings["quate_penalty"] if AntiSpamSettings["quate_users"] else 'Off'}
🤖 البوتات
 └ {AntiSpamSettings["quate_penalty"] if AntiSpamSettings["quate_bots"] else 'Off'}
 
العقاب: {AntiSpamSettings["quate_penalty"]}
حذف الرسالة: {'نعم ✔️' if AntiSpamSettings["quate_delete_msg"] else 'لا ✖️'}
'''
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if AntiSpamSettings['quate_penalty'] == 'Off' else ''}", f"setQuateAntiSpamPenalty_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if AntiSpamSettings['quate_penalty'] == 'Warn' else ''}", f"setQuateAntiSpamPenalty_Warn_{target_group_id}"),
            Button.inline(f"❗️ طرد {'✅' if AntiSpamSettings['quate_penalty'] == 'Kick' else ''}", f"setQuateAntiSpamPenalty_Kick_{target_group_id}")
        ],
        [
            Button.inline(f"🔇 كتم {'✅' if AntiSpamSettings['quate_penalty'] == 'Mute' else ''}", f"setQuateAntiSpamPenalty_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if AntiSpamSettings['quate_penalty'] == 'Ban' else ''}", f"setQuateAntiSpamPenalty_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"🗑 حذف الرسالة {'✔️' if AntiSpamSettings['quate_delete_msg'] else '✖️'}", f"DeleteMsgQuateAntiSpam_{target_group_id}")
        ],
        [
            Button.inline(f"📣 القنوات {'✔️' if AntiSpamSettings['quate_channels'] else '✖️'}", f"ChannelsQuateAntiSpam_{target_group_id}"),
            Button.inline(f"👥 المجموعات {'✔️' if AntiSpamSettings['quate_groups'] else '✖️'}", f"GroupsQuateAntiSpam_{target_group_id}")
        ],
        [
            Button.inline(f"👤 المستخدمين {'✔️' if AntiSpamSettings['quate_users'] else '✖️'}", f"UsersQuateAntiSpam_{target_group_id}"),
            Button.inline(f"🤖 البوتات {'✔️' if AntiSpamSettings['quate_bots'] else '✖️'}", f"BotsQuateAntiSpam_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToAntiSpamMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)



# Set Quate Anti-Spam Penalty
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setQuateAntiSpamPenalty_")))
async def setQuateAntiSpamPenalty(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setQuateAntiSpamPenalty_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["quate_penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await QuateAntiSpam(event, group_ID=target_group_id)


# Delete Msg Quate Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMsgQuateAntiSpam_")))
async def DeleteMsgQuateAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('DeleteMsgQuateAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["quate_delete_msg"] = not AntiSpamSettings["quate_delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await QuateAntiSpam(event, group_ID=target_group_id)


# Channels Quate Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"ChannelsQuateAntiSpam_")))
async def ChannelsQuateAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('ChannelsQuateAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["quate_channels"] = not AntiSpamSettings["quate_channels"]

    await SaveJsonGroupsData(groups_database)
    await QuateAntiSpam(event, group_ID=target_group_id)


# Groups Quate Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"GroupsQuateAntiSpam_")))
async def GroupsQuateAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('GroupsQuateAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["quate_groups"] = not AntiSpamSettings["quate_groups"]

    await SaveJsonGroupsData(groups_database)
    await QuateAntiSpam(event, group_ID=target_group_id)


# Users Quate Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"UsersQuateAntiSpam_")))
async def UsersQuateAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('UsersQuateAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["quate_users"] = not AntiSpamSettings["quate_users"]

    await SaveJsonGroupsData(groups_database)
    await QuateAntiSpam(event, group_ID=target_group_id)


# bots Quate Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"BotsQuateAntiSpam_")))
async def BotsQuateAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('BotsQuateAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["quate_bots"] = not AntiSpamSettings["quate_bots"]

    await SaveJsonGroupsData(groups_database)
    await QuateAntiSpam(event, group_ID=target_group_id)



# Total Links Block Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TotalLinksBlockAntiSpam_")))
async def TotalLinksBlockAntiSpam(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('TotalLinksBlockAntiSpam_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]

    MSG = f'''
🔗 **حظر جميع الروابط**  

اختر العقوبة لأولئك الذين يرسلون أي نوع من الروابط.

 
العقاب: {AntiSpamSettings["total_links_penalty"]}
حذف الرسالة: {'نعم ✔️' if AntiSpamSettings["total_links_delete_msg"] else 'لا ✖️'}
'''
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if AntiSpamSettings['total_links_penalty'] == 'Off' else ''}", f"setTotalLinksAntiSpamPenalty_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if AntiSpamSettings['total_links_penalty'] == 'Warn' else ''}", f"setTotalLinksAntiSpamPenalty_Warn_{target_group_id}"),
            Button.inline(f"❗️ طرد {'✅' if AntiSpamSettings['total_links_penalty'] == 'Kick' else ''}", f"setTotalLinksAntiSpamPenalty_Kick_{target_group_id}")
        ],
        [
            Button.inline(f"🔇 كتم {'✅' if AntiSpamSettings['total_links_penalty'] == 'Mute' else ''}", f"setTotalLinksAntiSpamPenalty_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if AntiSpamSettings['total_links_penalty'] == 'Ban' else ''}", f"setTotalLinksAntiSpamPenalty_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"🗑 حذف الرسالة {'✔️' if AntiSpamSettings['total_links_delete_msg'] else '✖️'}", f"DeleteMsgTotalLinksAntiSpam_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToAntiSpamMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)



# Set Total Links Anti-Spam Penalty
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setTotalLinksAntiSpamPenalty_")))
async def SetTotalLinksAntiSpamPenalty(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setTotalLinksAntiSpamPenalty_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["total_links_penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await TotalLinksBlockAntiSpam(event, group_ID=target_group_id)


# Delete Msg Total Links Anti-Spam
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMsgTotalLinksAntiSpam_")))
async def DeleteMsgTotalLinksAntiSpam(event):

    target_group_id = str(event.data.decode()).replace('DeleteMsgTotalLinksAntiSpam_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiSpamSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antispam"]
    AntiSpamSettings["total_links_delete_msg"] = not AntiSpamSettings["total_links_delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await TotalLinksBlockAntiSpam(event, group_ID=target_group_id)



#############################################################################

# antiFlood_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"antiFlood_")))
async def AntiFlood(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('antiFlood_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    AntiFloodSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antiflood"]

    MSG = f'''
🗣 **الرسائل المتكررة**

من خلال هذا القائمة، يمكنك تحديد العقوبة لأولئك الذين يرسلون العديد من الرسائل في وقت قصير.

حالياً، يتم تفعيل نظام مكافحة الرسائل المتكررة عندما يتم إرسال {AntiFloodSettings["messages_target"]} رسالة خلال {AntiFloodSettings["interval_time"]} ثانية.

العقاب: {AntiFloodSettings["penalty"]}
حذف الرسائل : {'نعم ✔️' if AntiFloodSettings["delete_msg"] else 'لا ✖️'}
'''
    
    buttons = [
        [
            Button.inline(f"📑 الرسائل", f"MessagesAntiFlood_{target_group_id}"),
            Button.inline(f"🕧 الوقت", f"TimeAntiFlood_{target_group_id}")
        ],
        [
            Button.inline(f"❌ لا شي {'✅' if AntiFloodSettings['penalty'] == 'Off' else ''}", f"setAntiFloodPenalty_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if AntiFloodSettings['penalty'] == 'Warn' else ''}", f"setAntiFloodPenalty_Warn_{target_group_id}")
        ],
        [
            Button.inline(f"❗️ طرد {'✅' if AntiFloodSettings['penalty'] == 'Kick' else ''}", f"setAntiFloodPenalty_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if AntiFloodSettings['penalty'] == 'Mute' else ''}", f"setAntiFloodPenalty_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if AntiFloodSettings['penalty'] == 'Ban' else ''}", f"setAntiFloodPenalty_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"🗑 حذف الرسائل {'✔️' if AntiFloodSettings['delete_msg'] else '✖️'}", f"DeleteMsgAntiFlood_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Time Anti-Flood
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TimeAntiFlood_")))
async def TimeAntiFlood(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('TimeAntiFlood_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    AntiFloodSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antiflood"]

    MSG = f'''
من هنا يمكنك تحديد فترة الوقت التي يتم اعتبارها لحساب مكافحة الرسائل المتكررة.

حالياً، يتم تفعيل نظام مكافحة الرسائل المتكررة عندما يتم إرسال {AntiFloodSettings["messages_target"]} رسالة خلال {AntiFloodSettings["interval_time"]} ثانية.
'''
    
    buttons = [
        [
            Button.inline(f"2", f"setTimeAntiFlood_2_{target_group_id}"),
            Button.inline(f"3", f"setTimeAntiFlood_3_{target_group_id}"),
            Button.inline(f"4", f"setTimeAntiFlood_4_{target_group_id}"),
            Button.inline(f"5", f"setTimeAntiFlood_5_{target_group_id}")
        ],
        [
            Button.inline(f"6", f"setTimeAntiFlood_6_{target_group_id}"),
            Button.inline(f"7", f"setTimeAntiFlood_7_{target_group_id}"),
            Button.inline(f"8", f"setTimeAntiFlood_8_{target_group_id}"),
            Button.inline(f"9", f"setTimeAntiFlood_9_{target_group_id}")
        ],
        [
            Button.inline(f"10", f"setTimeAntiFlood_10_{target_group_id}"),
            Button.inline(f"12", f"setTimeAntiFlood_12_{target_group_id}"),
            Button.inline(f"15", f"setTimeAntiFlood_15_{target_group_id}"),
            Button.inline(f"20", f"setTimeAntiFlood_20_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToAntiFloodMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Set Time Anti-Flood
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setTimeAntiFlood_")))
async def SetTimeAntiFlood(event):

    new_time, target_group_id = (str(event.data.decode()).replace('setTimeAntiFlood_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiFloodSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antiflood"]
    AntiFloodSettings["interval_time"] = int(new_time)

    await SaveJsonGroupsData(groups_database)
    await TimeAntiFlood(event, group_ID=target_group_id)


# Messages Anti-Flood
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"MessagesAntiFlood_")))
async def MessagesAntiFlood(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('MessagesAntiFlood_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    AntiFloodSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antiflood"]

    MSG = f'''
من هنا يمكنك تحديد الحد الأقصى لعدد الرسائل القابلة للإرسال في فترة الوقت المحددة.

حالياً، يتم تفعيل نظام مكافحة الرسائل المتكررة عندما يتم إرسال {AntiFloodSettings["messages_target"]} رسالة خلال {AntiFloodSettings["interval_time"]} ثانية.
'''
    
    buttons = [
        [
            Button.inline(f"2", f"setMessagesAntiFlood_2_{target_group_id}"),
            Button.inline(f"3", f"setMessagesAntiFlood_3_{target_group_id}"),
            Button.inline(f"4", f"setMessagesAntiFlood_4_{target_group_id}"),
            Button.inline(f"5", f"setMessagesAntiFlood_5_{target_group_id}")
        ],
        [
            Button.inline(f"6", f"setMessagesAntiFlood_6_{target_group_id}"),
            Button.inline(f"7", f"setMessagesAntiFlood_7_{target_group_id}"),
            Button.inline(f"8", f"setMessagesAntiFlood_8_{target_group_id}"),
            Button.inline(f"9", f"setMessagesAntiFlood_9_{target_group_id}")
        ],
        [
            Button.inline(f"10", f"setMessagesAntiFlood_10_{target_group_id}"),
            Button.inline(f"12", f"setMessagesAntiFlood_12_{target_group_id}"),
            Button.inline(f"15", f"setMessagesAntiFlood_15_{target_group_id}"),
            Button.inline(f"20", f"setMessagesAntiFlood_20_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToAntiFloodMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Set Messages Anti-Flood
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setMessagesAntiFlood_")))
async def SetMessagesAntiFlood(event):

    new_messages, target_group_id = (str(event.data.decode()).replace('setMessagesAntiFlood_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiFloodSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antiflood"]
    AntiFloodSettings["messages_target"] = int(new_messages)

    await SaveJsonGroupsData(groups_database)
    await MessagesAntiFlood(event, group_ID=target_group_id)


# Set Anti-Flood Penalty
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setAntiFloodPenalty_")))
async def SetAntiFloodPenalty(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setAntiFloodPenalty_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiFloodSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antiflood"]
    AntiFloodSettings["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await AntiFlood(event, group_ID=target_group_id)


# Delete Msg Anti-Flood
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMsgAntiFlood_")))
async def DeleteMsgAntiFlood(event):

    target_group_id = str(event.data.decode()).replace('DeleteMsgAntiFlood_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiFloodSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["antiflood"]
    AntiFloodSettings["delete_msg"] = not AntiFloodSettings["delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await AntiFlood(event, group_ID=target_group_id)


# Function to set max messages and time window for a group
async def set_group_settings(group_id, max_messages, time_window):
    group_settings_antiflood[group_id]['max_messages'] = max_messages
    group_settings_antiflood[group_id]['time_window'] = time_window


# Function to check if a user is spamming in a group
async def check_spam_and_take_action(group_id, user_id, message_id):
    current_time = time.time()

    # Retrieve the group settings (default if not set)
    max_messages = group_settings_antiflood[group_id]['max_messages']
    time_window = group_settings_antiflood[group_id]['time_window']

    # Get message timestamps and IDs for the user in this group
    message_data = group_message_times[group_id][user_id]
    message_data = [(t, msg_id) for t, msg_id in message_data if current_time - t <= time_window]

    # Add the current message's timestamp and message ID to the list
    message_data.append((current_time, message_id))
    group_message_times[group_id][user_id] = message_data

    # Check if the user has exceeded the allowed messages within the time window
    if len(message_data) > max_messages:
        group_message_times[group_id][user_id] = []
        spam_message_ids = [msg_id for _, msg_id in message_data]
        return True, spam_message_ids
    else:
        return False, []


#############################################################################

# alphabets_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"alphabets_")))
async def Alphabets(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('alphabets_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    AlphabetsSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["alphabets"]

    MSG = f'''
🕉 **الأبجديات**

اختر العقوبة لأي مستخدم يرسل رسائل مكتوبة باستخدام أبجديات معينة.


الأبجدية العربية ☪️ ([?](https://en.wikipedia.org/wiki/Arabic_alphabet))
  ⇐ الحالة: {'✔️' if AlphabetsSettings['watchArabic'] else '✖️'}

الأبجدية السيريلية 🇷🇺 ([?](https://en.wikipedia.org/wiki/Cyrillic_alphabets))
  ⇐ الحالة: {'✔️' if AlphabetsSettings['watchCyrillic'] else '✖️'}

الأبجدية الصينية 🇨🇳 ([?](https://en.wikipedia.org/wiki/Chinese_characters))
  ⇐ الحالة: {'✔️' if AlphabetsSettings['watchChinese'] else '✖️'}

الأبجدية اللاتينية 🔤 ([?](https://en.wikipedia.org/wiki/Latin_alphabet))
  ⇐ الحالة: {'✔️' if AlphabetsSettings['watchLatin'] else '✖️'}

العقاب: {AlphabetsSettings["penalty"]}
حذف الرسالة: {'نعم ✔️' if AlphabetsSettings["delete_msg"] else 'لا ✖️'}
'''
    
    # {AlphabetsSettings['penalty'] if AlphabetsSettings["watchArabic"] else ''}
    # {AlphabetsSettings['penalty'] if AlphabetsSettings["watchCyrillic"] else ''}
    # {AlphabetsSettings['penalty'] if AlphabetsSettings["watchChinese"] else ''}
    # {AlphabetsSettings['penalty'] if AlphabetsSettings["watchLatin"] else ''}
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if AlphabetsSettings['penalty'] == 'Off' else ''}", f"setAlphabetsPenalty_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if AlphabetsSettings['penalty'] == 'Warn' else ''}", f"setAlphabetsPenalty_Warn_{target_group_id}")
        ],
        [
            Button.inline(f"❗️ طرد {'✅' if AlphabetsSettings['penalty'] == 'Kick' else ''}", f"setAlphabetsPenalty_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if AlphabetsSettings['penalty'] == 'Mute' else ''}", f"setAlphabetsPenalty_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if AlphabetsSettings['penalty'] == 'Ban' else ''}", f"setAlphabetsPenalty_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"🗑 حذف الرسالة {'✔️' if AlphabetsSettings['delete_msg'] else '✖️'}", f"DeleteMsgAlphabets_{target_group_id}")
        ],
        [
            Button.inline(f"☪️ العربية {'✔️' if AlphabetsSettings['watchArabic'] else '✖️'}", f"setAlphabetsWatch_watchArabic_{target_group_id}"),
            Button.inline(f"🇷🇺 السيريلية {'✔️' if AlphabetsSettings['watchCyrillic'] else '✖️'}", f"setAlphabetsWatch_watchCyrillic_{target_group_id}")
        ],
        [
            Button.inline(f" 🇨🇳 الصينية {'✔️' if AlphabetsSettings['watchChinese'] else '✖️'}", f"setAlphabetsWatch_watchChinese_{target_group_id}"),
            Button.inline(f"🔤 اللاتينية {'✔️' if AlphabetsSettings['watchLatin'] else '✖️'}", f"setAlphabetsWatch_watchLatin_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Set Alphabets Penalty
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setAlphabetsPenalty_")))
async def SetAlphabetsPenalty(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setAlphabetsPenalty_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AlphabetsSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["alphabets"]
    AlphabetsSettings["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await Alphabets(event, group_ID=target_group_id)


# Set Alphabets Watch
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setAlphabetsWatch_")))
async def SetAlphabetsWatch(event):

    AlphabetWatch, target_group_id = (str(event.data.decode()).replace('setAlphabetsWatch_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AlphabetsSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["alphabets"]
    AlphabetsSettings[AlphabetWatch] = not AlphabetsSettings[AlphabetWatch]

    await SaveJsonGroupsData(groups_database)
    await Alphabets(event, group_ID=target_group_id)


# Delete Msg Alphabets
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMsgAlphabets_")))
async def DeleteMsgAlphabets(event):

    target_group_id = str(event.data.decode()).replace('DeleteMsgAlphabets_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AlphabetsSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["alphabets"]
    AlphabetsSettings["delete_msg"] = not AlphabetsSettings["delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await Alphabets(event, group_ID=target_group_id)



#############################################################################

# checks_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"checks_")))
async def Checks(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('checks_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]

    MSG = f'''
الالتزامات...
• اللقب: {ChecksSettings["obligation_surname"]}
• اسم المستخدم: {ChecksSettings["obligation_username"]}
• صورة الملف الشخصي: {ChecksSettings["obligation_profile_picture"]}

أسماء محظورة...
• الاسم العربي: {ChecksSettings["block_arabic_name"]}
• الاسم الصيني: {ChecksSettings["block_chinese_name"]}
• الاسم الروسي: {ChecksSettings["block_russian_name"]}
• الاسم سبام: {ChecksSettings["block_spam_name"]}

🚪 **التحقق عند الانضمام**
إذا كان مفعلاً، سيقوم البوت بالتحقق من الالتزامات والحظر عند انضمام المستخدمين إلى المجموعة، بالإضافة إلى عند إرسال الرسائل.
الحالة: {'مفعل ✔️' if ChecksSettings["check_at_the_join"] else 'معطل ✖️'}

🗑 **حذف الرسائل**
إذا كان مفعلاً، سيقوم البوت بحذف الرسائل التي يرسلها المستخدمون الذين لا يمتثلون للالتزامات/محظورات.
حذف الرسائل: {'نعم ✔️' if ChecksSettings["delete_msg"] else 'لا ✖️'}
'''

    # • إلزام القناة: {ChecksSettings["obligation_channel_obligation"]}
    # • إلزام الإضافة: {ChecksSettings["obligation_obligation_to_add"]}
    
    buttons = [
        [
            Button.inline(f"الالتزامات", f"ObligationsChecks_{target_group_id}"),
            Button.inline(f"أسماء محظورة", f"BlocksChecks_{target_group_id}")
        ],
        [
            Button.inline(f"🚪 التحقق عند الانضمام {'✔️' if ChecksSettings['check_at_the_join'] else '✖️'}", f"CheckAtJoinChecks_{target_group_id}"),
        ],
        [
            Button.inline(f"🗑 حذف الرسائل {'✔️' if ChecksSettings['delete_msg'] else '✖️'}", f"DeleteMsgChecks_{target_group_id}"),
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Check At Join Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"CheckAtJoinChecks_")))
async def CheckAtJoinChecks(event):

    target_group_id = str(event.data.decode()).replace('CheckAtJoinChecks_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]
    ChecksSettings["check_at_the_join"] = not ChecksSettings["check_at_the_join"]

    await SaveJsonGroupsData(groups_database)
    await Checks(event, group_ID=target_group_id)


# Delete Msg Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMsgChecks_")))
async def DeleteMsgChecks(event):

    target_group_id = str(event.data.decode()).replace('DeleteMsgChecks_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]
    ChecksSettings["delete_msg"] = not ChecksSettings["delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await Checks(event, group_ID=target_group_id)


# Obligations Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"ObligationsChecks_")))
async def ObligationsChecks(event, group_ID=None, showActions=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('ObligationsChecks_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]

    MSG = f'''
الالتزامات...
• بدون لقب: {ChecksSettings["obligation_surname"]}
• بدون اسم المستخدم: {ChecksSettings["obligation_username"]}
• بدون صورة الملف الشخصي: {ChecksSettings["obligation_profile_picture"]}

أسماء محظورة...
• الاسم العربي: {ChecksSettings["block_arabic_name"]}
• الاسم الصيني: {ChecksSettings["block_chinese_name"]}
• الاسم الروسي: {ChecksSettings["block_russian_name"]}
• الاسم سبام: {ChecksSettings["block_spam_name"]}

'''
    
    buttons = [
        [
            Button.inline(f"» الالتزامات «", f"ObligationsChecks_{target_group_id}"),
            Button.inline(f"أسماء محظورة", f"BlocksChecks_{target_group_id}")
        ]
    ]

    buttons.append([
        Button.inline(f"🫂 بدون لقب", f"ShowListChecks_surname_{target_group_id}"),
    ])

    if showActions == 'surname':
        buttons.append([
            Button.inline(f"❌ لا شي {'✅' if ChecksSettings['obligation_surname'] == 'Off' else ''}", f"setObligationSurnameChecks_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if ChecksSettings['obligation_surname'] == 'Warn' else ''}", f"setObligationSurnameChecks_Warn_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"❗️ طرد {'✅' if ChecksSettings['obligation_surname'] == 'Kick' else ''}", f"setObligationSurnameChecks_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if ChecksSettings['obligation_surname'] == 'Mute' else ''}", f"setObligationSurnameChecks_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if ChecksSettings['obligation_surname'] == 'Ban' else ''}", f"setObligationSurnameChecks_Ban_{target_group_id}")
        ])

    buttons.append([
        Button.inline(f"🌐 بدون اسم المستخدم", f"ShowListChecks_username_{target_group_id}"),
    ])

    if showActions == 'username':
        buttons.append([
            Button.inline(f"❌ لا شي {'✅' if ChecksSettings['obligation_username'] == 'Off' else ''}", f"setObligationUsernameChecks_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if ChecksSettings['obligation_username'] == 'Warn' else ''}", f"setObligationUsernameChecks_Warn_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"❗️ طرد {'✅' if ChecksSettings['obligation_username'] == 'Kick' else ''}", f"setObligationUsernameChecks_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if ChecksSettings['obligation_username'] == 'Mute' else ''}", f"setObligationUsernameChecks_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if ChecksSettings['obligation_username'] == 'Ban' else ''}", f"setObligationUsernameChecks_Ban_{target_group_id}")
        ])
    
    buttons.append([
        Button.inline(f"📸 بدون صورة الملف الشخصي", f"ShowListChecks_profilePic_{target_group_id}"),
    ])

    if showActions == 'profilePic':
        buttons.append([
            Button.inline(f"❌ لا شي {'✅' if ChecksSettings['obligation_profile_picture'] == 'Off' else ''}", f"setObligationProfilePicChecks_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if ChecksSettings['obligation_profile_picture'] == 'Warn' else ''}", f"setObligationProfilePicChecks_Warn_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"❗️ طرد {'✅' if ChecksSettings['obligation_profile_picture'] == 'Kick' else ''}", f"setObligationProfilePicChecks_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if ChecksSettings['obligation_profile_picture'] == 'Mute' else ''}", f"setObligationProfilePicChecks_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if ChecksSettings['obligation_profile_picture'] == 'Ban' else ''}", f"setObligationProfilePicChecks_Ban_{target_group_id}")
        ])
    
    # buttons.append([
    #     Button.inline(f"➕ Obligation to add 🆕", f"ShowListChecks_toAdd_{target_group_id}"),
    # ])
    
    # buttons.append([
    #     Button.inline(f"📣 Channel Obligation 🆕", f"ShowListChecks_channel_{target_group_id}"),
    # ])
    
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Show List Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"ShowListChecks_")))
async def ShowListChecks(event):

    showList, target_group_id = (str(event.data.decode()).replace('ShowListChecks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    if showList == "profilePic":
        # Check Paid Service & User VIP
        if bot_configs["NoProfilePicture_paid"]:
            is_vip = await check_user_vip(event, event.sender_id)
            if is_vip == False:
                buttons = [
                    [Button.inline('💳 شراء العضوية المدفوعة ⭐️', 'buy_vip')],
                    [Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")]
                ]
                await event.respond(f'''
📸 **بدون صورة الملف الشخصي**

لمستخدمين الذين ليس لديهم صورة في ملفهم الشخصي سيتم فرض عقوبة عليهم
                                    
🔰 **متاح فقط لـ المستخدمين المميزين**
''', buttons=buttons)
                return
        ################################# End VIP Check

    await ObligationsChecks(event, group_ID=target_group_id, showActions=showList)


# Set Obligation Surname Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setObligationSurnameChecks_")))
async def SetObligationSurnameChecks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setObligationSurnameChecks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]
    ChecksSettings["obligation_surname"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await ObligationsChecks(event, group_ID=target_group_id, showActions='surname')


# Set Obligation Username Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setObligationUsernameChecks_")))
async def SetObligationUsernameChecks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setObligationUsernameChecks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]
    ChecksSettings["obligation_username"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await ObligationsChecks(event, group_ID=target_group_id, showActions='username')


# Set Obligation Profile Pic Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setObligationProfilePicChecks_")))
async def SetObligationProfilePicChecks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setObligationProfilePicChecks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    # Check Paid Service & User VIP
    if bot_configs["NoProfilePicture_paid"]:
        is_vip = await check_user_vip(event, event.sender_id)
        if is_vip == False:
            buttons = [
                [Button.inline('💳 شراء العضوية المدفوعة ⭐️', 'buy_vip')],
                [Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")]
            ]
            await event.respond(f'''
📸 **بدون صورة الملف الشخصي**

لمستخدمين الذين ليس لديهم صورة في ملفهم الشخصي سيتم فرض عقوبة عليهم
                                
🔰 **متاح فقط لـ المستخدمين المميزين**
''', buttons=buttons)
            return
    ################################# End VIP Check

    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]
    ChecksSettings["obligation_profile_picture"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await ObligationsChecks(event, group_ID=target_group_id, showActions='profilePic')



# Blocks Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"BlocksChecks_")))
async def BlocksChecks(event, group_ID=None, showActions=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('BlocksChecks_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]

    MSG = f'''
الالتزامات...
• اللقب: {ChecksSettings["obligation_surname"]}
• اسم المستخدم: {ChecksSettings["obligation_username"]}
• صورة الملف الشخصي: {ChecksSettings["obligation_profile_picture"]}

أسماء محظورة...
• اسم عربي: {ChecksSettings["block_arabic_name"]}
• اسم صيني: {ChecksSettings["block_chinese_name"]}
• اسم روسي: {ChecksSettings["block_russian_name"]}
• اسم سبام: {ChecksSettings["block_spam_name"]}

'''
    
    buttons = [
        [
            Button.inline(f"الالتزامات", f"ObligationsChecks_{target_group_id}"),
            Button.inline(f"» أسماء محظورة «", f"BlocksChecks_{target_group_id}")
        ]
    ]

    buttons.append([
        Button.inline(f"☪️ منع أسماء عربية", f"ShowList2Checks_arabic_{target_group_id}"),
    ])

    if showActions == 'arabic':
        buttons.append([
            Button.inline(f"❌ لا شي {'✅' if ChecksSettings['block_arabic_name'] == 'Off' else ''}", f"setBlockArabicNameChecks_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if ChecksSettings['block_arabic_name'] == 'Warn' else ''}", f"setBlockArabicNameChecks_Warn_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"❗️ طرد {'✅' if ChecksSettings['block_arabic_name'] == 'Kick' else ''}", f"setBlockArabicNameChecks_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if ChecksSettings['block_arabic_name'] == 'Mute' else ''}", f"setBlockArabicNameChecks_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if ChecksSettings['block_arabic_name'] == 'Ban' else ''}", f"setBlockArabicNameChecks_Ban_{target_group_id}")
        ])

    buttons.append([
        Button.inline(f"🇨🇳 منع أسماء صينية", f"ShowList2Checks_chinese_{target_group_id}"),
    ])

    if showActions == 'chinese':
        buttons.append([
            Button.inline(f"❌ لا شي {'✅' if ChecksSettings['block_chinese_name'] == 'Off' else ''}", f"setBlockChineseNameChecks_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if ChecksSettings['block_chinese_name'] == 'Warn' else ''}", f"setBlockChineseNameChecks_Warn_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"❗️ طرد {'✅' if ChecksSettings['block_chinese_name'] == 'Kick' else ''}", f"setBlockChineseNameChecks_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if ChecksSettings['block_chinese_name'] == 'Mute' else ''}", f"setBlockChineseNameChecks_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if ChecksSettings['block_chinese_name'] == 'Ban' else ''}", f"setBlockChineseNameChecks_Ban_{target_group_id}")
        ])
    
    buttons.append([
        Button.inline(f"🇷🇺 منع أسماء روسية", f"ShowList2Checks_russian_{target_group_id}"),
    ])

    if showActions == 'russian':
        buttons.append([
            Button.inline(f"❌ لا شي {'✅' if ChecksSettings['block_russian_name'] == 'Off' else ''}", f"setBlockRussianNameChecks_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if ChecksSettings['block_russian_name'] == 'Warn' else ''}", f"setBlockRussianNameChecks_Warn_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"❗️ طرد {'✅' if ChecksSettings['block_russian_name'] == 'Kick' else ''}", f"setBlockRussianNameChecks_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if ChecksSettings['block_russian_name'] == 'Mute' else ''}", f"setBlockRussianNameChecks_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if ChecksSettings['block_russian_name'] == 'Ban' else ''}", f"setBlockRussianNameChecks_Ban_{target_group_id}")
        ])
    
    buttons.append([
        Button.inline(f"📩 منع أسماء سبام", f"ShowList2Checks_spam_{target_group_id}"),
    ])

    if showActions == 'spam':
        buttons.append([
            Button.inline(f"❌ لا شي {'✅' if ChecksSettings['block_spam_name'] == 'Off' else ''}", f"setBlockSpamNameChecks_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if ChecksSettings['block_spam_name'] == 'Warn' else ''}", f"setBlockSpamNameChecks_Warn_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"❗️ طرد {'✅' if ChecksSettings['block_spam_name'] == 'Kick' else ''}", f"setBlockSpamNameChecks_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if ChecksSettings['block_spam_name'] == 'Mute' else ''}", f"setBlockSpamNameChecks_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if ChecksSettings['block_spam_name'] == 'Ban' else ''}", f"setBlockSpamNameChecks_Ban_{target_group_id}")
        ])
    
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)



# Show List2 Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"ShowList2Checks_")))
async def ShowList2Checks(event):

    showList, target_group_id = (str(event.data.decode()).replace('ShowList2Checks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    await BlocksChecks(event, group_ID=target_group_id, showActions=showList)



# Set Block Arabic Name Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setBlockArabicNameChecks_")))
async def SetBlockArabicNameChecks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setBlockArabicNameChecks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]
    ChecksSettings["block_arabic_name"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await BlocksChecks(event, group_ID=target_group_id, showActions='arabic')


# Set Block Chinese Name Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setBlockChineseNameChecks_")))
async def SetBlockChineseNameChecks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setBlockChineseNameChecks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]
    ChecksSettings["block_chinese_name"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await BlocksChecks(event, group_ID=target_group_id, showActions='chinese')


# Set Block Russian Name Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setBlockRussianNameChecks_")))
async def SetBlockRussianNameChecks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setBlockRussianNameChecks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]
    ChecksSettings["block_russian_name"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await BlocksChecks(event, group_ID=target_group_id, showActions='russian')


# Set Block Spam Name Checks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setBlockSpamNameChecks_")))
async def SetBlockSpamNameChecks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setBlockSpamNameChecks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    ChecksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["checks"]
    ChecksSettings["block_spam_name"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await BlocksChecks(event, group_ID=target_group_id, showActions='spam')



#############################################################################

# blocks_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"blocks_")))
async def Blocks(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('blocks_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]

    MSG = f'''
🔐 القيود

من خلال هذا الإعداد، يمكنك تحديد مجموعة من القيود التي ستُطبق على المستخدمين في المجموعة. يمكنك تفعيل أو تعطيل هذه القيود بناءً على ما ترغب في تطبيقه
'''
    
    buttons = [
        [
            Button.inline(f"📛 القائمة السوداء", f"blacklistBlocks_{target_group_id}")
        ],
        [
            Button.inline(f"🤖 قيود البوت", f"BotBlockBlocks_{target_group_id}")
        ],
        [
            Button.inline(f"👨🏼‍🦱 قيود الانضمام 🆕", f"JoinBlockBlocks_{target_group_id}"),
            Button.inline(f"🚪 قيود المغادرة 🆕", f"LeaveBlockBlocks_{target_group_id}")
        ],
        [
            Button.inline(f"🏃‍♂️ قيود الانضمام والمغادرة", f"JoinLeaveBlockBlocks_{target_group_id}"),
        ],
        [
            Button.inline(f"🫂 قيود الانضمام المتعدد", f"MultipleJoinBlockBlocks_{target_group_id}"),
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Blacklist Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"blacklistBlocks_")))
async def BlacklistBlocks(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('blacklistBlocks_', ''))
    else:
        target_group_id = int(group_ID)

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    
    blacklist_penalty = BlocksSettings["blacklist"]["penalty"]
    if blacklist_penalty == "Deactivated":
        blacklist_status = "معطل ❌"
        description = ""
    else:
        blacklist_status = f"مفعل ({blacklist_penalty}) ✅"
        description = f" └ Blocklisted users will be **{blacklist_penalty} at the entrance.**"

    MSG = f'''
📛 **القائمة السوداء**

من خلال هذه القائمة يمكنك إدارة قوائم المستخدمين الذين سيتم حظرهم تلقائيًا عند انضمامهم إلى المجموعة.
➖➖➖➖➖➖➖➖➖➖
🚷 **القائمة المحظورة** ➔ {blacklist_status}
القائمة المحظورة هي قائمة سوداء عالمية تم إنشاؤها وإدارتها من قبل موظفي البوت.

⚠️ **تنبيه**: المستخدمون في هذه القائمة تسببوا في أضرار كبيرة للمجموعات الأخرى، لذا **نحن لا نوصي بإلغاء تفعيلها!**

💡 العقاب: {blacklist_status}
'''
    # {description}
    
    buttons = [
        # [
        #     Button.url(f"🚷 Blocklist", "http://t.me/+z0OtxcV030I0NjI5")
        # ],
        [
            Button.inline(f"تعطيل ❌", f"setPenaltyBlocks_Deactivated_{target_group_id}"),
            Button.inline(f"🚷 حظر", f"setPenaltyBlocks_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"🔇 كتم", f"setPenaltyBlocks_Mute_{target_group_id}"),
        ]
    ]
    
    buttons.append([Button.inline("🔙 الرجوع", f"BackToBlockListMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Set Penalty Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setPenaltyBlocks_")))
async def SetPenaltyBlocks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setPenaltyBlocks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    BlocksSettings["blacklist"]["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await BlacklistBlocks(event, group_ID=target_group_id)


# Bot Block Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"BotBlockBlocks_")))
async def BotBlockBlocks(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('BotBlockBlocks_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]

    MSG = f'''
🤖 **قيود البوتات**

إذا قمت بتفعيل هذه الميزة، فلن يتمكن المستخدمون من إضافة البوتات إلى المجموعة.
يمكنك أيضًا اختيار العقوبة للمستخدمين الذين يحاولون القيام بذلك.

الحالة: {'مفعل ✔️' if BlocksSettings["bot_block"]["is_active"] else 'معطل ✖️'}
العقاب: {BlocksSettings["bot_block"]["penalty"]}
'''
    
    buttons = [
        [
            Button.inline(f"✖️ ايقاف", f"TurnOffBlocks_{target_group_id}"),
            Button.inline(f"✔️ تشغيل", f"TurnOnBlocks_{target_group_id}")
        ],
        [
            Button.inline(f"❌ لا شي {'✅' if BlocksSettings['bot_block']['penalty'] == 'Off' else ''}", f"setBotBlockPenaltyBlocks_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if BlocksSettings['bot_block']['penalty']  == 'Warn' else ''}", f"setBotBlockPenaltyBlocks_Warn_{target_group_id}")
        ],
        [
            Button.inline(f"❗️ طرد {'✅' if BlocksSettings['bot_block']['penalty']  == 'Kick' else ''}", f"setBotBlockPenaltyBlocks_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if BlocksSettings['bot_block']['penalty']  == 'Mute' else ''}", f"setBotBlockPenaltyBlocks_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if BlocksSettings['bot_block']['penalty']  == 'Ban' else ''}", f"setBotBlockPenaltyBlocks_Ban_{target_group_id}")
        ]
    ]

 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToBlockListMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Turn Off Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOffBlocks_")))
async def TurnOffBlocks(event):

    target_group_id = str(event.data.decode()).replace('TurnOffBlocks_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    BlocksSettings["bot_block"]["is_active"] = False

    await SaveJsonGroupsData(groups_database)
    await BotBlockBlocks(event, group_ID=target_group_id)


# Turn On Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOnBlocks_")))
async def TurnOnBlocks(event):

    target_group_id = str(event.data.decode()).replace('TurnOnBlocks_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    BlocksSettings["bot_block"]["is_active"] = True

    await SaveJsonGroupsData(groups_database)
    await BotBlockBlocks(event, group_ID=target_group_id)



# Set Bot Block Penalty Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setBotBlockPenaltyBlocks_")))
async def SetBotBlockPenaltyBlocks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setBotBlockPenaltyBlocks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    BlocksSettings["bot_block"]["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await BotBlockBlocks(event, group_ID=target_group_id)



# Join Block Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"JoinBlockBlocks_")))
async def JoinBlockBlocks(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('JoinBlockBlocks_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]

    MSG = f'''
👨🏼 **قيود الانضمام**

اعطِ عقوبة للمستخدمين أو الروبوتات الذين يحاولون الانضمام إلى المجموعة.

الحالة: {BlocksSettings["join_block"]["penalty"]}
'''
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if BlocksSettings['join_block']['penalty'] == 'Off' else ''}", f"setJoinBlockPenaltyBlocks_Off_{target_group_id}"),
        ],
        [
            Button.inline(f"❗️ طرد {'✅' if BlocksSettings['join_block']['penalty']  == 'Kick' else ''}", f"setJoinBlockPenaltyBlocks_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if BlocksSettings['join_block']['penalty']  == 'Mute' else ''}", f"setJoinBlockPenaltyBlocks_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if BlocksSettings['join_block']['penalty']  == 'Ban' else ''}", f"setJoinBlockPenaltyBlocks_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"♻️ حذف رسالة الدخول {'✔️' if BlocksSettings['join_block']['delete_join_msg'] else '✖️'}", f"DeleteMsgJoinBlockBlocks_{target_group_id}")
        ]
    ]

 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToBlockListMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Set Join Block Penalty Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setJoinBlockPenaltyBlocks_")))
async def SetJoinBlockPenaltyBlocks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setJoinBlockPenaltyBlocks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    BlocksSettings["join_block"]["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await JoinBlockBlocks(event, group_ID=target_group_id)


# Delete Msg Join Block Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMsgJoinBlockBlocks_")))
async def DeleteMsgJoinBlockBlocks(event):

    target_group_id = str(event.data.decode()).replace('DeleteMsgJoinBlockBlocks_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    BlocksSettings["join_block"]["delete_join_msg"] = not BlocksSettings["join_block"]["delete_join_msg"]

    await SaveJsonGroupsData(groups_database)
    await JoinBlockBlocks(event, group_ID=target_group_id)



# Leave Block Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"LeaveBlockBlocks_")))
async def LeaveBlockBlocks(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('LeaveBlockBlocks_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]

    MSG = f'''
🚪 **قيود الخروج**

حظر للمستخدمين الذين يتركون المجموعة.

الحالة: {BlocksSettings["leave_block"]["penalty"]}
'''
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if BlocksSettings['leave_block']['penalty'] == 'Off' else ''}", f"setLeaveBlockPenaltyBlocks_Off_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if BlocksSettings['leave_block']['penalty']  == 'Ban' else ''}", f"setLeaveBlockPenaltyBlocks_Ban_{target_group_id}")
        ]
    ]

 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToBlockListMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Set Leave Block Penalty Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setLeaveBlockPenaltyBlocks_")))
async def SetLeaveBlockPenaltyBlocks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setLeaveBlockPenaltyBlocks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    BlocksSettings["leave_block"]["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await LeaveBlockBlocks(event, group_ID=target_group_id)



# Join-Leave Block Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"JoinLeaveBlockBlocks_")))
async def JoinLeaveBlockBlocks(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('JoinLeaveBlockBlocks_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    # Check Paid Service & User VIP
    if bot_configs["joinLeaveFast_paid"]:
        is_vip = await check_user_vip(event, event.sender_id)
        if is_vip == False:
            buttons = [
                [Button.inline('💳 شراء العضوية المدفوعة ⭐️', 'buy_vip')],
                [Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")]
            ]
            await event.respond(f'''
🏃‍♂️ **قيود الانضمام والخروج**

إذا غادر المستخدم المجموعة بعد ثوانٍ قليلة من الانضمام، سيتم حذف رسالة الخدمة.
يمكنك أيضًا تعيين عقوبة لهؤلاء المستخدمين.
                                
🔰 **متاح فقط لـ المستخدمين المميزين**
''', buttons=buttons)
            return
    ################################# End VIP Check


    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]

    MSG = f'''
🏃‍♂️ **قيود الانضمام والخروج**

إذا غادر المستخدم المجموعة بعد ثوانٍ قليلة من الانضمام، سيتم حذف رسالة الخدمة.
يمكنك أيضًا تعيين عقوبة لهؤلاء المستخدمين.

الحالة: {BlocksSettings["joinLeave_block"]["penalty"]}
'''
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if BlocksSettings['joinLeave_block']['penalty'] == 'Off' else ''}", f"setJoinLeavePenaltyBlocks_Off_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if BlocksSettings['joinLeave_block']['penalty']  == 'Ban' else ''}", f"setJoinLeavePenaltyBlocks_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"♻️ حذف رسالة الخدمة {'✔️' if BlocksSettings['joinLeave_block']['delete_service_msg'] else '✖️'}", f"DeleteServiceMsgJoinLeaveBlockBlocks_{target_group_id}")
        ],
        # [
        #     Button.inline(f"♻️ Delete welcome message {'✔️' if BlocksSettings['joinLeave_block']['delete_welcome_msg'] else '✖️'}", f"DeleteWelcomeMsgJoinLeaveBlockBlocks_{target_group_id}")
        # ]
    ]

    buttons.append([Button.inline("🔙 الرجوع", f"BackToBlockListMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Set Join-Leave Block Penalty Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setJoinLeavePenaltyBlocks_")))
async def SetJoinLeavePenaltyBlocks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setJoinLeavePenaltyBlocks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    BlocksSettings["joinLeave_block"]["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await JoinLeaveBlockBlocks(event, group_ID=target_group_id)


# Delete Service Msg Join Leave Block Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteServiceMsgJoinLeaveBlockBlocks_")))
async def DeleteServiceMsgJoinLeaveBlockBlocks(event):

    target_group_id = str(event.data.decode()).replace('DeleteServiceMsgJoinLeaveBlockBlocks_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    BlocksSettings["joinLeave_block"]["delete_service_msg"] = not BlocksSettings["joinLeave_block"]["delete_service_msg"]

    await SaveJsonGroupsData(groups_database)
    await JoinLeaveBlockBlocks(event, group_ID=target_group_id)



# Delete Welcome Msg Join Leave Block Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteWelcomeMsgJoinLeaveBlockBlocks_")))
async def DeleteWelcomeMsgJoinLeaveBlockBlocks(event):

    target_group_id = str(event.data.decode()).replace('DeleteWelcomeMsgJoinLeaveBlockBlocks_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    BlocksSettings["joinLeave_block"]["delete_welcome_msg"] = not BlocksSettings["joinLeave_block"]["delete_welcome_msg"]

    await SaveJsonGroupsData(groups_database)
    await JoinLeaveBlockBlocks(event, group_ID=target_group_id)



# Multiple Join Block Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"MultipleJoinBlockBlocks_")))
async def MultipleJoinBlockBlocks(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('MultipleJoinBlockBlocks_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]

    MSG = f'''
👨‍👩‍👧‍👦 **قيود الانضمام المتعدد**

قم بتعيين عقوبة إذا انضم {BlocksSettings["multiplejoins_block"]["users_count"]} مستخدمين إلى المجموعة في {BlocksSettings["multiplejoins_block"]["time"]} ثانية.

الحالة: {BlocksSettings["multiplejoins_block"]["penalty"]}
'''
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if BlocksSettings['multiplejoins_block']['penalty'] == 'Off' else ''}", f"setMultipleJoinPenaltyBlocks_Off_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if BlocksSettings['multiplejoins_block']['penalty'] == 'Mute' else ''}", f"setMultipleJoinPenaltyBlocks_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if BlocksSettings['multiplejoins_block']['penalty']  == 'Ban' else ''}", f"setMultipleJoinPenaltyBlocks_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"🚪 عدد المنظمين", f"JoinsMultipleJoinBlocks_{target_group_id}"),
            Button.inline(f"🕧 المدة", f"TimeMultipleJoinBlocks_{target_group_id}")
        ]
    ]

    buttons.append([Button.inline("🔙 الرجوع", f"BackToBlockListMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# set Multiple Join Penalty Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setMultipleJoinPenaltyBlocks_")))
async def SetMultipleJoinPenaltyBlocks(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setMultipleJoinPenaltyBlocks_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    BlocksSettings["multiplejoins_block"]["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await MultipleJoinBlockBlocks(event, group_ID=target_group_id)


# Joins Multiple Join Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"JoinsMultipleJoinBlocks_")))
async def JoinsMultipleJoinBlocks(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('JoinsMultipleJoinBlocks_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]

    MSG = f'''
هنا يمكنك تحديد الحد الأقصى لعدد الانضمام إلى المجموعة المسموح به في فترة الزمن المحددة.
⚠️ لا يُوصى بتحديد هذه القيمة لأكثر من 5 مستخدمين.

حاليًا، يتم تفعيل حظر الانضمام المتعدد إذا انضم {BlocksSettings["multiplejoins_block"]["users_count"]} مستخدمين خلال {BlocksSettings["multiplejoins_block"]["time"]} ثانية.
'''
    
    buttons = [
        [
            Button.inline(f"2", f"setJoinsMultiplejoins_2_{target_group_id}"),
            Button.inline(f"3", f"setJoinsMultiplejoins_3_{target_group_id}"),
            Button.inline(f"4", f"setJoinsMultiplejoins_4_{target_group_id}"),
            Button.inline(f"5", f"setJoinsMultiplejoins_5_{target_group_id}")
        ],
        [
            Button.inline(f"6", f"setJoinsMultiplejoins_6_{target_group_id}"),
            Button.inline(f"7", f"setJoinsMultiplejoins_7_{target_group_id}"),
            Button.inline(f"8", f"setJoinsMultiplejoins_8_{target_group_id}"),
            Button.inline(f"10", f"setJoinsMultiplejoins_10_{target_group_id}")
        ],
        [
            Button.inline(f"12", f"setJoinsMultiplejoins_12_{target_group_id}"),
            Button.inline(f"15", f"setJoinsMultiplejoins_15_{target_group_id}"),
            Button.inline(f"20", f"setJoinsMultiplejoins_20_{target_group_id}"),
            Button.inline(f"25", f"setJoinsMultiplejoins_25_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToMultipleJoinsMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Set Joins Multiple joins
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setJoinsMultiplejoins_")))
async def SetJoinsMultiplejoins(event):

    new_joins, target_group_id = (str(event.data.decode()).replace('setJoinsMultiplejoins_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiFloodSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    AntiFloodSettings["multiplejoins_block"]["users_count"] = int(new_joins)

    await SaveJsonGroupsData(groups_database)
    await JoinsMultipleJoinBlocks(event, group_ID=target_group_id)



# Time Multiple Join Blocks
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TimeMultipleJoinBlocks_")))
async def TimeMultipleJoinBlocks(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('TimeMultipleJoinBlocks_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    BlocksSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]

    MSG = f'''
هنا يمكنك تحديد فترة الزمن بين الانضمام إلى المجموعة.

حاليًا، يتم تفعيل حظر الانضمام المتعدد إذا انضم {BlocksSettings["multiplejoins_block"]["users_count"]} مستخدمين خلال {BlocksSettings["multiplejoins_block"]["time"]} ثانية.
'''
    
    buttons = [
        [
            Button.inline(f"1", f"setTimeMultiplejoins_1_{target_group_id}"),
            Button.inline(f"2", f"setTimeMultiplejoins_2_{target_group_id}"),
            Button.inline(f"3", f"setTimeMultiplejoins_3_{target_group_id}"),
            Button.inline(f"4", f"setTimeMultiplejoins_4_{target_group_id}")
        ],
        [
            Button.inline(f"5", f"setTimeMultiplejoins_5_{target_group_id}"),
            Button.inline(f"6", f"setTimeMultiplejoins_6_{target_group_id}"),
            Button.inline(f"8", f"setTimeMultiplejoins_8_{target_group_id}"),
            Button.inline(f"10", f"setTimeMultiplejoins_10_{target_group_id}")
        ],
        [
            Button.inline(f"15", f"setTimeMultiplejoins_15_{target_group_id}"),
            Button.inline(f"20", f"setTimeMultiplejoins_20_{target_group_id}"),
            Button.inline(f"25", f"setTimeMultiplejoins_25_{target_group_id}"),
            Button.inline(f"30", f"setTimeMultiplejoins_30_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToMultipleJoinsMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Set Time Multiple joins
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setTimeMultiplejoins_")))
async def SetTimeMultiplejoins(event):

    new_time, target_group_id = (str(event.data.decode()).replace('setTimeMultiplejoins_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    AntiFloodSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["blocks"]
    AntiFloodSettings["multiplejoins_block"]["time"] = int(new_time)

    await SaveJsonGroupsData(groups_database)
    await TimeMultipleJoinBlocks(event, group_ID=target_group_id)


#############################################################################

# porn_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"porn_")))
async def Porn(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('porn_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    # Check Paid Service & User VIP
    if bot_configs["porn_paid"]:
        is_vip = await check_user_vip(event, event.sender_id)
        if is_vip == False:
            buttons = [
                [Button.inline('💳 شراء العضوية المدفوعة ⭐️', 'buy_vip')],
                [Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")]
            ]
            await event.respond(f'''
🔞 **المحتوى الإباحي**

من خلال هذه القائمة يمكنك تعيين عقوبة للمستخدمين الذين يرسلون محتوى إباحي أو متعلق بالأطفال أو العنف الدموي في المجموعة.

🔰 **متاح فقط لـ المستخدمين المميزين**
''', buttons=buttons)
            return
    ################################# End VIP Check


    PornSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["porn"]

    MSG = f'''
🔞 **المحتوى الإباحي**

من خلال هذه القائمة يمكنك تعيين عقوبة للمستخدمين الذين يرسلون محتوى إباحي أو متعلق بالأطفال أو العنف الدموي في المجموعة.

العقاب: {PornSettings["penalty"]}
حذف الرسالة: {'نعم ✔️' if PornSettings['delete_msg'] else 'لا ✖️'}
'''
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if PornSettings['penalty'] == 'Off' else ''}", f"setPornPenalty_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if PornSettings['penalty'] == 'Warn' else ''}", f"setPornPenalty_Warn_{target_group_id}"),
        ],
        [
            Button.inline(f"❗️ طرد {'✅' if PornSettings['penalty']  == 'Kick' else ''}", f"setPornPenalty_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if PornSettings['penalty']  == 'Mute' else ''}", f"setPornPenalty_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if PornSettings['penalty']  == 'Ban' else ''}", f"setPornPenalty_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"♻️ حذف الرسالة {'✔️' if PornSettings['delete_msg'] else '✖️'}", f"setDeleteMsgPorn_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Set Porn Penalty
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setPornPenalty_")))
async def SetPornPenalty(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setPornPenalty_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    PornSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["porn"]
    PornSettings["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await Porn(event, group_ID=target_group_id)


# Set Delete Msg Porn
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setDeleteMsgPorn_")))
async def SetDeleteMsgPorn(event):

    target_group_id = str(event.data.decode()).replace('setDeleteMsgPorn_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    PornSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["porn"]
    PornSettings["delete_msg"] = not PornSettings["delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await Porn(event, group_ID=target_group_id)




#############################################################################

# link_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"link_")))
async def Link(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('link_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    LinkSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["link"]

    MSG = f'''
🔗 **رابط المجموعة**

هنا يمكنك تعيين رابط المجموعة، الذي سيكون مرئيًا عند استخدام الأمر /link.

الحالة: {'مفعل ✔️' if LinkSettings["is_active"] else 'معطل ✖️'}
الرابط: {LinkSettings["url"]}
'''
    
    buttons = [
        [
            Button.inline(f"✍🏻 تعيين", f"setLink_{target_group_id}")
        ]
    ]

    if LinkSettings["url"] != "":
        buttons.append([Button.inline(f"🗑 حذف الرابط", f"setDeleteLink_{target_group_id}")])
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Set Link
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setLink_")))
async def SetLink(event):

    target_group_id = str(event.data.decode()).replace('setLink_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('❌ الغاء', f'cancel5_{target_group_id}')]
            ]
            await conv.send_message('حسنًا، أرسل لي رابط هذه المجموعة الآن:', buttons=buttons)
            new_url = (await conv.get_response()).message

        LinkSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["link"]
        LinkSettings["url"] = new_url
        LinkSettings["is_active"] = True

        await SaveJsonGroupsData(groups_database)

    except Exception as error:pass
    await Link(event, group_ID=target_group_id)


# Set Delete Link
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setDeleteLink_")))
async def SetDeleteLink(event):

    target_group_id = str(event.data.decode()).replace('setDeleteLink_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    LinkSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["link"]
    LinkSettings["url"] = ""
    LinkSettings["is_active"] = False

    await SaveJsonGroupsData(groups_database)
    await Link(event, group_ID=target_group_id)


# Cancel Conversation 5
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"cancel5_")))
async def CancelConversation5(event):

    target_group_id = int(str(event.data.decode()).replace('cancel5_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await Link(event, group_ID=target_group_id)

    except Exception as error:pass



#############################################################################

# nightMode_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"nightMode_")))
async def NightMode(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('nightMode_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    NightModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["night_mode"]

    MSG = f'''
🌒 **الوضع الليلي**

حدد الإجراءات التي ترغب في تقييدها كل ليلة.

الحالة: {'مفعل ✔️' if NightModeSettings["is_active"] else 'معطل ✖️'}
'''
    
    if NightModeSettings["is_active"]:
        MSG += f'''
الاجراء: {'📸 حذف الميديا' if NightModeSettings["delete_medias"] else ''} {'🤫 صمت كامل' if NightModeSettings["global_silence"] else ''}

⇐ بدأ الاجراء من ساعة {NightModeSettings["timeSlot_start"]} الى {NightModeSettings["timeSlot_end"]}
⇐ رسالة تنبيه البدأ و النهاية: {'✔️' if NightModeSettings["send_advices"] else '✖️'}
⇐ الوقت الحالي: {await get_current_time_in_timezone('Asia/Riyadh')}
'''
    
    buttons = [
        [
            Button.inline(f"✖️ ايقاف", f"TurnOffNightMode_{target_group_id}"),
            Button.inline(f"✔️ تشغيل", f"TurnOnNightMode_{target_group_id}")
        ]
    ]

    if NightModeSettings["is_active"]:
        buttons.append([
            Button.inline(f"📸 حذف الميديا", f"DeleteMediasNightMode_{target_group_id}"),
            Button.inline(f"🤫 صمت كامل", f"GlobalSilenceNightMode_{target_group_id}")
        ])

        buttons.append([
            Button.inline(f"⏱️ تحديد وقت ( البدأ )", f"TimeStartNightMode_{target_group_id}"),
            Button.inline(f"⏱️ تحديد وقت ( النهاية )", f"TimeEndNightMode_{target_group_id}")
        ])

        buttons.append([
            Button.inline(f"📣 تنبيه عند البدأ و النهاية {'✔️' if NightModeSettings['send_advices'] else '✖️'}", f"SendAvisesNightMode_{target_group_id}")
        ])
 

    buttons.append([Button.inline("🔙 الرجوع", f"BackToGroupSettingMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Turn Off Night Mode
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOffNightMode_")))
async def TurnOffNightMode(event):

    target_group_id = str(event.data.decode()).replace('TurnOffNightMode_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    NightModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["night_mode"]
    NightModeSettings["is_active"] = False

    if str(target_group_id) in groups_manager["nightMode_pending"]:
        del groups_manager["nightMode_pending"][str(target_group_id)]
        await SaveJsonGroupsManager(groups_manager)

    await SaveJsonGroupsData(groups_database)
    await NightMode(event, group_ID=target_group_id)


# Turn On Night Mode
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOnNightMode_")))
async def TurnOnNightMode(event):

    target_group_id = str(event.data.decode()).replace('TurnOnNightMode_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    NightModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["night_mode"]
    NightModeSettings["is_active"] = True

    if str(target_group_id) not in groups_manager["nightMode_pending"]:
        groups_manager["nightMode_pending"][str(target_group_id)] = {
            "posted_today": False,
            "delete_medias": NightModeSettings["delete_medias"],
            "global_silence": NightModeSettings["global_silence"],
            "send_advices": NightModeSettings["send_advices"],
            "timeSlot_start": NightModeSettings["timeSlot_start"],
            "timeSlot_end": NightModeSettings["timeSlot_end"],
            "timezone": NightModeSettings["timezone"]
        }

    await SaveJsonGroupsManager(groups_manager)
    await SaveJsonGroupsData(groups_database)
    await NightMode(event, group_ID=target_group_id)


# Delete Medias Night Mode
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMediasNightMode_")))
async def DeleteMediasNightMode(event):

    target_group_id = str(event.data.decode()).replace('DeleteMediasNightMode_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    NightModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["night_mode"]
    NightModeSettings["delete_medias"] = True
    NightModeSettings["global_silence"] = False

    groups_manager["nightMode_pending"][str(target_group_id)]["delete_medias"] = True
    groups_manager["nightMode_pending"][str(target_group_id)]["global_silence"] = False
    
    await SaveJsonGroupsManager(groups_manager)
    await SaveJsonGroupsData(groups_database)
    await NightMode(event, group_ID=target_group_id)


# Global Silence Night Mode
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"GlobalSilenceNightMode_")))
async def GlobalSilenceNightMode(event):

    target_group_id = str(event.data.decode()).replace('GlobalSilenceNightMode_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    NightModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["night_mode"]
    NightModeSettings["global_silence"] = True
    NightModeSettings["delete_medias"] = False

    groups_manager["nightMode_pending"][str(target_group_id)]["delete_medias"] = False
    groups_manager["nightMode_pending"][str(target_group_id)]["global_silence"] = True
    
    await SaveJsonGroupsManager(groups_manager)
    await SaveJsonGroupsData(groups_database)
    await NightMode(event, group_ID=target_group_id)


# Send Avises Night Mode
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"SendAvisesNightMode_")))
async def SendAvisesNightMode(event):

    target_group_id = str(event.data.decode()).replace('SendAvisesNightMode_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    NightModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["night_mode"]
    NightModeSettings["send_advices"] = not NightModeSettings["send_advices"]

    groups_manager["nightMode_pending"][str(target_group_id)]["send_advices"] = not NightModeSettings["send_advices"]

    await SaveJsonGroupsManager(groups_manager)
    await SaveJsonGroupsData(groups_database)
    await NightMode(event, group_ID=target_group_id)


# Time Start Night Mode
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TimeStartNightMode_")))
async def TimeStartNightMode(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('TimeStartNightMode_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    NightModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["night_mode"]

    MSG = f'''
🌒 **الوضع الليلي**

من خلال هذا القائمة يمكنك تحديد فترة زمنية من الساعات، وفي هذه الساعات سيتم تفعيل وضع الليل كل يوم.

👉🏻 **حدد وقت البدء:**
'''
    
    buttons = [
        [
            Button.inline(f"1", f"setTimeStartNightMode_1_{target_group_id}"),
            Button.inline(f"2", f"setTimeStartNightMode_2_{target_group_id}"),
            Button.inline(f"3", f"setTimeStartNightMode_3_{target_group_id}"),
            Button.inline(f"4", f"setTimeStartNightMode_4_{target_group_id}")
        ],
        [
            Button.inline(f"5", f"setTimeStartNightMode_5_{target_group_id}"),
            Button.inline(f"6", f"setTimeStartNightMode_6_{target_group_id}"),
            Button.inline(f"7", f"setTimeStartNightMode_7_{target_group_id}"),
            Button.inline(f"8", f"setTimeStartNightMode_8_{target_group_id}"),
            Button.inline(f"9", f"setTimeStartNightMode_9_{target_group_id}")
        ],
        [
            Button.inline(f"10", f"setTimeStartNightMode_10_{target_group_id}"),
            Button.inline(f"11", f"setTimeStartNightMode_11_{target_group_id}"),
            Button.inline(f"12", f"setTimeStartNightMode_12_{target_group_id}"),
            Button.inline(f"13", f"setTimeStartNightMode_13_{target_group_id}"),
            Button.inline(f"14", f"setTimeStartNightMode_14_{target_group_id}")
        ],
        [
            Button.inline(f"15", f"setTimeStartNightMode_15_{target_group_id}"),
            Button.inline(f"16", f"setTimeStartNightMode_16_{target_group_id}"),
            Button.inline(f"17", f"setTimeStartNightMode_17_{target_group_id}"),
            Button.inline(f"18", f"setTimeStartNightMode_18_{target_group_id}"),
            Button.inline(f"19", f"setTimeStartNightMode_19_{target_group_id}")
        ],
        [
            Button.inline(f"20", f"setTimeStartNightMode_20_{target_group_id}"),
            Button.inline(f"21", f"setTimeStartNightMode_21_{target_group_id}"),
            Button.inline(f"22", f"setTimeStartNightMode_22_{target_group_id}"),
            Button.inline(f"23", f"setTimeStartNightMode_23_{target_group_id}"),
            Button.inline(f"00", f"setTimeStartNightMode_00_{target_group_id}"),
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToNightModeMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Time End Night Mode
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TimeEndNightMode_")))
async def TimeEndNightMode(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('TimeEndNightMode_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    NightModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["night_mode"]

    MSG = f'''
🌒 **الوضع الليلي**

في هذه القائمة، يمكنك تحديد فترة زمنية، وخلال هذه الساعات سيتم الغاء تفعيل وضع الليل كل يوم.

👉🏻 حدد وقت الانتهاء:
'''
    
    buttons = [
        [
            Button.inline(f"1", f"setTimeEndNightMode_1_{target_group_id}"),
            Button.inline(f"2", f"setTimeEndNightMode_2_{target_group_id}"),
            Button.inline(f"3", f"setTimeEndNightMode_3_{target_group_id}"),
            Button.inline(f"4", f"setTimeEndNightMode_4_{target_group_id}")
        ],
        [
            Button.inline(f"5", f"setTimeEndNightMode_5_{target_group_id}"),
            Button.inline(f"6", f"setTimeEndNightMode_6_{target_group_id}"),
            Button.inline(f"7", f"setTimeEndNightMode_7_{target_group_id}"),
            Button.inline(f"8", f"setTimeEndNightMode_8_{target_group_id}"),
            Button.inline(f"9", f"setTimeEndNightMode_9_{target_group_id}")
        ],
        [
            Button.inline(f"10", f"setTimeEndNightMode_10_{target_group_id}"),
            Button.inline(f"11", f"setTimeEndNightMode_11_{target_group_id}"),
            Button.inline(f"12", f"setTimeEndNightMode_12_{target_group_id}"),
            Button.inline(f"13", f"setTimeEndNightMode_13_{target_group_id}"),
            Button.inline(f"14", f"setTimeEndNightMode_14_{target_group_id}")
        ],
        [
            Button.inline(f"15", f"setTimeEndNightMode_15_{target_group_id}"),
            Button.inline(f"16", f"setTimeEndNightMode_16_{target_group_id}"),
            Button.inline(f"17", f"setTimeEndNightMode_17_{target_group_id}"),
            Button.inline(f"18", f"setTimeEndNightMode_18_{target_group_id}"),
            Button.inline(f"19", f"setTimeEndNightMode_19_{target_group_id}")
        ],
        [
            Button.inline(f"20", f"setTimeEndNightMode_20_{target_group_id}"),
            Button.inline(f"21", f"setTimeEndNightMode_21_{target_group_id}"),
            Button.inline(f"22", f"setTimeEndNightMode_22_{target_group_id}"),
            Button.inline(f"23", f"setTimeEndNightMode_23_{target_group_id}"),
            Button.inline(f"00", f"setTimeEndNightMode_00_{target_group_id}"),
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"BackToNightModeMenu_{target_group_id}")])
    await event.respond(MSG, buttons=buttons)


# Set Time Start Night Mode
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setTimeStartNightMode_")))
async def SetTimeStartNightMode(event):

    new_time, target_group_id = (str(event.data.decode()).replace('setTimeStartNightMode_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    NightModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["night_mode"]
    NightModeSettings["timeSlot_start"] = int(new_time)

    groups_manager["nightMode_pending"][str(target_group_id)]["timeSlot_start"] = int(new_time)

    await SaveJsonGroupsManager(groups_manager)
    await SaveJsonGroupsData(groups_database)
    await NightMode(event, group_ID=target_group_id)


# Set Time End Night Mode
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setTimeEndNightMode_")))
async def SetTimeEndNightMode(event):

    new_time, target_group_id = (str(event.data.decode()).replace('setTimeEndNightMode_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    NightModeSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["night_mode"]
    NightModeSettings["timeSlot_end"] = int(new_time)

    groups_manager["nightMode_pending"][str(target_group_id)]["timeSlot_end"] = int(new_time)

    await SaveJsonGroupsManager(groups_manager)
    await SaveJsonGroupsData(groups_database)
    await NightMode(event, group_ID=target_group_id)



#############################################################################

# bannedWords_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"bannedWords_")))
async def bannedWords(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('bannedWords_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    BannedWordsSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["banned_words"]

    MSG = f'''
🔤 **الكلمات المحظورة**

من خلال هذه القائمة يمكنك تحديد العقوبة للمستخدمين الذين يستخدمون الكلمات التي تقرر حظرها.

العقاب: {BannedWordsSettings["penalty"]}
حذف الرسالة: {'نعم ✔️' if BannedWordsSettings['delete_msg'] else 'لا ✖️'}
'''
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if BannedWordsSettings['penalty'] == 'Off' else ''}", f"setBannedWordsPenalty_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if BannedWordsSettings['penalty'] == 'Warn' else ''}", f"setBannedWordsPenalty_Warn_{target_group_id}"),
        ],
        [
            Button.inline(f"❗️ طرد {'✅' if BannedWordsSettings['penalty']  == 'Kick' else ''}", f"setBannedWordsPenalty_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if BannedWordsSettings['penalty']  == 'Mute' else ''}", f"setBannedWordsPenalty_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if BannedWordsSettings['penalty']  == 'Ban' else ''}", f"setBannedWordsPenalty_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"♻️ حذف الرسالة {'✔️' if BannedWordsSettings['delete_msg'] else '✖️'}", f"setDeleteMsgBannedWords_{target_group_id}")
        ],
        [
            Button.inline(f"➕ أضف كلمة", f"addBannedWords_{target_group_id}"),
            Button.inline(f"➖ حذف كلمة", f"removeBannedWords_{target_group_id}"),
        ],
        [
            Button.inline(f"🔤 الكلمات المحظورة", f"showListBannedWords_{target_group_id}"),
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"nextList_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Set Banned Words Penalty
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setBannedWordsPenalty_")))
async def SetBannedWordsPenalty(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setBannedWordsPenalty_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BannedWordsSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["banned_words"]
    BannedWordsSettings["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await bannedWords(event, group_ID=target_group_id)


# Set Delete Msg Banned Words
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setDeleteMsgBannedWords_")))
async def SetDeleteMsgBannedWords(event):

    target_group_id = str(event.data.decode()).replace('setDeleteMsgBannedWords_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BannedWordsSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["banned_words"]
    BannedWordsSettings["delete_msg"] = not BannedWordsSettings["delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await bannedWords(event, group_ID=target_group_id)


# Add Banned Words
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"addBannedWords_")))
async def AddBannedWords(event):

    target_group_id = str(event.data.decode()).replace('addBannedWords_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BannedWordsSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["banned_words"]
    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            cancel_buttons = [
                [Button.inline('❌ الغاء', f'cancel6_{target_group_id}')]
            ]

            await conv.send_message('''
حسنًا، الآن أرسل كلمة أو أكثر ستتم حظرها من المجموعة.

لإرسال المزيد من الكلمات، أرسل كل كلمة في سطر منفصل.

مثال:
يا غبي
غبي
تبا لك
''', buttons=cancel_buttons)
            words_list = (await conv.get_response()).message
            
        words = words_list.split('\n')
        for word in words:
            if word != "" and word not in BannedWordsSettings["banned_words_list"]:
                BannedWordsSettings["banned_words_list"].append(word)

        buttons = [
            [Button.inline('🔙 الرجوع', f'cancel6_{target_group_id}')]
        ]
        await event.respond('تم إضافة الكلمات المحظورة!', buttons=buttons)

    except Exception as error:pass

    await SaveJsonGroupsData(groups_database)


# Remove Banned Words
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeBannedWords_")))
async def RemoveBannedWords(event):

    target_group_id = str(event.data.decode()).replace('removeBannedWords_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BannedWordsSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["banned_words"]
    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            cancel_buttons = [
                [Button.inline('❌ الغاء', f'cancel6_{target_group_id}')]
            ]

            await conv.send_message('''
حسنًا، الآن أرسل كلمة أو أكثر لن يتم حظرها بعد الآن من المجموعة.

لإزالة كلمات إضافية، أرسل كل كلمة في سطر منفصل.
                                    
مثال:
يا غبي
غبي
تبا لك
''', buttons=cancel_buttons)
            words_list = (await conv.get_response()).message
            
        words = words_list.split('\n')
        for word in words:
            if word in BannedWordsSettings["banned_words_list"]:
                BannedWordsSettings["banned_words_list"].remove(word)

        buttons = [
            [Button.inline('🔙 الرجوع', f'cancel6_{target_group_id}')]
        ]
        await event.respond('تم إزالة الكلمات المحظورة!', buttons=buttons)

    except Exception as error:pass

    await SaveJsonGroupsData(groups_database)


# Cancel Conversation 6
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"cancel6_")))
async def CancelConversation6(event):

    target_group_id = int(str(event.data.decode()).replace('cancel6_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await bannedWords(event, group_ID=target_group_id)

    except Exception as error:pass


# Show List Banned Words
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showListBannedWords_")))
async def ShowListBannedWords(event):

    target_group_id = str(event.data.decode()).replace('showListBannedWords_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    BannedWordsSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["banned_words"]
    await DeleteEvent(event)

    back_buttons = [
        [Button.inline('🔙 الرجوع', f'cancel6_{target_group_id}')]
    ]

    bannedWords_msg = '**قائمة الكلمات المحظورة في هذه المجموعة:**\n\n'
    for word in BannedWordsSettings["banned_words_list"]:
        bannedWords_msg += f'{word}\n'

    await event.respond(bannedWords_msg, buttons=back_buttons, link_preview=False)
    await SaveJsonGroupsData(groups_database)



#############################################################################

# membersManagement_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"membersManagement_")))
async def MembersManagement(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('membersManagement_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)
    MSG = f'''
👥 **إدارة الأعضاء**

من خلال هذه القائمة يمكنك إدارة الإجراءات العامة على أعضاء المجموعة.
'''
    
    buttons = [
        [
            Button.inline(f"🔇 إلغاء كتم الجميع", f"ConfirmMembersManagement_unmute_{target_group_id}"),
            Button.inline(f"🚷 إلغاء الحظر عن الجميع", f"ConfirmMembersManagement_unban_{target_group_id}"),
        ],
        [
            Button.inline(f"❗️ طرد المستخدمين المكتومين", f"ConfirmMembersManagement_kickmuted_{target_group_id}"),
        ],
        [
            Button.inline(f"☠️ طرد الحسابات المحذوفة", f"ConfirmMembersManagement_kickdeleted_{target_group_id}")
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"nextList_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Confirm Members Management
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"ConfirmMembersManagement_")))
async def ConfirmMembersManagement(event):

    targetAction, target_group_id = (str(event.data.decode()).replace('ConfirmMembersManagement_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    if targetAction == 'unmute':text_action = '**إلغاء كتم** للجميع؟'
    if targetAction == 'unban':text_action = '**رفع الحظر** عن الجميع؟'
    if targetAction == 'kickmuted':text_action = '**طرد المستخدمين الذين تم كتمهم**'
    if targetAction == 'kickdeleted':text_action = '**طرد الحسابات المحذوفة؟**'

    MSG = f'''
❗️ هل أنت متأكد حقًا من القيام بـ {text_action}

⚠️ **تحذير:** هذه العملية غير قابلة للتراجع، بعد التأكيد لن يكون من الممكن إلغاء الأمر.
'''

    buttons = [
        [Button.inline("✅ تأكيد", f"StartActionMembersManagement_{targetAction}_{target_group_id}")]
    ]

    buttons.append([Button.inline("❌ الغاء", f"membersManagement_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Start Action Members Management
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"StartActionMembersManagement_")))
async def StartActionMembersManagement(event):

    targetAction, target_group_id = (str(event.data.decode()).replace('StartActionMembersManagement_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    if targetAction == 'unmute':text_action = 'إلغاء كتم'
    if targetAction == 'unban':text_action = 'إلغاء الحظر'
    if targetAction == 'kickmuted':text_action = 'طرد المستخدمين المكتومين'
    if targetAction == 'kickdeleted':text_action = 'طرد الحسابات المحذوفة'

    await event.reply(f'''⏳ **{text_action}** بدأ. عند الانتهاء من العملية سيتم إرسال رسالة.''')
    
    if targetAction == 'unmute':
        # Fetch muted users
        participants = await bot(GetParticipantsRequest(
            channel=int(target_group_id),
            filter=ChannelParticipantsBanned(q=''),
            offset=0, limit=1000, hash=0
        ))

        # Extract only muted & banned users
        muted_users = []

        for participant in participants.participants:
            # user_id = participant.peer.user_id
            if isinstance(participant, User):
                user_id = participant.id
                if participant.banned_rights:
                    until_date = participant.banned_rights.until_date
                    if participant.banned_rights.view_messages:pass
                    else:muted_users.append((user_id, until_date))

        # Print or return muted users
        for user in muted_users:
            user_id, until_date = user
            await bot.edit_permissions(int(target_group_id), user_id, send_messages=True)


    if targetAction == 'unban':
        # Fetch muted users
        participants = await bot(GetParticipantsRequest(
            channel=int(target_group_id),
            filter=ChannelParticipantsBanned(q=''),
            offset=0, limit=1000, hash=0
        ))

        # Extract only muted & banned users
        banned_users = []

        for participant in participants.participants:
            # user_id = participant.peer.user_id  # Extract user ID
            if isinstance(participant, User):
                user_id = participant.id
                if participant.banned_rights:  # Check if the user is banned/muted
                    until_date = participant.banned_rights.until_date  # Mute/Ban expiration
                    if participant.banned_rights.view_messages:banned_users.append((user_id, until_date))

        # Print or return banned users
        for user in banned_users:
            user_id, until_date = user
            await bot.edit_permissions(int(target_group_id), user_id, send_messages=True)


    if targetAction == 'kickmuted':
        # Fetch muted users
        participants = await bot(GetParticipantsRequest(
            channel=int(target_group_id),
            filter=ChannelParticipantsBanned(q=''),
            offset=0, limit=1000, hash=0
        ))

        # Extract only muted & banned users
        muted_users = []

        for participant in participants.participants:
            # user_id = participant.peer.user_id
            if isinstance(participant, User):
                user_id = participant.id
                if participant.banned_rights:
                    until_date = participant.banned_rights.until_date
                    if participant.banned_rights.view_messages:pass
                    else:muted_users.append((user_id, until_date))

        # Print or return muted users
        for user in muted_users:
            user_id, until_date = user
            await bot.edit_permissions(int(target_group_id), user_id, send_messages=False)
            await bot.edit_permissions(int(target_group_id), user_id)


    if targetAction == 'kickdeleted':
        # Fetch deleted users
        deleted_user_ids = []
        participants = await bot.get_participants(int(target_group_id), limit=5000)

        # Check each participant
        for participant in participants:
            if isinstance(participant, User) and participant.deleted:
                deleted_user_ids.append(participant.id)

        # Print or return muted users
        for user_id in deleted_user_ids:
            await bot.edit_permissions(int(target_group_id), user_id, send_messages=False)
            await bot.edit_permissions(int(target_group_id), user_id)

    await asyncio.sleep(5)
    await event.reply(f'''✅ **{text_action}**. تم الانتهاء من عملية''')



#############################################################################

# maskedUsers_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"maskedUsers_")))
async def MaskedUsers(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('maskedUsers_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    MaskedUsersSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["masked_users"]
    await DeleteEvent(event)

    MSG = f'''
😶‍🌫️ **المستخدمين المخفيين**

من خلال هذه القائمة، يمكنك تحديد العقوبة للمستخدمين الذين يكتبون في المجموعة متخفين وراء قناة.

ℹ️ يتيح تليجرام لكل مستخدم الكتابة في المجموعة من خلال إخفاء هويته عبر قناة يملكها.

👮🏻‍♂️ لا يمكن معرفة أي مستخدم يكتب عبر القناة وإذا كان هو المسؤول: هذه الحماية ستُطبّق على كل من يكتب عبر قناة.

🏃🏻 إذا كانت هذه الخيار مفعلًا، فإن المستخدم الذي كان يكتب عبر قناة سيكون قادرًا على الكتابة في المجموعة فقط من خلال هويته الحقيقية، ولن يكون قادرًا على الكتابة عبر قنوات أخرى بعد الآن.

الحالة: {'مفعل ✔️' if MaskedUsersSettings["is_active"] else 'معطل ✖️'}
حذف الرسائل: {'نعم ✔️' if MaskedUsersSettings["delete_msg"] else 'لا ✖️'}
'''
    
    buttons = [
        [
            Button.inline(f"✖️ ايقاف", f"TurnOffMaskedUsers_{target_group_id}"),
            Button.inline(f"✔️ تشغيل", f"TurnOnMaskedUsers_{target_group_id}"),
        ],
        [
            Button.inline(f"🗑 حذف الرسائل {'✔️' if MaskedUsersSettings['delete_msg'] else '✖️'}", f"DeleteMsgMaskedUsers_{target_group_id}"),
        ]
    ]
 
    buttons.append([Button.inline("🔙 الرجوع", f"nextList_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Turn Off Masked Users
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOffMaskedUsers_")))
async def TurnOffMaskedUsers(event):

    target_group_id = str(event.data.decode()).replace('TurnOffMaskedUsers_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    MaskedUsersSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["masked_users"]
    MaskedUsersSettings["is_active"] = False

    await SaveJsonGroupsData(groups_database)
    await MaskedUsers(event, group_ID=target_group_id)


# Turn On Masked Users
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOnMaskedUsers_")))
async def TurnOnMaskedUsers(event):

    target_group_id = str(event.data.decode()).replace('TurnOnMaskedUsers_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    MaskedUsersSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["masked_users"]
    MaskedUsersSettings["is_active"] = True

    await SaveJsonGroupsData(groups_database)
    await MaskedUsers(event, group_ID=target_group_id)


# Delete Msg Masked Users
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMsgMaskedUsers_")))
async def DeleteMsgMaskedUsers(event):

    target_group_id = str(event.data.decode()).replace('DeleteMsgMaskedUsers_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    MaskedUsersSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["masked_users"]
    MaskedUsersSettings["delete_msg"] = not MaskedUsersSettings["delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await MaskedUsers(event, group_ID=target_group_id)



#############################################################################

# discussionGroup_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"discussionGroup_")))
async def DiscussionGroup(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('discussionGroup_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    DiscussionGroupSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]
    await DeleteEvent(event)

    MSG = f'''
📣 **مجموعة المناقشة**  

من خلال هذه القائمة، يمكنك تحديد كيفية التعامل مع الرسائل المُعادة التوجيه من القناة المتصلة بهذه المجموعة: يمكنك اختيار حذفها أو إزالتها من الرسائل المثبتة.

💡 الحالة: {'مفعل ✔️' if DiscussionGroupSettings["is_active"] else 'معطل ✖️'}
'''
    
    buttons = [
        [
            Button.inline(f"✖️ ايقاف", f"TurnOffDiscussionGroup_{target_group_id}"),
            Button.inline(f"✔️ تشغيل", f"TurnOnDiscussionGroup_{target_group_id}"),
        ],
        [
            Button.inline(f"🗑 حذف الرسالة {'✔️' if DiscussionGroupSettings['delete_msg'] else '✖️'}", f"DeleteMsgDiscussionGroup_{target_group_id}"),
        ]
    ]

    if not DiscussionGroupSettings['delete_msg']:
        buttons.append([
            Button.inline(f"📌 إزالة من المثبت {'✔️' if DiscussionGroupSettings['remove_from_pin'] else '✖️'}", f"RemoveFromPinnedDiscussionGroup_{target_group_id}"),
        ])

    if DiscussionGroupSettings['remove_from_pin'] and not DiscussionGroupSettings['delete_msg']:
        buttons.append([
            Button.inline(f"🪧 التعليق الأول 📌", f"FirstCommentDiscussionGroup_{target_group_id}"),
        ])

 
    buttons.append([Button.inline("🔙 الرجوع", f"nextList_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Turn Off Discussion Group
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOffDiscussionGroup_")))
async def TurnOffDiscussionGroup(event):

    target_group_id = str(event.data.decode()).replace('TurnOffDiscussionGroup_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    DiscussionGroupSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]
    DiscussionGroupSettings["is_active"] = False

    await SaveJsonGroupsData(groups_database)
    await DiscussionGroup(event, group_ID=target_group_id)


# Turn On Discussion Group
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOnDiscussionGroup_")))
async def TurnOnDiscussionGroup(event):

    target_group_id = str(event.data.decode()).replace('TurnOnDiscussionGroup_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    DiscussionGroupSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]
    DiscussionGroupSettings["is_active"] = True

    await SaveJsonGroupsData(groups_database)
    await DiscussionGroup(event, group_ID=target_group_id)


# Delete Msg Discussion Group
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMsgDiscussionGroup_")))
async def DeleteMsgDiscussionGroup(event):

    target_group_id = str(event.data.decode()).replace('DeleteMsgDiscussionGroup_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    DiscussionGroupSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]
    DiscussionGroupSettings["delete_msg"] = not DiscussionGroupSettings["delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await DiscussionGroup(event, group_ID=target_group_id)


# Remove From Pinned Discussion Group
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"RemoveFromPinnedDiscussionGroup_")))
async def RemoveFromPinnedDiscussionGroup(event):

    target_group_id = str(event.data.decode()).replace('RemoveFromPinnedDiscussionGroup_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    DiscussionGroupSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]
    DiscussionGroupSettings["remove_from_pin"] = not DiscussionGroupSettings["remove_from_pin"]

    await SaveJsonGroupsData(groups_database)
    await DiscussionGroup(event, group_ID=target_group_id)


# First Comment Discussion Group
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"FirstCommentDiscussionGroup_")))
async def FirstCommentDiscussionGroup(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('FirstCommentDiscussionGroup_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    DiscussionGroupSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]
    await DeleteEvent(event)

    MSG = f'''
🪧 **التعليق الأول**  

من خلال هذا القائمة، يمكنك تعيين رسالة يتم إرسالها كأول تعليق على كل منشور من القناة المرتبطة بالمجموعة.

💡 الحالة: {'مفعل ✅' if DiscussionGroupSettings["first_comment"] else 'معطل ❌'}
'''
    
    buttons = [
        [
            Button.inline(f"✖️ ايقاف", f"TurnOffCustomizeMessageDiscussionGroup_{target_group_id}"),
            Button.inline(f"✔️ تشغيل", f"TurnOnCustomizeMessageDiscussionGroup_{target_group_id}"),
        ],
        [
            Button.inline(f"✍🏻 تخصيص الرسالة", f"CustomizeMessageDiscussionGroup_{target_group_id}"),
        ]
    ]

    buttons.append([Button.inline("🔙 الرجوع", f"discussionGroup_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Turn Off Customize Message Discussion Group
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOffCustomizeMessageDiscussionGroup_")))
async def TurnOffCustomizeMessageDiscussionGroup(event):

    target_group_id = int(str(event.data.decode()).replace('TurnOffCustomizeMessageDiscussionGroup_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    DiscussionGroupSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]
    DiscussionGroupSettings["first_comment"] = False

    await SaveJsonGroupsData(groups_database)
    await FirstCommentDiscussionGroup(event, group_ID=target_group_id)


# Turn On Customize Message Discussion Group
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"TurnOnCustomizeMessageDiscussionGroup_")))
async def TurnOnCustomizeMessageDiscussionGroup(event):

    target_group_id = int(str(event.data.decode()).replace('TurnOnCustomizeMessageDiscussionGroup_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    DiscussionGroupSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]
    DiscussionGroupSettings["first_comment"] = True

    await SaveJsonGroupsData(groups_database)
    await FirstCommentDiscussionGroup(event, group_ID=target_group_id)


# Customize Message Discussion Group
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"CustomizeMessageDiscussionGroup_")))
async def CustomizeMessageDiscussionGroup(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('CustomizeMessageDiscussionGroup_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    DiscussionGroup_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["text"]
    DiscussionGroup_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["media"]
    DiscussionGroup_buttons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["buttons"]
    
    MSG = f'''
🪧 **التعليق الأول**

📄 النص {'✅' if DiscussionGroup_text else '❌'}
📸 الميديا {'✅' if DiscussionGroup_media else '❌'}
🔠 الأزرار {'✅' if len(DiscussionGroup_buttons) != 0 else '❌'}

👉🏻 استخدم الأزرار أدناه لاختيار ما ترغب في تعيينه.
'''

    buttons = [
        [Button.inline("📄 النص", f"editDiscussionGroupText_{target_group_id}"), Button.inline("👀 عرض", f"showDiscussionGroupText_{target_group_id}")],
        [Button.inline("📸 الميديا", f"editDiscussionGroupMedia_{target_group_id}"), Button.inline("👀 عرض", f"showDiscussionGroupMedia_{target_group_id}")],
        [Button.inline("🔠 الأزرار", f"editDiscussionGroupUrlButtons_{target_group_id}"), Button.inline("👀 عرض", f"showDiscussionGroupUrlButtons_{target_group_id}")],
        [Button.inline("👀 عرض كامل", f"showDiscussionGroupAll_{target_group_id}")],
        [Button.inline("🔙 الرجوع", f"FirstCommentDiscussionGroup_{target_group_id}")]
    ]

    await event.respond(MSG, buttons=buttons)


# Edit Discussion Group Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editDiscussionGroupText_")))
async def EditDiscussionGroupText(event):

    target_group_id = int(str(event.data.decode()).replace('editDiscussionGroupText_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الرسالة', f'removeDiscussionGroupText_{target_group_id}')],
                [Button.inline('❌ الغاء', f'cancel7_{target_group_id}')]
            ]

            await conv.send_message('''👉🏻 أرسل الآن الرسالة التي ترغب في تعيينها.''', buttons=buttons)
            the_message = (await conv.get_response()).message

        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["text"] = str(the_message)
        await SaveJsonGroupsData(groups_database)
        await CustomizeMessageDiscussionGroup(event, target_group_id)

    except Exception as error:pass


# Remove Discussion Group Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeDiscussionGroupText_")))
async def RemoveDiscussionGroupText(event):

    target_group_id = int(str(event.data.decode()).replace('removeDiscussionGroupText_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        

    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["text"] = None
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeMessageDiscussionGroup(event, group_ID=target_group_id)

    except Exception as error:pass


# Cancel Conversation 7
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"cancel7_")))
async def CancelConversation7(event):

    target_group_id = int(str(event.data.decode()).replace('cancel7_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
    
    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeMessageDiscussionGroup(event, group_ID=target_group_id)

    except Exception as error:pass


# Edit Discussion Group Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editDiscussionGroupMedia_")))
async def EditDiscussionGroupMedia(event):

    target_group_id = int(str(event.data.decode()).replace('editDiscussionGroupMedia_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الميديا', f'removeDiscussionGroupMedia_{target_group_id}')],
                [Button.inline('❌ الغاء', f'cancel7_{target_group_id}')]
            ]

            await conv.send_message('''👉🏻 أرسل الآن الوسائط (صور، فيديوهات، ملصقات...) التي ترغب في تعيينها.''', buttons=buttons)
            the_message = await conv.get_response()

        media_path = await the_message.download_media('groupDiscussion_media/')

        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["media"] = media_path
        await SaveJsonGroupsData(groups_database)
        await CustomizeMessageDiscussionGroup(event, target_group_id)

    except Exception as error:pass


# Remove Discussion Group Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeDiscussionGroupMedia_")))
async def RemoveDiscussionGroupMedia(event):

    target_group_id = int(str(event.data.decode()).replace('removeDiscussionGroupMedia_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["media"] = None
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeMessageDiscussionGroup(event, group_ID=target_group_id)

    except Exception as error:pass


# Edit Discussion Group Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"editDiscussionGroupUrlButtons_")))
async def EditDiscussionGroupUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('editDiscussionGroupUrlButtons_', ''))
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    await DeleteEvent(event)

    try:
        async with bot.conversation(event.chat_id, timeout=300, exclusive=True) as conv:
            buttons = [
                [Button.inline('🚫 حذف الأزرار', f'removeDiscussionGroupUrlButtons_{target_group_id}')],
                [Button.inline('❌ الغاء', f'cancel7_{target_group_id}')]
            ]

            await conv.send_message('''
👉🏻 الآن أرسل قائمة الأزرار لإدراجها في لوحة المفاتيح المدمجة، مع النصوص والروابط، باستخدام هذا التنسيق:
                                    
`Button text - link.com`
`Button text - link.net`

• إذا كنت ترغب في تعيين زرين في نفس الصف، قم بفصلهم باستخدام &&.
• عند تعيين القواعد كرابط، سيقوم الزر بإرسال المستخدمين إلى قواعد المجموعة، إذا تم تعيينها باستخدام الروبوت.

مثال:
`Group - https://t.me/username && Channel - google.com`
''', buttons=buttons, link_preview=False)
            the_message = (await conv.get_response()).message

        if not all('-' in line for line in the_message.split('\n') if line.strip()):
            buttons = [[Button.inline('❌ الغاء', f'cancel7_{target_group_id}')]]
            await event.respond("تنسيق لوحة المفاتيح غير صحيح. حاول مرة أخرى.", buttons=buttons)
            return
        
        list_buttons = []
        for line in the_message.split('\n'):
            buttons = []
            for btn in line.split('&&'):
                parts = btn.strip().split(' - ')
                if len(parts) == 2:
                    text, url = parts
                    buttons.append({"text": text.strip(), "url": url.strip()})
            if buttons:
                list_buttons.append(buttons)
        
        groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["buttons"] = list_buttons
        
        row_btn, test_buttons = [], []
        for row in list_buttons:
            for button in row:
                row_btn.append(Button.url(button.get('text'), button.get('url')))
            test_buttons.append(row_btn)
            row_btn = []
            
        test_buttons.append([Button.inline("🔙 الرجوع", f"CustomizeMessageDiscussionGroup_{target_group_id}")])

        try:
            test_msg = await event.respond('الأزرار المضافة حاليا', buttons=test_buttons)
            await DeleteEvent(test_msg)
        
        except Exception as error:
            buttons = [[Button.inline('❌ الغاء', f'cancel7_{target_group_id}')]]
            await event.respond("تنسيق لوحة المفاتيح غير صحيح. حاول مرة أخرى.", buttons=buttons)
            return
        
        await SaveJsonGroupsData(groups_database)
        await CustomizeMessageDiscussionGroup(event, target_group_id)

    except Exception as error:pass


# Remove Discussion Group Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"removeDiscussionGroupUrlButtons_")))
async def RemoveDiscussionGroupUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('removeDiscussionGroupUrlButtons_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["buttons"] = []
    await SaveJsonGroupsData(groups_database)

    try:
        async with bot.conversation(event.chat_id, exclusive=False) as conv:
            await conv.cancel_all()
            await CustomizeMessageDiscussionGroup(event, group_ID=target_group_id)

    except Exception as error:pass


# Show Discussion Group Text
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showDiscussionGroupText_")))
async def ShowDiscussionGroupText(event):

    target_group_id = int(str(event.data.decode()).replace('showDiscussionGroupText_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    buttons = [
        [Button.inline("🔙 الرجوع", f"CustomizeMessageDiscussionGroup_{target_group_id}")]
    ]
    rules_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["text"]
    
    if rules_text:
        await DeleteEvent(event)
        await event.respond(rules_text, buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)


# Show Discussion Group Media
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showDiscussionGroupMedia_")))
async def ShowDiscussionGroupMedia(event):

    target_group_id = int(str(event.data.decode()).replace('showDiscussionGroupMedia_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    buttons = [
        [Button.inline("🔙 الرجوع", f"CustomizeMessageDiscussionGroup_{target_group_id}")]
    ]

    rules_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["media"]
    
    if rules_media:
        await DeleteEvent(event)
        await event.respond(file=rules_media, buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)


# Show Discussion Group Url Buttons
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showDiscussionGroupUrlButtons_")))
async def ShowDiscussionGroupUrlButtons(event):

    target_group_id = int(str(event.data.decode()).replace('showDiscussionGroupUrlButtons_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    rules_urlButtons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["buttons"]
    
    if rules_urlButtons:
        await DeleteEvent(event)
        row_btn, buttons = [], []
        for row in rules_urlButtons:
            for button in row:
                row_btn.append(Button.url(button.get('text'), button.get('url')))
            buttons.append(row_btn)
            row_btn = []
            
        buttons.append([Button.inline("🔙 الرجوع", f"CustomizeMessageDiscussionGroup_{target_group_id}")])
        await event.respond('الأزرار المضافة حاليا', buttons=buttons)
    else:
        await event.answer('لم تقم بتعيينها بعد', alert=True)



# Show Discussion Group All
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"showDiscussionGroupAll_")))
async def ShowDiscussionGroupAll(event):

    target_group_id = int(str(event.data.decode()).replace('showDiscussionGroupAll_', ''))

    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    rules_text = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["text"]
    rules_media = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["media"]
    rules_urlButtons = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["discussion_group"]["buttons"]
    
    if not rules_text and not rules_media and not rules_urlButtons:
        await event.answer('لم تقم بتعيينها بعد', alert=True)
        return

    await DeleteEvent(event)
    row_btn, buttons = [], []
    for row in rules_urlButtons:
        for button in row:
            row_btn.append(Button.url(button.get('text'), button.get('url')))
        buttons.append(row_btn)
        row_btn = []
        
    buttons.append([Button.inline("🔙 الرجوع", f"CustomizeMessageDiscussionGroup_{target_group_id}")])
    
    msg_text = f'💬 **التعليق الأول**\n\n{rules_text}'
    await event.respond(msg_text, file=rules_media, buttons=buttons)



#############################################################################

# channelsManagement
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"channelsManagement")))
async def ChannelsManagement(event, group_ID=None):

    await event.answer('📣 بوت ادارة القنوات غير متوفرة حاليا', alert=True)


#############################################################################

# messageLength_
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"messageLength_")))
async def MessageLength(event, group_ID=None):

    if group_ID == None:
        target_group_id = int(str(event.data.decode()).replace('messageLength_', ''))
    else:
        target_group_id = int(group_ID)
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    MessageLengthSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["message_length"]
    await DeleteEvent(event)

    MSG = f'''
📏 **طول الرسالة** 

من خلال هذا القائمة، يمكنك تعيين الحد الأدنى/الأقصى لعدد الأحرف في الرسائل التي يرسلها المستخدمون.

العقاب: {MessageLengthSettings["penalty"]}
حذف الرسالة: {'نعم ✔️' if MessageLengthSettings["delete_msg"] else 'لا ✖️'}
الحد الأدنى للطول: {f'{MessageLengthSettings["min_length"]} حرف' if MessageLengthSettings["min_length"] else 'بدون حدود ✖️'}
الحد الأقصى للطول: {f'{MessageLengthSettings["max_length"]} حرف' if MessageLengthSettings["max_length"] else 'بدون حدود ✖️'}
'''
    
    buttons = [
        [
            Button.inline(f"❌ لا شي {'✅' if MessageLengthSettings['penalty'] == 'Off' else ''}", f"setMessageLengthPenalty_Off_{target_group_id}"),
            Button.inline(f"❕ تحذير {'✅' if MessageLengthSettings['penalty'] == 'Warn' else ''}", f"setMessageLengthPenalty_Warn_{target_group_id}"),
        ],
        [
            Button.inline(f"❗️ طرد {'✅' if MessageLengthSettings['penalty']  == 'Kick' else ''}", f"setMessageLengthPenalty_Kick_{target_group_id}"),
            Button.inline(f"🔇 كتم {'✅' if MessageLengthSettings['penalty']  == 'Mute' else ''}", f"setMessageLengthPenalty_Mute_{target_group_id}"),
            Button.inline(f"🚷 حظر {'✅' if MessageLengthSettings['penalty']  == 'Ban' else ''}", f"setMessageLengthPenalty_Ban_{target_group_id}")
        ],
        [
            Button.inline(f"🗑 حذف الرسالة {'✔️' if MessageLengthSettings['delete_msg'] else '✖️'}", f"DeleteMsgMessageLength_{target_group_id}"),
        ]
    ]

    buttons.append([
            Button.inline(f"📏 الطول الأدنى للرسالة", f"MininumLengthMessageLength_{target_group_id}"),
        ])
    if MessageLengthSettings['min_length_open']:
        buttons.append([
            Button.inline(f"بدون حدود {'✔️' if MessageLengthSettings['min_length'] == None else ''}", f"setMininumLengthMessageLength_none_{target_group_id}"),
        ])
        buttons.append([
            Button.inline(f"5 {'✔️' if MessageLengthSettings['min_length'] == 5 else ''}", f"setMininumLengthMessageLength_5_{target_group_id}"),
            Button.inline(f"10 {'✔️' if MessageLengthSettings['min_length'] == 10 else ''}", f"setMininumLengthMessageLength_10_{target_group_id}"),
            Button.inline(f"20 {'✔️' if MessageLengthSettings['min_length'] == 20 else ''}", f"setMininumLengthMessageLength_20_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"25 {'✔️' if MessageLengthSettings['min_length'] == 25 else ''}", f"setMininumLengthMessageLength_25_{target_group_id}"),
            Button.inline(f"50 {'✔️' if MessageLengthSettings['min_length'] == 50 else ''}", f"setMininumLengthMessageLength_50_{target_group_id}"),
            Button.inline(f"100 {'✔️' if MessageLengthSettings['min_length'] == 100 else ''}", f"setMininumLengthMessageLength_100_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"200 {'✔️' if MessageLengthSettings['min_length'] == 200 else ''}", f"setMininumLengthMessageLength_200_{target_group_id}"),
            Button.inline(f"400 {'✔️' if MessageLengthSettings['min_length'] == 400 else ''}", f"setMininumLengthMessageLength_400_{target_group_id}"),
            Button.inline(f"800 {'✔️' if MessageLengthSettings['min_length'] == 800 else ''}", f"setMininumLengthMessageLength_800_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"1000 {'✔️' if MessageLengthSettings['min_length'] == 1000 else ''}", f"setMininumLengthMessageLength_1000_{target_group_id}"),
            Button.inline(f"1500 {'✔️' if MessageLengthSettings['min_length'] == 1500 else ''}", f"setMininumLengthMessageLength_1500_{target_group_id}"),
            Button.inline(f"2000 {'✔️' if MessageLengthSettings['min_length'] == 2000 else ''}", f"setMininumLengthMessageLength_2000_{target_group_id}")
        ])

    buttons.append([
            Button.inline(f"📏 الحد الأقصى للرسالة", f"MaxinumLengthMessageLength_{target_group_id}"),
        ])
    if MessageLengthSettings['max_length_open']:
        buttons.append([
            Button.inline(f"بدون حدود {'✔️' if MessageLengthSettings['max_length'] == None else ''}", f"setMaxinumLengthMessageLength_none_{target_group_id}"),
        ])
        buttons.append([
            Button.inline(f"50 {'✔️' if MessageLengthSettings['max_length'] == 50 else ''}", f"setMaxinumLengthMessageLength_50_{target_group_id}"),
            Button.inline(f"100 {'✔️' if MessageLengthSettings['max_length'] == 100 else ''}", f"setMaxinumLengthMessageLength_100_{target_group_id}"),
            Button.inline(f"150 {'✔️' if MessageLengthSettings['max_length'] == 150 else ''}", f"setMaxinumLengthMessageLength_150_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"200 {'✔️' if MessageLengthSettings['max_length'] == 200 else ''}", f"setMaxinumLengthMessageLength_200_{target_group_id}"),
            Button.inline(f"400 {'✔️' if MessageLengthSettings['max_length'] == 400 else ''}", f"setMaxinumLengthMessageLength_400_{target_group_id}"),
            Button.inline(f"800 {'✔️' if MessageLengthSettings['max_length'] == 800 else ''}", f"setMaxinumLengthMessageLength_800_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"1000 {'✔️' if MessageLengthSettings['max_length'] == 1000 else ''}", f"setMaxinumLengthMessageLength_1000_{target_group_id}"),
            Button.inline(f"1500 {'✔️' if MessageLengthSettings['max_length'] == 1500 else ''}", f"setMaxinumLengthMessageLength_1500_{target_group_id}"),
            Button.inline(f"2000 {'✔️' if MessageLengthSettings['max_length'] == 2000 else ''}", f"setMaxinumLengthMessageLength_2000_{target_group_id}")
        ])
        buttons.append([
            Button.inline(f"2500 {'✔️' if MessageLengthSettings['max_length'] == 2500 else ''}", f"setMaxinumLengthMessageLength_2500_{target_group_id}"),
            Button.inline(f"3000 {'✔️' if MessageLengthSettings['max_length'] == 3000 else ''}", f"setMaxinumLengthMessageLength_3000_{target_group_id}"),
            Button.inline(f"3500 {'✔️' if MessageLengthSettings['max_length'] == 3500 else ''}", f"setMaxinumLengthMessageLength_3500_{target_group_id}")
        ])


    buttons.append([Button.inline("🔙 الرجوع", f"nextList_{target_group_id}")])
    await event.respond(MSG, buttons=buttons, link_preview=False)


# Set Message Length Penalty
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setMessageLengthPenalty_")))
async def SetMessageLengthPenalty(event):

    new_penalty, target_group_id = (str(event.data.decode()).replace('setMessageLengthPenalty_', '')).split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    MessageLengthSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["message_length"]
    MessageLengthSettings["penalty"] = str(new_penalty)

    await SaveJsonGroupsData(groups_database)
    await MessageLength(event, group_ID=target_group_id)


# Delete Msg Message Length
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"DeleteMsgMessageLength_")))
async def DeleteMsgMessageLength(event):

    target_group_id = str(event.data.decode()).replace('DeleteMsgMessageLength_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    MessageLengthSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["message_length"]
    MessageLengthSettings["delete_msg"] = not MessageLengthSettings["delete_msg"]

    await SaveJsonGroupsData(groups_database)
    await MessageLength(event, group_ID=target_group_id)


# Mininum Length Message Length
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"MininumLengthMessageLength_")))
async def MininumLengthMessageLength(event):

    target_group_id = str(event.data.decode()).replace('MininumLengthMessageLength_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    MessageLengthSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["message_length"]
    MessageLengthSettings["min_length_open"] = not MessageLengthSettings["min_length_open"]

    await SaveJsonGroupsData(groups_database)
    await MessageLength(event, group_ID=target_group_id)


# Maxinum Length Message Length
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"MaxinumLengthMessageLength_")))
async def MaxinumLengthMessageLength(event):

    target_group_id = str(event.data.decode()).replace('MaxinumLengthMessageLength_', '')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    MessageLengthSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["message_length"]
    MessageLengthSettings["max_length_open"] = not MessageLengthSettings["max_length_open"]

    await SaveJsonGroupsData(groups_database)
    await MessageLength(event, group_ID=target_group_id)


# Set Mininum Length Message Length
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setMininumLengthMessageLength_")))
async def SetMininumLengthMessageLength(event):

    new_length, target_group_id = str(event.data.decode()).replace('setMininumLengthMessageLength_', '').split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    MessageLengthSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["message_length"]
    MessageLengthSettings["min_length"] = int(new_length) if new_length != 'none' else None

    await SaveJsonGroupsData(groups_database)
    await MessageLength(event, group_ID=target_group_id)


# Set Maxinum Length Message Length
@bot.on(events.CallbackQuery(data=lambda b: b.startswith(b"setMaxinumLengthMessageLength_")))
async def SetMaxinumLengthMessageLength(event):

    new_length, target_group_id = str(event.data.decode()).replace('setMaxinumLengthMessageLength_', '').split('_')
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(event.chat_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]

        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return
        
    if event.is_private:
        group_ownerID = await find_group_creator(target_group_id, groups_database)

        CoFounders, Admins = [], []
        if str(group_ownerID) in groups_database:
            if str(target_group_id) in groups_database[str(group_ownerID)]["groups"]:
                group_data = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]
                CoFounders = group_data["co_founders"]
                Admins = group_data["admins"]
        
        if event.sender_id != group_ownerID and event.sender_id not in CoFounders and event.sender_id not in Admins:
            return

    MessageLengthSettings = groups_database[str(group_ownerID)]["groups"][str(target_group_id)]["message_length"]
    MessageLengthSettings["max_length"] = int(new_length) if new_length != 'none' else None

    await SaveJsonGroupsData(groups_database)
    await MessageLength(event, group_ID=target_group_id)



























































#######################################

# Infinite Function
async def RunOneTimeFunction():
    global RUN_ONE_TIME

    print('Start Checking proccess...')
    while True:
        for group_id in groups_manager["nightMode_pending"]:
            group = groups_manager["nightMode_pending"][group_id]
            timeSlot_start = group["timeSlot_start"]
            timeSlot_end = group["timeSlot_end"]

            # Get current hour and minute
            current_hour = datetime.now().hour
            current_minute = datetime.now().minute

            # Handle the case where the time range crosses midnight
            if timeSlot_start > timeSlot_end:  # Midnight crossing
                if current_hour >= timeSlot_start or current_hour < timeSlot_end:
                    is_in_time_slot = True
                elif current_hour == timeSlot_start and current_minute > 0:  # Handle if start is 2:00 and current time is 2:30
                    is_in_time_slot = True
                else:
                    is_in_time_slot = False
            else:
                if timeSlot_start <= current_hour < timeSlot_end or (current_hour == timeSlot_end and current_minute == 0):
                    is_in_time_slot = True
                else:
                    is_in_time_slot = False

            # Night Mode Start (only post once per day)
            if not group["posted_today"] and is_in_time_slot:
                group["posted_today"] = True
                await SaveJsonGroupsManager(groups_manager)
                await bot.send_message(int(group_id), '''
🌒 تفعيل الوضع الليلي

✅ المجموعة في وضع الليل الآن.
''')

            # Night Mode End (reset `posted_today` at the end of the time range)
            elif group["posted_today"] and not is_in_time_slot:
                group["posted_today"] = False
                await SaveJsonGroupsManager(groups_manager)
                await bot.send_message(int(group_id), '''
🌒 إنهاء الوضع الليلي

✅ تم إيقاف وضع الليل في المجموعة.
''')

        await asyncio.sleep(5)


# Contains Alphabets
async def contains_alphabets(text):
    scripts = {
        "Arabic": re.compile(r'[؀-ۿ]'),
        "Chinese": re.compile(r'[一-鿿]'),
        "Latin": re.compile(r'[A-Za-z]'),
        "Cyrillic": re.compile(r'[Ѐ-ӿ]')
    }
    
    result = {script: bool(pattern.search(text)) for script, pattern in scripts.items()}
    return result


# Delete Warn
async def ChangeWarn(event, group_ownerID, user_id, onlyShow=False, increase=False, decrease=False, reset=False):

    WarnerUsersSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["warned_users"]
    WarnSystemSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["warn_system"]
    if str(user_id) not in WarnerUsersSettings:
        WarnerUsersSettings[str(user_id)] = {
            "warn_count": 0,
            "warn_penalty": None
        }

    if reset == True:
        WarnerUsersSettings[str(user_id)]["warn_count"] = 0
        await SaveJsonGroupsData(groups_database)

    if increase == True:
        WarnerUsersSettings[str(user_id)]["warn_count"] += 1
        await SaveJsonGroupsData(groups_database)
    
    if decrease == True:
        if WarnerUsersSettings[str(user_id)]["warn_count"] != 0:
            WarnerUsersSettings[str(user_id)]["warn_count"] -= 1
            await SaveJsonGroupsData(groups_database)

    max_warns = WarnSystemSettings["max_warns"]
    user_warns = WarnerUsersSettings[str(user_id)]["warn_count"]
    user_data = await bot.get_entity(user_id)

    buttons = None
    if onlyShow == True and (user_warns < max_warns):
        buttons = [
            [Button.inline('-', f'decreaseWarn_{user_id}'), Button.inline('+', f'increaseWarn_{user_id}')],
            [Button.inline('♻️ تصفير التحذيرات', f'resetWarns_{user_id}')]
        ]

    await event.respond(f'''
[{user_data.first_name}](tg://user?id={user_id}) [`{user_id}`]

❕ تحذيراته : ({user_warns}/{max_warns})
''', buttons=buttons)


# Take Action
async def TakePenaltyAction(event, group_ownerID, penalty, deleteMSG, Actiontype):

    try:
        user_id = event.sender_id
    except:
        user_id = event.user_id
    
    if penalty == 'Warn':
        WarnerUsersSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["warned_users"]
        WarnSystemSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]["warn_system"]
        if str(user_id) not in WarnerUsersSettings:
            WarnerUsersSettings[str(user_id)] = {
                "warn_count": 0,
                "warn_penalty": None
            }

        WarnerUsersSettings[str(user_id)]["warn_count"] += 1
        await SaveJsonGroupsData(groups_database)

        max_warns = WarnSystemSettings["max_warns"]
        user_warns = WarnerUsersSettings[str(user_id)]["warn_count"]

        user_data = await bot.get_entity(user_id)

        buttons = [
            [Button.inline('❌ الغاء', f'WarnCancel_{user_id}')] # cancel warn
        ]

        if user_warns == max_warns:
            await event.respond(f'''
[{user_data.first_name}](tg://user?id={user_id}) [`{user_id}`] {Actiontype}
الإجراء: تحذير ({user_warns}/{max_warns}) ❕
''')
        else:
            await event.respond(f'''
[{user_data.first_name}](tg://user?id={user_id}) [`{user_id}`] {Actiontype}
الإجراء: تحذير ({user_warns}/{max_warns}) ❕
''', buttons=buttons)
        

        if user_warns >= max_warns:
            del WarnerUsersSettings[str(user_id)]
            await SaveJsonGroupsData(groups_database)

        # if warn reach max do this
        if WarnSystemSettings["is_active"] and user_warns >= max_warns:
            warnPunishment = WarnSystemSettings["punishment"]
            warnDuration = WarnSystemSettings["duration"]

            button_text = None
            inform_MSG = f'''
[{user_data.first_name}](tg://user?id={user_id}) [`{user_id}`] {Actiontype}
'''
            
            if warnPunishment == 'Mute':
                await bot.edit_permissions(event.chat_id, user_id, send_messages=False)
                inform_MSG += 'الإجراء: كتم 🔇'
                button_text = '✅ أزل الكتم'

            if warnPunishment == 'Kick':
                await bot.edit_permissions(event.chat_id, user_id, view_messages=False)
                await bot.edit_permissions(event.chat_id, user_id)
                inform_MSG += 'الإجراء: طرد ❗️'

            if warnPunishment == 'Ban':
                await bot.edit_permissions(event.chat_id, user_id, view_messages=None)
                inform_MSG += 'الإجراء: حظر 🚷'

            action_buttons = [[Button.inline(button_text, '')]]
            await event.respond(inform_MSG) # , buttons=action_buttons


    if penalty == 'Mute':
        await bot.edit_permissions(event.chat_id, user_id, send_messages=False)

    if penalty == 'Kick':
        await bot.edit_permissions(event.chat_id, user_id, view_messages=False)  
        await bot.edit_permissions(event.chat_id, user_id)

    if penalty == 'Ban':
        await bot.edit_permissions(event.chat_id, user_id, view_messages=None)

    if deleteMSG:
        await DeleteEvent(event)


# watch chat messages
@bot.on(events.NewMessage)
async def handlerChatMessages(event):
    global RUN_ONE_TIME

    if RUN_ONE_TIME == False:
        RUN_ONE_TIME = True
        asyncio.create_task(RunOneTimeFunction())

    # checks
    if event.is_private or event.sender_id == None:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

    if str(group_ownerID) not in groups_database:
        return

    if str(event.chat_id) not in groups_database[str(group_ownerID)]["groups"]:
        return


    ##################################################################
    # after checks
    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]

    if str(event.sender_id) not in targetGroupSettings["group_satistics"]["users"]:
        user_data = await bot.get_entity(event.sender_id)
        targetGroupSettings["group_satistics"]["users"][str(event.sender_id)] = {
            "full_name": user_data.first_name,
            "messages_count": 0
        }

    targetGroupSettings["group_satistics"]["users"][str(event.sender_id)]["messages_count"] += 1
    await SaveJsonGroupsData(groups_database)


    ##################################################################
    # Tag Alert
    if targetGroupSettings["tag_alert"]["is_active"]:
        mentions = re.findall(r'@[\w]+', event.message.message)
        for mention in mentions:
            try:
                user_data = await bot.get_entity(mention)
                group_data = await bot.get_entity(event.chat_id)

                await bot.send_message(mention, f'''
🔔 **تنبيه!**
[{user_data.first_name}](tg://user?id={user_data.id}) [{user_data.id}] تم الاشارة اليك في احد الرسائل

👉🏻 [انتقل إلى الرسالة](http://t.me/{f'c/{str(event.chat_id).replace("-100", "")}' if group_data.username == None else group_data.username}/{event.message.id})''', link_preview=False)

            except Exception as error:pass


    # chech if admin was tagged
    if '@admin' in event.message.message:
        if targetGroupSettings["adminTag"]["send_to"] != "✖️ NoBody":
            await event.respond('✅ `تم إرسال التقرير`')

            send_to_ids = []
            if targetGroupSettings["adminTag"]["send_to"] == "👑 Founder":
                send_to_ids.append(group_ownerID)

            if targetGroupSettings["adminTag"]["send_to"] == "👥 Staff Group":
                # get staff group later
                for admin_id in targetGroupSettings["admins"]:
                    send_to_ids.append(admin_id)

            tag_founder = targetGroupSettings["adminTag"]["tag_founder"]
            user_data = await bot.get_entity(event.sender_id)
            group_data = await bot.get_entity(event.chat_id)

            for send_to_id in send_to_ids:
                try:
                    await bot.send_message(int(send_to_id), f'''
⚠️ **انتباه!**
[{user_data.first_name}](tg://user?id={event.sender_id}) [{event.sender_id}] طلب إجراء إداري في المجموعة

👉🏻 [انتقل إلى الرسالة](http://t.me/{f'c/{str(event.chat_id).replace("-100", "")}' if group_data.username == None else group_data.username}/{event.message.id})''', link_preview=False)

                    # await bot.forward_messages(event.chat_id, event.message.id, event.sender_id)

                except Exception as error:pass

    #############################################
    CoFounders = targetGroupSettings["co_founders"]
    Admins = targetGroupSettings["admins"]
    FreeUsers = targetGroupSettings["free_users"]
    Muters = targetGroupSettings["muters"]
    Moderators = targetGroupSettings["moderators"]

    if event.sender_id in CoFounders:
        return

    if event.sender_id in Admins:
        return

    if event.sender_id in FreeUsers:
        return

    if event.sender_id in Muters:
        return
    
    if event.sender_id in Moderators:
        return
  
    if event.sender_id == group_ownerID:
        return


    ######################################################
    
    # check media type
    if targetGroupSettings["allowed_media"]:
        duration = targetGroupSettings["allowed_media"]["duration"]

        # add -  story

        if event.message.photo:
            action_data = targetGroupSettings["allowed_media"]["photo"]
            await TakePenaltyAction(event, group_ownerID, action_data["penalty"], action_data["delete_msg"], "أرسل 📸 صورة دون الحصول على إذن.")

        elif event.message.video:
            action_data = targetGroupSettings["allowed_media"]["video"]
            await TakePenaltyAction(event, group_ownerID, action_data["penalty"], action_data["delete_msg"], "أرسل 🎞 فيديو دون الحصول على إذن.")

        # add - album

        elif event.message.gif:
            action_data = targetGroupSettings["allowed_media"]["gif"]
            await TakePenaltyAction(event, group_ownerID, action_data["penalty"], action_data["delete_msg"], "أرسل 🎥 صور GIF دون الحصول على إذن.")

        elif event.message.voice:
            action_data = targetGroupSettings["allowed_media"]["voice"]
            await TakePenaltyAction(event, group_ownerID, action_data["penalty"], action_data["delete_msg"], "أرسل 🎤 رسالة صوتية دون الحصول على إذن.")

        elif event.message.audio:
            action_data = targetGroupSettings["allowed_media"]["audio"]
            await TakePenaltyAction(event, group_ownerID, action_data["penalty"], action_data["delete_msg"], "أرسل 🎧 صوتية دون الحصول على إذن.")

        elif event.message.sticker:
            action_data = targetGroupSettings["allowed_media"]["sticker"]
            await TakePenaltyAction(event, group_ownerID, action_data["penalty"], action_data["delete_msg"], "أرسل 🃏 ملصق دون الحصول على إذن.")

        elif event.message.document:
            print("Media type: Document")

        elif event.message.contact:
            action_data = targetGroupSettings["allowed_media"]["contacts"]
            await TakePenaltyAction(event, group_ownerID, action_data["penalty"], action_data["delete_msg"], "أرسل 🏷 جهات الاتصال دون الحصول على إذن.")

        elif event.message.poll:
            action_data = targetGroupSettings["allowed_media"]["polls"]
            await TakePenaltyAction(event, group_ownerID, action_data["penalty"], action_data["delete_msg"], "أرسل 📊 الاستطلاعات دون الحصول على إذن.")

        elif event.message.geo:
            print("Media type: Geo")

        elif event.message.dice:
            print("Media type: Dice")

        elif event.message.file:
            action_data = targetGroupSettings["allowed_media"]["files"]
            await TakePenaltyAction(event, group_ownerID, action_data["penalty"], action_data["delete_msg"], "أرسل 💾 الملفات دون الحصول على إذن.")

        elif event.message.game:
            action_data = targetGroupSettings["allowed_media"]["games"]
            await TakePenaltyAction(event, group_ownerID, action_data["penalty"], action_data["delete_msg"], "أرسل 🎮 الألعاب دون الحصول على إذن.")

        elif event.message.invoice:
            action_data = targetGroupSettings["allowed_media"]["payments"]
            await TakePenaltyAction(event, group_ownerID, action_data["penalty"], action_data["delete_msg"], "أرسل 💶 المدفوعات دون الحصول على إذن.")


    # check anti-spam | forwarding - quate
    if event.message.forward:
        forwardPenalty = targetGroupSettings["antispam"]["forwarding_penalty"]
        forwardingDeleteMsg = targetGroupSettings["antispam"]["forwarding_delete_msg"]
        quatePenalty = targetGroupSettings["antispam"]["quate_penalty"]
        quateDeleteMsg = targetGroupSettings["antispam"]["quate_delete_msg"]

        if forwardingDeleteMsg:
            await DeleteEvent(event)

        if quateDeleteMsg:
            await DeleteEvent(event)

        if forwardPenalty == 'Off' and quatePenalty == 'Off':
            pass

        else:
            check_type = await bot.get_entity(event.message.forward.from_id)
            if isinstance(check_type, User):
                if check_type.bot:
                    if targetGroupSettings["antispam"]["forwarding_bots"]:
                        await TakePenaltyAction(event, group_ownerID, forwardPenalty, forwardingDeleteMsg, '**أرسل رسالة معاد توجيهها**')
                    
                    if targetGroupSettings["antispam"]["quate_bots"]:
                        if 'MessageEntityBlockquote' in str(event.message):
                            await TakePenaltyAction(event, group_ownerID, quatePenalty, quateDeleteMsg, '**أرسل رسالة مع اقتباس من محادثة خارجية**')
                else:
                    if targetGroupSettings["antispam"]["forwarding_users"]:
                        await TakePenaltyAction(event, group_ownerID, forwardPenalty, forwardingDeleteMsg, '**أرسل رسالة معاد توجيهها**')
                    
                    if targetGroupSettings["antispam"]["quate_users"]:
                        if 'MessageEntityBlockquote' in str(event.message):
                            await TakePenaltyAction(event, group_ownerID, quatePenalty, quateDeleteMsg, '**أرسل رسالة مع اقتباس من محادثة خارجية**')

            elif isinstance(check_type, Channel):
                if check_type.broadcast:
                    if targetGroupSettings["antispam"]["forwarding_channels"]:
                        await TakePenaltyAction(event, group_ownerID, forwardPenalty, forwardingDeleteMsg, '**أرسل رسالة معاد توجيهها**')
                    
                    if targetGroupSettings["antispam"]["quate_channels"]:
                        if 'MessageEntityBlockquote' in str(event.message):
                            await TakePenaltyAction(event, group_ownerID, quatePenalty, quateDeleteMsg, '**أرسل رسالة مع اقتباس من محادثة خارجية**')
                else:
                    if targetGroupSettings["antispam"]["forwarding_groups"]:
                        await TakePenaltyAction(event, group_ownerID, forwardPenalty, forwardingDeleteMsg, '**أرسل رسالة معاد توجيهها**')
                    
                    if targetGroupSettings["antispam"]["quate_groups"]:
                        if 'MessageEntityBlockquote' in str(event.message):
                            await TakePenaltyAction(event, group_ownerID, quatePenalty, quateDeleteMsg, '**أرسل رسالة مع اقتباس من محادثة خارجية**')


    # check anti-spam | total links block
    async def has_url(text):
        return bool(re.search(r"https?://\S+|www\.\S+|(?:\w+\.)+\w+", text))

    if event.message.message:
        hasUrl = await has_url(event.message.message)
        if hasUrl == True:
            totalLinksPenalty = targetGroupSettings["antispam"]["total_links_penalty"]
            totalLinksDeleteMsg = targetGroupSettings["antispam"]["total_links_delete_msg"]

            if totalLinksDeleteMsg:
                await DeleteEvent(event)

            await TakePenaltyAction(event, group_ownerID, totalLinksPenalty, totalLinksDeleteMsg, '**أرسل رابط خارجي**')


    # check anti-spam | total links block
    async def check_telegram_content(text, check_mentions=True, check_bot_links=True):
        # Patterns
        telegram_link_pattern = r"(?:https?://)?t\.me/(?!\w+bot\b)\w+" # Telegram links (excluding bots)
        bot_link_pattern = r"(?:https?://)?t\.me/\w+bot\b"  # Bot links
        mention_pattern = r"@\w+"  # Mentions starting with @
        text = str(text).lower()

        # Check conditions
        has_telegram_link = bool(re.search(telegram_link_pattern, text))
        has_bot_link = bool(re.search(bot_link_pattern, text)) if check_bot_links else False
        has_mention = bool(re.search(mention_pattern, text)) if check_mentions else False

        return has_telegram_link or has_bot_link or has_mention


    if event.message.message:
        TelegramLinksPenalty = targetGroupSettings["antispam"]["penalty"]
        TelegramLinksDeleteMsg = targetGroupSettings["antispam"]["delete_msg"]
        UsernameIs_spam = targetGroupSettings["antispam"]["username_antispam"]
        BotsIs_spam = targetGroupSettings["antispam"]["bots_antispam"]
        
        has_url = await check_telegram_content(event.message.message, check_mentions=UsernameIs_spam, check_bot_links=BotsIs_spam)
        if has_url == True:
            if TelegramLinksDeleteMsg:
                await DeleteEvent(event)

            await TakePenaltyAction(event, group_ownerID, TelegramLinksPenalty, TelegramLinksDeleteMsg, '**أرسل رابط تلغرام/معرف**')


    # check anti-flood
    anitflood_penalty = targetGroupSettings["antiflood"]["penalty"]
    anitflood_deleteMSG = targetGroupSettings["antiflood"]["delete_msg"]

    if anitflood_penalty == 'Off' and anitflood_deleteMSG == False:
        pass
    else:
        messages_target = targetGroupSettings["antiflood"]["messages_target"]
        interval_time = targetGroupSettings["antiflood"]["interval_time"]
        
        await set_group_settings(str(event.chat_id), messages_target, interval_time) 
        is_spam, messages_id = await check_spam_and_take_action(str(event.chat_id), event.sender_id, event.message.id)
        
        if is_spam:
            if anitflood_deleteMSG:
                try:
                    await bot.delete_messages(event.chat_id, message_ids=messages_id)
                except:pass

            await TakePenaltyAction(event, group_ownerID, anitflood_penalty, anitflood_deleteMSG, '**أرسل رسائل عديدة في وقت قصير**')


    # check alphabets
    if event.message.message:
        AlphabetsPenalty = targetGroupSettings["alphabets"]["penalty"]
        AlphabetsDeleteMsg = targetGroupSettings["alphabets"]["delete_msg"]
        AlphabetswatchArabic = targetGroupSettings["alphabets"]["watchArabic"]
        AlphabetswatchCyrillic = targetGroupSettings["alphabets"]["watchCyrillic"]
        AlphabetswatchChinese = targetGroupSettings["alphabets"]["watchChinese"]
        AlphabetswatchLatin = targetGroupSettings["alphabets"]["watchLatin"]

        containsAlphabets = await contains_alphabets(event.message.message)

        if containsAlphabets["Arabic"] and AlphabetswatchArabic:
            await TakePenaltyAction(event, group_ownerID, AlphabetsPenalty, AlphabetsDeleteMsg, '**أرسل رسالة تحتوي على الحروف العربية**')

        if containsAlphabets["Chinese"] and AlphabetswatchChinese:
            await TakePenaltyAction(event, group_ownerID, AlphabetsPenalty, AlphabetsDeleteMsg, '**أرسل رسالة تحتوي على الحروف الصينية**')

        if containsAlphabets["Latin"] and AlphabetswatchLatin:
            await TakePenaltyAction(event, group_ownerID, AlphabetsPenalty, AlphabetsDeleteMsg, '**أرسل رسالة تحتوي على الحروف اللاتينية**')

        if containsAlphabets["Cyrillic"] and AlphabetswatchCyrillic:
            await TakePenaltyAction(event, group_ownerID, AlphabetsPenalty, AlphabetsDeleteMsg, '**أرسل رسالة تحتوي على الحروف السيريلية**')


    # Min/Max Message
    check_minLength = targetGroupSettings["message_length"]["min_length"]
    check_maxLength = targetGroupSettings["message_length"]["max_length"]
    messageLengthPenalty = targetGroupSettings["message_length"]["penalty"]
    messageLengthDeleteMSG = targetGroupSettings["message_length"]["delete_msg"]

    message_length = len(event.message.message)
    if check_minLength != None and message_length < check_minLength:
        await TakePenaltyAction(event, group_ownerID, messageLengthPenalty, messageLengthDeleteMSG, '**أرسل رسالة طولها أقل من المطلوب**')
        
        if messageLengthDeleteMSG:
            await DeleteEvent(event)

    elif check_maxLength != None and message_length > check_maxLength:
        await TakePenaltyAction(event, group_ownerID, messageLengthPenalty, messageLengthDeleteMSG, '**أرسل رسالة طولها أكبر من المطلوب**')
    
        if messageLengthDeleteMSG:
            await DeleteEvent(event)


    # check if discussion group
    if targetGroupSettings["discussion_group"]["is_active"]:
        if isinstance(event.message.peer_id, PeerChannel):
            if isinstance(event.message.from_id, PeerChannel):
                print(f"Message sent from a discussed channel: {event.message.from_id.channel_id}")

                if targetGroupSettings["discussion_group"]["delete_msg"]:
                    await DeleteEvent(event)
                
                else:
                    if targetGroupSettings["discussion_group"]["remove_from_pin"]:
                        try:
                            await bot.unpin_message(event.chat_id, event.message.id)
                        except Exception as error:pass

                    if targetGroupSettings["discussion_group"]["first_comment"]:
                        discussionGroup_text = targetGroupSettings["discussion_group"]["text"]
                        discussionGroup_media = targetGroupSettings["discussion_group"]["media"]
                        discussionGroup_urlButtons = targetGroupSettings["discussion_group"]["buttons"]

                        # await DeleteEvent(event)
                        row_btn, buttons = [], []
                        for row in discussionGroup_urlButtons:
                            for button in row:
                                row_btn.append(Button.url(button.get('text'), button.get('url')))
                            buttons.append(row_btn)
                            row_btn = []

                        if not buttons:
                            buttons = None

                        try:
                            if discussionGroup_text == None or discussionGroup_text == '':
                                await event.reply(file=discussionGroup_media, buttons=buttons)
                            else:
                                await event.reply(discussionGroup_text, file=discussionGroup_media, buttons=buttons)
                        except:pass


    # check if masked users
    if targetGroupSettings["masked_users"]["is_active"]:
        if targetGroupSettings["masked_users"]["delete_msg"]:
            # Check if it's from a channel
            if isinstance(event.message.peer_id, PeerChannel):
                if isinstance(event.message.from_id, PeerChannel):
                    await DeleteEvent(event)
                elif isinstance(event.message.from_id, PeerChat):
                    await DeleteEvent(event)


    # check banned words
    bannedWordsList = targetGroupSettings["banned_words"]["banned_words_list"]
    for bannedWord in bannedWordsList:
        if bannedWord in str(event.message.message):
            bannedWordsPenalty = targetGroupSettings["banned_words"]["penalty"]
            bannedWordsDeleteMSG = targetGroupSettings["banned_words"]["delete_msg"]

            await TakePenaltyAction(event, group_ownerID, bannedWordsPenalty, bannedWordsDeleteMSG, '**أرسل كلمة محظورة**')


    # check night mode
    if targetGroupSettings["night_mode"]["is_active"]:
        group = groups_manager["nightMode_pending"][str(event.chat_id)]
        timeSlot_start = group["timeSlot_start"]
        timeSlot_end = group["timeSlot_end"]

        # Get current hour and minute
        current_hour = datetime.now().hour
        current_minute = datetime.now().minute

        # Handle the case where the time range crosses midnight
        if timeSlot_start > timeSlot_end:  # Midnight crossing
            if current_hour >= timeSlot_start or current_hour < timeSlot_end:
                is_in_time_slot = True
            elif current_hour == timeSlot_start and current_minute > 0:  # Handle if start is 2:00 and current time is 2:30
                is_in_time_slot = True
            else:
                is_in_time_slot = False
        else:
            if timeSlot_start <= current_hour < timeSlot_end or (current_hour == timeSlot_end and current_minute == 0):
                is_in_time_slot = True
            else:
                is_in_time_slot = False

        # If inside the night mode time slot, delete the message
        if is_in_time_slot:
            if targetGroupSettings["night_mode"]["delete_medias"]:
                if event.message.media:
                    await DeleteEvent(event)

            elif targetGroupSettings["night_mode"]["global_silence"]:
                await DeleteEvent(event)


    # check porn
    porn_penalty = targetGroupSettings["porn"]["penalty"]
    porn_delete_msg = targetGroupSettings["porn"]["delete_msg"]

    if event.message.media:
        if porn_penalty == 'Off' and porn_delete_msg == False:
            pass
        else:
            print('Porn Checking...')
            if str(event.message.media).startswith('MessageMediaPhoto'):
                pass

            if str(event.message.media).startswith('MessageMediaDocument'):
                if event.message.media.document.mime_type == 'video/mp4':
                    pass

                if event.message.media.document.mime_type == 'image/webp':
                    pass






# watch chat actions
@bot.on(events.ChatAction)
async def handlerChatActions(event):

    # checks
    if event.is_private:
        return
    
    if event.is_group:
        group_ownerID, group_admins = await GetGroupAdmins(event)

    if group_ownerID == event.user_id or group_ownerID == None:
        return

    if str(group_ownerID) not in groups_database:
        return

    if str(event.chat_id) not in groups_database[str(group_ownerID)]["groups"]:
        return

    # after checks
    targetGroupSettings = groups_database[str(group_ownerID)]["groups"][str(event.chat_id)]
    CoFounders = targetGroupSettings["co_founders"]
    Admins = targetGroupSettings["admins"]
    FreeUsers = targetGroupSettings["free_users"]
    Muters = targetGroupSettings["muters"]
    Moderators = targetGroupSettings["moderators"]

    if event.user_id in CoFounders:
        return

    if event.user_id in Admins:
        return

    if event.user_id in FreeUsers:
        return

    if event.user_id in Muters:
        return
    
    if event.user_id in Moderators:
        return


    #################################################################
    if targetGroupSettings["welcome_message"]["is_active"]:
        # Welcome every new user
        if event.user_joined:
            welcomeMessage_text = targetGroupSettings["welcome_message"]["text"]
            welcomeMessage_media = targetGroupSettings["welcome_message"]["media"]
            welcomeMessage_urlButtons = targetGroupSettings["welcome_message"]["buttons"]
            
            # if not welcomeMessage_text and not welcomeMessage_media and not welcomeMessage_urlButtons:
            #     return

            await DeleteEvent(event)
            row_btn, buttons = [], []
            for row in welcomeMessage_urlButtons:
                for button in row:
                    row_btn.append(Button.url(button.get('text'), button.get('url')))
                buttons.append(row_btn)
                row_btn = []

            if not buttons:
                buttons = None
            
            try:
                if welcomeMessage_text == None or welcomeMessage_text == '':
                    await event.respond(file=welcomeMessage_media, buttons=buttons)
                else:
                    await event.respond(welcomeMessage_text, file=welcomeMessage_media, buttons=buttons)
            
            except:pass


    if targetGroupSettings["goodbye_message"]["is_active"]:
        # goodbye every left user
        if event.user_left and event.action_message:

            GoodbyeMessage_text = targetGroupSettings["goodbye_message"]["text"]
            GoodbyeMessage_media = targetGroupSettings["goodbye_message"]["media"]
            GoodbyeMessage_urlButtons = targetGroupSettings["goodbye_message"]["buttons"]

            # if not GoodbyeMessage_text and not GoodbyeMessage_media and not GoodbyeMessage_urlButtons:
            #     return

            await DeleteEvent(event)
            row_btn, buttons = [], []
            for row in GoodbyeMessage_urlButtons:
                for button in row:
                    row_btn.append(Button.url(button.get('text'), button.get('url')))
                buttons.append(row_btn)
                row_btn = []

            if not buttons:
                buttons = None
            
            try:
                if GoodbyeMessage_text == None or GoodbyeMessage_text == '':
                    if targetGroupSettings["goodbye_message"]["send_in_private"]:
                        try:
                            await bot.send_message(entity=event.user_id, file=GoodbyeMessage_media, buttons=buttons)
                        except Exception as error:print(f'goodbye_message : {error}')
                    else:await event.respond(file=GoodbyeMessage_media, buttons=buttons)
                else:
                    if targetGroupSettings["goodbye_message"]["send_in_private"]:
                        try:
                            await bot.send_message(entity=event.user_id, message=GoodbyeMessage_text, file=GoodbyeMessage_media, buttons=buttons)
                        except Exception as error:print(f'goodbye_message : {error}')
                    else:await event.respond(GoodbyeMessage_text, file=GoodbyeMessage_media, buttons=buttons)
            
            except:pass


    if targetGroupSettings["captcha"]["is_active"]:
        # send captcha to user
        if event.user_joined:
            await bot.edit_permissions(event.chat_id, event.user_id, send_messages=False)

            mode = targetGroupSettings["captcha"]["mode"]
            penalty = targetGroupSettings["captcha"]["penalty"]
            timer = targetGroupSettings["captcha"]["timer"]
            delete_service_message = targetGroupSettings["captcha"]["delete_service_message"]
            captcha_mode = targetGroupSettings["captcha"]["captcha_modes"][mode]

            if str(event.user_id) not in groups_manager["pending_verify"]:
                groups_manager["pending_verify"][str(event.user_id)] = {
                    "group_id": event.chat_id,
                    "user_id": event.user_id,
                    "penalty": penalty,
                    "timer": timer
                }
            
            await SaveJsonGroupsManager(groups_manager)

            try:
                user_data = await bot.get_entity(event.user_id)
                first_name = user_data.first_name
            except:first_name = 'user'

            captcha_MSG = str(captcha_mode["text"]).replace('{MENTION}', f'[{first_name}](tg://user?id={event.user_id})')
            captcha_MSG = captcha_MSG.replace('{TIMER}', f'{timer}')

            buttons = [[Button.inline(captcha_mode["button_text"], f'VerifyCaptcha_{event.user_id}_{event.chat_id}')]]
            request_captcha = await event.respond(captcha_MSG, buttons=buttons)

            await asyncio.sleep(int(timer) * 60)

            if str(event.user_id) in groups_manager["pending_verify"]:
                del groups_manager["pending_verify"][str(event.user_id)]
                await SaveJsonGroupsManager(groups_manager)

                if delete_service_message:
                    await DeleteEvent(request_captcha)

                if penalty == 'Mute':
                    pass

                if penalty == 'Ban':
                    await bot.edit_permissions(event.chat_id, event.user_id, view_messages=None)

                if penalty == 'Kick':
                    await bot.edit_permissions(event.chat_id, event.user_id, view_messages=False)
                    await bot.kick_participant(event.chat_id, event.user_id)


    if targetGroupSettings["approval_mode"]["is_active"]:
        # auto-approval
        if event.user_added or event.user_left:
            try:
                user_joined = await bot(HideChatJoinRequestRequest(peer=event.chat_id, user_id=event.user_id, approved=True))
            except Exception as error:pass #print(f'Auto-Approval : {error}')


    # checks
    checkAtTheJoin = targetGroupSettings["checks"]["check_at_the_join"]

    if checkAtTheJoin:
        arabicBlock = targetGroupSettings["checks"]["block_arabic_name"]
        chineseBlock = targetGroupSettings["checks"]["block_chinese_name"]
        russianBlock = targetGroupSettings["checks"]["block_russian_name"]
        spamBlock = targetGroupSettings["checks"]["block_spam_name"]
        Delete_MSG = targetGroupSettings["checks"]["delete_msg"]

        if arabicBlock != 'Off' and chineseBlock != 'Off' and russianBlock != 'Off':
            if event.user_joined: # or event.user_added:
                user_data = await bot.get_entity(event.user_id)
                containsAlphabets = await contains_alphabets(f'{user_data.first_name} {user_data.last_name}')
                
                if containsAlphabets["Arabic"]:
                    await TakePenaltyAction(event, group_ownerID, arabicBlock, Delete_MSG, '**.. حسابه يمتلك اسم عربي**')

                if containsAlphabets["Chinese"]:
                    await TakePenaltyAction(event, group_ownerID, arabicBlock, Delete_MSG, '**.. حسابه يمتلك اسم صيني**')

                if containsAlphabets["Cyrillic"]:
                    await TakePenaltyAction(event, group_ownerID, arabicBlock, Delete_MSG, '**.. حسابه يمتلك اسم روسي**')


        obligationSurname = targetGroupSettings["checks"]["obligation_surname"]
        obligationUsername = targetGroupSettings["checks"]["obligation_username"]
        obligationProfilePicture = targetGroupSettings["checks"]["obligation_profile_picture"]

        if obligationSurname != 'Off' and obligationUsername != 'Off' and obligationProfilePicture != 'Off':
            if event.user_joined: # or event.user_added:
                user_data = await bot.get_entity(event.user_id)

                if user_data.last_name == None:
                    await TakePenaltyAction(event, group_ownerID, obligationSurname, Delete_MSG, '**.. حسابه لا يمتلك لقب**')

                if user_data.username == None:
                    await TakePenaltyAction(event, group_ownerID, obligationUsername, Delete_MSG, '**.. حسابه لا يمتلك معرف**')

                if user_data.photo == None:
                    await TakePenaltyAction(event, group_ownerID, obligationProfilePicture, Delete_MSG, '**.. حسابه لا يمتلك صورة**')


    if Delete_MSG and event.user_joined: # or event.user_added:
        user_data = await bot.get_entity(event.user_id)

        containsAlphabets = await contains_alphabets(f'{user_data.first_name} {user_data.last_name}')
        if containsAlphabets["Arabic"] or containsAlphabets["Chinese"] or containsAlphabets["Cyrillic"]:
            await DeleteEvent(event)

        if user_data.last_name == None:
            await DeleteEvent(event)

        if user_data.username == None:
            await DeleteEvent(event)

        if user_data.photo == None:
            await DeleteEvent(event)


    # blocks - bot block
    if targetGroupSettings["blocks"]["bot_block"]["is_active"]:
        # if event.user_added:
        #     user = event.user
        #     group_id = event.chat_id

        #     # Check if the user is the bot itself or not
        #     if user.is_bot:
        #         print(f"Bot {user.username} added to the group.")
        #         return 
        pass

    # blocks - join block
    if targetGroupSettings["blocks"]["join_block"]["penalty"] != 'Off':
        JoinBlockPenalty = targetGroupSettings["blocks"]["join_block"]["penalty"]
        JoinBlockDelete = targetGroupSettings["blocks"]["join_block"]["delete_join_msg"]

        if event.user_joined:
            if JoinBlockDelete:
                await DeleteEvent(event)

            await TakePenaltyAction(event, group_ownerID, JoinBlockPenalty, JoinBlockDelete, '**قام بالانضمام أثناء وضع قيود على الانضمام**')


    # blocks - leave block
    if targetGroupSettings["blocks"]["leave_block"]["penalty"] != 'Off':
        LeaveBlockPenalty = targetGroupSettings["blocks"]["leave_block"]["penalty"]
        if event.user_left:
            await TakePenaltyAction(event, group_ownerID, LeaveBlockPenalty, True, '**قام بالمغادرة أثناء وضع قيود على المغادرة**')


    # blocks - join/leave block
    if targetGroupSettings["blocks"]["joinLeave_block"]["penalty"] != 'Off':
        if event.user_joined or event.user_added:
            user_join_times[(event.chat_id, event.user_id)] = asyncio.get_event_loop().time()

        elif event.user_left or event.user_kicked:
            join_time = user_join_times.get((event.chat_id, event.user_id))
            if join_time:
                elapsed_time = asyncio.get_event_loop().time() - join_time

                if elapsed_time <= LEAVE_TIME_THRESHOLD:
                    if targetGroupSettings["blocks"]["joinLeave_block"]["delete_service_msg"]:
                        await DeleteEvent(event)
                    # print(f"🚨 المستخدم {event.user_id} غادر سريعًا بعد {elapsed_time:.2f} ثانية! تم حذف رسالة المغادرة.")
                    await TakePenaltyAction(event, group_ownerID, LeaveBlockPenalty, True, '**لأنه غادر بعد الانضمام بسرعة**')

                user_join_times.pop((event.chat_id, event.user_id), None)


    # blocks - multiple joins block
    if targetGroupSettings["blocks"]["multiplejoins_block"]["penalty"] != 'Off':
        if event.user_joined or event.user_added:
            users_count = targetGroupSettings["blocks"]["multiplejoins_block"]["users_count"]
            max_timer = targetGroupSettings["blocks"]["multiplejoins_block"]["time"]
            await set_group_join_settings(event.chat_id, users_count, max_timer)

            chat_id = event.chat_id
            current_time = asyncio.get_event_loop().time()

            settings = get_group_settings(chat_id)
            max_joins = settings["max_joins"]
            time_window = settings["time_window"]

            if chat_id not in group_join_times:
                group_join_times[chat_id] = []

            group_join_times[chat_id].append(current_time)
            group_join_times[chat_id] = [t for t in group_join_times[chat_id] if current_time - t <= time_window]

            if len(group_join_times[chat_id]) >= max_joins:
                pass
                # print(f"🚨 تم اكتشاف انضمام جماعي في المجموعة {chat_id}! أكثر من {max_joins} مستخدمين في {time_window} ثانية.")

                # مثال على حظر جميع المستخدمين الذين انضموا في آخر 10 ثوانٍ:
                # for user_id in event.user_ids:
                #     await TakePenaltyAction(event, group_ownerID, LeaveBlockPenalty, True, '**قام بالمغادرة أثناء وضع قيود على المغادرة**')






print ("BOT STARTED")
bot.run_until_disconnected()