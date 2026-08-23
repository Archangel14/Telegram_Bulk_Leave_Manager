# Telegram Bulk Leave Manager

We all know Telegram is not just for your personal chats anymore. I'm not admitting to anything, but let's just say there is a lot of "free media" to go around there. For some of these, you have to join groups and channels, then their bots tell you to join more, and then you have to join even more if one channel doesn't have every season of what you want. Now you have a lot of bots, groups, and channels sending you media on a minute basis, and someone that looks at your notification bar thinks they found out about your private time partner. Depending on the person, things might get pretty manipulative or weird.

Now, considering some of "you" download lots of media from some of these platforms and bots, and are too lazy to leave all of them manually, I present to you: **Telegram Bulk Leave Manager**. *(Yeah, inputs are invited for new names of this thing!)* 

Its purpose is simple: remove those groups and channels you don't need anymore. The setup is kinda simple. It runs on Python, so you set up your dependencies, and you're good to go.

---

### Setup & Usage Guide

Here's what to do in case you want to use this:

1. Run `install_dependencies.bat`, indicating whether you want the required dependencies installed in a virtual environment or globally. *(This sets up the Python packages needed for running this project).*

> **Note:** To actually make use of the app, you'd need a way for it to interface with your Telegram account and its content. For this, you'd need to get your official Telegram API credentials. 

2. Visit [my.telegram.org](https://my.telegram.org).
3. Log in with your phone number in international format and the special code you will be sent via the Telegram app.
4. Go to **"API development tools"**.
5. Create a new application.
6. Fill in the fields. The names don't really matter, but they must follow certain rules like *no upper case letters*, a minimum length of 5, and a maximum length of 32 for the short name (which Telegram doesn't bother to tell you). You can set the platform to desktop and leave the URL field empty.
7. You will get an `api_id` (a number) and an `api_hash` (a long string). **Keep these safe and only use them in software you absolutely trust.**
8. Come back to the project folder and double-click `Launch App.vbs`.
9. Log in via the app interface with your `api_id`, `api_hash`, phone number, auth code, and 2FA password (if prompted).
10. Select your preferred default action (this will be applied to all fetched platforms before you edit them) and click the **Fetch Chats** button.
11. Go through all the groups and channels in the list, toggle the action to be made for each (KEEP or LEAVE), and confirm your execution!

---

That's it, basically. This is just a simple passion project I worked on to solve my current dilemma. If you have suggestions for a better way to do a specific task within this project, more features without overengineering, or anything at all, just let me know!

And with all this in mind, happy Telegramming! 🏴‍☠️ *\*popular sea shanty playing in background\**
