#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SELVA & OTP - Complete Management System
النسخة النهائية الكاملة بجميع المميزات + نظام Queue لإعادة التوجيه
"""

import sys
import asyncio
import sqlite3
import os
import threading
import time
import json
import hashlib
import re
from collections import deque
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, make_response, session, redirect, url_for
from werkzeug.utils import secure_filename
from telethon import TelegramClient, events
from telethon.errors import ChannelPrivateError, ChatAdminRequiredError, FloodWaitError
from functools import wraps

# ============================================================
#                  الإعدادات
# ============================================================

API_ID = 33437938
API_HASH = '4aa02cced89e0eb1c509ac1f5336d5b7'
CHANNEL_ID = -1003889045343
SESSION_NAME = 'selva_user_session'
BOT_TOKEN = '8630472381:AAGUK1apd8IHJnq1_O_JPiM6nNnABnGdvFc'

OWNER_USERNAME = 'mohaymen'
OWNER_PASSWORD = 'mohaymen'

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) or '.'
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
ALLOWED_EXTENSIONS = {'txt', 'csv', 'json'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'elva_otp_secret_key_2024'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ============================================================
#                      نظام Queue لإعادة التوجيه
# ============================================================

message_queue = deque()
forwarding_task = None
queue_lock = threading.Lock()

# ============================================================
#                      دوال مساعدة
# ============================================================

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def owner_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        if session.get('username') != OWNER_USERNAME:
            return redirect('/dashboard')
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def parse_numbers_file(filepath):
    numbers = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                nums = re.findall(r'\b\d{8,15}\b', line)
                numbers.extend(nums)
    except:
        pass
    return numbers

def extract_otp_from_message(text):
    if not text:
        return None
    patterns = [
        r'\b(\d{4,8})\b',
        r'code[:\s]*(\d{4,8})',
        r'OTP[:\s]*(\d{4,8})',
        r'verify[:\s]*(\d{4,8})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None

def log_activity(user_id, action, details=""):
    try:
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT INTO activity_logs (user_id, action, details, created_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, action, details, datetime.now().isoformat()))
        db_conn.commit()
    except:
        pass

def add_notification(user_id, title, message, notif_type="info"):
    try:
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT INTO notifications (user_id, title, message, type, created_at, is_read)
            VALUES (?, ?, ?, ?, ?, 0)
        ''', (user_id, title, message, notif_type, datetime.now().isoformat()))
        db_conn.commit()
    except:
        pass

def add_owner_notification(message):
    try:
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT INTO owner_notifications (message, created_at)
            VALUES (?, ?)
        ''', (message, datetime.now().isoformat()))
        db_conn.commit()
    except:
        pass

# ============================================================
#                      قاعدة البيانات
# ============================================================

def init_database():
    db_path = os.path.join(BASE_DIR, 'selv_system.db')
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            whatsapp TEXT,
            email TEXT,
            profile_pic TEXT,
            theme TEXT DEFAULT 'dark',
            language TEXT DEFAULT 'ar',
            is_blocked INTEGER DEFAULT 0,
            number_limit INTEGER DEFAULT 150,
            created_at TEXT,
            last_login TEXT,
            parent_id INTEGER DEFAULT 0,
            is_client INTEGER DEFAULT 0
        )
    ''')
    
    for col in ['email', 'profile_pic', 'theme', 'language', 'parent_id', 'is_client']:
        try:
            cursor.execute(f'ALTER TABLE users ADD COLUMN {col} TEXT')
        except:
            pass
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS number_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            numbers TEXT,
            created_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test_number_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            country_name TEXT NOT NULL,
            numbers TEXT,
            numbers_count INTEGER DEFAULT 0,
            created_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_numbers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_id INTEGER,
            number TEXT,
            added_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (file_id) REFERENCES number_files(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_numbers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            file_id INTEGER,
            number TEXT,
            added_at TEXT,
            added_by INTEGER,
            FOREIGN KEY (client_id) REFERENCES users(id),
            FOREIGN KEY (added_by) REFERENCES users(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deleted_user_numbers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_id INTEGER,
            number TEXT,
            deleted_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deleted_user_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_id INTEGER,
            file_name TEXT,
            deleted_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER UNIQUE,
            text TEXT,
            date TEXT,
            saved_at TEXT,
            is_deleted INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS owner_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT,
            created_at TEXT,
            is_read INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT,
            sent_at TEXT,
            recipients_count INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            number TEXT,
            code TEXT,
            received_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            message TEXT,
            type TEXT,
            created_at TEXT,
            is_read INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS support_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            message TEXT,
            created_at TEXT,
            is_read INTEGER DEFAULT 0,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS linked_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id TEXT NOT NULL,
            channel_name TEXT,
            added_at TEXT,
            is_active INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    
    conn.commit()
    
    cursor.execute('SELECT id FROM users WHERE username = ?', (OWNER_USERNAME,))
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO users (username, password, number_limit, created_at)
            VALUES (?, ?, ?, ?)
        ''', (OWNER_USERNAME, hash_password(OWNER_PASSWORD), 999999, datetime.now().isoformat()))
        conn.commit()
        print(f'✅ تم إنشاء حساب المالك: {OWNER_USERNAME}')
    
    return conn

db_conn = init_database()

def get_user_numbers_count(user_id):
    cursor = db_conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM user_numbers WHERE user_id = ?', (user_id,))
    return cursor.fetchone()[0]

def get_user_limit(user_id):
    cursor = db_conn.cursor()
    cursor.execute('SELECT number_limit FROM users WHERE id = ?', (user_id,))
    result = cursor.fetchone()
    if result and result[0]:
        try:
            return int(result[0])
        except:
            return 150
    return 150

def get_unread_notifications_count(user_id):
    try:
        cursor = db_conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0', (user_id,))
        return cursor.fetchone()[0]
    except:
        return 0

def get_unread_messages_count(user_id):
    try:
        cursor = db_conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM support_messages WHERE receiver_id = ? AND is_read = 0', (user_id,))
        return cursor.fetchone()[0]
    except:
        return 0

def is_client(user_id):
    cursor = db_conn.cursor()
    cursor.execute('SELECT is_client FROM users WHERE id = ?', (user_id,))
    result = cursor.fetchone()
    return result and result[0] == 1

def save_codes_for_user(user_id, number, code):
    try:
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT INTO user_codes (user_id, number, code, received_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, number, code, datetime.now().isoformat()))
        db_conn.commit()
        add_notification(user_id, "🔐 كود OTP جديد", f"تم استلام كود جديد: {code}", "otp")
    except:
        pass

def save_message_to_db(msg_id, text, date):
    try:
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO messages (message_id, text, date, saved_at, is_deleted)
            VALUES (?, ?, ?, ?, 0)
        ''', (msg_id, text, date, datetime.now().isoformat()))
        
        code = extract_otp_from_message(text)
        if code:
            cursor.execute('''
                SELECT user_id FROM user_numbers 
                WHERE ? LIKE '%' || substr(number, -4) 
                OR number LIKE '%' || ?
            ''', (text, code))
            user_rows = cursor.fetchall()
            for row in user_rows:
                save_codes_for_user(row[0], '', code)
        
        db_conn.commit()
        return True
    except Exception as e:
        print(f"خطأ في حفظ الرسالة: {e}")
        return False

def get_user_linked_channels(user_id):
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT id, channel_id, channel_name, is_active, added_at 
        FROM linked_channels 
        WHERE user_id = ? AND is_active = 1
        ORDER BY id DESC
    ''', (user_id,))
    return cursor.fetchall()

def get_all_active_linked_channels():
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT DISTINCT channel_id FROM linked_channels WHERE is_active = 1
    ''')
    return [row[0] for row in cursor.fetchall()]

# ============================================================
#                      تيليجرام مع Queue
# ============================================================

user_client = None
bot_client = None
loop = None

async def login_user_session():
    global user_client
    print('📱 جاري تسجيل الدخول بحساب المستخدم...')
    try:
        await user_client.start()
        me = await user_client.get_me()
        print(f'✅ تم تسجيل الدخول كـ: {me.first_name} (@{me.username})')
        return True
    except Exception as e:
        print(f'❌ فشل تسجيل الدخول: {e}')
        return False

async def login_bot():
    global bot_client
    print('🤖 جاري تسجيل الدخول بالبوت...')
    try:
        await bot_client.start(bot_token=BOT_TOKEN)
        me = await bot_client.get_me()
        print(f'✅ تم تسجيل الدخول بالبوت: @{me.username}')
        return True
    except Exception as e:
        print(f'❌ فشل تسجيل الدخول بالبوت: {e}')
        return False

async def forward_worker():
    """عامل إعادة التوجيه - يشتغل في الخلفية"""
    global bot_client, message_queue
    
    print('🔄 عامل إعادة التوجيه بدأ العمل...')
    
    while True:
        try:
            if message_queue and bot_client:
                # جيب رسالة من القائمة
                message_text = message_queue.popleft()
                channels = get_all_active_linked_channels()
                
                if channels:
                    print(f'📤 جاري إرسال الرسالة إلى {len(channels)} قناة...')
                    
                    # إرسال لأول قناة
                    first_channel = channels[0]
                    try:
                        entity = await bot_client.get_entity(int(first_channel))
                        await bot_client.send_message(entity, message_text)
                        print(f'   ✅ تم الإرسال إلى: {first_channel}')
                        
                        # إعادة توجيه لباقي القنوات مع تأخير
                        for i, channel_id in enumerate(channels[1:], 1):
                            try:
                                await asyncio.sleep(2)  # تأخير 2 ثانية بين كل رسالة
                                entity = await bot_client.get_entity(int(channel_id))
                                await bot_client.send_message(entity, message_text)
                                print(f'   ✅ تم الإرسال إلى: {channel_id} ({i+1}/{len(channels)})')
                            except FloodWaitError as e:
                                print(f'   ⏳ انتظار {e.seconds} ثانية...')
                                await asyncio.sleep(e.seconds)
                                entity = await bot_client.get_entity(int(channel_id))
                                await bot_client.send_message(entity, message_text)
                                print(f'   ✅ تم الإرسال إلى: {channel_id}')
                            except Exception as e:
                                print(f'   ❌ فشل الإرسال إلى {channel_id}: {e}')
                                
                    except FloodWaitError as e:
                        print(f'   ⏳ انتظار {e.seconds} ثانية...')
                        await asyncio.sleep(e.seconds)
                        entity = await bot_client.get_entity(int(first_channel))
                        await bot_client.send_message(entity, message_text)
                        print(f'   ✅ تم الإرسال إلى: {first_channel}')
                    except Exception as e:
                        print(f'   ❌ فشل الإرسال: {e}')
            
            await asyncio.sleep(1)  # فحص كل ثانية
            
        except Exception as e:
            print(f'❌ خطأ في العامل: {e}')
            await asyncio.sleep(5)

def start_forwarding_worker():
    """بدء عامل إعادة التوجيه"""
    global forwarding_task, loop
    if loop:
        forwarding_task = loop.create_task(forward_worker())
        print('✅ عامل إعادة التوجيه جاهز')

def add_to_queue(message_text):
    """إضافة رسالة إلى قائمة الانتظار"""
    message_queue.append(message_text)
    print(f'📥 تمت إضافة رسالة إلى قائمة الانتظار (الإجمالي: {len(message_queue)})')

def start_message_listener():
    @user_client.on(events.NewMessage(chats=CHANNEL_ID))
    async def handler(event):
        msg = event.message
        if msg.message:
            print(f'📨 رسالة جديدة: {msg.message[:50]}...')
            save_message_to_db(msg.id, msg.message, msg.date.isoformat())
            
            cursor = db_conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO stats (key, value) 
                VALUES ('last_sync', ?)
            ''', (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
            db_conn.commit()
            
            # إضافة للقائمة بدل الإرسال الفوري
            add_to_queue(msg.message)
            add_owner_notification(f'📨 رسالة جديدة: {msg.message[:30]}...')

def init_telegram():
    global user_client, bot_client, loop
    if user_client is None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        user_client = TelegramClient(SESSION_NAME, API_ID, API_HASH, loop=loop)
        success = loop.run_until_complete(login_user_session())
        if not success:
            raise Exception("فشل تسجيل الدخول بحساب المستخدم")
        
        bot_client = TelegramClient('bot_session', API_ID, API_HASH, loop=loop)
        success = loop.run_until_complete(login_bot())
        if not success:
            print('⚠️ فشل تسجيل الدخول بالبوت - إعادة التوجيه معطلة')
        else:
            print('✅ البوت جاهز لإعادة التوجيه')
            start_forwarding_worker()
        
        start_message_listener()
        print('🔔 تم تفعيل مراقبة الرسائل الجديدة')

async def fetch_and_save_messages():
    global user_client
    try:
        print(f'📡 جاري جلب الرسائل من القناة {CHANNEL_ID}...')
        entity = await user_client.get_entity(CHANNEL_ID)
        messages = await user_client.get_messages(entity, limit=100)
        print(f'📨 عدد الرسائل المستلمة: {len(messages)}')
        
        count = 0
        for msg in messages:
            if msg.message:
                if save_message_to_db(msg.id, msg.message, msg.date.isoformat()):
                    count += 1
        
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO stats (key, value) 
            VALUES ('last_sync', ?)
        ''', (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
        db_conn.commit()
        
        print(f'💾 تم حفظ {count} رسالة في قاعدة البيانات')
        return {'success': True, 'new_messages': count}
    except Exception as e:
        print(f'❌ خطأ في جلب الرسائل: {e}')
        return {'success': False, 'error': str(e)}

# ============================================================
#                      الأنماط الأساسية
# ============================================================

def get_base_style(theme='light'):  # خليتها light دايمًا
    # لو عايز تجبرها على الأبيض دائمًا، ممكن ترجع الـ Light Mode مباشرة
    return '''
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #f8f9fc;
            font-family: 'Segoe UI', 'Cairo', sans-serif;
            color: #1a1a2e;
            min-height: 100vh;
        }
        .header {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(8px);
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #e0d4f5;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 10px rgba(0,0,0,0.02);
        }
        h1, h2, h3 { color: #4a1d6e; font-weight: 600; }
        .container { padding: 20px; max-width: 1200px; margin: 0 auto; }
        .card {
            background: #ffffff;
            padding: 20px;
            border-radius: 24px;
            border: 1px solid #ede4f5;
            margin-bottom: 20px;
            box-shadow: 0 8px 20px rgba(157, 78, 221, 0.04);
        }
        input, select, textarea {
            width: 100%;
            padding: 12px 16px;
            margin: 8px 0;
            background: #ffffff;
            border: 1.5px solid #e2d5f0;
            border-radius: 16px;
            color: #1a1a2e;
            font-size: 1rem;
        }
        input:focus, select:focus, textarea:focus {
            border-color: #9d4edd;
            outline: none;
            background: #fdfaff;
        }
        button, .btn {
            padding: 12px 25px;
            background: #9d4edd;
            border: none;
            border-radius: 40px;
            color: white;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
            display: inline-block;
            margin: 5px;
            box-shadow: 0 6px 12px rgba(157, 78, 221, 0.2);
        }
        button:hover, .btn:hover { background: #7b2cbf; box-shadow: 0 10px 18px rgba(157, 78, 221, 0.3); }
        .btn-danger { background: #ff5e5e; box-shadow: 0 6px 12px rgba(255,94,94,0.2); }
        .btn-success { background: #2cc185; box-shadow: 0 6px 12px rgba(44,193,133,0.2); }
        .btn-warning { background: #fdb44b; color: #1a1a2e; }
        table { width: 100%; border-collapse: collapse; margin-top: 15px; }
        th, td { padding: 12px; text-align: right; border-bottom: 1px solid #e9ddf5; }
        th { background: #f6f0ff; color: #5a189a; font-weight: 600; }
        .sidebar {
            position: fixed;
            top: 0;
            right: -280px;
            width: 260px;
            height: 100vh;
            background: rgba(255, 255, 255, 0.98);
            border-left: 1px solid #d9c2f0;
            transition: right 0.3s;
            z-index: 200;
            overflow-y: auto;
            padding: 20px;
            box-shadow: -4px 0 20px rgba(0,0,0,0.02);
        }
        .sidebar.active { right: 0; }
        .sidebar-item {
            display: block;
            padding: 12px 15px;
            color: #4a1d6e;
            text-decoration: none;
            border-radius: 40px;
            margin-bottom: 8px;
            font-weight: 500;
            background: #ffffff;
            border: 1px solid #f0e8fa;
        }
        .sidebar-item:hover { background: #f5edff; border-color: #9d4edd; }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 40px; font-size: 0.75rem; font-weight: 600; }
        .badge-success { background: #2cc185; color: white; }
        .badge-danger { background: #ff5e5e; color: white; }
        .notification-badge {
            background: #ff5e5e;
            color: white;
            border-radius: 40px;
            padding: 2px 8px;
            font-size: 0.7rem;
            margin-right: 5px;
        }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .stat-card {
            background: #ffffff;
            padding: 20px 15px;
            border-radius: 24px;
            border: 1px solid #ede4f5;
            text-align: center;
            box-shadow: 0 4px 10px rgba(157, 78, 221, 0.02);
        }
        .stat-card .number { font-size: 2.2rem; font-weight: 700; color: #5a189a; }
        .menu-btn { font-size: 1.5rem; cursor: pointer; color: #5a189a; background: none; border: none; }
        .overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.2);
            z-index: 150;
            display: none;
        }
        .overlay.active { display: block; }
        .sidebar-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #e0d4f5;
        }
        .close-btn { background: none; border: none; color: #5a189a; font-size: 1.5rem; cursor: pointer; }
        .logout-btn, .back-btn {
            background: #f3ebfc;
            color: #4a1d6e;
            padding: 8px 18px;
            border-radius: 40px;
            text-decoration: none;
            font-size: 0.9rem;
            font-weight: 500;
            border: 1px solid #d9c2f0;
        }
        .chat-container { display: flex; flex-direction: column; height: calc(100vh - 150px); }
        .messages-area { flex: 1; overflow-y: auto; padding: 20px; background: #fcfaff; border-radius: 24px; }
        .input-area { display: flex; gap: 10px; padding: 20px; background: #ffffff; border-radius: 40px; margin-top: 10px; border: 1px solid #ede4f5; }
        .input-area input { flex: 1; }
        .status-active { color: #2cc185; font-weight: 600; }
        .status-inactive { color: #ff5e5e; }
        .queue-badge {
            background: #fdb44b;
            color: #1a1a2e;
            padding: 2px 10px;
            border-radius: 40px;
            font-size: 0.7rem;
            margin-left: 10px;
            font-weight: 600;
        }
    </style>
    '''

# ============================================================
#                      قاموس اللغات
# ============================================================

LANGUAGES = {
    'ar': {
        'app_name': 'SELVA & Panel',
        'login': 'تسجيل الدخول',
        'register': 'إنشاء حساب',
        'username': 'اسم المستخدم',
        'password': 'كلمة المرور',
        'whatsapp': 'رقم الواتساب',
        'login_btn': 'دخول',
        'register_btn': 'إنشاء حساب',
        'logout': 'خروج',
        'dashboard': 'لوحة التحكم',
        'welcome': 'مرحباً',
        'owner_account': 'حساب المالك',
        'user_account': 'حساب مستخدم',
        'client_account': 'حساب عميل',
        'numbers': 'الأرقام',
        'limit': 'الحد',
        'remaining': 'المتبقي',
        'menu': 'القائمة',
        'back': 'رجوع',
        'add_number': 'إضافة أرقام',
        'delete_number': 'حذف أرقام',
        'my_number': 'أرقامي',
        'my_file': 'ملفاتي',
        'delete_file': 'حذف ملف',
        'my_sms': 'رسائلي',
        'public_sms': 'الرسائل العامة',
        'test_number': 'أرقام الاختبار',
        'notifications': 'الإشعارات',
        'profile': 'الملف الشخصي',
        'support': 'الدعم الفني',
        'activity_log': 'سجل النشاطات',
        'dark_mode': 'الوضع الليلي',
        'light_mode': 'الوضع النهاري',
        'sync_now': 'مزامنة الآن',
        'refresh': 'تحديث',
        'send': 'إرسال',
        'save': 'حفظ',
        'delete': 'حذف',
        'block': 'حظر',
        'unblock': 'فك الحظر',
        'increase_limit': 'زيادة الحد',
        'no_messages': 'لا توجد رسائل',
        'loading': 'جاري التحميل...',
        'success': 'تم بنجاح',
        'error': 'حدث خطأ',
        'confirm_delete': 'هل أنت متأكد من الحذف؟',
        'new_message': 'رسالة جديدة',
        'channels': 'القنوات',
        'telegram_channel': 'قناة تيليجرام ✨🪐',
        'whatsapp_channel': 'قناة واتساب ✨🪐',
        'client': 'عميل',
        'create_client': 'إنشاء حساب عميل',
        'client_username': 'اسم المستخدم للعميل',
        'client_password': 'كلمة المرور للعميل',
        'add_number_client': 'إضافة أرقام لعميل',
        'select_client': 'اختر العميل',
        'select_file': 'اختر الملف',
        'select_number_total': 'اختر عدد الأرقام',
        'all': 'الكل',
        'add_number_test': 'إضافة أرقام اختبار',
        'country_name': 'اسم الدولة',
        'numbers_count': 'عدد الأرقام',
        'upload': 'رفع',
        'my_sms_number': 'رسائل أرقامي',
        'current_clients': 'العملاء الحاليين',
        'display_name': 'اسم العرض',
        'example': 'مثال',
        'choose_user': 'اختر المستخدم',
        'additional_numbers': 'عدد الأرقام الإضافية',
        'current_limit': 'الحد الحالي',
        'active': 'نشط',
        'blocked': 'محظور',
        'actions': 'إجراءات',
        'all_users': 'جميع المستخدمين',
        'user_list': 'قائمة المستخدمين',
        'downloaded_file': 'تحميل الملف',
        'codes': 'الأكواد',
        'code': 'الكود',
        'date': 'التاريخ',
        'file': 'الملف',
        'add_150_numbers': 'إضافة 150 رقم',
        'choose_file_to_add': 'اختر ملف لإضافة الأرقام',
        'can_add_150_per_file': 'يمكنك إضافة 150 رقم فقط لكل ملف',
        'no_files_available': 'لا توجد ملفات متاحة حالياً',
        'delete_numbers': 'حذف الأرقام',
        'enter_file_name': 'أدخل اسم الملف',
        'my_numbers': 'أرقامي',
        'all_numbers': 'جميع الأرقام',
        'no_numbers': 'لا توجد أرقام',
        'my_files': 'ملفاتي',
        'added_files': 'الملفات المضافة',
        'no_files': 'لا توجد ملفات',
        'delete_file_confirmation': 'حذف ملف من حسابك',
        'your_codes': 'الأكواد الخاصة بك',
        'no_codes': 'لا توجد أكواد',
        'all_public_messages': 'جميع الرسائل العامة',
        'last_sync': 'آخر مزامنة',
        'sync_messages': 'مزامنة الرسائل',
        'account_info': 'معلومات الحساب',
        'user_stats': 'إحصائيات المستخدم',
        'chat_with': 'محادثة مع',
        'type_message': 'اكتب رسالتك...',
        'broadcast': 'بث',
        'results': 'النتائج',
        'phone': 'رقم الهاتف',
        'status': 'الحالة',
        'user': 'المستخدم',
        'details': 'التفاصيل',
        'activity': 'النشاط',
        'last_100_activities': 'آخر 100 نشاط',
        'messages': 'الرسائل',
        'unknown': 'غير معروف',
        'leave_empty': 'اتركه فارغاً إذا لم ترغب في التغيير',
        'language': 'اللغة',
        'theme': 'المظهر',
        'email': 'البريد الإلكتروني',
        'stats': 'إحصائيات',
        'registration_date': 'تاريخ التسجيل',
        'last_login': 'آخر تسجيل دخول',
        'linking_channels': 'ربط القنوات',
        'link_channel': 'ربط قناة',
        'channel_id': 'ايدي القناة',
        'channel_id_placeholder': 'مثال: -1001234567890',
        'channel_name': 'اسم القناة (اختياري)',
        'linked_channels': 'القنوات المرتبطة',
        'no_linked_channels': 'لا توجد قنوات مرتبطة',
        'add_channel': 'إضافة قناة',
        'delete_channel': 'حذف',
        'forwarding_active': 'التوجيه نشط',
        'forwarding_info': 'سيتم إعادة توجيه جميع رسائل Public SMS تلقائياً إلى القنوات المرتبطة',
        'queue_status': 'حالة قائمة الانتظار',
        'messages_in_queue': 'رسائل في الانتظار',
    },
    'en': {
        'app_name': 'SELVA & Panel',
        'login': 'Login',
        'register': 'Register',
        'username': 'Username',
        'password': 'Password',
        'whatsapp': 'WhatsApp Number',
        'login_btn': 'Login',
        'register_btn': 'Create Account',
        'logout': 'Logout',
        'dashboard': 'Dashboard',
        'welcome': 'Welcome',
        'owner_account': 'Owner Account',
        'user_account': 'User Account',
        'client_account': 'Client Account',
        'numbers': 'Numbers',
        'limit': 'Limit',
        'remaining': 'Remaining',
        'menu': 'Menu',
        'back': 'Back',
        'add_number': 'Add Number',
        'delete_number': 'Delete Number',
        'my_number': 'My Numbers',
        'my_file': 'My Files',
        'delete_file': 'Delete File',
        'my_sms': 'My SMS',
        'public_sms': 'Public SMS',
        'test_number': 'Test Numbers',
        'notifications': 'Notifications',
        'profile': 'Profile',
        'support': 'Support',
        'activity_log': 'Activity Log',
        'dark_mode': 'Dark Mode',
        'light_mode': 'Light Mode',
        'sync_now': 'Sync Now',
        'refresh': 'Refresh',
        'send': 'Send',
        'save': 'Save',
        'delete': 'Delete',
        'block': 'Block',
        'unblock': 'Unblock',
        'increase_limit': 'Increase Limit',
        'no_messages': 'No messages',
        'loading': 'Loading...',
        'success': 'Success',
        'error': 'Error',
        'confirm_delete': 'Are you sure you want to delete?',
        'new_message': 'New Message',
        'channels': 'Channels',
        'telegram_channel': 'Telegram Channel ✨🪐',
        'whatsapp_channel': 'WhatsApp Channel ✨🪐',
        'client': 'Client',
        'create_client': 'Create Client Account',
        'client_username': 'Client Username',
        'client_password': 'Client Password',
        'add_number_client': 'Add Numbers to Client',
        'select_client': 'Select Client',
        'select_file': 'Select File',
        'select_number_total': 'Select Number Total',
        'all': 'All',
        'add_number_test': 'Add Test Numbers',
        'country_name': 'Country Name',
        'numbers_count': 'Numbers Count',
        'upload': 'Upload',
        'my_sms_number': 'My Numbers SMS',
        'current_clients': 'Current Clients',
        'display_name': 'Display Name',
        'example': 'Example',
        'choose_user': 'Choose User',
        'additional_numbers': 'Additional Numbers',
        'current_limit': 'Current Limit',
        'active': 'Active',
        'blocked': 'Blocked',
        'actions': 'Actions',
        'all_users': 'All Users',
        'user_list': 'User List',
        'downloaded_file': 'Download File',
        'codes': 'Codes',
        'code': 'Code',
        'date': 'Date',
        'file': 'File',
        'add_150_numbers': 'Add 150 Numbers',
        'choose_file_to_add': 'Choose file to add numbers',
        'can_add_150_per_file': 'You can only add 150 numbers per file',
        'no_files_available': 'No files available',
        'delete_numbers': 'Delete Numbers',
        'enter_file_name': 'Enter file name',
        'my_numbers': 'My Numbers',
        'all_numbers': 'All Numbers',
        'no_numbers': 'No numbers',
        'my_files': 'My Files',
        'added_files': 'Added Files',
        'no_files': 'No files',
        'delete_file_confirmation': 'Delete file from your account',
        'your_codes': 'Your Codes',
        'no_codes': 'No codes',
        'all_public_messages': 'All Public Messages',
        'last_sync': 'Last Sync',
        'sync_messages': 'Sync Messages',
        'account_info': 'Account Information',
        'user_stats': 'User Statistics',
        'chat_with': 'Chat with',
        'type_message': 'Type your message...',
        'broadcast': 'Broadcast',
        'results': 'Results',
        'phone': 'Phone',
        'status': 'Status',
        'user': 'User',
        'details': 'Details',
        'activity': 'Activity',
        'last_100_activities': 'Last 100 Activities',
        'messages': 'Messages',
        'unknown': 'Unknown',
        'leave_empty': 'Leave empty if you do not want to change',
        'language': 'Language',
        'theme': 'Theme',
        'email': 'Email',
        'stats': 'Statistics',
        'registration_date': 'Registration Date',
        'last_login': 'Last Login',
        'linking_channels': 'Linking Channels',
        'link_channel': 'Link Channel',
        'channel_id': 'Channel ID',
        'channel_id_placeholder': 'Example: -1001234567890',
        'channel_name': 'Channel Name (Optional)',
        'linked_channels': 'Linked Channels',
        'no_linked_channels': 'No linked channels',
        'add_channel': 'Add Channel',
        'delete_channel': 'Delete',
        'forwarding_active': 'Forwarding Active',
        'forwarding_info': 'All Public SMS messages will be automatically forwarded to linked channels',
        'queue_status': 'Queue Status',
        'messages_in_queue': 'Messages in queue',
    }
}

def get_text(key, lang=None):
    if not lang:
        lang = session.get('lang', 'ar')
    return LANGUAGES.get(lang, LANGUAGES['ar']).get(key, key)

# ============================================================
#                      صفحات المصادقة
# ============================================================

def get_login_page(error=None, lang='ar'):
    t = LANGUAGES[lang]
    error_html = f'<div class="error">{error}</div>' if error else ''
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['login']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #ffffff;
            font-family: 'Segoe UI', 'Cairo', sans-serif;
            color: #1a1a2e;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .login-container {{
            background: #ffffff;
            box-shadow: 0 10px 40px rgba(0,0,0,0.08);
            padding: 30px;
            border-radius: 28px;
            border: 1px solid rgba(157, 78, 221, 0.15);
            width: 90%;
            max-width: 400px;
        }}
        .logo-circle {{
            width: 90px;
            height: 90px;
            margin: 0 auto 20px;
            border-radius: 50%;
            background: #f8f5ff;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 2px solid #9d4edd;
            padding: 8px;
        }}
        .logo-circle img {{
            width: 100%;
            height: 100%;
            border-radius: 50%;
            object-fit: cover;
        }}
        h1 {{ 
            text-align: center; 
            color: #5a189a; 
            margin-bottom: 10px; 
            font-weight: 600;
        }}
        .lang-selector {{ 
            display: flex; 
            justify-content: center; 
            gap: 10px; 
            margin-bottom: 20px; 
        }}
        .lang-btn {{
            background: none;
            border: 1px solid #9d4edd;
            color: #5a189a;
            padding: 5px 15px;
            border-radius: 30px;
            font-size: 0.85rem;
            text-decoration: none;
            transition: all 0.2s;
        }}
        .lang-btn.active {{ 
            background: #9d4edd; 
            color: white; 
        }}
        input {{
            width: 100%;
            padding: 14px 16px;
            margin: 8px 0;
            background: #fafafa;
            border: 1.5px solid #eae0f5;
            border-radius: 16px;
            color: #1a1a2e;
            font-size: 1rem;
            transition: border 0.2s;
        }}
        input:focus {{
            outline: none;
            border-color: #9d4edd;
            background: #ffffff;
        }}
        button {{
            width: 100%;
            padding: 14px;
            margin: 20px 0 10px;
            background: #9d4edd;
            border: none;
            border-radius: 30px;
            color: white;
            font-size: 1.1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.25s;
            box-shadow: 0 6px 14px rgba(157, 78, 221, 0.25);
        }}
        button:hover {{
            background: #7b2cbf;
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(157, 78, 221, 0.35);
        }}
        .create-link {{ 
            text-align: center; 
            margin-top: 18px; 
        }}
        .create-link a {{ 
            color: #9d4edd; 
            text-decoration: none; 
            font-weight: 500;
        }}
        .error {{
            background: #fff5f5;
            color: #d32f2f;
            padding: 12px 15px;
            border-radius: 16px;
            margin-bottom: 18px;
            text-align: center;
            border: 1px solid #ffcdd2;
        }}
        .channel-buttons {{ 
            display: flex; 
            flex-direction: column; 
            gap: 10px; 
            margin-top: 20px; 
        }}
        .channel-btn {{
            background: #f9f6ff;
            border: 1px solid #d9c2f0;
            color: #5a189a;
            padding: 14px 12px;
            border-radius: 40px;
            text-decoration: none;
            text-align: center;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            font-weight: 500;
            transition: all 0.2s;
        }}
        .channel-btn:hover {{ 
            background: #9d4edd; 
            color: white; 
            border-color: #9d4edd;
        }}
        .channels-title {{ 
            text-align: center; 
            color: #6b4f8c; 
            margin-top: 18px; 
            font-size: 0.9rem; 
            font-weight: 500;
        }}
        .theme-toggle {{
            text-align: center;
            margin-top: 15px;
        }}
        .theme-toggle a {{
            color: #9d4edd;
            text-decoration: none;
            font-weight: 500;
        }}
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo-circle">
            <img src="https://i.ibb.co/9kRgLMNM/logo.png" alt="Logo">
        </div>
        <h1>{t['app_name']}</h1>
        <div class="lang-selector">
            <a href="/set-language/ar" class="lang-btn {'active' if lang == 'ar' else ''}">العربية</a>
            <a href="/set-language/en" class="lang-btn {'active' if lang == 'en' else ''}">English</a>
        </div>
        {error_html}
        <form method="POST">
            <input type="text" name="username" placeholder="{t['username']}" required>
            <input type="password" name="password" placeholder="{t['password']}" required>
            <button type="submit">{t['login_btn']}</button>
        </form>
        <div class="create-link">
            <a href="/register">{t['register']}؟</a>
        </div>
        
        <div class="channels-title">━━━ {t['channels']} ━━━</div>
        <div class="channel-buttons">
            <a href="https://t.me/selva_card" target="_blank" class="channel-btn">
                <i class="fab fa-telegram"></i> {t['telegram_channel']}
            </a>
            <a href="https://whatsapp.com/channel/0029VbBz7PZADTOEXAjs0P2z" target="_blank" class="channel-btn">
                <i class="fab fa-whatsapp"></i> {t['whatsapp_channel']}
            </a>
        </div>
        
        <div class="theme-toggle">
            <a href="/toggle-theme">🌙 الوضع الليلي</a>
        </div>
    </div>
</body>
</html>
'''

def get_register_page(error=None, lang='ar'):
    t = LANGUAGES[lang]
    error_html = f'<div class="error">{error}</div>' if error else ''
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['register']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #ffffff;
            font-family: 'Segoe UI', 'Cairo', sans-serif;
            color: #1a1a2e;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .register-container {{
            background: #ffffff;
            box-shadow: 0 10px 40px rgba(0,0,0,0.08);
            padding: 30px;
            border-radius: 28px;
            border: 1px solid rgba(157, 78, 221, 0.15);
            width: 90%;
            max-width: 420px;
        }}
        .logo-circle {{
            width: 90px;
            height: 90px;
            margin: 0 auto 20px;
            border-radius: 50%;
            background: #f8f5ff;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 2px solid #9d4edd;
            padding: 8px;
        }}
        .logo-circle img {{
            width: 100%;
            height: 100%;
            border-radius: 50%;
            object-fit: cover;
        }}
        h1 {{ 
            text-align: center; 
            color: #5a189a; 
            margin-bottom: 5px; 
            font-weight: 600;
        }}
        .subtitle {{ 
            text-align: center; 
            color: #8b6baf; 
            margin-bottom: 25px; 
            font-size: 0.95rem;
        }}
        .lang-selector {{ 
            display: flex; 
            justify-content: center; 
            gap: 10px; 
            margin-bottom: 20px; 
        }}
        .lang-btn {{
            background: none;
            border: 1px solid #9d4edd;
            color: #5a189a;
            padding: 5px 15px;
            border-radius: 30px;
            font-size: 0.85rem;
            text-decoration: none;
            transition: all 0.2s;
        }}
        .lang-btn.active {{ 
            background: #9d4edd; 
            color: white; 
        }}
        .input-group {{ margin-bottom: 15px; }}
        label {{ 
            display: block; 
            color: #4a1d6e; 
            margin-bottom: 6px; 
            font-weight: 500;
            font-size: 0.9rem;
        }}
        label i {{
            color: #9d4edd;
            width: 20px;
        }}
        input {{
            width: 100%;
            padding: 14px 16px;
            background: #fafafa;
            border: 1.5px solid #eae0f5;
            border-radius: 16px;
            color: #1a1a2e;
            font-size: 1rem;
            transition: border 0.2s;
        }}
        input:focus {{
            outline: none;
            border-color: #9d4edd;
            background: #ffffff;
        }}
        input::placeholder {{
            color: #b8a6cc;
        }}
        button {{
            width: 100%;
            padding: 14px;
            margin: 20px 0 10px;
            background: #9d4edd;
            border: none;
            border-radius: 30px;
            color: white;
            font-size: 1.1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.25s;
            box-shadow: 0 6px 14px rgba(157, 78, 221, 0.25);
        }}
        button:hover {{
            background: #7b2cbf;
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(157, 78, 221, 0.35);
        }}
        .login-link {{ 
            text-align: center; 
            margin-top: 18px; 
        }}
        .login-link a {{ 
            color: #9d4edd; 
            text-decoration: none; 
            font-weight: 500;
        }}
        .error {{
            background: #fff5f5;
            color: #d32f2f;
            padding: 12px 15px;
            border-radius: 16px;
            margin-bottom: 18px;
            text-align: center;
            border: 1px solid #ffcdd2;
        }}
        .theme-toggle {{
            text-align: center;
            margin-top: 15px;
        }}
        .theme-toggle a {{
            color: #9d4edd;
            text-decoration: none;
            font-weight: 500;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <div class="register-container">
        <div class="logo-circle">
            <img src="https://i.ibb.co/9kRgLMNM/logo.png" alt="Logo">
        </div>
        <h1>{t['app_name']}</h1>
        <div class="subtitle">✨🪐 Create Account</div>
        <div class="lang-selector">
            <a href="/set-language/ar" class="lang-btn {'active' if lang == 'ar' else ''}">العربية</a>
            <a href="/set-language/en" class="lang-btn {'active' if lang == 'en' else ''}">English</a>
        </div>
        {error_html}
        <form method="POST">
            <div class="input-group">
                <label><i class="fas fa-user"></i> {t['username']} ✨👋</label>
                <input type="text" name="username" placeholder="{t['username']}" required>
            </div>
            <div class="input-group">
                <label><i class="fas fa-lock"></i> {t['password']} ✨🔐</label>
                <input type="password" name="password" placeholder="{t['password']}" required>
            </div>
            <div class="input-group">
                <label><i class="fas fa-phone"></i> {t['whatsapp']} ✨✅</label>
                <input type="text" name="whatsapp" placeholder="{t['whatsapp']}" required>
            </div>
            <button type="submit">{t['register_btn']}</button>
        </form>
        <div class="login-link">
            <a href="/login">{t['login']}؟</a>
        </div>
        <div class="theme-toggle">
            <a href="/toggle-theme">🌙 الوضع الليلي</a>
        </div>
    </div>
</body>
</html>
'''

def get_blocked_page(lang='ar'):
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['app_name']}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: {'linear-gradient(135deg, #0a0a1a 0%, #0d0d2b 50%, #050510 100%)' if theme == 'dark' else 'linear-gradient(135deg, #f0f0f5 0%, #e8e8ff 50%, #d5d5ff 100%)'};
            font-family: 'Segoe UI', 'Cairo', sans-serif;
            color: {'#e0e0ff' if theme == 'dark' else '#1a1a2e'};
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .blocked-container {{
            background: {'rgba(15, 8, 30, 0.8)' if theme == 'dark' else 'rgba(255, 255, 255, 0.8)'};
            backdrop-filter: blur(10px);
            padding: 40px;
            border-radius: 20px;
            border: 2px solid #ff4444;
            text-align: center;
        }}
        h1 {{ color: #ff9999; margin-bottom: 15px; }}
        p {{ color: #ffcccc; font-size: 1.1rem; }}
        .icon {{ font-size: 3rem; margin-bottom: 15px; }}
    </style>
</head>
<body>
    <div class="blocked-container">
        <div class="icon">🚫</div>
        <h1>Your account is locked</h1>
        <p>Contact support.</p>
    </div>
</body>
</html>
'''

# ============================================================
#                      لوحة التحكم
# ============================================================

def get_dashboard_page(user):
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    is_owner = user[1] == OWNER_USERNAME
    is_client_user = user[13] == 1 if len(user) > 13 else False
    
    numbers_count = get_user_numbers_count(user[0])
    user_limit = get_user_limit(user[0])
    unread_notifications = get_unread_notifications_count(user[0])
    unread_messages = get_unread_messages_count(user[0])
    
    if is_owner:
        sidebar_items = [
            ('/owner/add-file', '📁 Add file'),
            ('/owner/delete-file', '🗑️ Delet file'),
            ('/owner/broadcast', '📢 Broadcast'),
            ('/owner/create-account', '👤 Create account'),
            ('/owner/increase-limit', '⬆️ Increase Limit'),
            ('/owner/results', '📊 Results'),
            ('/owner/add-number-test', '🧪 Add number test'),
            ('/activity-log', '📝 Activity Log'),
        ]
    elif is_client_user:
        sidebar_items = [
            ('/user/my-number', '📱 My number'),
            ('/user/my-sms-number', '💬 My sms number'),
            ('/user/public-sms', '🌐 Public sms'),
        ]
    else:
        notif_badge = f' <span class="notification-badge">{unread_notifications}</span>' if unread_notifications > 0 else ''
        msg_badge = f' <span class="notification-badge">{unread_messages}</span>' if unread_messages > 0 else ''
        
        sidebar_items = [
            ('/user/add-number', '➕ Add number'),
            ('/user/delete-number', '➖ Delet number'),
            ('/user/my-number', '📱 My number'),
            ('/user/my-file', '📂 My file number'),
            ('/user/delete-file', '🗑️ Delet file number'),
            ('/user/client', '👤 Cilent'),
            ('/user/add-number-client', '📱 Add number cilent'),
            ('/user/test-number', '🧪 Test number'),
            ('/user/linking-channels', '🔗 Linking the codes to the channel'),
            ('/user/my-sms', '💬 My sms'),
            ('/user/public-sms', '🌐 Public sms'),
            ('/notifications', f'🔔 Notifications{notif_badge}'),
            ('/support', f'💬 Support{msg_badge}'),
        ]
    
    sidebar_html = ''
    for item in sidebar_items:
        sidebar_html += f'<a href="{item[0]}" class="sidebar-item"><i class="fas fa-chevron-left"></i> {item[1]}</a>\n'
    
    cursor = db_conn.cursor()
    cursor.execute("SELECT value FROM stats WHERE key = 'last_sync'")
    last_sync = cursor.fetchone()
    last_sync_time = last_sync[0] if last_sync else t['no_messages']
    
    queue_size = len(message_queue)
    queue_badge = f' <span class="queue-badge">{queue_size} {t["messages_in_queue"]}</span>' if queue_size > 0 else ''
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['dashboard']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <button class="menu-btn" onclick="toggleSidebar()">☰</button>
        <h1>{t['app_name']}{queue_badge}</h1>
        <div>
            <a href="/profile" class="logout-btn" style="margin-right: 10px;"><i class="fas fa-user"></i></a>
            <a href="/logout" class="logout-btn"><i class="fas fa-sign-out-alt"></i> {t['logout']}</a>
        </div>
    </div>
    
    <div class="overlay" id="overlay" onclick="toggleSidebar()"></div>
    
    <div class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <h3>{t['menu']}</h3>
            <button class="close-btn" onclick="toggleSidebar()">✕</button>
        </div>
        <div style="margin-bottom: 20px;">
            <a href="/profile" class="sidebar-item" style="background: rgba(157, 78, 221, 0.2);">
                <i class="fas fa-user-circle"></i> {user[1]}
            </a>
        </div>
        {sidebar_html}
        <div style="margin-top: 20px; border-top: 1px solid #5a189a; padding-top: 15px;">
            <a href="/toggle-theme" class="sidebar-item">
                <i class="fas fa-{'moon' if theme == 'dark' else 'sun'}"></i> {t['light_mode'] if theme == 'dark' else t['dark_mode']}
            </a>
            <div style="display: flex; justify-content: center; gap: 5px; margin-top: 10px;">
                <a href="/set-language/ar" class="lang-btn" style="color: {'#c77dff' if lang == 'ar' else '#e0aaff'}; text-decoration: none;">🇪🇬</a>
                <a href="/set-language/en" class="lang-btn" style="color: {'#c77dff' if lang == 'en' else '#e0aaff'}; text-decoration: none;">🇬🇧</a>
            </div>
        </div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['welcome']}, {user[1]}!</h2>
            <p>{t['owner_account'] if is_owner else (t['client_account'] if is_client_user else t['user_account'])}</p>
            <p style="margin-top: 10px;"><i class="fas fa-sync-alt"></i> {t['last_sync']}: {last_sync_time}</p>
        </div>
        
        <div class="grid">
            <div class="stat-card"><h3>{t['numbers']}</h3><div class="number">{numbers_count}</div></div>
            <div class="stat-card"><h3>{t['limit']}</h3><div class="number">{user_limit}</div></div>
            <div class="stat-card"><h3>{t['remaining']}</h3><div class="number">{user_limit - numbers_count}</div></div>
        </div>
    </div>
    
    <script>
        function toggleSidebar() {{
            document.getElementById('sidebar').classList.toggle('active');
            document.getElementById('overlay').classList.toggle('active');
        }}
        
        // تحديث حالة قائمة الانتظار كل 5 ثواني
        setInterval(async function() {{
            try {{
                const r = await fetch('/api/queue/status');
                const d = await r.json();
                if (d.queue_size > 0) {{
                    document.querySelector('h1').innerHTML = '{t["app_name"]} <span class="queue-badge">' + d.queue_size + ' {t["messages_in_queue"]}</span>';
                }}
            }} catch(e) {{}}
        }}, 5000);
    </script>
</body>
</html>
'''

# ============================================================
#                      صفحات المستخدم
# ============================================================

@app.route('/user/add-number')
@login_required
def user_add_number_page():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = 'light'
    
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT nf.id, nf.display_name,
               (SELECT COUNT(*) FROM user_numbers WHERE user_id = ? AND file_id = nf.id) as added_count
        FROM number_files nf
        WHERE nf.id NOT IN (
            SELECT file_id FROM deleted_user_files WHERE user_id = ?
        )
        ORDER BY nf.id DESC
    ''', (user_id, user_id))
    files = cursor.fetchall()
    
    files_html = ''
    for f in files:
        file_id, display_name, added_count = f
        added_count = added_count or 0
        remaining = 150 - added_count
        
        if remaining <= 0:
            status = f'<span style="color: #2cc185;"><i class="fas fa-check-circle"></i> تمت إضافة 150 رقم (مكتمل)</span>'
            btn_disabled = 'disabled style="opacity: 0.5; pointer-events: none;"'
        else:
            status = f'<span style="color: #fdb44b;"><i class="fas fa-plus-circle"></i> تمت إضافة {added_count} رقم - متبقي {remaining}</span>'
            btn_disabled = ''
        
        files_html += f'''
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h3 style="margin: 0 0 8px 0;">📁 {display_name}</h3>
                        <p style="margin: 0; opacity: 0.8;">{status}</p>
                    </div>
                    <a href="/user/add-numbers/{file_id}" class="btn btn-success" {btn_disabled}>
                        ➕ إضافة 150 رقم
                    </a>
                </div>
            </div>
        '''
    
    if not files_html:
        files_html = f'<div class="card"><p>{t["no_files_available"]}</p></div>'
    
    # إحصائيات عامة
    total_numbers = get_user_numbers_count(user_id)
    total_files_with_numbers = len(set([f[0] for f in files if f[2] > 0]))
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['add_number']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
    <style>
        .header {{
            background: #ffffff;
            border-bottom: 1px solid #e8e0f0;
        }}
        
        .info-banner {{
            background: linear-gradient(135deg, #9d4edd, #7b2cbf);
            color: white;
            padding: 20px;
            border-radius: 20px;
            margin-bottom: 25px;
        }}
        
        .info-banner h3 {{
            color: white;
            margin-bottom: 10px;
        }}
        
        .stats-mini {{
            display: flex;
            gap: 30px;
            margin-top: 15px;
        }}
        
        .stats-mini div {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1 style="color: #5a189a;">➕ {t['add_number']}</h1>
        <div></div>
    </div>
    
    <div class="container" style="max-width: 900px;">
        <div class="info-banner">
            <h3><i class="fas fa-info-circle"></i> طريقة إضافة الأرقام</h3>
            <p>يمكنك إضافة حتى 150 رقم من كل ملف. لا يوجد حد أقصى لعدد الملفات التي يمكنك الإضافة منها.</p>
            <div class="stats-mini">
                <div><i class="fas fa-database"></i> إجمالي أرقامك: <strong>{total_numbers}</strong></div>
                <div><i class="fas fa-folder-open"></i> الملفات المستخدمة: <strong>{total_files_with_numbers}</strong></div>
            </div>
        </div>
        
        <div class="card">
            <h2>{t['choose_file_to_add']}</h2>
            <p style="opacity: 0.7;">الحد الأقصى: 150 رقم لكل ملف</p>
        </div>
        
        {files_html}
        
        <div style="margin-top: 20px; text-align: center;">
            <a href="/user/my-number" class="btn">
                <i class="fas fa-list"></i> عرض جميع أرقامي
            </a>
        </div>
    </div>
</body>
</html>
'''

@app.route('/user/delete-number')
@login_required
def user_delete_number_page():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['delete_number']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>➖ {t['delete_number']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['delete_numbers']}</h2>
            <form action="/user/delete-number" method="POST">
                <label>{t['file']}:</label>
                <input type="text" name="file_name" placeholder="{t['enter_file_name']}" required>
                <button type="submit" class="btn btn-danger" onclick="return confirm('{t['confirm_delete']}')">🗑️ {t['delete']}</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

@app.route('/user/my-number')
@login_required
def user_my_number_page():
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = 'light'
    
    if is_client(user_id):
        cursor = db_conn.cursor()
        cursor.execute('''
            SELECT cn.number, nf.display_name, cn.added_at, cn.file_id
            FROM client_numbers cn
            LEFT JOIN number_files nf ON cn.file_id = nf.id
            WHERE cn.client_id = ?
            ORDER BY cn.added_at DESC
        ''', (user_id,))
        numbers = cursor.fetchall()
    else:
        cursor = db_conn.cursor()
        cursor.execute('''
            SELECT un.number, nf.display_name, un.added_at, un.file_id
            FROM user_numbers un
            LEFT JOIN number_files nf ON un.file_id = nf.id
            WHERE un.user_id = ?
            ORDER BY un.added_at DESC
        ''', (user_id,))
        numbers = cursor.fetchall()
    
    # إحصائيات
    numbers_count = len(numbers)
    
    # تجميع حسب الملفات
    file_stats = {}
    for n in numbers:
        file_name = n[1] or t['unknown']
        if file_name not in file_stats:
            file_stats[file_name] = {'count': 0, 'file_id': n[3]}
        file_stats[file_name]['count'] += 1
    
    rows = ''
    for n in numbers[:200]:
        rows += f'<tr><td>{n[0]}</td><td>{n[1] or t["unknown"]}</td><td>{n[2][:16] if n[2] else ""}</td></tr>'
    
    # عرض الملفات مع عدد الأرقام
    files_summary = ''
    for file_name, stats in file_stats.items():
        files_summary += f'''
            <div class="stat-card" style="text-align: center;">
                <i class="fas fa-folder" style="font-size: 1.5rem; color: #9d4edd; margin-bottom: 8px;"></i>
                <h4 style="margin: 5px 0;">{file_name}</h4>
                <div class="number" style="font-size: 1.5rem;">{stats['count']}</div>
                <small>رقم</small>
                <div style="margin-top: 5px;">
                    <span class="badge badge-success">{min(stats['count'], 150)}/150</span>
                </div>
            </div>
        '''
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['my_number']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
    <style>
        .header {{
            background: #ffffff;
            border-bottom: 1px solid #e8e0f0;
        }}
        
        .main-stats {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 25px;
        }}
        
        .main-stat-card {{
            background: linear-gradient(135deg, #9d4edd, #7b2cbf);
            color: white;
            padding: 20px;
            border-radius: 20px;
            text-align: center;
        }}
        
        .main-stat-card h3 {{
            color: white;
            margin-bottom: 10px;
            font-size: 1rem;
        }}
        
        .main-stat-card .number {{
            font-size: 2.5rem;
            font-weight: bold;
        }}
        
        .files-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1 style="color: #5a189a;">📱 {t['my_number']}</h1>
        <div></div>
    </div>
    
    <div class="container" style="max-width: 1200px;">
        <div class="main-stats">
            <div class="main-stat-card">
                <h3><i class="fas fa-database"></i> إجمالي الأرقام</h3>
                <div class="number">{numbers_count}</div>
            </div>
            <div class="main-stat-card" style="background: linear-gradient(135deg, #2cc185, #1a9e6a);">
                <h3><i class="fas fa-folder-open"></i> عدد الملفات</h3>
                <div class="number">{len(file_stats)}</div>
            </div>
        </div>
        
        <div class="card">
            <h2 style="display: flex; align-items: center; gap: 10px;">
                <i class="fas fa-chart-pie"></i>
                توزيع الأرقام حسب الملفات
            </h2>
            <div class="files-grid">
                {files_summary if files_summary else f'<p>{t["no_files"]}</p>'}
            </div>
        </div>
        
        <div class="card">
            <h2>{t['all_numbers']}</h2>
            <table>
                <thead><tr><th>{t['phone']}</th><th>{t['file']}</th><th>{t['date']}</th></tr></thead>
                <tbody>{rows if rows else f'<tr><td colspan="3" style="text-align:center;">{t["no_numbers"]}</td></tr>'}</tbody>
            </table>
            {f'<p style="text-align: center; margin-top: 15px; opacity: 0.7;">عرض أول 200 رقم من إجمالي {numbers_count}</p>' if numbers_count > 200 else ''}
        </div>
        
        <div style="display: flex; gap: 10px; justify-content: center; margin-top: 20px;">
            <a href="/user/add-number" class="btn btn-success">
                <i class="fas fa-plus"></i> {t['add_number']}
            </a>
            <a href="/user/delete-number" class="btn btn-danger">
                <i class="fas fa-trash"></i> {t['delete_number']}
            </a>
        </div>
    </div>
</body>
</html>
'''

@app.route('/user/my-file')
@login_required
def user_my_file_page():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT DISTINCT nf.display_name, nf.id
        FROM user_numbers un
        JOIN number_files nf ON un.file_id = nf.id
        WHERE un.user_id = ?
    ''', (user_id,))
    files = cursor.fetchall()
    
    files_html = ''
    for f in files:
        cursor.execute('SELECT COUNT(*) FROM user_numbers WHERE user_id = ? AND file_id = ?', (user_id, f[1]))
        count = cursor.fetchone()[0]
        files_html += f'''
            <div class="card">
                <h3>📂 {f[0]}</h3>
                <p>{t['numbers_count']}: {count}</p>
                <a href="/user/download-file/{f[1]}" class="btn btn-success">📥 {t['downloaded_file']}</a>
            </div>
        '''
    
    if not files_html:
        files_html = f'<div class="card"><p>{t["no_files"]}</p></div>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['my_file']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>📂 {t['my_file']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['added_files']}</h2>
        </div>
        {files_html}
    </div>
</body>
</html>
'''

@app.route('/user/delete-file')
@login_required
def user_delete_file_page():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['delete_file']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>🗑️ {t['delete_file']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['delete_file_confirmation']}</h2>
            <form action="/user/delete-file" method="POST">
                <label>{t['file']}:</label>
                <input type="text" name="file_name" placeholder="{t['enter_file_name']}" required>
                <button type="submit" class="btn btn-danger" onclick="return confirm('{t['confirm_delete']}')">🗑️ {t['delete']}</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

@app.route('/user/my-sms')
@login_required
def user_my_sms_page():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT number, code, received_at
        FROM user_codes
        WHERE user_id = ?
        ORDER BY received_at DESC
        LIMIT 100
    ''', (user_id,))
    codes = cursor.fetchall()
    
    rows = ''
    for c in codes:
        rows += f'<tr><td>{c[0] or t["unknown"]}</td><td><strong>{c[1]}</strong></td><td>{c[2][:16] if c[2] else ""}</td></tr>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['my_sms']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>💬 {t['my_sms']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['your_codes']}</h2>
            <table>
                <thead><tr><th>{t['phone']}</th><th>{t['code']}</th><th>{t['date']}</th></tr></thead>
                <tbody>{rows if rows else f'<tr><td colspan="3" style="text-align:center;">{t["no_codes"]}</td></tr>'}</tbody>
            </table>
        </div>
    </div>
</body>
</html>
'''
@app.route('/user/public-sms')
@login_required
def user_public_sms_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = 'light'  # تثبيت الثيم الأبيض
    
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT text, date FROM messages 
        WHERE is_deleted = 0 
        ORDER BY message_id DESC 
        LIMIT 100
    ''')
    messages = cursor.fetchall()
    
    cursor.execute("SELECT value FROM stats WHERE key = 'last_sync'")
    last_sync = cursor.fetchone()
    last_sync_time = last_sync[0] if last_sync else t['no_messages']
    
    # ============================================================
    #         قاموس شامل لجميع دول العالم (العلم + الكود + الاسم)
    # ============================================================
    COUNTRIES_DB = {
        # الدول العربية
        'dz': {'flag': '🇩🇿', 'code': '+213', 'name': 'Algeria', 'name_ar': 'الجزائر'},
        'eg': {'flag': '🇪🇬', 'code': '+20', 'name': 'Egypt', 'name_ar': 'مصر'},
        'sa': {'flag': '🇸🇦', 'code': '+966', 'name': 'Saudi Arabia', 'name_ar': 'السعودية'},
        'ae': {'flag': '🇦🇪', 'code': '+971', 'name': 'UAE', 'name_ar': 'الإمارات'},
        'kw': {'flag': '🇰🇼', 'code': '+965', 'name': 'Kuwait', 'name_ar': 'الكويت'},
        'qa': {'flag': '🇶🇦', 'code': '+974', 'name': 'Qatar', 'name_ar': 'قطر'},
        'bh': {'flag': '🇧🇭', 'code': '+973', 'name': 'Bahrain', 'name_ar': 'البحرين'},
        'om': {'flag': '🇴🇲', 'code': '+968', 'name': 'Oman', 'name_ar': 'عمان'},
        'jo': {'flag': '🇯🇴', 'code': '+962', 'name': 'Jordan', 'name_ar': 'الأردن'},
        'lb': {'flag': '🇱🇧', 'code': '+961', 'name': 'Lebanon', 'name_ar': 'لبنان'},
        'iq': {'flag': '🇮🇶', 'code': '+964', 'name': 'Iraq', 'name_ar': 'العراق'},
        'sy': {'flag': '🇸🇾', 'code': '+963', 'name': 'Syria', 'name_ar': 'سوريا'},
        'ps': {'flag': '🇵🇸', 'code': '+970', 'name': 'Palestine', 'name_ar': 'فلسطين'},
        'ma': {'flag': '🇲🇦', 'code': '+212', 'name': 'Morocco', 'name_ar': 'المغرب'},
        'tn': {'flag': '🇹🇳', 'code': '+216', 'name': 'Tunisia', 'name_ar': 'تونس'},
        'ly': {'flag': '🇱🇾', 'code': '+218', 'name': 'Libya', 'name_ar': 'ليبيا'},
        'sd': {'flag': '🇸🇩', 'code': '+249', 'name': 'Sudan', 'name_ar': 'السودان'},
        'ye': {'flag': '🇾🇪', 'code': '+967', 'name': 'Yemen', 'name_ar': 'اليمن'},
        'so': {'flag': '🇸🇴', 'code': '+252', 'name': 'Somalia', 'name_ar': 'الصومال'},
        'dj': {'flag': '🇩🇯', 'code': '+253', 'name': 'Djibouti', 'name_ar': 'جيبوتي'},
        'km': {'flag': '🇰🇲', 'code': '+269', 'name': 'Comoros', 'name_ar': 'جزر القمر'},
        'mr': {'flag': '🇲🇷', 'code': '+222', 'name': 'Mauritania', 'name_ar': 'موريتانيا'},
        
        # دول أوروبا
        'gb': {'flag': '🇬🇧', 'code': '+44', 'name': 'United Kingdom', 'name_ar': 'بريطانيا'},
        'fr': {'flag': '🇫🇷', 'code': '+33', 'name': 'France', 'name_ar': 'فرنسا'},
        'de': {'flag': '🇩🇪', 'code': '+49', 'name': 'Germany', 'name_ar': 'ألمانيا'},
        'it': {'flag': '🇮🇹', 'code': '+39', 'name': 'Italy', 'name_ar': 'إيطاليا'},
        'es': {'flag': '🇪🇸', 'code': '+34', 'name': 'Spain', 'name_ar': 'إسبانيا'},
        'pt': {'flag': '🇵🇹', 'code': '+351', 'name': 'Portugal', 'name_ar': 'البرتغال'},
        'nl': {'flag': '🇳🇱', 'code': '+31', 'name': 'Netherlands', 'name_ar': 'هولندا'},
        'be': {'flag': '🇧🇪', 'code': '+32', 'name': 'Belgium', 'name_ar': 'بلجيكا'},
        'ch': {'flag': '🇨🇭', 'code': '+41', 'name': 'Switzerland', 'name_ar': 'سويسرا'},
        'at': {'flag': '🇦🇹', 'code': '+43', 'name': 'Austria', 'name_ar': 'النمسا'},
        'se': {'flag': '🇸🇪', 'code': '+46', 'name': 'Sweden', 'name_ar': 'السويد'},
        'no': {'flag': '🇳🇴', 'code': '+47', 'name': 'Norway', 'name_ar': 'النرويج'},
        'dk': {'flag': '🇩🇰', 'code': '+45', 'name': 'Denmark', 'name_ar': 'الدنمارك'},
        'fi': {'flag': '🇫🇮', 'code': '+358', 'name': 'Finland', 'name_ar': 'فنلندا'},
        'pl': {'flag': '🇵🇱', 'code': '+48', 'name': 'Poland', 'name_ar': 'بولندا'},
        'cz': {'flag': '🇨🇿', 'code': '+420', 'name': 'Czech Republic', 'name_ar': 'التشيك'},
        'hu': {'flag': '🇭🇺', 'code': '+36', 'name': 'Hungary', 'name_ar': 'المجر'},
        'ro': {'flag': '🇷🇴', 'code': '+40', 'name': 'Romania', 'name_ar': 'رومانيا'},
        'bg': {'flag': '🇧🇬', 'code': '+359', 'name': 'Bulgaria', 'name_ar': 'بلغاريا'},
        'gr': {'flag': '🇬🇷', 'code': '+30', 'name': 'Greece', 'name_ar': 'اليونان'},
        'ie': {'flag': '🇮🇪', 'code': '+353', 'name': 'Ireland', 'name_ar': 'أيرلندا'},
        'ru': {'flag': '🇷🇺', 'code': '+7', 'name': 'Russia', 'name_ar': 'روسيا'},
        'ua': {'flag': '🇺🇦', 'code': '+380', 'name': 'Ukraine', 'name_ar': 'أوكرانيا'},
        'tr': {'flag': '🇹🇷', 'code': '+90', 'name': 'Turkey', 'name_ar': 'تركيا'},
        
        # أمريكا الشمالية
        'us': {'flag': '🇺🇸', 'code': '+1', 'name': 'United States', 'name_ar': 'أمريكا'},
        'ca': {'flag': '🇨🇦', 'code': '+1', 'name': 'Canada', 'name_ar': 'كندا'},
        'mx': {'flag': '🇲🇽', 'code': '+52', 'name': 'Mexico', 'name_ar': 'المكسيك'},
        
        # أمريكا الجنوبية
        'br': {'flag': '🇧🇷', 'code': '+55', 'name': 'Brazil', 'name_ar': 'البرازيل'},
        'ar': {'flag': '🇦🇷', 'code': '+54', 'name': 'Argentina', 'name_ar': 'الأرجنتين'},
        'cl': {'flag': '🇨🇱', 'code': '+56', 'name': 'Chile', 'name_ar': 'تشيلي'},
        'co': {'flag': '🇨🇴', 'code': '+57', 'name': 'Colombia', 'name_ar': 'كولومبيا'},
        'pe': {'flag': '🇵🇪', 'code': '+51', 'name': 'Peru', 'name_ar': 'بيرو'},
        've': {'flag': '🇻🇪', 'code': '+58', 'name': 'Venezuela', 'name_ar': 'فنزويلا'},
        'ec': {'flag': '🇪🇨', 'code': '+593', 'name': 'Ecuador', 'name_ar': 'الإكوادور'},
        'uy': {'flag': '🇺🇾', 'code': '+598', 'name': 'Uruguay', 'name_ar': 'أوروغواي'},
        'py': {'flag': '🇵🇾', 'code': '+595', 'name': 'Paraguay', 'name_ar': 'باراغواي'},
        'bo': {'flag': '🇧🇴', 'code': '+591', 'name': 'Bolivia', 'name_ar': 'بوليفيا'},
        
        # آسيا
        'cn': {'flag': '🇨🇳', 'code': '+86', 'name': 'China', 'name_ar': 'الصين'},
        'jp': {'flag': '🇯🇵', 'code': '+81', 'name': 'Japan', 'name_ar': 'اليابان'},
        'kr': {'flag': '🇰🇷', 'code': '+82', 'name': 'South Korea', 'name_ar': 'كوريا'},
        'in': {'flag': '🇮🇳', 'code': '+91', 'name': 'India', 'name_ar': 'الهند'},
        'pk': {'flag': '🇵🇰', 'code': '+92', 'name': 'Pakistan', 'name_ar': 'باكستان'},
        'bd': {'flag': '🇧🇩', 'code': '+880', 'name': 'Bangladesh', 'name_ar': 'بنغلاديش'},
        'id': {'flag': '🇮🇩', 'code': '+62', 'name': 'Indonesia', 'name_ar': 'إندونيسيا'},
        'my': {'flag': '🇲🇾', 'code': '+60', 'name': 'Malaysia', 'name_ar': 'ماليزيا'},
        'sg': {'flag': '🇸🇬', 'code': '+65', 'name': 'Singapore', 'name_ar': 'سنغافورة'},
        'th': {'flag': '🇹🇭', 'code': '+66', 'name': 'Thailand', 'name_ar': 'تايلاند'},
        'vn': {'flag': '🇻🇳', 'code': '+84', 'name': 'Vietnam', 'name_ar': 'فيتنام'},
        'ph': {'flag': '🇵🇭', 'code': '+63', 'name': 'Philippines', 'name_ar': 'الفلبين'},
        'ir': {'flag': '🇮🇷', 'code': '+98', 'name': 'Iran', 'name_ar': 'إيران'},
        'il': {'flag': '🇮🇱', 'code': '+972', 'name': 'Israel', 'name_ar': 'إسرائيل'},
        'kz': {'flag': '🇰🇿', 'code': '+7', 'name': 'Kazakhstan', 'name_ar': 'كازاخستان'},
        'uz': {'flag': '🇺🇿', 'code': '+998', 'name': 'Uzbekistan', 'name_ar': 'أوزبكستان'},
        'af': {'flag': '🇦🇫', 'code': '+93', 'name': 'Afghanistan', 'name_ar': 'أفغانستان'},
        
        # أفريقيا
        'ng': {'flag': '🇳🇬', 'code': '+234', 'name': 'Nigeria', 'name_ar': 'نيجيريا'},
        'za': {'flag': '🇿🇦', 'code': '+27', 'name': 'South Africa', 'name_ar': 'جنوب أفريقيا'},
        'ke': {'flag': '🇰🇪', 'code': '+254', 'name': 'Kenya', 'name_ar': 'كينيا'},
        'et': {'flag': '🇪🇹', 'code': '+251', 'name': 'Ethiopia', 'name_ar': 'إثيوبيا'},
        'gh': {'flag': '🇬🇭', 'code': '+233', 'name': 'Ghana', 'name_ar': 'غانا'},
        'ci': {'flag': '🇨🇮', 'code': '+225', 'name': 'Ivory Coast', 'name_ar': 'ساحل العاج'},
        'cm': {'flag': '🇨🇲', 'code': '+237', 'name': 'Cameroon', 'name_ar': 'الكاميرون'},
        'sn': {'flag': '🇸🇳', 'code': '+221', 'name': 'Senegal', 'name_ar': 'السنغال'},
        'ug': {'flag': '🇺🇬', 'code': '+256', 'name': 'Uganda', 'name_ar': 'أوغندا'},
        'tz': {'flag': '🇹🇿', 'code': '+255', 'name': 'Tanzania', 'name_ar': 'تنزانيا'},
        'ao': {'flag': '🇦🇴', 'code': '+244', 'name': 'Angola', 'name_ar': 'أنغولا'},
        
        # أوقيانوسيا
        'au': {'flag': '🇦🇺', 'code': '+61', 'name': 'Australia', 'name_ar': 'أستراليا'},
        'nz': {'flag': '🇳🇿', 'code': '+64', 'name': 'New Zealand', 'name_ar': 'نيوزيلندا'},
    }
    
    def extract_country_info(text):
        """استخراج الدولة والكود والعلم"""
        text_lower = text.lower()
        import re
        
        # 1. البحث عن رمز الدولة (#XX)
        hashtag_match = re.search(r'#([A-Za-z]{2,3})\b', text)
        if hashtag_match:
            code = hashtag_match.group(1).lower()
            if code in COUNTRIES_DB:
                return COUNTRIES_DB[code]['flag'], COUNTRIES_DB[code]['code'], COUNTRIES_DB[code]['name']
        
        # 2. البحث عن اسم الدولة كامل
        for key, data in COUNTRIES_DB.items():
            if data['name'].lower() in text_lower or data['name_ar'] in text:
                return data['flag'], data['code'], data['name']
        
        # 3. البحث عن مفتاح الدولة (+XXX)
        code_match = re.search(r'\+(\d{1,3})\b', text)
        if code_match:
            dial_code = '+' + code_match.group(1)
            for key, data in COUNTRIES_DB.items():
                if data['code'] == dial_code:
                    return data['flag'], data['code'], data['name']
        
        # 4. البحث عن أعلام موجودة
        for key, data in COUNTRIES_DB.items():
            if data['flag'] in text:
                return data['flag'], data['code'], data['name']
        
        return '🌍', '', 'Unknown'
    
    def extract_phone_number(text):
        """استخراج رقم الهاتف"""
        import re
        patterns = [
            r'([A-Za-z]?\d{8,15})',
            r'(\+\d{1,3}[\s.-]?\d{8,15})',
            r'(\d{2,3}[•*]{2,}\d{3,5})',
            r'\b(\d{8,15})\b',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                number = match.group(1)
                if '•' in number or '*' in number:
                    return number
                if len(number) > 8:
                    return number[:4] + '••••' + number[-4:]
                return number
        return '—'
    
    def extract_cli_info(text):
        """استخراج CLI"""
        text_lower = text.lower()
        cli_map = {
            'whatsapp': '📱 WhatsApp', 'واتساب': '📱 WhatsApp', 'واتس': '📱 WhatsApp',
            'telegram': '✈️ Telegram', 'تيليجرام': '✈️ Telegram',
            'viber': '📞 Viber', 'فايبر': '📞 Viber',
            'signal': '🔒 Signal',
            'tinder': '🔥 Tinder',
            'tiktok': '🎵 TikTok',
            'google': '𝐆 Google',
            'facebook': '𝐟 Facebook',
            'instagram': '📷 Instagram',
            'snapchat': '👻 Snapchat',
            'twitter': '🐦 X', 'x.com': '🐦 X',
            'binance': '₿ Binance', 'binance': '₿ Binance',
            'paypal': '💰 PayPal',
            'amazon': '📦 Amazon',
            'netflix': '🎬 Netflix',
            'uber': '🚗 Uber',
            'code': '🔐 OTP', 'otp': '🔐 OTP', 'verify': '🔐 OTP', 'رمز': '🔐 OTP', 'كود': '🔐 OTP',
        }
        for key, value in cli_map.items():
            if key in text_lower:
                return value
        return '📨 SMS'
    
    def extract_clean_message(text, flag, country_code, number):
        """استخراج الرسالة النظيفة"""
        import re
        clean = text
        if flag != '🌍':
            clean = clean.replace(flag, '')
        clean = re.sub(r'#[A-Z]{2,3}\s*', '', clean)
        if number != '—':
            clean = clean.replace(number.replace('•', '•'), '')
        clean = re.sub(r'\+\d{1,3}\s*', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        # استخراج الكود
        code = extract_otp_from_message(text)
        if code:
            return f'{clean[:50]}... <span style="background: #9d4edd; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.7rem; margin-right: 5px;">🔐 {code}</span>' if len(clean) > 50 else f'{clean} <span style="background: #9d4edd; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.7rem; margin-right: 5px;">🔐 {code}</span>'
        
        return clean[:80] + '...' if len(clean) > 80 else clean
    
    # تجهيز الصفوف
    rows = ''
    total_payout = 0
    for m in messages:
        text = m[0]
        msg_date = m[1][:19] if m[1] else ''
        
        flag, dial_code, country_name = extract_country_info(text)
        number = extract_phone_number(text)
        cli = extract_cli_info(text)
        message = extract_clean_message(text, flag, dial_code, number)
        payout = 0.01
        total_payout += payout
        
        # اختيار الاسم حسب اللغة
        display_name = country_name
        if lang == 'ar':
            for key, data in COUNTRIES_DB.items():
                if data['name'] == country_name:
                    display_name = data['name_ar']
                    break
        
        rows += f'''
            <tr>
                <td style="white-space: nowrap;">{msg_date}</td>
                <td style="white-space: nowrap;">
                    <span style="display: flex; align-items: center; gap: 8px;">
                        <span style="font-size: 1.4rem;">{flag}</span>
                        <span style="font-weight: 500;">{display_name}</span>
                    </span>
                </td>
                <td style="direction: ltr; font-family: 'Courier New', monospace;">{number}</td>
                <td><span class="cli-badge">{cli}</span></td>
                <td style="max-width: 400px;">{message}</td>
                <td style="color: #2cc185; font-weight: 600;">$ {payout:.2f}</td>
            </tr>
        '''
    
    # تجهيز رسالة "لا توجد رسائل"
    empty_message = '''
    <tr>
        <td colspan="6" style="text-align: center; padding: 50px;">
            <i class="far fa-comment-dots" style="font-size: 3rem; color: #d9c2f0; margin-bottom: 15px; display: block;"></i>
            <span style="color: #8b6baf;">No messages found</span>
        </td>
    </tr>
    '''
    
    table_body = rows if rows else empty_message
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Show Records - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style('light')}
    <style>
        * {{ box-sizing: border-box; }}
        body {{ 
            background: #f8f9fc; 
        }}
        
        .records-container {{
            max-width: 100% !important;
            width: 100% !important;
            padding: 15px 20px !important;
            margin: 0 !important;
        }}
        
        .page-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 15px;
        }}
        
        .page-header h1 {{
            margin: 0;
            font-size: 1.8rem;
            display: flex;
            align-items: center;
            gap: 15px;
            color: #4a1d6e;
        }}
        
        .total-badge {{
            background: #f0e8fa;
            padding: 6px 15px;
            border-radius: 30px;
            font-size: 0.9rem;
            color: #5a189a;
            border: 1px solid #d9c2f0;
        }}
        
        .table-wrapper {{
            overflow-x: auto;
            border-radius: 16px;
            background: #ffffff;
            border: 1px solid #e8e0f0;
            box-shadow: 0 4px 12px rgba(0,0,0,0.04);
            margin-bottom: 20px;
        }}
        
        .records-table {{
            width: 100%;
            border-collapse: collapse;
            min-width: 1100px;
            font-size: 0.9rem;
        }}
        
        .records-table th {{
            background: #f8f5ff;
            padding: 14px 12px;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 0.5px;
            border-bottom: 2px solid #d9c2f0;
            white-space: nowrap;
            color: #5a189a;
        }}
        
        .records-table td {{
            padding: 12px;
            border-bottom: 1px solid #f0e8fa;
            vertical-align: middle;
            color: #1a1a2e;
        }}
        
        .records-table tr:hover td {{
            background: #fdfbff;
        }}
        
        .cli-badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
            background: #f0e8fa;
            color: #5a189a;
            white-space: nowrap;
        }}
        
        .table-footer {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 15px;
            flex-wrap: wrap;
            gap: 15px;
        }}
        
        .total-info {{
            background: #e8faf1;
            padding: 10px 20px;
            border-radius: 30px;
            border: 1px solid #2cc185;
            color: #1a1a2e;
        }}
        
        .total-info strong {{
            color: #2cc185;
            font-size: 1.3rem;
            margin: 0 10px;
        }}
        
        .pagination {{
            display: flex;
            gap: 5px;
        }}
        
        .pagination button {{
            padding: 8px 15px;
            background: #ffffff;
            border: 1px solid #d9c2f0;
            border-radius: 8px;
            color: #4a1d6e;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.2s;
        }}
        
        .pagination button:hover {{
            background: #9d4edd;
            color: white;
            border-color: #9d4edd;
        }}
        
        .action-bar {{
            display: flex;
            gap: 10px;
        }}
        
        .btn-success {{
            background: #2cc185;
            box-shadow: 0 4px 10px rgba(44, 193, 133, 0.2);
        }}
        
        .btn-success:hover {{
            background: #25a86f;
        }}
        
        /* تنسيق عرض الأعمدة */
        .records-table th:nth-child(1) {{ width: 160px; }}
        .records-table th:nth-child(2) {{ width: 180px; }}
        .records-table th:nth-child(3) {{ width: 140px; }}
        .records-table th:nth-child(4) {{ width: 110px; }}
        .records-table th:nth-child(5) {{ /* Message - auto */ }}
        .records-table th:nth-child(6) {{ width: 100px; }}
        
        .header {{
            background: #ffffff;
            border-bottom: 1px solid #e8e0f0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.02);
        }}
        
        .back-btn {{
            background: #f8f5ff;
            color: #5a189a;
            border: 1px solid #d9c2f0;
        }}
        
        @media (max-width: 768px) {{
            .records-container {{ padding: 10px !important; }}
            .page-header {{ flex-direction: column; align-items: flex-start; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <div style="display: flex; align-items: center; gap: 15px;">
            <a href="/dashboard" class="back-btn">
                <i class="fas fa-arrow-right"></i> {t['back']}
            </a>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
            <span id="syncStatus"></span>
            <span class="total-badge">
                <i class="far fa-clock"></i> {last_sync_time}
            </span>
        </div>
    </div>
    
    <div class="container records-container">
        <div class="page-header">
            <h1>
                <i class="fas fa-table" style="color: #9d4edd;"></i>
                Show Records
            </h1>
            <div class="action-bar">
                <button class="btn btn-success" onclick="syncMessages()" id="syncBtn">
                    <i class="fas fa-cloud-download-alt"></i> Sync
                </button>
                <button class="btn" onclick="location.reload()">
                    <i class="fas fa-redo-alt"></i> Refresh
                </button>
            </div>
        </div>
        
        <div class="table-wrapper">
            <table class="records-table">
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Range</th>
                        <th>Number</th>
                        <th>CLI</th>
                        <th>SMS</th>
                        <th>My Payout</th>
                    </tr>
                </thead>
                <tbody>
                    {table_body}
                </tbody>
            </table>
        </div>
        
        <div class="table-footer">
            <div class="total-info">
                <i class="fas fa-envelope"></i> Total SMS <strong>{len(messages)}</strong>
                <span style="margin: 0 15px; opacity: 0.5;">|</span>
                <i class="fas fa-dollar-sign"></i> Total Payout <strong>$ {total_payout:.2f}</strong>
            </div>
            
            <div class="pagination">
                <button><i class="fas fa-angle-double-left"></i> First</button>
                <button><i class="fas fa-angle-left"></i> Previous</button>
                <button style="background: #9d4edd; color: white; border-color: #9d4edd;">1</button>
                <button><i class="fas fa-angle-right"></i> Next</button>
                <button>Last <i class="fas fa-angle-double-right"></i></button>
            </div>
        </div>
        
        <div style="text-align: center; margin-top: 15px; color: #8b6baf; font-size: 0.85rem;">
            Showing 1 to {len(messages)} of {len(messages)} entries
        </div>
    </div>
    
    <script>
        async function syncMessages() {{
            const btn = document.getElementById('syncBtn');
            const statusEl = document.getElementById('syncStatus');
            const originalText = btn.innerHTML;
            
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Syncing...';
            statusEl.innerHTML = '<span style="color: #fdb44b;"><i class="fas fa-spinner fa-spin"></i> Syncing...</span>';
            
            try {{
                const r = await fetch('/api/sync');
                const d = await r.json();
                
                if (d.success) {{
                    statusEl.innerHTML = '<span style="color: #2cc185;"><i class="fas fa-check-circle"></i> +' + d.new_messages + ' new</span>';
                    setTimeout(() => location.reload(), 1500);
                }} else {{
                    statusEl.innerHTML = '<span style="color: #ff5e5e;"><i class="fas fa-times-circle"></i> Error</span>';
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                }}
            }} catch(e) {{
                statusEl.innerHTML = '<span style="color: #ff5e5e;"><i class="fas fa-times-circle"></i> Error</span>';
                btn.disabled = false;
                btn.innerHTML = originalText;
            }}
        }}
        
        setInterval(function() {{
            fetch('/api/sync').then(r => r.json()).then(d => {{
                if (d.success && d.new_messages > 0) location.reload();
            }});
        }}, 30000);
    </script>
</body>
</html>
'''

# ============================================================
#                      صفحة ربط القنوات
# ============================================================

@app.route('/user/linking-channels')
@login_required
def user_linking_channels_page():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    channels = get_user_linked_channels(user_id)
    
    channels_html = ''
    for ch in channels:
        status_class = 'status-active' if ch[3] else 'status-inactive'
        status_text = '✅ نشط' if ch[3] else '❌ غير نشط'
        channels_html += f'''
            <tr>
                <td>{ch[2] or ch[1]}</td>
                <td><code>{ch[1]}</code></td>
                <td class="{status_class}">{status_text}</td>
                <td>{ch[4][:16] if ch[4] else ''}</td>
                <td>
                    <a href="/user/linking-channels/delete/{ch[0]}" class="btn btn-danger btn-sm" onclick="return confirm('{t['confirm_delete']}')">🗑️ {t['delete']}</a>
                </td>
            </tr>
        '''
    
    if not channels_html:
        channels_html = f'<tr><td colspan="5" style="text-align:center;">{t["no_linked_channels"]}</td></tr>'
    
    queue_size = len(message_queue)
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['linking_channels']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>🔗 {t['linking_channels']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2><i class="fas fa-link"></i> {t['link_channel']}</h2>
            <p style="color: #00b894; margin-bottom: 15px;">
                <i class="fas fa-info-circle"></i> {t['forwarding_info']}
            </p>
            <p style="color: #fdcb6e; margin-bottom: 15px;">
                <i class="fas fa-clock"></i> {t['queue_status']}: {queue_size} {t['messages_in_queue']}
            </p>
            <form action="/user/linking-channels/add" method="POST">
                <label>📱 {t['channel_id']}:</label>
                <input type="text" name="channel_id" placeholder="{t['channel_id_placeholder']}" required>
                <small style="color: #9d4edd;">يجب أن يبدأ بـ -100 للقنوات الخاصة أو - للقنوات العامة</small>
                
                <label>📝 {t['channel_name']}:</label>
                <input type="text" name="channel_name" placeholder="{t['example']}: قناتي">
                
                <button type="submit" class="btn btn-success">🔗 {t['add_channel']}</button>
            </form>
        </div>
        
        <div class="card">
            <h2><i class="fas fa-list"></i> {t['linked_channels']}</h2>
            <table>
                <thead>
                    <tr>
                        <th>{t['channel_name']}</th>
                        <th>{t['channel_id']}</th>
                        <th>{t['status']}</th>
                        <th>{t['date']}</th>
                        <th>{t['actions']}</th>
                    </tr>
                </thead>
                <tbody>
                    {channels_html}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
'''

@app.route('/user/linking-channels/add', methods=['POST'])
@login_required
def add_linked_channel():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    channel_id = request.form.get('channel_id').strip()
    channel_name = request.form.get('channel_name', '').strip()
    
    try:
        int(channel_id)
    except:
        return redirect('/user/linking-channels')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id FROM linked_channels WHERE user_id = ? AND channel_id = ?', (user_id, channel_id))
    if cursor.fetchone():
        return redirect('/user/linking-channels')
    
    cursor.execute('''
        INSERT INTO linked_channels (user_id, channel_id, channel_name, added_at, is_active)
        VALUES (?, ?, ?, ?, 1)
    ''', (user_id, channel_id, channel_name, datetime.now().isoformat()))
    db_conn.commit()
    
    log_activity(user_id, 'link_channel', f'Linked channel: {channel_id}')
    add_notification(user_id, "🔗 تم ربط القناة", f"تم ربط القناة {channel_id} بنجاح", "success")
    
    return redirect('/user/linking-channels')

@app.route('/user/linking-channels/delete/<int:channel_id>')
@login_required
def delete_linked_channel(channel_id):
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    
    cursor = db_conn.cursor()
    cursor.execute('DELETE FROM linked_channels WHERE id = ? AND user_id = ?', (channel_id, user_id))
    db_conn.commit()
    
    log_activity(user_id, 'unlink_channel', f'Unlinked channel ID: {channel_id}')
    
    return redirect('/user/linking-channels')

# ============================================================
#                      صفحة الملف الشخصي
# ============================================================

@app.route('/profile')
@login_required
def profile_page():
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    
    user_theme = user[6] if len(user) > 6 and user[6] else 'dark'
    user_lang = user[7] if len(user) > 7 and user[7] else 'ar'
    user_whatsapp = user[3] if len(user) > 3 else ''
    user_email = user[4] if len(user) > 4 else ''
    user_created = user[10] if len(user) > 10 else None
    user_last_login = user[11] if len(user) > 11 else None
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['profile']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>👤 {t['profile']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['account_info']}</h2>
            <form action="/profile/update" method="POST">
                <label>👤 {t['username']}:</label>
                <input type="text" value="{user[1]}" readonly style="background: rgba(0,0,0,0.5);">
                
                <label>🔐 {t['password']}:</label>
                <input type="password" name="password" placeholder="{t['leave_empty']}">
                
                <label>📱 {t['whatsapp']}:</label>
                <input type="text" name="whatsapp" value="{user_whatsapp}" placeholder="{t['whatsapp']}">
                
                <label>📧 {t['email']}:</label>
                <input type="email" name="email" value="{user_email}" placeholder="Email">
                
                <label>🌐 {t['language']}:</label>
                <select name="language">
                    <option value="ar" {"selected" if user_lang == 'ar' else ""}>🇪🇬 العربية</option>
                    <option value="en" {"selected" if user_lang == 'en' else ""}>🇬🇧 English</option>
                </select>
                
                <label>🎨 {t['theme']}:</label>
                <select name="theme">
                    <option value="dark" {"selected" if user_theme == 'dark' else ""}>🌙 {t['dark_mode']}</option>
                    <option value="light" {"selected" if user_theme == 'light' else ""}>☀️ {t['light_mode']}</option>
                </select>
                
                <button type="submit" class="btn btn-success">{t['save']}</button>
            </form>
        </div>
        
        <div class="card">
            <h2>📊 {t['stats']}</h2>
            <p>📱 {t['numbers']}: {get_user_numbers_count(user_id)}</p>
            <p>📅 {t['registration_date']}: {user_created[:10] if user_created else t['unknown']}</p>
            <p>🕐 {t['last_login']}: {user_last_login[:16] if user_last_login else t['unknown']}</p>
        </div>
    </div>
</body>
</html>
'''

@app.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    user_id = session['user_id']
    password = request.form.get('password')
    whatsapp = request.form.get('whatsapp')
    email = request.form.get('email')
    language = request.form.get('language', 'ar')
    theme = request.form.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    
    if password:
        cursor.execute('UPDATE users SET password = ? WHERE id = ?', (hash_password(password), user_id))
    
    try:
        cursor.execute('''
            UPDATE users SET whatsapp = ?, email = ?, language = ?, theme = ?
            WHERE id = ?
        ''', (whatsapp, email, language, theme, user_id))
        db_conn.commit()
    except:
        pass
    
    session['lang'] = language
    session['theme'] = theme
    
    log_activity(user_id, 'update_profile', 'Updated profile')
    
    return redirect('/profile')

# ============================================================
#                      صفحة الإشعارات
# ============================================================

@app.route('/notifications')
@login_required
def notifications_page():
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT id, title, message, type, created_at, is_read
        FROM notifications
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 50
    ''', (user_id,))
    notifications = cursor.fetchall()
    
    cursor.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ?', (user_id,))
    db_conn.commit()
    
    notif_html = ''
    for n in notifications:
        icon = {'otp': '🔐', 'info': 'ℹ️', 'success': '✅', 'warning': '⚠️'}.get(n[3], '🔔')
        notif_html += f'''
            <div class="card" style="margin-bottom: 10px; {'opacity: 0.7;' if n[5] else ''}">
                <h3>{icon} {n[1]}</h3>
                <p>{n[2]}</p>
                <small>{n[4][:16]}</small>
            </div>
        '''
    
    if not notif_html:
        notif_html = f'<div class="card"><p>{t["no_messages"]}</p></div>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['notifications']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>🔔 {t['notifications']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        {notif_html}
    </div>
</body>
</html>
'''

# ============================================================
#                      نظام المراسلة
# ============================================================

@app.route('/support')
@login_required
def support_page():
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    is_owner = session.get('username') == OWNER_USERNAME
    
    cursor = db_conn.cursor()
    
    if is_owner:
        cursor.execute('''
            SELECT DISTINCT u.id, u.username
            FROM users u
            WHERE u.id != ?
            ORDER BY u.username ASC
        ''', (user_id,))
        users = cursor.fetchall()
        
        users_html = ''
        for u in users:
            unread = get_unread_messages_count(u[0])
            badge = f' <span class="notification-badge">{unread}</span>' if unread > 0 else ''
            
            # عرض اسم المالك بشكل مختلف
            display_name = 'Selva🔥' if u[1] == OWNER_USERNAME else u[1]
            is_owner_user = u[1] == OWNER_USERNAME
            owner_badge = ' 👑' if is_owner_user else ''
            
            users_html += f'''
                <a href="/support/chat/{u[0]}" class="sidebar-item" style="{'background: rgba(157, 78, 221, 0.3);' if is_owner_user else ''}">
                    👤 {display_name}{owner_badge}{badge}
                </a>
            '''
        
        return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['support']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
    <style>
        .support-header {{
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 20px;
        }}
        .owner-card {{
            background: linear-gradient(135deg, #9d4edd, #c77dff);
            padding: 20px;
            border-radius: 15px;
            color: white;
            margin-bottom: 20px;
        }}
        .owner-card h3 {{
            color: white;
            text-shadow: none;
            margin-bottom: 10px;
        }}
        .owner-card .owner-name {{
            font-size: 1.5rem;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>💬 {t['support']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="owner-card">
            <h3><i class="fas fa-crown"></i> المالك</h3>
            <div class="owner-name">Selva 🔥</div>
            <p style="opacity: 0.9; margin-top: 10px;">
                <i class="fas fa-envelope"></i> mohaymen190@gmail.com
            </p>
        </div>
        
        <div class="card">
            <h2><i class="fas fa-users"></i> {t['user_list']}</h2>
            <div style="margin-top: 20px;">
                {users_html if users_html else f'<p>{t["no_messages"]}</p>'}
            </div>
        </div>
    </div>
</body>
</html>
'''
    else:
        cursor.execute('SELECT id FROM users WHERE username = ?', (OWNER_USERNAME,))
        owner = cursor.fetchone()
        
        if owner:
            return redirect(f'/support/chat/{owner[0]}')
        
        return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['support']} - {t['app_name']}</title>
    {get_base_style(theme)}
</head>
<body>
    <div class="container">
        <div class="card">
            <p>{t['error']}</p>
        </div>
    </div>
</body>
</html>
'''

@app.route('/support/chat/<int:other_id>')
@login_required
def support_chat_page(other_id):
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    
    cursor.execute('SELECT username FROM users WHERE id = ?', (other_id,))
    other = cursor.fetchone()
    
    # عرض اسم المالك بشكل مختلف
    if other and other[0] == OWNER_USERNAME:
        other_name = 'Selva 🔥'
    else:
        other_name = other[0] if other else 'Unknown'
    
    cursor.execute('''
        UPDATE support_messages SET is_read = 1 
        WHERE sender_id = ? AND receiver_id = ?
    ''', (other_id, user_id))
    db_conn.commit()
    
    cursor.execute('''
        SELECT sm.message, sm.created_at, sm.sender_id, u.username
        FROM support_messages sm
        JOIN users u ON sm.sender_id = u.id
        WHERE (sm.sender_id = ? AND sm.receiver_id = ?)
           OR (sm.sender_id = ? AND sm.receiver_id = ?)
        ORDER BY sm.created_at ASC
    ''', (user_id, other_id, other_id, user_id))
    messages = cursor.fetchall()
    
    messages_html = ''
    for m in messages:
        is_sent = m[2] == user_id
        # عرض اسم المرسل بشكل مختلف لو كان المالك
        sender_name = 'Selva 🔥' if m[3] == OWNER_USERNAME else m[3]
        messages_html += f'''
            <div style="
                max-width: 70%;
                margin: 10px 0;
                padding: 12px 16px;
                border-radius: 20px;
                background: {'#9d4edd' if is_sent else 'rgba(15, 8, 30, 0.7)'};
                color: white;
                {'margin-right: auto;' if is_sent else 'margin-left: auto;'}
                border: 1px solid {'#c77dff' if is_sent else '#5a189a'};
            ">
                <small style="opacity: 0.7; display: block; margin-bottom: 5px;">
                    <i class="fas fa-user"></i> {sender_name}
                </small>
                <p>{m[0]}</p>
                <small style="opacity: 0.5; display: block; margin-top: 5px;">{m[1][:16]}</small>
            </div>
        '''
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['chat_with']} {other_name}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
    <style>
        .chat-header {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .owner-badge {{
            background: linear-gradient(135deg, #fdcb6e, #f39c12);
            color: #2d3436;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.8rem;
            margin-right: 10px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/support" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <div class="chat-header">
            <h1>💬 {other_name}</h1>
            {'<span class="owner-badge"><i class="fas fa-crown"></i> المالك</span>' if other_name == 'Selva 🔥' else ''}
        </div>
        <div></div>
    </div>
    
    <div class="container">
        <div class="chat-container">
            <div class="messages-area" id="messagesArea">
                {messages_html}
            </div>
            <div class="input-area">
                <input type="text" id="messageInput" placeholder="{t['type_message']}">
                <button class="btn btn-success" onclick="sendMessage()">{t['send']}</button>
            </div>
        </div>
    </div>
    
    <script>
        const otherId = {other_id};
        
        async function sendMessage() {{
            const input = document.getElementById('messageInput');
            const message = input.value.trim();
            if (!message) return;
            
            try {{
                const r = await fetch('/support/send', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{receiver_id: otherId, message: message}})
                }});
                const d = await r.json();
                if (d.success) {{
                    input.value = '';
                    location.reload();
                }}
            }} catch(e) {{}}
        }}
        
        document.getElementById('messageInput').addEventListener('keypress', function(e) {{
            if (e.key === 'Enter') sendMessage();
        }});
        
        setInterval(function() {{ location.reload(); }}, 5000);
    </script>
</body>
</html>
'''

@app.route('/support/send', methods=['POST'])
@login_required
def send_support_message():
    data = request.get_json()
    receiver_id = data.get('receiver_id')
    message = data.get('message')
    sender_id = session['user_id']
    
    cursor = db_conn.cursor()
    cursor.execute('''
        INSERT INTO support_messages (sender_id, receiver_id, message, created_at)
        VALUES (?, ?, ?, ?)
    ''', (sender_id, receiver_id, message, datetime.now().isoformat()))
    db_conn.commit()
    
    add_notification(receiver_id, "💬 رسالة جديدة", f"لديك رسالة جديدة من {session['username']}", "info")
    
    return jsonify({'success': True})

# ============================================================
#                      سجل النشاطات
# ============================================================

@app.route('/activity-log')
@owner_required
def activity_log_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT al.action, al.details, al.created_at, u.username
        FROM activity_logs al
        JOIN users u ON al.user_id = u.id
        ORDER BY al.created_at DESC
        LIMIT 100
    ''')
    logs = cursor.fetchall()
    
    rows = ''
    for l in logs:
        rows += f'''
            <tr>
                <td>{l[3]}</td>
                <td>{l[0]}</td>
                <td>{l[1]}</td>
                <td>{l[2][:16]}</td>
            </tr>
        '''
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['activity_log']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>📝 {t['activity_log']}</h1>
        <button class="btn" onclick="location.reload()">{t['refresh']}</button>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['last_100_activities']}</h2>
            <table>
                <thead>
                    <tr>
                        <th>{t['user']}</th>
                        <th>{t['activity']}</th>
                        <th>{t['details']}</th>
                        <th>{t['date']}</th>
                    </tr>
                </thead>
                <tbody>
                    {rows if rows else f'<tr><td colspan="4" style="text-align:center;">{t["no_messages"]}</td></tr>'}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
'''

# ============================================================
#                      صفحات المالك
# ============================================================

@app.route('/owner/add-file')
@owner_required
def owner_add_file_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['add_number']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>📁 Add File</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['upload']} {t['file']}</h2>
            <form action="/owner/add-file" method="POST" enctype="multipart/form-data">
                <label>{t['select_file']} (TXT/CSV):</label>
                <input type="file" name="file" accept=".txt,.csv" required>
                <label>{t['display_name']}:</label>
                <input type="text" name="display_name" placeholder="{t['example']}: أرقام قطر" required>
                <button type="submit" class="btn btn-success">📤 {t['upload']}</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

@app.route('/owner/delete-file')
@owner_required
def owner_delete_file_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id, display_name FROM number_files ORDER BY id DESC')
    files = cursor.fetchall()
    
    options = ''
    for f in files:
        options += f'<option value="{f[0]}">{f[1]}</option>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['delete_file']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>🗑️ Delete File</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['delete_file']}</h2>
            <form action="/owner/delete-file" method="POST">
                <select name="file_id" required>
                    <option value="">{t['select_file']}</option>
                    {options}
                </select>
                <button type="submit" class="btn btn-danger" onclick="return confirm('{t['confirm_delete']}')">🗑️ {t['delete']}</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

@app.route('/owner/broadcast')
@owner_required
def owner_broadcast_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['broadcast']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>📢 {t['broadcast']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['send']} {t['messages']} {t['all_users']}</h2>
            <form action="/owner/broadcast" method="POST">
                <textarea name="message" rows="5" placeholder="{t['type_message']}" required></textarea>
                <button type="submit" class="btn btn-success">📨 {t['send']}</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

@app.route('/owner/create-account')
@owner_required
def owner_create_account_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['register']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>👤 Create Account</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['register']}</h2>
            <form action="/owner/create-account" method="POST">
                <label>{t['username']}:</label>
                <input type="text" name="username" placeholder="Username" required>
                <label>{t['password']}:</label>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit" class="btn btn-success">✅ {t['register_btn']}</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

@app.route('/owner/increase-limit')
@owner_required
def owner_increase_limit_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id, username, number_limit FROM users WHERE username != ?', (OWNER_USERNAME,))
    users = cursor.fetchall()
    
    options = ''
    for u in users:
        limit_val = u[2] if u[2] else 150
        options += f'<option value="{u[0]}">{u[1]} ({t["current_limit"]}: {limit_val})</option>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['increase_limit']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>⬆️ {t['increase_limit']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['increase_limit']}</h2>
            <form action="/owner/increase-limit" method="POST">
                <label>{t['choose_user']}:</label>
                <select name="user_id" required>
                    <option value="">{t['choose_user']}</option>
                    {options}
                </select>
                <label>{t['additional_numbers']}:</label>
                <input type="number" name="limit_amount" placeholder="{t['example']}: 50" required>
                <button type="submit" class="btn btn-success">⬆️ {t['increase_limit']}</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

@app.route('/owner/results')
@owner_required
def owner_results_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT u.id, u.username, u.whatsapp, u.is_blocked, u.number_limit,
               (SELECT COUNT(*) FROM user_numbers WHERE user_id = u.id) as numbers_count
        FROM users u
        WHERE u.username != ?
        ORDER BY u.id DESC
    ''', (OWNER_USERNAME,))
    users = cursor.fetchall()
    
    rows = ''
    for u in users:
        user_id, username, whatsapp, is_blocked, limit_num, count = u
        blocked_text = t['active'] if not is_blocked else t['blocked']
        block_btn = f'<a href="/owner/block/{user_id}" class="btn btn-sm btn-warning">🚫 {t["block"]}</a>' if not is_blocked else f'<a href="/owner/unblock/{user_id}" class="btn btn-sm btn-success">✅ {t["unblock"]}</a>'
        rows += f'''
            <tr>
                <td>{username}</td>
                <td>{whatsapp or t['unknown']}</td>
                <td><span class="badge {'badge-danger' if is_blocked else 'badge-success'}">{blocked_text}</span></td>
                <td>{count}/{limit_num if limit_num else 150}</td>
                <td>
                    {block_btn}
                    <a href="/owner/increase-limit?user_id={user_id}" class="btn btn-sm" style="padding:5px 10px;">⬆️ {t['increase_limit']}</a>
                </td>
            </tr>
        '''
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['results']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>📊 {t['all_users']}</h1>
        <button class="btn" onclick="location.reload()"><i class="fas fa-sync-alt"></i> {t['refresh']}</button>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['user_list']}</h2>
            <table>
                <thead>
                    <tr>
                        <th>{t['user']}</th>
                        <th>{t['whatsapp']}</th>
                        <th>{t['status']}</th>
                        <th>{t['numbers']}</th>
                        <th>{t['actions']}</th>
                    </tr>
                </thead>
                <tbody>
                    {rows if rows else f'<tr><td colspan="5" style="text-align:center;">{t["no_messages"]}</td></tr>'}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
'''

# ============================================================
#                      صفحة إنشاء عميل (Cilent)
# ============================================================

@app.route('/user/client')
@login_required
def user_client_page():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT id, username, created_at FROM users 
        WHERE parent_id = ? AND is_client = 1
        ORDER BY id DESC
    ''', (session['user_id'],))
    clients = cursor.fetchall()
    
    clients_html = ''
    for c in clients:
        cursor.execute('SELECT COUNT(*) FROM client_numbers WHERE client_id = ?', (c[0],))
        count = cursor.fetchone()[0]
        clients_html += f'''
            <tr>
                <td>{c[1]}</td>
                <td>{count}</td>
                <td>{c[2][:16] if c[2] else ''}</td>
            </tr>
        '''
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['client']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>👤 {t['client']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['create_client']}</h2>
            <form action="/user/client/create" method="POST">
                <label>{t['client_username']}:</label>
                <input type="text" name="username" placeholder="{t['username']}" required>
                <label>{t['client_password']}:</label>
                <input type="password" name="password" placeholder="{t['password']}" required>
                <button type="submit" class="btn btn-success">✅ {t['create_client']}</button>
            </form>
        </div>
        
        <div class="card">
            <h2>{t['current_clients']}</h2>
            <table>
                <thead>
                    <tr><th>{t['username']}</th><th>{t['numbers']}</th><th>{t['date']}</th></tr>
                </thead>
                <tbody>
                    {clients_html if clients_html else f'<tr><td colspan="3" style="text-align:center;">{t["no_messages"]}</td></tr>'}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
'''

@app.route('/user/client/create', methods=['POST'])
@login_required
def create_client():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    username = request.form.get('username')
    password = request.form.get('password')
    parent_id = session['user_id']
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    if cursor.fetchone():
        return redirect('/user/client')
    
    cursor.execute('''
        INSERT INTO users (username, password, parent_id, is_client, number_limit, created_at)
        VALUES (?, ?, ?, 1, 1000, ?)
    ''', (username, hash_password(password), parent_id, datetime.now().isoformat()))
    db_conn.commit()
    
    log_activity(parent_id, 'create_client', f'Created client: {username}')
    
    return redirect('/user/client')

# ============================================================
#                      صفحة إضافة أرقام لعميل
# ============================================================

@app.route('/user/add-number-client')
@login_required
def user_add_number_client_page():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    
    cursor.execute('SELECT id, username FROM users WHERE parent_id = ? AND is_client = 1', (user_id,))
    clients = cursor.fetchall()
    
    if not clients:
        return f'''
        <!DOCTYPE html>
        <html>
        <head><title>{t['add_number_client']}</title>{get_base_style(theme)}</head>
        <body>
            <div class="header">
                <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
                <h1>📱 {t['add_number_client']}</h1>
                <div></div>
            </div>
            <div class="container">
                <div class="card">
                    <p>لا يوجد عملاء. قم بإنشاء عميل أولاً من صفحة Cilent</p>
                    <a href="/user/client" class="btn btn-success">👤 إنشاء عميل</a>
                </div>
            </div>
        </body>
        </html>
        '''
    
    clients_options = ''.join([f'<option value="{c[0]}">{c[1]}</option>' for c in clients])
    
    cursor.execute('''
        SELECT nf.id, nf.display_name 
        FROM number_files nf
        WHERE nf.id NOT IN (
            SELECT file_id FROM deleted_user_files WHERE user_id = ?
        )
        ORDER BY nf.id DESC
    ''', (user_id,))
    files = cursor.fetchall()
    
    files_options = ''.join([f'<option value="{f[0]}">{f[1]}</option>' for f in files])
    
    number_options = [100, 150, 200, 500, 1000, 3000]
    numbers_html = ''.join([f'<option value="{n}">{n}</option>' for n in number_options])
    numbers_html += '<option value="all">All</option>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['add_number_client']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>📱 {t['add_number_client']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['add_number_client']}</h2>
            <form action="/user/add-number-client" method="POST">
                <label>{t['select_client']}:</label>
                <select name="client_id" required>
                    <option value="">{t['select_client']}</option>
                    {clients_options}
                </select>
                
                <label>{t['select_file']}:</label>
                <select name="file_id" required>
                    <option value="">{t['select_file']}</option>
                    {files_options}
                </select>
                
                <label>{t['select_number_total']}:</label>
                <select name="number_total" required>
                    {numbers_html}
                </select>
                
                <button type="submit" class="btn btn-success">📱 {t['add_number']}</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

@app.route('/user/add-number-client', methods=['POST'])
@login_required
def add_number_client():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    client_id = request.form.get('client_id')
    file_id = request.form.get('file_id')
    number_total = request.form.get('number_total')
    
    cursor = db_conn.cursor()
    
    cursor.execute('SELECT id FROM users WHERE id = ? AND parent_id = ?', (client_id, user_id))
    if not cursor.fetchone():
        return redirect('/dashboard')
    
    cursor.execute('SELECT numbers FROM number_files WHERE id = ?', (file_id,))
    result = cursor.fetchone()
    
    if result:
        numbers = json.loads(result[0])
        
        if number_total == 'all':
            numbers_to_add = numbers
        else:
            numbers_to_add = numbers[:int(number_total)]
        
        added = 0
        for num in numbers_to_add:
            cursor.execute('''
                INSERT OR IGNORE INTO client_numbers (client_id, file_id, number, added_at, added_by)
                VALUES (?, ?, ?, ?, ?)
            ''', (client_id, file_id, num, datetime.now().isoformat(), user_id))
            if cursor.rowcount > 0:
                added += 1
        
        db_conn.commit()
        log_activity(user_id, 'add_numbers_client', f'Added {added} numbers to client {client_id}')
    
    return redirect('/user/client')

# ============================================================
#                      صفحة أرقام الاختبار للمستخدم
# ============================================================

@app.route('/user/test-number')
@login_required
def user_test_number_page():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT id, country_name, numbers_count, created_at 
        FROM test_number_files 
        ORDER BY id DESC
    ''')
    files = cursor.fetchall()
    
    files_html = ''
    for f in files:
        files_html += f'''
            <div class="card">
                <h3>🧪 {f[1]}</h3>
                <p>{t['numbers_count']}: {f[2]}</p>
                <p>{t['date']}: {f[3][:16] if f[3] else ''}</p>
                <a href="/user/test-number/view/{f[0]}" class="btn btn-success">👀 عرض الأرقام</a>
            </div>
        '''
    
    if not files_html:
        files_html = f'<div class="card"><p>{t["no_messages"]}</p></div>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['test_number']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>🧪 {t['test_number']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['test_number']}</h2>
        </div>
        {files_html}
    </div>
</body>
</html>
'''

@app.route('/user/test-number/view/<int:file_id>')
@login_required
def view_test_numbers(file_id):
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT country_name, numbers FROM test_number_files WHERE id = ?', (file_id,))
    result = cursor.fetchone()
    
    if not result:
        return redirect('/user/test-number')
    
    country_name = result[0]
    numbers = json.loads(result[1])
    
    rows = ''
    for i, num in enumerate(numbers[:100], 1):
        rows += f'<tr><td>{i}</td><td>{num}</td></tr>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{country_name} - {t['test_number']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/user/test-number" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>🧪 {country_name}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{country_name} - {len(numbers)} {t['numbers']}</h2>
            <table>
                <thead><tr><th>#</th><th>{t['phone']}</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
            {f'<p style="margin-top:15px; color:#9d4edd;">و {len(numbers)-100} رقم آخر...</p>' if len(numbers) > 100 else ''}
        </div>
    </div>
</body>
</html>
'''

# ============================================================
#                      صفحة إضافة أرقام اختبار (للمالك)
# ============================================================

@app.route('/owner/add-number-test')
@owner_required
def owner_add_number_test_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['add_number_test']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>🧪 {t['add_number_test']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['upload']} {t['test_number']}</h2>
            <form action="/owner/add-number-test" method="POST" enctype="multipart/form-data">
                <label>{t['select_file']} (TXT/CSV):</label>
                <input type="file" name="file" accept=".txt,.csv" required>
                
                <label>{t['country_name']}:</label>
                <input type="text" name="country_name" placeholder="{t['example']}: Qatar" required>
                
                <label>{t['numbers_count']}:</label>
                <input type="number" name="numbers_count" placeholder="{t['example']}: 1000" required>
                
                <button type="submit" class="btn btn-success">📤 {t['upload']}</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

@app.route('/owner/add-number-test', methods=['POST'])
@owner_required
def owner_add_number_test():
    if 'file' not in request.files:
        return redirect('/owner/add-number-test')
    
    file = request.files['file']
    country_name = request.form.get('country_name')
    numbers_count = request.form.get('numbers_count')
    
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        numbers = parse_numbers_file(filepath)
        
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT INTO test_number_files (file_name, country_name, numbers, numbers_count, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (filename, country_name, json.dumps(numbers), int(numbers_count), datetime.now().isoformat()))
        db_conn.commit()
        
        log_activity(session['user_id'], 'add_test_numbers', f'Added test numbers: {country_name} ({len(numbers)} numbers)')
    
    return redirect('/dashboard')

# ============================================================
#                      صفحة رسائل أرقام العميل
# ============================================================

@app.route('/user/my-sms-number')
@login_required
def user_my_sms_number_page():
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    
    if is_client(user_id):
        cursor.execute('''
            SELECT cn.number, uc.code, uc.received_at
            FROM client_numbers cn
            LEFT JOIN user_codes uc ON cn.number LIKE '%' || substr(uc.number, -4)
            WHERE cn.client_id = ?
            ORDER BY uc.received_at DESC
            LIMIT 100
        ''', (user_id,))
    else:
        cursor.execute('''
            SELECT number, code, received_at
            FROM user_codes
            WHERE user_id = ?
            ORDER BY received_at DESC
            LIMIT 100
        ''', (user_id,))
    
    codes = cursor.fetchall()
    
    rows = ''
    for c in codes:
        rows += f'<tr><td>{c[0] or t["unknown"]}</td><td><strong>{c[1]}</strong></td><td>{c[2][:16] if c[2] else ""}</td></tr>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['my_sms']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>💬 {t['my_sms']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="card">
            <h2>{t['your_codes']}</h2>
            <table>
                <thead><tr><th>{t['phone']}</th><th>{t['code']}</th><th>{t['date']}</th></tr></thead>
                <tbody>{rows if rows else f'<tr><td colspan="3" style="text-align:center;">{t["no_messages"]}</td></tr>'}</tbody>
            </table>
        </div>
    </div>
</body>
</html>
'''

# ============================================================
#                           المسارات
# ============================================================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect('/dashboard')
    return redirect('/login')

@app.route('/set-language/<lang>')
def set_language(lang):
    if lang in ['ar', 'en']:
        session['lang'] = lang
    return redirect(request.referrer or '/dashboard')

@app.route('/toggle-theme')
def toggle_theme():
    current = session.get('theme', 'dark')
    session['theme'] = 'light' if current == 'dark' else 'dark'
    return redirect(request.referrer or '/dashboard')

@app.route('/login', methods=['GET', 'POST'])
def login():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        cursor = db_conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', 
                       (username, hash_password(password)))
        user = cursor.fetchone()
        
        if user:
            if len(user) > 8 and user[8] == 1:
                return get_blocked_page(lang)
            
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['lang'] = user[7] if len(user) > 7 and user[7] else 'ar'
            session['theme'] = user[6] if len(user) > 6 and user[6] else 'dark'
            
            try:
                cursor.execute('UPDATE users SET last_login = ? WHERE id = ?', 
                              (datetime.now().isoformat(), user[0]))
                db_conn.commit()
            except:
                pass
            
            log_activity(user[0], 'login', 'User logged in')
            return redirect('/dashboard')
        
        return get_login_page(t['error'], lang)
    
    return get_login_page(lang=lang)

@app.route('/register', methods=['GET', 'POST'])
def register():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        whatsapp = request.form.get('whatsapp')
        
        cursor = db_conn.cursor()
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        if cursor.fetchone():
            return get_register_page(t['error'], lang)
        
        cursor.execute('''
            INSERT INTO users (username, password, whatsapp, created_at)
            VALUES (?, ?, ?, ?)
        ''', (username, hash_password(password), whatsapp, datetime.now().isoformat()))
        db_conn.commit()
        
        user_id = cursor.lastrowid
        log_activity(user_id, 'register', f'New user registered: {username}')
        return redirect('/login')
    
    return get_register_page(lang=lang)

@app.route('/dashboard')
@login_required
def dashboard():
    cursor = db_conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],))
    user = cursor.fetchone()
    
    if user and len(user) > 8 and user[8] == 1:
        session.clear()
        return get_blocked_page()
    
    return get_dashboard_page(user)

@app.route('/logout')
def logout():
    if 'user_id' in session:
        log_activity(session['user_id'], 'logout', 'User logged out')
    session.clear()
    return redirect('/login')

# ============================================================
#                      مسارات المالك (POST)
# ============================================================

@app.route('/owner/add-file', methods=['POST'])
@owner_required
def owner_add_file():
    if 'file' not in request.files:
        return redirect('/owner/add-file')
    
    file = request.files['file']
    display_name = request.form.get('display_name')
    
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        numbers = parse_numbers_file(filepath)
        
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT INTO number_files (file_name, display_name, numbers, created_at)
            VALUES (?, ?, ?, ?)
        ''', (filename, display_name, json.dumps(numbers), datetime.now().isoformat()))
        db_conn.commit()
        
        log_activity(session['user_id'], 'add_file', f'Added file: {display_name} ({len(numbers)} numbers)')
    
    return redirect('/dashboard')

@app.route('/owner/delete-file', methods=['POST'])
@owner_required
def owner_delete_file():
    file_id = request.form.get('file_id')
    cursor = db_conn.cursor()
    cursor.execute('DELETE FROM number_files WHERE id = ?', (file_id,))
    cursor.execute('DELETE FROM user_numbers WHERE file_id = ?', (file_id,))
    db_conn.commit()
    
    log_activity(session['user_id'], 'delete_file', f'Deleted file ID: {file_id}')
    
    return redirect('/dashboard')

@app.route('/owner/broadcast', methods=['POST'])
@owner_required
def owner_broadcast():
    message = request.form.get('message')
    cursor = db_conn.cursor()
    cursor.execute('SELECT id FROM users WHERE username != ? AND is_blocked = 0', (OWNER_USERNAME,))
    users = cursor.fetchall()
    
    cursor.execute('''
        INSERT INTO broadcasts (message, sent_at, recipients_count)
        VALUES (?, ?, ?)
    ''', (message, datetime.now().isoformat(), len(users)))
    db_conn.commit()
    
    for u in users:
        add_notification(u[0], "📢 بث", message, "info")
    
    log_activity(session['user_id'], 'broadcast', f'Sent broadcast to {len(users)} users')
    
    return redirect('/dashboard')

@app.route('/owner/create-account', methods=['POST'])
@owner_required
def owner_create_account():
    username = request.form.get('username')
    password = request.form.get('password')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    if cursor.fetchone():
        return redirect('/owner/create-account')
    
    cursor.execute('''
        INSERT INTO users (username, password, created_at)
        VALUES (?, ?, ?)
    ''', (username, hash_password(password), datetime.now().isoformat()))
    db_conn.commit()
    
    log_activity(session['user_id'], 'create_account', f'Created account: {username}')
    
    return redirect('/dashboard')

@app.route('/owner/increase-limit', methods=['POST'])
@owner_required
def owner_increase_limit():
    user_id = request.form.get('user_id')
    amount = int(request.form.get('limit_amount', 0))
    
    cursor = db_conn.cursor()
    cursor.execute('UPDATE users SET number_limit = number_limit + ? WHERE id = ?', (amount, user_id))
    db_conn.commit()
    
    log_activity(session['user_id'], 'increase_limit', f'Increased limit for user {user_id} by {amount}')
    
    return redirect('/dashboard')

@app.route('/owner/block/<int:user_id>')
@owner_required
def owner_block_user(user_id):
    cursor = db_conn.cursor()
    cursor.execute('UPDATE users SET is_blocked = 1 WHERE id = ?', (user_id,))
    db_conn.commit()
    
    add_notification(user_id, "🚫 حظر", "تم حظر حسابك. تواصل مع الدعم الفني.", "warning")
    log_activity(session['user_id'], 'block_user', f'Blocked user {user_id}')
    
    return redirect('/owner/results')

@app.route('/owner/unblock/<int:user_id>')
@owner_required
def owner_unblock_user(user_id):
    cursor = db_conn.cursor()
    cursor.execute('UPDATE users SET is_blocked = 0 WHERE id = ?', (user_id,))
    db_conn.commit()
    
    add_notification(user_id, "✅ فك الحظر", "تم فك الحظر عن حسابك.", "success")
    log_activity(session['user_id'], 'unblock_user', f'Unblocked user {user_id}')
    
    return redirect('/owner/results')

# ============================================================
#                      مسارات المستخدم (POST)
# ============================================================

@app.route('/user/add-numbers/<int:file_id>')
@login_required
def user_add_numbers(file_id):
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    
    cursor = db_conn.cursor()
    
    # نحسب كام رقم المستخدم ضاف من الملف ده تحديداً
    cursor.execute('SELECT COUNT(*) FROM user_numbers WHERE user_id = ? AND file_id = ?', (user_id, file_id))
    file_count = cursor.fetchone()[0]
    
    # الحد الأقصى لكل ملف هو 150 رقم
    FILE_LIMIT = 150
    
    if file_count >= FILE_LIMIT:
        # المستخدم وصل للحد الأقصى لهذا الملف
        return redirect('/user/add-number')
    
    # جلب الأرقام من الملف
    cursor.execute('SELECT numbers FROM number_files WHERE id = ?', (file_id,))
    result = cursor.fetchone()
    
    if result:
        all_numbers = json.loads(result[0])
        
        # حساب المساحة المتبقية في هذا الملف
        remaining_in_file = FILE_LIMIT - file_count
        
        # ناخد الأرقام الجديدة (اللي مش مضافة قبل كدا من نفس الملف)
        numbers_to_add = []
        
        for num in all_numbers:
            # التحقق من عدم وجود الرقم مسبقاً للمستخدم من نفس الملف
            cursor.execute('SELECT id FROM user_numbers WHERE user_id = ? AND file_id = ? AND number = ?', 
                          (user_id, file_id, num))
            if not cursor.fetchone():
                numbers_to_add.append(num)
                if len(numbers_to_add) >= remaining_in_file:
                    break
        
        added = 0
        for num in numbers_to_add:
            cursor.execute('''
                INSERT INTO user_numbers (user_id, file_id, number, added_at)
                VALUES (?, ?, ?, ?)
            ''', (user_id, file_id, num, datetime.now().isoformat()))
            if cursor.rowcount > 0:
                added += 1
        
        db_conn.commit()
        log_activity(user_id, 'add_numbers', f'Added {added} numbers from file {file_id}')
    
    return redirect('/user/my-number')

@app.route('/user/delete-file', methods=['POST'])
@login_required
def user_delete_file():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    file_name = request.form.get('file_name')
    user_id = session['user_id']
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id FROM number_files WHERE display_name = ?', (file_name,))
    file_result = cursor.fetchone()
    
    if file_result:
        file_id = file_result[0]
        cursor.execute('''
            INSERT INTO deleted_user_files (user_id, file_id, file_name, deleted_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, file_id, file_name, datetime.now().isoformat()))
        db_conn.commit()
        log_activity(user_id, 'delete_file', f'Deleted file: {file_name}')
    
    return redirect('/user/my-file')

@app.route('/user/download-file/<int:file_id>')
@login_required
def user_download_file(file_id):
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    cursor = db_conn.cursor()
    cursor.execute('SELECT number FROM user_numbers WHERE user_id = ? AND file_id = ?', (user_id, file_id))
    numbers = cursor.fetchall()
    content = '\n'.join([n[0] for n in numbers])
    response = make_response(content)
    response.headers['Content-Type'] = 'text/plain'
    response.headers['Content-Disposition'] = f'attachment; filename=numbers_{file_id}.txt'
    
    log_activity(user_id, 'download_file', f'Downloaded file {file_id}')
    
    return response

# ============================================================
#                      API Routes
# ============================================================

@app.route('/api/sync')
def api_sync():
    global loop
    try:
        result = loop.run_until_complete(fetch_and_save_messages())
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/queue/status')
def api_queue_status():
    return jsonify({'queue_size': len(message_queue)})

@app.route('/api/linked-channels/count')
def api_linked_channels_count():
    channels = get_all_active_linked_channels()
    return jsonify({'count': len(channels)})

@app.route('/health')
def health():
    cursor = db_conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM messages')
    msg_count = cursor.fetchone()[0]
    channels_count = len(get_all_active_linked_channels())
    return jsonify({
        'status': 'ok',
        'messages': msg_count,
        'linked_channels': channels_count,
        'queue_size': len(message_queue)
    })

# ============================================================
#                      التشغيل
# ============================================================

def print_banner():
    print('=' * 60)
    print('   SELVA & OTP - Complete Advanced System')
    print('   النسخة النهائية مع Queue للإرسال السريع')
    print('=' * 60)

if __name__ == '__main__':
    print_banner()
    
    try:
        init_telegram()
        print('✅ تم الاتصال بتليجرام')
        print('🔔 مراقبة الرسائل الجديدة وإعادة التوجيه مفعلة')
        print('🔄 نظام Queue يعمل في الخلفية')
        
        print('📥 جاري مزامنة الرسائل القديمة...')
        result = loop.run_until_complete(fetch_and_save_messages())
        if result['success']:
            print(f'✅ تمت المزامنة الأولية: {result["new_messages"]} رسالة')
    except Exception as e:
        print(f'⚠️ تيليجرام غير متاح: {e}')
        print('📱 النظام سيعمل بدون مزامنة تيليجرام')
    
    try:
        port = 5000
        print(f'  🚀 http://127.0.0.1:{port}')
        print(f'  👑 المالك: {OWNER_USERNAME} / {OWNER_PASSWORD}')
        print(f'  🤖 البوت: {BOT_TOKEN[:20]}...')
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print('\n👋 تم إيقاف السيرفر')
        db_conn.close()
        if loop:
            loop.close()
        sys.exit(0)
