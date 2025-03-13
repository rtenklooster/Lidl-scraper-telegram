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

## Usage

- `/start`: Initialize the bot and register the user
- `/menu`: Show the main menu with options to manage queries
- `/list`: List all current queries
- `/pause`: Pause all notifications
- `/resume`: Resume all notifications
- `/delete`: Delete a query

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

This project is licensed under the MIT License.
