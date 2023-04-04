from telethon.sync import TelegramClient, Button, events
from configparser import ConfigParser
import logging
from enum import auto
import os
import sqlite3
import json
import asyncio
import uuid
import traceback


# console logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%d-%b-%y %H:%M:%S'
    )


# Read config
parser = ConfigParser()
parser.read(os.path.join(os.path.dirname(__file__), 'config.ini'))
tg_api_id: int = int(parser['Telegram']['api_id'])
tg_api_hash: str = parser['Telegram']['api_hash']
tg_bot_token: str = parser['Telegram']['bot_token']

admins: list = [ int(x) for x in parser['Settings']['admins'].split(',') ]
bot_lang: str = parser['Settings']['language']
    

# read bot commands and messages
with open(file=os.path.join(os.path.dirname(__file__), 'bot_text.json'), mode='rt', encoding='utf-8') as f:
    bot_text: dict = json.loads(f.read())


# connect database
class SQLite():
    def __init__(self, file: str = os.path.join(os.path.dirname(__file__), 'database.db')):
        self.file = file

    def __enter__(self):
        self.conn = sqlite3.connect(self.file)
        self.conn.row_factory = sqlite3.Row
        return self.conn.cursor()

    def __exit__(self, type, value, traceback):
        self.conn.commit()
        self.conn.close()

with SQLite() as db_con:
    db_con.execute('CREATE TABLE IF NOT EXISTS groups(id INTEGER, username TEXT)')
    db_con.execute('CREATE TABLE IF NOT EXISTS messages(text TEXT, msg_id INTEGER)')
    db_con.execute('CREATE TABLE IF NOT EXISTS buttons(name TEXT, link TEXT, msg_id INTEGER)')
    db_con.execute('CREATE TABLE IF NOT EXISTS message_files(file_link TEXT, msg_id INTEGER)')


# interval
class Interval(object):
    def __init__(self) -> None:
        self.current_interval = 60

    def set_interval(self, interval) -> None:
        self.current_interval = interval

interval = Interval()

# chat states
class ChatState:
    bot_started = auto()
    waiting_for_del_group_id = auto()
    waiting_for_message_json = auto()
    waiting_for_message_text = auto()
    waiting_for_message_media = auto()
    waiting_for_message_button_name = auto()
    waiting_for_message_button_link = auto()
    do_you_wanna_add_button = auto()
    waiting_for_del_msg_id = auto()
    waiting_for_interval_button_input = auto()
    set_run_24x7_state: auto = auto()


chat_state: dict = dict()

pending_message_data = {}


# Run state
class RunState:
    STOPPED = auto()
    STARTED = auto()

    def __init__(self):
        self.current_run_state = self.STOPPED

    def set_run_state(self, state):
        self.current_run_state = state

run_state = RunState()


# start bot
session_folder_path: str = os.path.join(os.path.dirname(__file__), 'sessions')
if not os.path.exists(session_folder_path):
    os.mkdir(session_folder_path)

bot_session_path = os.path.join(session_folder_path, 'bot.session')
if os.path.exists(bot_session_path):
    os.remove(bot_session_path)

bot = TelegramClient(
    session=os.path.join(bot_session_path),
    api_id=tg_api_id,
    api_hash=tg_api_hash
)

bot.start(bot_token=tg_bot_token)


