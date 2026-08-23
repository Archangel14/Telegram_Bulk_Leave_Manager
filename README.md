# Telegram Bulk Leave Manager

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python)
![Telethon](https://img.shields.io/badge/Telethon-API-blueviolet?style=for-the-badge)
![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-2ea44f?style=for-the-badge)

We all know Telegram is not just for your personal chats anymore. I'm not admitting to anything, but let's just say there is a lot of "free media" to go around there. For some of these, you have to join groups and channels, then their bots tell you to join more, and then you have to join even more if one channel doesn't have every season of what you want. Now you have a lot of bots, groups, and channels **spamming you with questionable media** on a minute-by-minute basis, and someone that looks at your notification bar thinks you have a highly questionable secret life. Depending on the person, things might get pretty manipulative or weird.

Now, considering "some of you" download lots of media from some of these bots and channels, and are too lazy to leave all of them manually after you're done, I present to you: **Telegram Bulk Leave Manager**. *(Yeah, inputs are invited for new names of this thing!)* 

Its purpose is simple: remove those groups and channels you don't need anymore. The setup is kinda simple. It runs on Python, so you set up your dependencies, validate your account, and you're good to go.

---

## Setup & Usage Guide

Here's what to do in case you want to use this:

1. Run `install_dependencies.bat`, indicating whether you want the required dependencies installed in a virtual environment or globally. *(This automatically sets up the Python packages needed for running this project).*

> [!NOTE]
> **API Credentials Needed**
> To actually make use of the app, you need a way for it to interface with your Telegram account. For this, you need to get your official Telegram API credentials directly from Telegram.

2. Visit [my.telegram.org](https://my.telegram.org).
3. Log in with your phone number in international format and the special code you will be sent via the Telegram app.
4. Go to **"API development tools"**.
5. Create a new application.
6. Fill in the fields. The names don't really matter, but they must follow certain rules like *no upper case letters*, a minimum length of 5, and a maximum length of 32 for the short name (which Telegram doesn't bother to tell you). You can set the platform to desktop and leave the URL field empty.

> [!IMPORTANT]
> You will get an `api_id` (a number) and an `api_hash` (a long string). **Keep these safe and only use them in software you absolutely trust.**

7. Come back to the project folder and double-click `Launch App.vbs`.
8. Log in via the app interface with your `api_id`, `api_hash`, phone number, auth code, and 2FA password (if prompted).
9. Select your preferred default action (this will be applied to all chats by default before you manually select what to choose and keep for each chat) and click the **Fetch Chats** button.
10. Go through all the chats in the list, toggle the action to be made for each (KEEP or LEAVE), and confirm your execution!

---

That's it, basically. This is just a simple passion project I worked on to solve my current dilemma. If you have suggestions for a better way to do a specific task within this project, more features without overengineering, or anything at all, just let me know!

And with all this in mind, happy Telegramming! 🏴‍☠️ *\*popular sea shanty playing in background\**
