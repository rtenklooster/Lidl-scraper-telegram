# Lidl Scraper Bot

This project is a Telegram bot that scrapes Lidl's website for product information and sends notifications to users.

## Features

- Add, remove, pause, and resume queries
- List current queries
- Send notifications for new products and price changes
- Multi-language support (Dutch and English)

## Setup

### Prerequisites

- Python 3.11
- Telegram bot token

### Installation

1. Clone the repository:
   ```sh
   git clone https://github.com/yourusername/lidl-scraper.git
   cd lidl-scraper
   ```

2. Create a virtual environment and activate it:
   ```sh
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. Install the required packages:
   ```sh
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the root directory and add your Telegram bot token and database name:
   ```env
   TOKEN=your-telegram-bot-token
   DATABASE_NAME=lidl_scraper.db
   ```

5. Run the bot:
   ```sh
   python bot.py
   ```

### Running the Bot with a Custom Database Path

You can specify a custom path for the database file when running the bot using the `--db-path` parameter. For example:

```sh
python bot.py --db-path path/to/your/database.db
```

This allows you to use a different database file instead of the default one specified in the `.env` file.

## Usage

- `/start`: Initialize the bot and register the user
- `/menu`: Show the main menu with options to manage queries
- `/list`: List all current queries
- `/pause`: Pause all notifications
- `/resume`: Resume all notifications
- `/delete`: Delete a query

## Notifications

Notifications are sent when new items appear in one of the configured searches, or when existing items in a search change in price.

## Adding a Search Query

Adding a search query is very simple. Go to the Lidl website for your country (e.g., lidl.nl, lidl.de, lidl.it), search for products in the Lidl shop, apply any desired filters, copy the URL from the address bar, and paste it into the chat.

## Registering a Telegram Bot

To register a Telegram bot, follow these steps:

1. Open the Telegram app and search for the BotFather.
2. Start a chat with the BotFather and send the command `/newbot`.
3. Follow the instructions to choose a name and username for your bot.
4. Once the bot is created, you will receive a token. Copy this token.
5. Add the token to your `.env` file as described in the Setup section.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

This project is licensed under the MIT License.