@bot.on(events.NewMessage(pattern='^/start|{}$'.format(bot_text['button']['back'][bot_lang])))
async def start_command_handler(event: events.NewMessage.Event) -> None:
    '''
    /start command handler
    '''
    if event.is_group:
        return
    
    if event.sender_id in admins:
        await bot.send_message(
            entity=event.chat,
            message=bot_text['response']['welcome'][bot_lang],
            buttons=[
            [
                Button.text(
                    text=bot_text['button']['get_current_setting'][bot_lang],
                    resize=True
                ),
                Button.text(
                    text=bot_text['button']['remove_group'][bot_lang],
                    resize=True
                )
            ],
            [
                Button.text(
                    text=bot_text['button']['add_msg_json'][bot_lang],
                    resize=True
                ),
                Button.text(
                    text=bot_text['button']['add_message'][bot_lang],
                    resize=True
                ),
                Button.text(
                    text=bot_text['button']['delete_message'][bot_lang],
                    resize=True
                )
            ],
            [
                Button.text(
                    text=bot_text['button']['change_interval'][bot_lang],
                    resize=True
                ),
                Button.text(
                    text=bot_text['button']['run_24x7'][bot_lang],
                    resize=True
                )
            ]
        ])
    else:
        await bot.send_message(
            entity=event.chat,
            message=bot_text['response']['no_bot_access'][bot_lang])
    
    chat_state[str(event.sender_id)] = ChatState.bot_started
    raise events.StopPropagation


@bot.on(events.NewMessage(pattern='^{}$'.format(bot_text['button']['get_current_setting'][bot_lang])))
async def get_current_settings_command_handler(event: events.NewMessage.Event) -> None:
    '''
    Get Current Settings command handler
    '''
    if event.is_group:
        return

    with SQLite() as db_con:
        group_usernames = db_con.execute('SELECT username FROM groups').fetchall()

    run_status = 'Turned On' if run_state.current_run_state == RunState.STARTED else 'Turned Off'

    message = bot_text['response']['current_setting'][bot_lang].format(
        ' '.join(['@' + username[0] for username in group_usernames]),
        run_status,
        interval.current_interval
    )

    await bot.send_message(
        entity=event.chat,
        message=message
    )

    raise events.StopPropagation
    
@bot.on(events.NewMessage(pattern='^{}$'.format(bot_text['button']['remove_group'][bot_lang])))
async def remove_group_command_handler(event: events.NewMessage.Event) -> None:
    '''
    Remove group command handler
    '''
    if event.is_group:
        return
    
    message = bot_text['response']['groups'][bot_lang]
    with SQLite() as db_con:
        group_usernames = db_con.execute('SELECT username FROM groups').fetchall()
        
    if len(group_usernames) >= 1:
        for username in group_usernames:
            message = message + f"\n{group_usernames.index(username) + 1} ➖ {username[0]}"
            
        message = message + '\n' + bot_text['response']['enter_group_number'][bot_lang]
            
        await bot.send_message(
            entity=event.chat,
            message=message,
            buttons=[
                Button.text(
                    text=bot_text['button']['back'][bot_lang],
                    resize=True
                )
            ]
        )
        chat_state[str(event.sender_id)] = ChatState.waiting_for_del_group_id
    else:
        await bot.send_message(
            entity=event.chat,
            message=bot_text['response']['no_groups_to_remove'][bot_lang]
        )
        
    raise events.StopPropagation


@bot.on(events.NewMessage(pattern='^{}$'.format(bot_text['button']['add_msg_json'][bot_lang])))
async def add_message_json_command_handler(event: events.NewMessage.Event) -> None:
    '''
    Add Message JSON command handler
    '''
    if event.is_group:
        return

    await bot.send_message(
        entity=event.chat,
        message=bot_text['response']['upload_json'][bot_lang],
        buttons=[
                Button.text(
                    text=bot_text['button']['back'][bot_lang],
                    resize=True
                )
            ]
    )

    chat_state[str(event.sender_id)] = ChatState.waiting_for_message_json
    raise events.StopPropagation

@bot.on(events.NewMessage(pattern='^{}$'.format(bot_text['button']['add_message'][bot_lang])))
async def add_message_command_handler(event: events.NewMessage.Event) -> None:
    '''
    Add message command handler
    '''
    if event.is_group:
        return
        
    await bot.send_message(
        entity=event.chat,
        message=bot_text['response']['enter_message_text'][bot_lang],
        buttons=[
                Button.text(
                    text=bot_text['button']['back'][bot_lang],
                    resize=True
                )
            ]
    )

    pending_message_data[str(event.sender_id)] = {}
    pending_message_data[str(event.sender_id)]['buttons'] = []

    chat_state[str(event.sender_id)] = ChatState.waiting_for_message_text
    raise events.StopPropagation


