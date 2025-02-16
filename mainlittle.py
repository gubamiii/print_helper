import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, User
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)
from datetime import datetime, timedelta
import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import aiohttp
import io
import traceback
from google.oauth2.service_account import Credentials
import warnings
from dotenv import load_dotenv
import sys
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
(NAME, COURSE, DIRECTION, FORMAT_CHOICE,
 CUSTOM_FORMAT, FILE, PRINT_DATE, CONFIRM_DATE, CONFIRMATION) = range(9)


BASE_DIR = Path(__file__).resolve().parent

# Путь к файлу с сообщениями
MESSAGES_FILE = os.path.join(BASE_DIR, 'resources', 'conversation_strings_2_ru.json')

def load_messages():
    try:
        with open(MESSAGES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Messages file not found at: {MESSAGES_FILE}")
        logger.error(f"Current working directory: {os.getcwd()}")
        logger.error(f"BASE_DIR: {BASE_DIR}")
        logger.error(f"File exists: {os.path.exists(MESSAGES_FILE)}")
        raise
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in messages file: {MESSAGES_FILE}")
        raise

# Загрузка сообщений
MESSAGES = load_messages()

def get_message(key):
    message = MESSAGES.get(key)
    if message is None:
        logger.error(f"Message key '{key}'not found "
                     "in conversation_strings_2_ru.json")
        return f"Сообщение с ключом '{key}' не найдено."
    return message


# Define choices for keyboards
DIRECTION_CHOICES = [['Архитектура', 'Дизайн']]
UNIVERSITY_CHOICES = [['1', '2', '3', '4', '5']]
FORMAT_CHOICES = [['A1', 'A2', 'A3', 'A4'], ['Свой формат']]

# File to store all user messages
LOG_FILE = 'all_users_log.json'


def log_message(user_id, message):
    timestamp = datetime.now().isoformat()
    log_entry = {
        "user_id": user_id, "timestamp": timestamp, "message": message}

    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            log = json.load(f)
    else:
        log = []

    log.append(log_entry)

    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# Define the keyboard layouts
def create_course_keyboard():
    keyboard = UNIVERSITY_CHOICES
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True,
                               one_time_keyboard=True)


def create_direction_keyboard():
    keyboard = DIRECTION_CHOICES
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True,
                               one_time_keyboard=True)


def create_format_keyboard():
    keyboard = [
        ["A4", "A3"],
        ["A2", "A1"],
        ["A0", "Свой формат"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True,
                               one_time_keyboard=True)


def create_date_keyboard():
    keyboard = []
    today = datetime.now().date()
    for i in range(30):
        date = today + timedelta(days=i)
        keyboard.append([date.strftime("%d.%m.%Y")])
    return ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)


BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, 'credentials', 'service-account.json')
FOLDER_ID = os.getenv('GOOGLE_DRIVE_FOLDER_ID')


