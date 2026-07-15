# Authored By Iota Coders © 2025
from pyrogram import filters
from IotaXMedia import app
from config import OWNER_ID, POST_GROUP_ID

@app.on_message(filters.command(["post"], prefixes=["/", "."]) & filters.user(OWNER_ID))
async def copy_messages(_, message):

    if message.reply_to_message:

        await message.reply_to_message.copy(POST_GROUP_ID)
        await message.reply("ᴘᴏsᴛ sᴜᴄᴄᴇssғᴜʟ ᴅᴏɴᴇ ")