@bot.on(events.NewMessage(pattern='^{}$'.format(bot_text['button']['delete_message'][bot_lang])))
async def delete_message_command_handler(event: events.NewMessage.Event) -> None:
    '''
    Delete message command handler
    ''' 
    if event.is_group:
        return
        
    await bot.send_message(
        entity=event.chat,
        message=bot_text['response']['enter_msg_id'][bot_lang],
        buttons=[
            Button.text(
                text=bot_text['button']['delete_all'][bot_lang],
                resize=True
            ),
            Button.text(
                text=bot_text['button']['back'][bot_lang],
                resize=True
            )
        ]
    )
    
    chat_state[str(event.sender_id)] = ChatState.waiting_for_del_msg_id
    raise events.StopPropagation


@bot.on(events.NewMessage(pattern='^{}$'.format(bot_text['button']['change_interval'][bot_lang])))
async def change_interval_command_handler(event: events.NewMessage.Event) -> None:
    '''
    Change Interval command handler
    '''
    if event.is_group:
        return

    await bot.send_message(
        entity=event.chat,
        message=bot_text['response']['set_interval'][bot_lang],
        buttons=[
        [
            Button.text(
                text='➕1',
                resize=True
            ),
            Button.text(
                text='➕10',
                resize=True
            ),
            Button.text(
                text='➕100',
                resize=True
            )
        ],
        [
            Button.text(
                text='➖1',
                resize=True
            ),
            Button.text(
                text='➖10',
                resize=True
            ),
            Button.text(
                text='➖100',
                resize=True
            )
        ],
        [
            Button.text(
                text=bot_text['button']['back'][bot_lang],
                resize=True
            )
        ]
    ])

    chat_state[str(event.sender_id)] = ChatState.waiting_for_interval_button_input
    raise events.StopPropagation


@bot.on(events.NewMessage(pattern='^{}$'.format(bot_text['button']['run_24x7'][bot_lang])))
async def run_24x7_command_handler(event: events.NewMessage.Event) -> None:
    '''
    run 24x7 command handler
    '''
    if event.is_group:
        return

    await bot.send_message(
        entity=event.chat,
        message=bot_text['response']['select_option'][bot_lang],
        buttons=[
            [
                Button.text(
                    text=bot_text['button']['turn_on'][bot_lang],
                    resize=True
                ),
                Button.text(
                    text=bot_text['button']['turn_off'][bot_lang],
                    resize=True
                )
            ],
            [
                Button.text(
                    text=bot_text['button']['back'][bot_lang],
                    resize=True
                )
            ]
        ]
    )

    chat_state[str(event.sender_id)] = ChatState.set_run_24x7_state
    raise events.StopPropagation


@bot.on(events.ChatAction)
async def chat_action_handler(event: events.ChatAction.Event) -> None:
    '''
    Chat action handler
    '''
    bot_id: int = (await bot.get_me()).id

    if not(event.is_group) and event.chat_id != bot_id:
        return
        
    if event.user_added:

        entity = await event.get_chat()

        with SQLite() as db_con:
            groups_count = len(db_con.execute('SELECT id FROM groups').fetchall())

        if groups_count >= 10:
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['max_group_count_exceeded'][bot_lang]
            )
        else:
            try:
                username = entity.username if entity.username else str(entity.id)
            except:
                await bot.send_message(
                    entity=event.added_by,
                    message=bot_text['response']['private_group_err'][bot_lang]
                )
                return
            
            with SQLite() as db_con:
                db_con.execute(
                    'INSERT INTO groups VALUES(?, ?)', (event.chat_id,  username)
                    )
                    
            await bot.send_message(
                entity=event.added_by.id,
                message=bot_text['response']['bot_added_msg'][bot_lang]
                )
    
    elif event.user_kicked:
        with SQLite() as db_con:
            db_con.execute('DELETE FROM groups WHERE id=?', (event.chat_id, ))
    
    raise events.StopPropagation