def get_google_credentials():
    try:
        credentials_dict = {
            "type": "service_account",
            "project_id": os.getenv('GOOGLE_PROJECT_ID'),
            "private_key_id": os.getenv('GOOGLE_PRIVATE_KEY_ID'),
            "private_key": os.getenv('GOOGLE_PRIVATE_KEY').replace('\\n', '\n'),
            "client_email": os.getenv('GOOGLE_CLIENT_EMAIL'),
            "client_id": os.getenv('GOOGLE_CLIENT_ID'),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.getenv('GOOGLE_CLIENT_X509_CERT_URL'),
            "universe_domain": "googleapis.com"
        }

        required_vars = ['GOOGLE_PROJECT_ID', 'GOOGLE_PRIVATE_KEY_ID', 
                        'GOOGLE_PRIVATE_KEY', 'GOOGLE_CLIENT_EMAIL', 
                        'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_X509_CERT_URL']
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise EnvironmentError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )

        # Создаем учетные данные из словаря
        credentials = Credentials.from_service_account_info(
            credentials_dict,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        return credentials
        
    except Exception as e:
        logger.error(f"Error getting Google credentials: {str(e)}")
        raise


class TelegramBot:
    def __init__(self):
        self.user_states = {}
        logger.info("TelegramBot initialized")

    async def ask_print_format(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Какой формат печати вам нужен?", reply_markup=create_format_keyboard())

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        logger.info(f"Start command received from user {update.effective_user.id}")
        context.user_data.clear()

        await update.message.reply_text(MESSAGES['format_choice_prompt'], reply_markup=create_format_keyboard())
        return FORMAT_CHOICE

    async def handle_format_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        logger.info(f"Handling format choice for user {update.effective_user.id}")
        user_choice = update.message.text.strip()
        logger.info(f"User chose format: {user_choice}")
        
        if user_choice == "Свой формат":
            await update.message.reply_text(MESSAGES['custom_format_prompt'])
            context.user_data['awaiting_custom_format'] = True
            logger.info("Awaiting custom format")
            return FORMAT_CHOICE
        elif context.user_data.get('awaiting_custom_format'):
            context.user_data['print_format'] = user_choice
            context.user_data['awaiting_custom_format'] = False
            await update.message.reply_text(MESSAGES['file_request'])
            logger.info(f"Custom format set: {user_choice}. Requesting file.")
            return FILE
        else:
            context.user_data['print_format'] = user_choice
            await update.message.reply_text(MESSAGES['file_request'])
            logger.info(f"Format set: {user_choice}. Requesting file.")
            return FILE


    async def download_file(self, file, context):
        try:
            file_id = file.file_id
            logging.info(f"Attempting to download file with ID: {file_id}")

            # Get file path using Telegram Bot API
            bot_token = context.bot.token
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api.telegram.org/'
                                       f'bot{bot_token}/getFile?file_id={file_id}'
                                       ) as response:
                    file_info = await response.json()
                    if not file_info.get('ok'):
                        raise Exception("Failed to get file info:"
                                        f"{file_info.get('description')}")
                    file_path = file_info['result']['file_path']

            # Download file
            file_url = f'https://api.telegram.org/file/bot{bot_token}/{file_path}'
            logging.info(f"Downloading file from: {file_url}")

            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as response:
                    if response.status != 200:
                        raise Exception("Failed to download file:"
                                        f"HTTP {response.status}")
                    file_content = await response.read()

            # Save file locally
            file_name = os.path.basename(file_path)
            with open(file_name, 'wb') as f:
                f.write(file_content)

            logging.info(f"File downloaded successfully: {file_name}")

            return file_name
        except Exception as e:
            logging.error(f"Error in download_file: {str(e)}")
            logging.error(traceback.format_exc())
            raise

    def get_user_mention(self, user: User) -> str:
        if user.username:
            return f"@{user.username}"
        else:
            return f"tg://user?id={user.id}"

    async def handle_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        logger.info(f"Handling file for user {update.effective_user.id}")
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.pdf']
        allowed_mime_types = ['image/jpeg', 'image/png', 'application/pdf']

        if update.message.document:
            file = update.message.document
            file_name = file.file_name
            mime_type = file.mime_type
            file_extension = os.path.splitext(file_name)[1].lower()

            if file_extension not in allowed_extensions or mime_type not in allowed_mime_types:
                await update.message.reply_text(MESSAGES['unsupported_file_type'])
                return FILE

            file_obj = await file.get_file()

        elif update.message.photo:
            # Telegram автоматически конвертирует изображения в JPEG
            file = update.message.photo[-1]
            file_name = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            file_obj = await file.get_file()

        else:
            await update.message.reply_text(MESSAGES['unsupported_file_type'])
            return FILE

        context.user_data['file'] = file_obj
        context.user_data['original_filename'] = file_name

        await update.message.reply_text(MESSAGES['file_received'], reply_markup=create_date_keyboard())
        return PRINT_DATE

    async def get_print_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_response = update.message.text.strip()
        today = datetime.now().date()

        logger.debug(f"get_print_date: User response: {user_response}")

        valid_dates = [(today + timedelta(days=i)).strftime("%d.%m.%Y") for i in range(30)]

        if user_response in valid_dates:
            context.user_data['print_date'] = user_response
            logger.debug(f"get_print_date: Date accepted: {user_response}")

            await update.message.reply_text(MESSAGES['confirm_date'].format(
                print_date=context.user_data['print_date']
            ), reply_markup=ReplyKeyboardMarkup([['Да', 'Нет']], one_time_keyboard=True, resize_keyboard=True))

            logger.debug(f"get_print_date: Returning CONFIRM_DATE state")
            return CONFIRM_DATE
        else:
            logger.debug(f"get_print_date: Invalid date: {user_response}")
            await update.message.reply_text(MESSAGES['invalid_date'], reply_markup=create_date_keyboard())
            return PRINT_DATE

    async def confirm_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        logger.debug("confirm_date: Entering function")
        if 'print_date' not in context.user_data:
            logger.debug("confirm_date: Print date not found in user data")
            await update.message.reply_text(MESSAGES['error_missing_data'])
            return ConversationHandler.END

        user_response = update.message.text.lower()
        logger.debug(f"confirm_date: User response: {user_response}")

        if user_response == 'да':
            logger.debug("confirm_date: Date confirmed")
            await update.message.reply_text(MESSAGES['date_confirmed'])
            # Show the order summary and proceed to confirmation
            await self.show_order_summary(update, context)
            return CONFIRMATION
        elif user_response == 'нет':
            logger.debug("confirm_date: Date rejected")
            await update.message.reply_text(MESSAGES['choose_date_again'], reply_markup=create_date_keyboard())
            return PRINT_DATE
        else:
            logger.debug("confirm_date: Invalid confirmation response")
            await update.message.reply_text(MESSAGES['invalid_confirmation'], reply_markup=ReplyKeyboardMarkup([['Да', 'Нет']], one_time_keyboard=True, resize_keyboard=True))
            return CONFIRM_DATE

    async def handle_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_response = update.message.text.strip()

        if user_response == MESSAGES['confirm_order_button']:
            try:
                await self.upload_file_to_drive(update, context)
                return ConversationHandler.END
            except Exception as e:
                await update.message.reply_text(
                    f"Произошла ошибка при обработке заказа: {str(e)}\n\n"
                    "Чтобы попробовать снова, нажмите /start",
                    reply_markup=ReplyKeyboardMarkup([['/start']], resize_keyboard=True)
                )
                return ConversationHandler.END
        else:
            await update.message.reply_text(MESSAGES['please_choose_one'])
            return CONFIRMATION

    async def upload_file_to_drive(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_data = context.user_data

        file = user_data['file']
        original_filename = user_data['original_filename']
        print_date = user_data['print_date']
        print_format = user_data.get('print_format', 'NoFormat')

        user_name = user.full_name
        user_mention = self.get_user_mention(user)

        new_filename = f"{print_date}_{print_format}_{user_name}_{user_mention}_{original_filename}"
        new_filename = new_filename.replace(' ', '_')

        logger.info(f"Uploading file with name: {new_filename}")

        try:
            file_buffer = io.BytesIO(await file.download_as_bytearray())

            credentials = get_google_credentials()
            service = build('drive', 'v3', credentials=credentials)

            file_metadata = {
                'name': new_filename,
                'parents': [FOLDER_ID],
            }
            media = MediaIoBaseUpload(file_buffer,
                                      mimetype='application/octet-stream',
                                      resumable=True)
            uploaded_file = service.files().create(body=file_metadata,
                                                   media_body=media,
                                                   fields='id').execute()

            file_id = uploaded_file.get('id')
            context.user_data['file_id'] = file_id

            logger.info(f"File uploaded successfully with ID: {file_id}")
            await update.message.reply_text(
                MESSAGES['order_confirmed'] + "\n\nЧтобы сделать новый заказ, нажмите /start",
                reply_markup=ReplyKeyboardMarkup([['/start']], resize_keyboard=True)
            )

        except Exception as drive_error:
            logger.error(f"Error uploading file to Google Drive: {str(drive_error)}")
            raise Exception(MESSAGES['file_upload_error'].format(
                error_message=str(drive_error)))

    async def cancel(self, update: Update,
                     context: ContextTypes.DEFAULT_TYPE) -> int:
        user_id = update.effective_user.id
        message = MESSAGES['cancel_message']
        await update.message.reply_text(message,
                                        reply_markup=ReplyKeyboardRemove())
        log_message(user_id, f"Bot: {message}")
        return ConversationHandler.END

    def print_log_contents(self):
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                log_data = json.load(f)
                for entry in log_data:
                    print(f"User ID: {entry['user_id']}")
                    print(f"Timestamp: {entry['timestamp']}")
                    print(f"Message: {entry['message']}")
                    print("---")
        else:
            print("Log file does not exist yet.")

    def run(self):
        logger.info("Starting the bot")
        application = Application.builder().token(BOT_TOKEN).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start)],
            states={
                FORMAT_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_format_choice)],
                FILE: [MessageHandler(filters.PHOTO | filters.Document.ALL, self.handle_file)],
                PRINT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_print_date)],
                CONFIRM_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.confirm_date)],
                CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_confirmation)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel)],
        )

        application.add_handler(conv_handler)
        application.run_polling()
        self.print_log_contents()

    def create_confirmation_keyboard(self):
        keyboard = [
            [MESSAGES['confirm_order_button']]
        ]
        return ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

    async def show_order_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        print_format = context.user_data.get('print_format', 'Не указан')
        print_date = context.user_data.get('print_date', "Не указана")
        file_name = context.user_data.get('original_filename', 'Не указано')

        summary = f"Формат печати: {print_format}\n"
        summary += f"Дата печати: {print_date}\n"
        summary += f"Файл: {file_name}\n"
        summary += "\nПожалуйста, подтвердите ваш заказ:"

        await update.message.reply_text(summary, reply_markup=self.create_confirmation_keyboard())



def validate_google_credentials():
    required_vars = [
        'GOOGLE_PROJECT_ID',
        'GOOGLE_PRIVATE_KEY_ID',
        'GOOGLE_PRIVATE_KEY',
        'GOOGLE_CLIENT_EMAIL',
        'GOOGLE_CLIENT_ID',
        'GOOGLE_CLIENT_X509_CERT_URL',
        'GOOGLE_DRIVE_FOLDER_ID'
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        raise EnvironmentError(
            f"Missing required Google credentials: {', '.join(missing_vars)}"
        )

if __name__ == '__main__':
    try:
        load_dotenv()
        validate_google_credentials()
        bot = TelegramBot()
        bot.run()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        sys.exit(1)