def log_to_file(error: str) -> None:
    logging.error(error)
    with open(file='log.txt', mode='wt', encoding='utf-8') as f:
        f.write(error)


async def send_messages(messages, groups):
    '''
    send messages to groups
    '''

    while run_state.current_run_state == RunState.STARTED:
        for message in messages:
            text = message[0]
            msg_id = message[1]
            
            with SQLite() as db_con:                
                buttons_data = db_con.execute('SELECT * FROM buttons WHERE msg_id=?', (msg_id, )).fetchall()
                file_path = db_con.execute('SELECT file_link FROM message_files WHERE msg_id=?', (msg_id, )).fetchone()
            
            msg_buttons = []
            row = []
            
            for button_data in buttons_data:
                button = Button.url(
                    text=button_data[0].strip(),
                    url=button_data[1].strip()
                )
                row.append(button)

                if len(row) == 2:
                    msg_buttons.append(row.copy())
                    row.clear()
                if len(row) == 1 and buttons_data.index(button_data) == len(buttons_data) - 1:
                    msg_buttons.append(row)

            for group_id in groups:
                chat_entity = await bot.get_entity(group_id[0])

                try:
                    await bot.send_message(
                        entity=chat_entity,
                        message=text + '\n' + f"(MESSAGE ID: {msg_id})",
                        file=file_path[0],
                        buttons=msg_buttons)
                except Exception:
                    tb = traceback.format_exc()
                    log_to_file(tb)
                
            await asyncio.sleep(interval.current_interval)


files_folder_path = os.path.join(os.path.dirname(__file__), 'files')
if not os.path.exists(files_folder_path):
    os.mkdir(files_folder_path)


@bot.on(events.NewMessage)
async def state_handler(event: events.NewMessage.Event) -> None:
    '''
    state handler
    '''
    if event.is_group:
        return
    
    current_chat_state = chat_state.get(str(event.sender_id), None)

    if current_chat_state == ChatState.waiting_for_del_group_id:
        text = event.message.message.strip()
        
        if text.isdigit():
            group_index = int(text)
        else:
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['incorrect_group_number'][bot_lang]
            )
            return
            
        with SQLite() as db_con:
            group_usernames = db_con.execute('SELECT username FROM groups').fetchall()
            
        if len(group_usernames) >= group_index:
            username = group_usernames[group_index - 1]
            with SQLite() as db_con:
                db_con.execute('DELETE FROM groups WHERE username=?', (username[0], ))
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['group_removed'][bot_lang]
            )
            chat_state[str(event.sender_id)] = ChatState.bot_started
            raise events.StopPropagation
        else:
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['incorrect_group_number'][bot_lang]
            )

    elif current_chat_state == ChatState.waiting_for_message_json:
        if not event.media:
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['upload_json'][bot_lang]
            )
            return

        if event.media.document.mime_type != 'application/json':
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['upload_json'][bot_lang]
            )
            return

        file_path = os.path.join(
            os.path.dirname(__file__), event.media.document.attributes[0].file_name)

        await event.download_media(file_path)

        with open(file=file_path, mode='rt', encoding='utf-8') as f:
            message_data = json.loads(f.read())

        with SQLite() as db_con:
            message_id = len(db_con.execute('SELECT msg_id FROM messages').fetchall()) + 1

        try:
            messages = message_data['messages']
            for message in messages:
                
                with SQLite() as db_con:
                    text = '\n'.join(message['text'])
                    db_con.execute(
                        'INSERT INTO messages VALUES(?, ?)', (text, message_id))

                    file_link = message['file']
                    db_con.execute(
                        'INSERT INTO message_files VALUES(?, ?)', (file_link, message_id))
                    
                    for button in message['buttons']:
                        name = button['name']
                        link = button['link']

                        db_con.execute(
                            'INSERT INTO buttons VALUES(?, ?, ?)', (name, link, message_id)
                            )
                message_id += 1

            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['messages_added'][bot_lang]
            )
            
            chat_state[str(event.sender_id)] = ChatState.bot_started
            
        except Exception:
            tb = traceback.format_exc()
            log_to_file(tb)
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['json_format_error'][bot_lang])

    elif current_chat_state == ChatState.waiting_for_message_text:
        text = event.message.message.strip()
        
        if len(text) >= 1:
            pending_message_data[str(event.sender_id)]['text'] = text
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['upload_message_media'][bot_lang]
            )
            chat_state[str(event.sender_id)] = ChatState.waiting_for_message_media
            raise events.StopPropagation
        else:
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['enter_message_text'][bot_lang]
            )
            
    elif current_chat_state == ChatState.waiting_for_message_media:
        if event.message.media:
            file_path = os.path.join(
                files_folder_path,
                str(uuid.uuid4()) + '.' + event.message.media.document.attributes[-1].file_name.split('.')[-1]
                )
            await bot.download_media(message=event.message.media, file=file_path)
            pending_message_data[str(event.sender_id)]['file_path'] = file_path
            
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['do_you_wanna_add_button'][bot_lang],
                buttons=[
                    Button.text(
                        text=bot_text['button']['yes'][bot_lang],
                        resize=True
                    ),
                    Button.text(
                        text=bot_text['button']['no'][bot_lang],
                        resize=True
                    ),
                    Button.text(
                        text=bot_text['button']['back'][bot_lang],
                        resize=True
                    )
                ])
            chat_state[str(event.sender_id)] = ChatState.do_you_wanna_add_button
            raise events.StopPropagation
        else:
            await bot.send_message(event.chat, bot_text['response']['upload_message_media'][bot_lang])
    
    elif current_chat_state == ChatState.do_you_wanna_add_button:
        text = event.message.message.strip()
        
        if text == bot_text['button']['yes'][bot_lang]:
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['add_button_name'][bot_lang],
                buttons=[
                    Button.text(
                        text=bot_text['button']['back'][bot_lang],
                        resize=True
                    )
                ])
            chat_state[str(event.sender_id)] = ChatState.waiting_for_message_button_name
            raise events.StopPropagation
            
        elif text == bot_text['button']['no'][bot_lang]:
            with SQLite() as db_con:
                message_id = len(db_con.execute('SELECT msg_id FROM messages').fetchall()) + 1
                
                db_con.execute(
                    'INSERT INTO messages VALUES(?, ?)',
                    (pending_message_data[str(event.sender_id)]['text'], message_id))
                    
                db_con.execute('INSERT INTO message_files VALUES (?, ?)', 
                (pending_message_data[str(event.sender_id)]['file_path'], message_id))
                
                for button in pending_message_data[str(event.sender_id)]['buttons']:
                    db_con.execute('INSERT INTO buttons VALUES(?, ?, ?)',
                    (button[0], button[1], message_id))
                
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['message_added'][bot_lang],
                buttons=[
                    Button.text(
                        text=bot_text['button']['back'][bot_lang],
                        resize=True
                    )
                ])
                
            chat_state[str(event.sender_id)] = ChatState.bot_started
            raise events.StopPropagation
        else:
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['do_you_wanna_add_button'][bot_lang])
            
    
    elif current_chat_state == ChatState.waiting_for_message_button_name:
        text = event.message.message.strip()
        
        if len(text) >= 1:
            pending_message_data[str(event.sender_id)]['button_name'] = text
            
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['add_button_link'][bot_lang],
                buttons=[
                    Button.text(
                        text=bot_text['button']['back'][bot_lang],
                        resize=True
                    )
                ]
            )
            chat_state[str(event.sender_id)] = ChatState.waiting_for_message_button_link
            raise events.StopPropagation
        else:
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['add_button_name'][bot_lang])
        
    elif current_chat_state == ChatState.waiting_for_message_button_link:
        text = event.message.message.strip()
        
        if len(text) >= 1:
            pending_message_data[str(event.sender_id)]['buttons'].append(
                (pending_message_data[str(event.sender_id)]['button_name'], text)
                )
            
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['add_another_button'][bot_lang],
                buttons=[[
                    Button.text(
                        text=bot_text['button']['yes'][bot_lang],
                        resize=True
                    ),
                    Button.text(
                        text=bot_text['button']['no'][bot_lang],
                        resize=True
                    ),
                    Button.text(
                        text=bot_text['button']['back'][bot_lang],
                        resize=True
                    )
                ]])
                
            chat_state[str(event.sender_id)] = ChatState.do_you_wanna_add_button
            raise events.StopPropagation
            
        else:
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['add_button_link'][bot_lang],
                buttons=[
                    Button.text(
                        text=bot_text['button']['back'][bot_lang],
                        resize=True
                    )
                ]
            )
            
    elif current_chat_state == ChatState.waiting_for_del_msg_id:
        text = event.message.message.strip()
        
        if text.isdigit():
            msg_id = int(text)
            with SQLite() as db_con:
                db_con.execute('DELETE from messages WHERE msg_id=?', (msg_id, ))
                db_con.execute('DELETE from buttons WHERE msg_id=?', (msg_id, ))
                db_con.execute('DELETE from message_files WHERE msg_id=?', (msg_id, ))

            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['message_deleted'][bot_lang]
            )

            chat_state[str(event.sender_id)] = ChatState.bot_started
            raise events.StopPropagation
        elif text == bot_text['button']['delete_all'][bot_lang]:
            with SQLite() as db_con:
                db_con.execute('DELETE from messages')
                db_con.execute('DELETE from buttons')
                db_con.execute('DELETE from message_files')

            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['message_deleted'][bot_lang]
            )

            chat_state[str(event.sender_id)] = ChatState.bot_started
            raise events.StopPropagation
            
        else:
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['incorrect_msg_id'][bot_lang]
            )
            return

    elif current_chat_state == ChatState.waiting_for_interval_button_input:
        try:
            count = int(event.message.message[1:])
        except:
            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['button_input_error'][bot_lang]
            )
            return

        if event.message.message.startswith('➖'):
            if interval.current_interval >= count:
                interval.set_interval(interval.current_interval - count)
            else:
                interval.set_interval(0)
        elif event.message.message.startswith('➕'):
            interval.set_interval(interval.current_interval + count)

        await bot.send_message(
            entity=event.chat,
            message=bot_text['response']['message_send_time_set'][bot_lang].format(interval.current_interval)
        )

    elif current_chat_state == ChatState.set_run_24x7_state:
        if event.message.message == bot_text['button']['turn_on'][bot_lang]:
            
            with SQLite() as db_con:
                messages = db_con.execute('SELECT text, msg_id FROM messages').fetchall()
                group_ids = db_con.execute('SELECT id FROM groups').fetchall()
                
            if len(messages) == 0:
                await bot.send_message(
                    entity=event.chat, message=bot_text['response']['pls_add_message'][bot_lang])
                chat_state[str(event.sender_id)] = ChatState.bot_started
                raise events.StopPropagation
                
            if len(group_ids) == 0:
                await bot.send_message(
                    entity=event.chat, message=bot_text['response']['pls_add_groups'][bot_lang])
                chat_state[str(event.sender_id)] = ChatState.bot_started
                raise events.StopPropagation
            
            run_state.set_run_state(RunState.STARTED)

            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['message_send_time_updated_24x7'][bot_lang]
            )

            await send_messages(
                messages=messages, groups=group_ids
            )

        elif event.message.message == bot_text['button']['turn_off'][bot_lang]:
            run_state.set_run_state(RunState.STOPPED)

            await bot.send_message(
                entity=event.chat,
                message=bot_text['response']['message_sending_turned_off'][bot_lang]
            )


bot.run_until_disconnected()