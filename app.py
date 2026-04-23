#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SELVA & OTP - Complete Management System
النسخة النهائية الكاملة بجميع المميزات + نظام Queue لإعادة التوجيه
+ نظام الأدوار (Owner, Admin, Test, User, Client)
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
from flask import Flask, jsonify, request, make_response, session, redirect, url_for, Response
from werkzeug.utils import secure_filename
from telethon import TelegramClient, events
from telethon.errors import ChannelPrivateError, ChatAdminRequiredError, FloodWaitError
from functools import wraps
import queue
# ============================================================
#                  الإعدادات
# ============================================================

API_ID = 30827918
API_HASH = '096144aab00ad92c5d9bb6160cd8bd81'
CHANNEL_ID = -1003693518087
SESSION_NAME = 'sela_user_session'
BOT_TOKEN = '8569083733:AAFCfoxnzvhdzWkcDCkUCqpRonxBACIOByk'

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
        role = session.get('role', 'user')
        if role != 'owner' and role != 'admin':
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
            is_client INTEGER DEFAULT 0,
            role TEXT DEFAULT 'user'
        )
    ''')
    
    for col in ['email', 'profile_pic', 'theme', 'language', 'parent_id', 'is_client', 'role']:
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
            INSERT INTO users (username, password, number_limit, role, created_at)
            VALUES (?, ?, ?, 'owner', ?)
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
        
        # التحقق من وجود الرسالة مسبقاً في messages
        cursor.execute('SELECT id FROM messages WHERE message_id = ?', (msg_id,))
        if cursor.fetchone():
            print(f'⚠️ الرسالة {msg_id} موجودة مسبقاً - تم تجاهلها')
            return True
        
        cursor.execute('''
            INSERT INTO messages (message_id, text, date, saved_at, is_deleted)
            VALUES (?, ?, ?, ?, 0)
        ''', (msg_id, text, date, datetime.now().isoformat()))
        
        print(f'\n{"="*60}')
        print(f'📝 رسالة جديدة (ID: {msg_id})')
        print(f'📨 النص: {text[:150]}...')
        print(f'{"="*60}')
        
        # ============================================================
        # استخراج الأرقام بكل الطرق الممكنة
        # ============================================================
        
        # 1. تنظيف النص - استبدال كل شيء غير رقم بمسافة
        clean_text = re.sub(r'[^\d]', ' ', text)
        
        # 2. استخراج كل الأرقام
        all_numbers = re.findall(r'\d+', clean_text)
        
        # 3. الأرقام الطويلة (8-15 خانة)
        numbers_in_message = [num for num in all_numbers if 8 <= len(num) <= 15]
        numbers_in_message = list(set(numbers_in_message))
        
        # 4. أرقام مع + (بدون مسافات)
        plus_numbers = re.findall(r'\+\d{8,15}', text)
        for pn in plus_numbers:
            clean = re.sub(r'[^\d]', '', pn)
            if 8 <= len(clean) <= 15:
                numbers_in_message.append(clean)
        
        # 5. أرقام مفصولة بمسافات مع +
        spaced_numbers = re.findall(r'\+\d{1,3}[\s.-]?\d{2,4}[\s.-]?\d{2,4}[\s.-]?\d{2,4}', text)
        for sn in spaced_numbers:
            clean = re.sub(r'[^\d]', '', sn)
            if 8 <= len(clean) <= 15:
                numbers_in_message.append(clean)
        
        numbers_in_message = list(set(numbers_in_message))
        print(f'🔍 الأرقام المستخرجة: {numbers_in_message}')
        
        if numbers_in_message:
            for search_num in numbers_in_message:
                print(f'   🔎 البحث عن: {search_num}')
                
                # البحث عن تطابق كامل في user_numbers
                cursor.execute('SELECT user_id, number FROM user_numbers WHERE number = ?', (search_num,))
                user_rows = cursor.fetchall()
                
                # البحث عن آخر 4-8 أرقام
                if not user_rows:
                    for length in [8, 7, 6, 5, 4]:
                        if len(search_num) >= length:
                            suffix = search_num[-length:]
                            cursor.execute('SELECT user_id, number FROM user_numbers WHERE number LIKE ?', (f'%{suffix}',))
                            user_rows = cursor.fetchall()
                            if user_rows:
                                break
                
                # البحث العكسي: هل أي رقم مخزن موجود في النص؟
                if not user_rows:
                    cursor.execute('SELECT user_id, number FROM user_numbers')
                    all_db = cursor.fetchall()
                    for db_row in all_db:
                        db_num = db_row[1]
                        if db_num and len(db_num) >= 8:
                            if db_num in text or db_num[-8:] in text:
                                user_rows.append(db_row)
                
                # حفظ النتائج مع منع التكرار
                seen_users = set()
                for row in user_rows:
                    user_id = row[0]
                    full_number = row[1]
                    
                    if user_id in seen_users:
                        continue
                    seen_users.add(user_id)
                    
                    # منع تكرار نفس الرسالة للمستخدم خلال 60 ثانية
                    cursor.execute('''
                        SELECT id, code, received_at FROM user_codes 
                        WHERE user_id = ? 
                        ORDER BY id DESC LIMIT 1
                    ''', (user_id,))
                    last = cursor.fetchone()
                    
                    code = extract_otp_from_message(text)
                    notification_text = code if code else text[:100]
                    
                    if last:
                        last_code = last[1]
                        last_time = last[2]
                        if last_code == notification_text:
                            try:
                                last_dt = datetime.fromisoformat(last_time)
                                now = datetime.now()
                                diff = (now - last_dt).total_seconds()
                                if diff < 60:
                                    print(f'      ⏭️ المستخدم {user_id} - رسالة مكررة (قبل {diff:.0f} ثانية)')
                                    continue
                            except:
                                pass
                    
                    cursor.execute('''
                        INSERT INTO user_codes (user_id, number, code, received_at)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, full_number, notification_text, datetime.now().isoformat()))
                    
                    add_notification(user_id, "📨 رسالة جديدة", "تم استلام رسالة", "otp")
                    print(f'      ✅ المستخدم {user_id} - {full_number}')
                    
                    # إرسال إشعار فوري للمستخدم عبر SSE
                    try:
                        notify_user_new_sms(user_id, {
                            'number': full_number,
                            'code': notification_text,
                            'received_at': datetime.now().isoformat()
                        })
                    except:
                        pass
        
        db_conn.commit()
        print(f'{"="*60}\n')
        return True
    except Exception as e:
        print(f"❌ خطأ في حفظ الرسالة: {e}")
        import traceback
        traceback.print_exc()
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
                message_text = message_queue.popleft()
                channels = get_all_active_linked_channels()
                
                if channels:
                    print(f'📤 جاري إرسال الرسالة إلى {len(channels)} قناة...')
                    
                    first_channel = channels[0]
                    try:
                        entity = await bot_client.get_entity(int(first_channel))
                        await bot_client.send_message(entity, message_text)
                        print(f'   ✅ تم الإرسال إلى: {first_channel}')
                        
                        for i, channel_id in enumerate(channels[1:], 1):
                            try:
                                await asyncio.sleep(2)
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
            
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f'❌ خطأ في العامل: {e}')
            await asyncio.sleep(5)

def start_forwarding_worker():
    global forwarding_task, loop
    if loop:
        forwarding_task = loop.create_task(forward_worker())
        print('✅ عامل إعادة التوجيه جاهز')
async def auto_sync_worker():
    """عامل مزامنة تلقائية في الخلفية"""
    await asyncio.sleep(10)  # انتظار 10 ثواني قبل أول مزامنة
    
    while True:
        try:
            print('🔄 جاري المزامنة التلقائية...')
            result = await fetch_and_save_messages()
            if result['success'] and result['new_messages'] > 0:
                print(f'✅ تمت المزامنة التلقائية: {result["new_messages"]} رسالة جديدة')
            else:
                print(f'ℹ️ لا توجد رسائل جديدة في المزامنة التلقائية')
        except Exception as e:
            print(f'❌ خطأ في المزامنة التلقائية: {e}')
        
        await asyncio.sleep(60)  # انتظار 60 ثانية قبل المزامنة التالية

def start_auto_sync():
    """بدء عامل المزامنة التلقائية"""
    global loop
    if loop:
        loop.create_task(auto_sync_worker())
        print('✅ عامل المزامنة التلقائية جاهز (كل 60 ثانية)')

def add_to_queue(message_text):
    message_queue.append(message_text)
    print(f'📥 تمت إضافة رسالة إلى قائمة الانتظار (الإجمالي: {len(message_queue)})')

def start_message_listener():
    @user_client.on(events.NewMessage(chats=CHANNEL_ID))
    async def handler(event):
        msg = event.message
        if msg.message:
            print(f'\n{"="*60}')
            print(f'📨 رسالة جديدة من تيليجرام!')
            print(f'{"="*60}')
            print(f'📝 النص: {msg.message[:200]}...')
            
            # انتظر قليلاً للتأكد من اكتمال الرسالة
            await asyncio.sleep(2)
            
            # استخدم نفس آلية المزامنة
            try:
                entity = await user_client.get_entity(CHANNEL_ID)
                # جلب آخر رسالة فقط
                messages = await user_client.get_messages(entity, limit=1)
                if messages and messages[0].message:
                    latest_msg = messages[0]
                    print(f'🔄 جاري معالجة الرسالة عبر get_messages...')
                    result = save_message_to_db(latest_msg.id, latest_msg.message, latest_msg.date.isoformat())
                    if result:
                        print(f'✅ تم حفظ الرسالة وربطها بالمستخدمين')
                    else:
                        print(f'❌ فشل حفظ الرسالة')
            except Exception as e:
                print(f'❌ خطأ في جلب الرسالة: {e}')
                # محاولة مباشرة كاحتياط
                save_message_to_db(msg.id, msg.message, msg.date.isoformat())
            
            cursor = db_conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO stats (key, value) 
                VALUES ('last_sync', ?)
            ''', (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
            db_conn.commit()
            
            add_to_queue(msg.message)
            add_owner_notification(f'📨 رسالة جديدة: {msg.message[:30]}...')
            print(f'{"="*60}\n')

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
        start_auto_sync()  # ← إضافة هذا السطر
        print('🔔 تم تفعيل مراقبة الرسائل الجديدة والمزامنة التلقائية')

async def fetch_and_save_messages():
    global user_client
    try:
        print(f'📡 جاري جلب الرسائل من القناة {CHANNEL_ID}...')
        entity = await user_client.get_entity(CHANNEL_ID)
        
        count = 0
        # استخدام iter_messages بدلاً من get_messages لتجنب مشاكل البوت
        async for msg in user_client.iter_messages(entity, limit=50):
            if msg.message:
                if save_message_to_db(msg.id, msg.message, msg.date.isoformat()):
                    count += 1
        
        if count > 0:
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

def get_base_style(theme='light'):
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
        'admin_account': 'حساب أدمن',
        'test_account': 'حساب Test',
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
        'create_admin': 'إنشاء أدمن',
        'create_test': 'إنشاء Test',
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
        'admin_account': 'Admin Account',
        'test_account': 'Test Account',
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
        'create_admin': 'Create Admin',
        'create_test': 'Create Test',
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
    
    role = 'user'
    if len(user) > 14 and user[14]:
        role = user[14]
    
    if is_owner:
        role = 'owner'
    
    numbers_count = get_user_numbers_count(user[0])
    user_limit = get_user_limit(user[0])
    unread_notifications = get_unread_notifications_count(user[0])
    unread_messages = get_unread_messages_count(user[0])
    
    if role == 'owner' or role == 'admin':
        sidebar_items = [
            ('/owner/add-file', '📁 Add file'),
            ('/owner/delete-file', '🗑️ Delete file'),
            ('/owner/broadcast', '📢 Broadcast'),
            ('/owner/create-account', '👤 Create account'),
            ('/owner/increase-limit', '⬆️ Increase Limit'),
            ('/owner/results', '📊 Results'),
            ('/owner/add-number-test', '🧪 Add number test'),
            ('/owner/create-admin', '👑 Create Admin'),
            ('/owner/create-test', '🧪 Create Test'),
            ('/activity-log', '📝 Activity Log'),
        ]
    elif role == 'test':
        sidebar_items = [
            ('/user/test-number', '🧪 Test number'),
            ('/user/public-sms', '🌐 Public sms'),
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
            ('/user/delete-number', '➖ Delete number'),
            ('/user/my-number', '📱 My number'),
            ('/user/my-file', '📂 My file number'),
            ('/user/delete-file', '🗑️ Delete file number'),
            ('/user/client', '👤 Client'),
            ('/user/add-number-client', '📱 Add number client'),
            ('/user/test-number', '🧪 Test number'),
            ('/user/linking-channels', '🔗 Linking channels'),
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
    
    if role == 'owner':
        account_type = '👑 Owner Account'
    elif role == 'admin':
        account_type = '👑 Admin Account'
    elif role == 'test':
        account_type = '🧪 Test Account'
    elif is_client_user:
        account_type = t['client_account']
    else:
        account_type = t['user_account']
    
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
            <p>{account_type}</p>
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
        .header {{ background: #ffffff; border-bottom: 1px solid #e8e0f0; }}
        .info-banner {{
            background: linear-gradient(135deg, #9d4edd, #7b2cbf);
            color: white;
            padding: 20px;
            border-radius: 20px;
            margin-bottom: 25px;
        }}
        .info-banner h3 {{ color: white; margin-bottom: 10px; }}
        .stats-mini {{ display: flex; gap: 30px; margin-top: 15px; }}
        .stats-mini div {{ display: flex; align-items: center; gap: 8px; }}
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

@app.route('/user/add-numbers/<int:file_id>')
@login_required
def user_add_numbers(file_id):
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    cursor = db_conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM user_numbers WHERE user_id = ? AND file_id = ?', (user_id, file_id))
    file_count = cursor.fetchone()[0]
    
    FILE_LIMIT = 150
    
    if file_count >= FILE_LIMIT:
        return redirect('/user/add-number')
    
    cursor.execute('SELECT numbers FROM number_files WHERE id = ?', (file_id,))
    result = cursor.fetchone()
    
    if result:
        all_numbers = json.loads(result[0])
        remaining_in_file = FILE_LIMIT - file_count
        numbers_to_add = []
        
        for num in all_numbers:
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
@app.route('/user/my-sms')
@login_required
def user_my_sms_page():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = 'light'
    
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
        number = c[0] if c[0] else t['unknown']
        code_text = c[1] if c[1] else ''
        date_text = c[2][:16] if c[2] else ''
        
        rows += f'''
            <tr>
                <td style="direction: ltr; font-family: monospace; font-size: 1.1rem;">{number}</td>
                <td><strong style="color: #9d4edd;">{code_text}</strong></td>
                <td>{date_text}</td>
            </tr>
        '''
    
    if not rows:
        rows = f'<tr><td colspan="3" style="text-align:center; padding: 40px;"><i class="fas fa-inbox" style="font-size: 3rem; color: #d9c2f0; margin-bottom: 15px; display: block;"></i>{t["no_codes"]}</td></tr>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['my_sms']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
    <style>
        .header {{ background: #ffffff; border-bottom: 1px solid #e8e0f0; }}
        .sms-container {{ max-width: 1200px; margin: 0 auto; }}
        .table-wrapper {{ overflow-x: auto; border-radius: 16px; background: #ffffff; border: 1px solid #e8e0f0; }}
        .sms-table {{ width: 100%; border-collapse: collapse; }}
        .sms-table th {{ background: #f8f5ff; padding: 14px 15px; font-weight: 600; color: #5a189a; border-bottom: 2px solid #d9c2f0; text-align: right; }}
        .sms-table td {{ padding: 12px 15px; border-bottom: 1px solid #f0e8fa; }}
        .sms-table tr:hover td {{ background: #fdfbff; }}
        .stats-card {{ background: linear-gradient(135deg, #9d4edd, #7b2cbf); color: white; padding: 20px; border-radius: 20px; margin-bottom: 25px; }}
        .stats-card h3 {{ color: white; margin-bottom: 10px; }}
        .action-bar {{ display: flex; gap: 10px; margin-bottom: 15px; }}
        .btn-sync {{ background: #2cc185; box-shadow: 0 4px 10px rgba(44, 193, 133, 0.2); }}
        .btn-sync:hover {{ background: #25a86f; }}
        .sync-status {{ margin-left: 15px; font-size: 0.9rem; }}
        .new-message-alert {{
            background: #2cc185;
            color: white;
            padding: 10px 20px;
            border-radius: 10px;
            margin-bottom: 15px;
            display: none;
            animation: pulse 1s infinite;
        }}
        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.7; }}
            100% {{ opacity: 1; }}
        }}
        .connection-status {{
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #2cc185;
            margin-left: 10px;
        }}
        .connection-status.disconnected {{
            background: #ff5e5e;
        }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1 style="color: #5a189a;">
            💬 {t['my_sms']}
            <span id="connectionStatus" class="connection-status" title="متصل - التحديث الفوري نشط"></span>
        </h1>
        <div>
            <button class="btn btn-sync" onclick="syncMySMS()" id="syncBtn">
                <i class="fas fa-sync-alt"></i> Sync
            </button>
        </div>
    </div>
    
    <div class="container sms-container">
        <div class="stats-card">
            <h3><i class="fas fa-envelope"></i> رسائلك الخاصة</h3>
            <p>تظهر هنا جميع الرسائل التي تحتوي على أرقامك المخزنة في النظام</p>
            <p style="margin-top: 10px; font-size: 1.2rem;">
                عدد الرسائل: <strong id="messagesCount">{len(codes)}</strong>
                <span id="syncStatus" class="sync-status"></span>
            </p>
            <p style="margin-top: 5px; font-size: 0.9rem; opacity: 0.9;">
                <i class="fas fa-bolt"></i> اضغط Sync لتحديث الرسائل يدوياً
            </p>
        </div>
        
        <div id="newMessageAlert" class="new-message-alert">
            <i class="fas fa-bell"></i> رسالة جديدة! جاري التحديث...
        </div>
        
        <div class="card" style="padding: 0; overflow: hidden;">
            <div style="padding: 20px; border-bottom: 1px solid #e8e0f0; display: flex; justify-content: space-between; align-items: center;">
                <h2 style="margin: 0;"><i class="fas fa-list"></i> سجل الرسائل</h2>
                <button class="btn btn-sm" onclick="location.reload()" style="padding: 8px 15px;">
                    <i class="fas fa-redo-alt"></i> تحديث الصفحة
                </button>
            </div>
            <div class="table-wrapper" style="border: none; border-radius: 0;">
                <table class="sms-table">
                    <thead>
                        <tr>
                            <th><i class="fas fa-phone"></i> {t['phone']}</th>
                            <th><i class="fas fa-key"></i> {t['code']} / الرسالة</th>
                            <th><i class="far fa-calendar"></i> {t['date']}</th>
                        </tr>
                    </thead>
                    <tbody id="messagesTableBody">
                        {rows}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
    <script>
        const userId = {user_id};
        let eventSource = null;
        let messageCount = {len(codes)};
        
        // وظيفة المزامنة
        async function syncMySMS() {{
            const btn = document.getElementById('syncBtn');
            const statusEl = document.getElementById('syncStatus');
            const originalText = btn.innerHTML;
            
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> جاري المزامنة...';
            statusEl.innerHTML = '<span style="color: #fdb44b;"><i class="fas fa-spinner fa-spin"></i> جاري المزامنة...</span>';
            
            try {{
                const r = await fetch('/api/sync');
                const d = await r.json();
                
                if (d.success) {{
                    if (d.new_messages > 0) {{
                        statusEl.innerHTML = '<span style="color: #2cc185;"><i class="fas fa-check-circle"></i> تمت المزامنة! جاري التحديث...</span>';
                        setTimeout(() => location.reload(), 1000);
                    }} else {{
                        statusEl.innerHTML = '<span style="color: #2cc185;"><i class="fas fa-check-circle"></i> لا توجد رسائل جديدة</span>';
                        btn.disabled = false;
                        btn.innerHTML = originalText;
                        setTimeout(() => statusEl.innerHTML = '', 3000);
                    }}
                }} else {{
                    statusEl.innerHTML = '<span style="color: #ff5e5e;"><i class="fas fa-times-circle"></i> خطأ في المزامنة</span>';
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                }}
            }} catch(e) {{
                statusEl.innerHTML = '<span style="color: #ff5e5e;"><i class="fas fa-times-circle"></i> خطأ في الاتصال</span>';
                btn.disabled = false;
                btn.innerHTML = originalText;
            }}
        }}
        
        // الاتصال بـ SSE للتحديث الفوري
        function connectSSE() {{
            if (eventSource) {{
                eventSource.close();
            }}
            
            eventSource = new EventSource('/api/sse/connect/' + userId);
            
            eventSource.onopen = function() {{
                console.log('✅ SSE Connected');
                document.getElementById('connectionStatus').className = 'connection-status';
                document.getElementById('connectionStatus').title = 'متصل - التحديث الفوري نشط';
            }};
            
            eventSource.onerror = function() {{
                console.log('❌ SSE Error');
                document.getElementById('connectionStatus').className = 'connection-status disconnected';
                document.getElementById('connectionStatus').title = 'انقطع الاتصال - جاري إعادة المحاولة...';
                setTimeout(connectSSE, 5000);
            }};
            
            eventSource.onmessage = function(event) {{
                try {{
                    const data = JSON.parse(event.data);
                    
                    if (data.type === 'new_sms') {{
                        // إظهار تنبيه
                        const alert = document.getElementById('newMessageAlert');
                        alert.style.display = 'block';
                        setTimeout(() => alert.style.display = 'none', 3000);
                        
                        // إضافة الرسالة الجديدة إلى أعلى الجدول
                        const smsData = data.data;
                        const tbody = document.getElementById('messagesTableBody');
                        
                        const newRow = `
                            <tr style="background: #f0e8fa;">
                                <td style="direction: ltr; font-family: monospace; font-size: 1.1rem;">${{smsData.number || 'غير معروف'}}</td>
                                <td><strong style="color: #9d4edd;">${{smsData.code || ''}}</strong></td>
                                <td>${{smsData.received_at ? smsData.received_at.slice(0, 16) : ''}}</td>
                            </tr>
                        `;
                        
                        // إزالة صف "لا توجد رسائل" إذا كان موجوداً
                        const firstRow = tbody.querySelector('tr');
                        if (firstRow && firstRow.cells.length === 1) {{
                            tbody.innerHTML = newRow;
                        }} else {{
                            tbody.insertAdjacentHTML('afterbegin', newRow);
                        }}
                        
                        // تحديث العداد
                        messageCount++;
                        document.getElementById('messagesCount').textContent = messageCount;
                        
                        // إزالة تأثير الخلفية بعد 3 ثواني
                        setTimeout(() => {{
                            const rows = tbody.querySelectorAll('tr');
                            if (rows.length > 0) {{
                                rows[0].style.background = '';
                                rows[0].style.transition = 'background 1s';
                            }}
                        }}, 3000);
                    }}
                }} catch(e) {{
                    console.error('Error parsing SSE message:', e);
                }}
            }};
        }}
        
        // بدء الاتصال
        connectSSE();
        
        // تنظيف عند مغادرة الصفحة
        window.addEventListener('beforeunload', function() {{
            if (eventSource) {{
                eventSource.close();
            }}
        }});
        
        // تحديث تلقائي كل 60 ثانية كاحتياط
        setInterval(function() {{
            fetch('/api/sync').then(r => r.json()).then(d => {{
                if (d.success && d.new_messages > 0) {{
                    location.reload();
                }}
            }});
        }}, 60000);
    </script>
</body>
</html>
'''
@app.route('/user/public-sms')
@login_required
def user_public_sms_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = 'light'
    
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
        # أفغانستان
        'af': {'flag': '🇦🇫', 'code': '+93', 'name': 'Afghanistan', 'name_ar': 'أفغانستان'},
        # ألبانيا
        'al': {'flag': '🇦🇱', 'code': '+355', 'name': 'Albania', 'name_ar': 'ألبانيا'},
        # الجزائر
        'dz': {'flag': '🇩🇿', 'code': '+213', 'name': 'Algeria', 'name_ar': 'الجزائر'},
        # أندورا
        'ad': {'flag': '🇦🇩', 'code': '+376', 'name': 'Andorra', 'name_ar': 'أندورا'},
        # أنغولا
        'ao': {'flag': '🇦🇴', 'code': '+244', 'name': 'Angola', 'name_ar': 'أنغولا'},
        # أنتيغوا وبربودا
        'ag': {'flag': '🇦🇬', 'code': '+1268', 'name': 'Antigua and Barbuda', 'name_ar': 'أنتيغوا وبربودا'},
        # الأرجنتين
        'ar': {'flag': '🇦🇷', 'code': '+54', 'name': 'Argentina', 'name_ar': 'الأرجنتين'},
        # أرمينيا
        'am': {'flag': '🇦🇲', 'code': '+374', 'name': 'Armenia', 'name_ar': 'أرمينيا'},
        # أستراليا
        'au': {'flag': '🇦🇺', 'code': '+61', 'name': 'Australia', 'name_ar': 'أستراليا'},
        # النمسا
        'at': {'flag': '🇦🇹', 'code': '+43', 'name': 'Austria', 'name_ar': 'النمسا'},
        # أذربيجان
        'az': {'flag': '🇦🇿', 'code': '+994', 'name': 'Azerbaijan', 'name_ar': 'أذربيجان'},
        # باهاماس
        'bs': {'flag': '🇧🇸', 'code': '+1242', 'name': 'Bahamas', 'name_ar': 'باهاماس'},
        # البحرين
        'bh': {'flag': '🇧🇭', 'code': '+973', 'name': 'Bahrain', 'name_ar': 'البحرين'},
        # بنغلاديش
        'bd': {'flag': '🇧🇩', 'code': '+880', 'name': 'Bangladesh', 'name_ar': 'بنغلاديش'},
        # باربادوس
        'bb': {'flag': '🇧🇧', 'code': '+1246', 'name': 'Barbados', 'name_ar': 'باربادوس'},
        # بيلاروسيا
        'by': {'flag': '🇧🇾', 'code': '+375', 'name': 'Belarus', 'name_ar': 'بيلاروسيا'},
        # بلجيكا
        'be': {'flag': '🇧🇪', 'code': '+32', 'name': 'Belgium', 'name_ar': 'بلجيكا'},
        # بليز
        'bz': {'flag': '🇧🇿', 'code': '+501', 'name': 'Belize', 'name_ar': 'بليز'},
        # بنين
        'bj': {'flag': '🇧🇯', 'code': '+229', 'name': 'Benin', 'name_ar': 'بنين'},
        # بوتان
        'bt': {'flag': '🇧🇹', 'code': '+975', 'name': 'Bhutan', 'name_ar': 'بوتان'},
        # بوليفيا
        'bo': {'flag': '🇧🇴', 'code': '+591', 'name': 'Bolivia', 'name_ar': 'بوليفيا'},
        # البوسنة والهرسك
        'ba': {'flag': '🇧🇦', 'code': '+387', 'name': 'Bosnia and Herzegovina', 'name_ar': 'البوسنة والهرسك'},
        # بوتسوانا
        'bw': {'flag': '🇧🇼', 'code': '+267', 'name': 'Botswana', 'name_ar': 'بوتسوانا'},
        # البرازيل
        'br': {'flag': '🇧🇷', 'code': '+55', 'name': 'Brazil', 'name_ar': 'البرازيل'},
        # بروناي
        'bn': {'flag': '🇧🇳', 'code': '+673', 'name': 'Brunei', 'name_ar': 'بروناي'},
        # بلغاريا
        'bg': {'flag': '🇧🇬', 'code': '+359', 'name': 'Bulgaria', 'name_ar': 'بلغاريا'},
        # بوركينا فاسو
        'bf': {'flag': '🇧🇫', 'code': '+226', 'name': 'Burkina Faso', 'name_ar': 'بوركينا فاسو'},
        # بوروندي
        'bi': {'flag': '🇧🇮', 'code': '+257', 'name': 'Burundi', 'name_ar': 'بوروندي'},
        # الرأس الأخضر
        'cv': {'flag': '🇨🇻', 'code': '+238', 'name': 'Cabo Verde', 'name_ar': 'الرأس الأخضر'},
        # كمبوديا
        'kh': {'flag': '🇰🇭', 'code': '+855', 'name': 'Cambodia', 'name_ar': 'كمبوديا'},
        # الكاميرون
        'cm': {'flag': '🇨🇲', 'code': '+237', 'name': 'Cameroon', 'name_ar': 'الكاميرون'},
        # كندا
        'ca': {'flag': '🇨🇦', 'code': '+1', 'name': 'Canada', 'name_ar': 'كندا'},
        # جمهورية أفريقيا الوسطى
        'cf': {'flag': '🇨🇫', 'code': '+236', 'name': 'Central African Republic', 'name_ar': 'جمهورية أفريقيا الوسطى'},
        # تشاد
        'td': {'flag': '🇹🇩', 'code': '+235', 'name': 'Chad', 'name_ar': 'تشاد'},
        # تشيلي
        'cl': {'flag': '🇨🇱', 'code': '+56', 'name': 'Chile', 'name_ar': 'تشيلي'},
        # الصين
        'cn': {'flag': '🇨🇳', 'code': '+86', 'name': 'China', 'name_ar': 'الصين'},
        # كولومبيا
        'co': {'flag': '🇨🇴', 'code': '+57', 'name': 'Colombia', 'name_ar': 'كولومبيا'},
        # جزر القمر
        'km': {'flag': '🇰🇲', 'code': '+269', 'name': 'Comoros', 'name_ar': 'جزر القمر'},
        # الكونغو
        'cg': {'flag': '🇨🇬', 'code': '+242', 'name': 'Congo', 'name_ar': 'الكونغو'},
        # كوستاريكا
        'cr': {'flag': '🇨🇷', 'code': '+506', 'name': 'Costa Rica', 'name_ar': 'كوستاريكا'},
        # كرواتيا
        'hr': {'flag': '🇭🇷', 'code': '+385', 'name': 'Croatia', 'name_ar': 'كرواتيا'},
        # كوبا
        'cu': {'flag': '🇨🇺', 'code': '+53', 'name': 'Cuba', 'name_ar': 'كوبا'},
        # قبرص
        'cy': {'flag': '🇨🇾', 'code': '+357', 'name': 'Cyprus', 'name_ar': 'قبرص'},
        # التشيك
        'cz': {'flag': '🇨🇿', 'code': '+420', 'name': 'Czech Republic', 'name_ar': 'التشيك'},
        # الدنمارك
        'dk': {'flag': '🇩🇰', 'code': '+45', 'name': 'Denmark', 'name_ar': 'الدنمارك'},
        # جيبوتي
        'dj': {'flag': '🇩🇯', 'code': '+253', 'name': 'Djibouti', 'name_ar': 'جيبوتي'},
        # دومينيكا
        'dm': {'flag': '🇩🇲', 'code': '+1767', 'name': 'Dominica', 'name_ar': 'دومينيكا'},
        # جمهورية الدومينيكان
        'do': {'flag': '🇩🇴', 'code': '+1809', 'name': 'Dominican Republic', 'name_ar': 'جمهورية الدومينيكان'},
        # الإكوادور
        'ec': {'flag': '🇪🇨', 'code': '+593', 'name': 'Ecuador', 'name_ar': 'الإكوادور'},
        # مصر
        'eg': {'flag': '🇪🇬', 'code': '+20', 'name': 'Egypt', 'name_ar': 'مصر'},
        # السلفادور
        'sv': {'flag': '🇸🇻', 'code': '+503', 'name': 'El Salvador', 'name_ar': 'السلفادور'},
        # غينيا الاستوائية
        'gq': {'flag': '🇬🇶', 'code': '+240', 'name': 'Equatorial Guinea', 'name_ar': 'غينيا الاستوائية'},
        # إريتريا
        'er': {'flag': '🇪🇷', 'code': '+291', 'name': 'Eritrea', 'name_ar': 'إريتريا'},
        # إستونيا
        'ee': {'flag': '🇪🇪', 'code': '+372', 'name': 'Estonia', 'name_ar': 'إستونيا'},
        # إسواتيني
        'sz': {'flag': '🇸🇿', 'code': '+268', 'name': 'Eswatini', 'name_ar': 'إسواتيني'},
        # إثيوبيا
        'et': {'flag': '🇪🇹', 'code': '+251', 'name': 'Ethiopia', 'name_ar': 'إثيوبيا'},
        # فيجي
        'fj': {'flag': '🇫🇯', 'code': '+679', 'name': 'Fiji', 'name_ar': 'فيجي'},
        # فنلندا
        'fi': {'flag': '🇫🇮', 'code': '+358', 'name': 'Finland', 'name_ar': 'فنلندا'},
        # فرنسا
        'fr': {'flag': '🇫🇷', 'code': '+33', 'name': 'France', 'name_ar': 'فرنسا'},
        # الغابون
        'ga': {'flag': '🇬🇦', 'code': '+241', 'name': 'Gabon', 'name_ar': 'الغابون'},
        # غامبيا
        'gm': {'flag': '🇬🇲', 'code': '+220', 'name': 'Gambia', 'name_ar': 'غامبيا'},
        # جورجيا
        'ge': {'flag': '🇬🇪', 'code': '+995', 'name': 'Georgia', 'name_ar': 'جورجيا'},
        # ألمانيا
        'de': {'flag': '🇩🇪', 'code': '+49', 'name': 'Germany', 'name_ar': 'ألمانيا'},
        # غانا
        'gh': {'flag': '🇬🇭', 'code': '+233', 'name': 'Ghana', 'name_ar': 'غانا'},
        # اليونان
        'gr': {'flag': '🇬🇷', 'code': '+30', 'name': 'Greece', 'name_ar': 'اليونان'},
        # غرينادا
        'gd': {'flag': '🇬🇩', 'code': '+1473', 'name': 'Grenada', 'name_ar': 'غرينادا'},
        # غواتيمالا
        'gt': {'flag': '🇬🇹', 'code': '+502', 'name': 'Guatemala', 'name_ar': 'غواتيمالا'},
        # غينيا
        'gn': {'flag': '🇬🇳', 'code': '+224', 'name': 'Guinea', 'name_ar': 'غينيا'},
        # غينيا بيساو
        'gw': {'flag': '🇬🇼', 'code': '+245', 'name': 'Guinea-Bissau', 'name_ar': 'غينيا بيساو'},
        # غيانا
        'gy': {'flag': '🇬🇾', 'code': '+592', 'name': 'Guyana', 'name_ar': 'غيانا'},
        # هايتي
        'ht': {'flag': '🇭🇹', 'code': '+509', 'name': 'Haiti', 'name_ar': 'هايتي'},
        # هندوراس
        'hn': {'flag': '🇭🇳', 'code': '+504', 'name': 'Honduras', 'name_ar': 'هندوراس'},
        # المجر
        'hu': {'flag': '🇭🇺', 'code': '+36', 'name': 'Hungary', 'name_ar': 'المجر'},
        # آيسلندا
        'is': {'flag': '🇮🇸', 'code': '+354', 'name': 'Iceland', 'name_ar': 'آيسلندا'},
        # الهند
        'in': {'flag': '🇮🇳', 'code': '+91', 'name': 'India', 'name_ar': 'الهند'},
        # إندونيسيا
        'id': {'flag': '🇮🇩', 'code': '+62', 'name': 'Indonesia', 'name_ar': 'إندونيسيا'},
        # إيران
        'ir': {'flag': '🇮🇷', 'code': '+98', 'name': 'Iran', 'name_ar': 'إيران'},
        # العراق
        'iq': {'flag': '🇮🇶', 'code': '+964', 'name': 'Iraq', 'name_ar': 'العراق'},
        # أيرلندا
        'ie': {'flag': '🇮🇪', 'code': '+353', 'name': 'Ireland', 'name_ar': 'أيرلندا'},
        # إسرائيل
        'il': {'flag': '🇮🇱', 'code': '+972', 'name': 'Israel', 'name_ar': 'إسرائيل'},
        # إيطاليا
        'it': {'flag': '🇮🇹', 'code': '+39', 'name': 'Italy', 'name_ar': 'إيطاليا'},
        # ساحل العاج
        'ci': {'flag': '🇨🇮', 'code': '+225', 'name': 'Ivory Coast', 'name_ar': 'ساحل العاج'},
        # جامايكا
        'jm': {'flag': '🇯🇲', 'code': '+1876', 'name': 'Jamaica', 'name_ar': 'جامايكا'},
        # اليابان
        'jp': {'flag': '🇯🇵', 'code': '+81', 'name': 'Japan', 'name_ar': 'اليابان'},
        # الأردن
        'jo': {'flag': '🇯🇴', 'code': '+962', 'name': 'Jordan', 'name_ar': 'الأردن'},
        # كازاخستان
        'kz': {'flag': '🇰🇿', 'code': '+7', 'name': 'Kazakhstan', 'name_ar': 'كازاخستان'},
        # كينيا
        'ke': {'flag': '🇰🇪', 'code': '+254', 'name': 'Kenya', 'name_ar': 'كينيا'},
        # كيريباتي
        'ki': {'flag': '🇰🇮', 'code': '+686', 'name': 'Kiribati', 'name_ar': 'كيريباتي'},
        # كوريا الشمالية
        'kp': {'flag': '🇰🇵', 'code': '+850', 'name': 'North Korea', 'name_ar': 'كوريا الشمالية'},
        # كوريا الجنوبية
        'kr': {'flag': '🇰🇷', 'code': '+82', 'name': 'South Korea', 'name_ar': 'كوريا الجنوبية'},
        # الكويت
        'kw': {'flag': '🇰🇼', 'code': '+965', 'name': 'Kuwait', 'name_ar': 'الكويت'},
        # قيرغيزستان
        'kg': {'flag': '🇰🇬', 'code': '+996', 'name': 'Kyrgyzstan', 'name_ar': 'قيرغيزستان'},
        # لاوس
        'la': {'flag': '🇱🇦', 'code': '+856', 'name': 'Laos', 'name_ar': 'لاوس'},
        # لاتفيا
        'lv': {'flag': '🇱🇻', 'code': '+371', 'name': 'Latvia', 'name_ar': 'لاتفيا'},
        # لبنان
        'lb': {'flag': '🇱🇧', 'code': '+961', 'name': 'Lebanon', 'name_ar': 'لبنان'},
        # ليسوتو
        'ls': {'flag': '🇱🇸', 'code': '+266', 'name': 'Lesotho', 'name_ar': 'ليسوتو'},
        # ليبيريا
        'lr': {'flag': '🇱🇷', 'code': '+231', 'name': 'Liberia', 'name_ar': 'ليبيريا'},
        # ليبيا
        'ly': {'flag': '🇱🇾', 'code': '+218', 'name': 'Libya', 'name_ar': 'ليبيا'},
        # ليختنشتاين
        'li': {'flag': '🇱🇮', 'code': '+423', 'name': 'Liechtenstein', 'name_ar': 'ليختنشتاين'},
        # ليتوانيا
        'lt': {'flag': '🇱🇹', 'code': '+370', 'name': 'Lithuania', 'name_ar': 'ليتوانيا'},
        # لوكسمبورغ
        'lu': {'flag': '🇱🇺', 'code': '+352', 'name': 'Luxembourg', 'name_ar': 'لوكسمبورغ'},
        # مدغشقر
        'mg': {'flag': '🇲🇬', 'code': '+261', 'name': 'Madagascar', 'name_ar': 'مدغشقر'},
        # مالاوي
        'mw': {'flag': '🇲🇼', 'code': '+265', 'name': 'Malawi', 'name_ar': 'مالاوي'},
        # ماليزيا
        'my': {'flag': '🇲🇾', 'code': '+60', 'name': 'Malaysia', 'name_ar': 'ماليزيا'},
        # المالديف
        'mv': {'flag': '🇲🇻', 'code': '+960', 'name': 'Maldives', 'name_ar': 'المالديف'},
        # مالي
        'ml': {'flag': '🇲🇱', 'code': '+223', 'name': 'Mali', 'name_ar': 'مالي'},
        # مالطا
        'mt': {'flag': '🇲🇹', 'code': '+356', 'name': 'Malta', 'name_ar': 'مالطا'},
        # جزر مارشال
        'mh': {'flag': '🇲🇭', 'code': '+692', 'name': 'Marshall Islands', 'name_ar': 'جزر مارشال'},
        # موريتانيا
        'mr': {'flag': '🇲🇷', 'code': '+222', 'name': 'Mauritania', 'name_ar': 'موريتانيا'},
        # موريشيوس
        'mu': {'flag': '🇲🇺', 'code': '+230', 'name': 'Mauritius', 'name_ar': 'موريشيوس'},
        # المكسيك
        'mx': {'flag': '🇲🇽', 'code': '+52', 'name': 'Mexico', 'name_ar': 'المكسيك'},
        # ميكرونيسيا
        'fm': {'flag': '🇫🇲', 'code': '+691', 'name': 'Micronesia', 'name_ar': 'ميكرونيسيا'},
        # مولدوفا
        'md': {'flag': '🇲🇩', 'code': '+373', 'name': 'Moldova', 'name_ar': 'مولدوفا'},
        # موناكو
        'mc': {'flag': '🇲🇨', 'code': '+377', 'name': 'Monaco', 'name_ar': 'موناكو'},
        # منغوليا
        'mn': {'flag': '🇲🇳', 'code': '+976', 'name': 'Mongolia', 'name_ar': 'منغوليا'},
        # الجبل الأسود
        'me': {'flag': '🇲🇪', 'code': '+382', 'name': 'Montenegro', 'name_ar': 'الجبل الأسود'},
        # المغرب
        'ma': {'flag': '🇲🇦', 'code': '+212', 'name': 'Morocco', 'name_ar': 'المغرب'},
        # موزمبيق
        'mz': {'flag': '🇲🇿', 'code': '+258', 'name': 'Mozambique', 'name_ar': 'موزمبيق'},
        # ميانمار
        'mm': {'flag': '🇲🇲', 'code': '+95', 'name': 'Myanmar', 'name_ar': 'ميانمار'},
        # ناميبيا
        'na': {'flag': '🇳🇦', 'code': '+264', 'name': 'Namibia', 'name_ar': 'ناميبيا'},
        # ناورو
        'nr': {'flag': '🇳🇷', 'code': '+674', 'name': 'Nauru', 'name_ar': 'ناورو'},
        # نيبال
        'np': {'flag': '🇳🇵', 'code': '+977', 'name': 'Nepal', 'name_ar': 'نيبال'},
        # هولندا
        'nl': {'flag': '🇳🇱', 'code': '+31', 'name': 'Netherlands', 'name_ar': 'هولندا'},
        # نيوزيلندا
        'nz': {'flag': '🇳🇿', 'code': '+64', 'name': 'New Zealand', 'name_ar': 'نيوزيلندا'},
        # نيكاراغوا
        'ni': {'flag': '🇳🇮', 'code': '+505', 'name': 'Nicaragua', 'name_ar': 'نيكاراغوا'},
        # النيجر
        'ne': {'flag': '🇳🇪', 'code': '+227', 'name': 'Niger', 'name_ar': 'النيجر'},
        # نيجيريا
        'ng': {'flag': '🇳🇬', 'code': '+234', 'name': 'Nigeria', 'name_ar': 'نيجيريا'},
        # مقدونيا الشمالية
        'mk': {'flag': '🇲🇰', 'code': '+389', 'name': 'North Macedonia', 'name_ar': 'مقدونيا الشمالية'},
        # النرويج
        'no': {'flag': '🇳🇴', 'code': '+47', 'name': 'Norway', 'name_ar': 'النرويج'},
        # عمان
        'om': {'flag': '🇴🇲', 'code': '+968', 'name': 'Oman', 'name_ar': 'عمان'},
        # باكستان
        'pk': {'flag': '🇵🇰', 'code': '+92', 'name': 'Pakistan', 'name_ar': 'باكستان'},
        # بالاو
        'pw': {'flag': '🇵🇼', 'code': '+680', 'name': 'Palau', 'name_ar': 'بالاو'},
        # فلسطين
        'ps': {'flag': '🇵🇸', 'code': '+970', 'name': 'Palestine', 'name_ar': 'فلسطين'},
        # بنما
        'pa': {'flag': '🇵🇦', 'code': '+507', 'name': 'Panama', 'name_ar': 'بنما'},
        # بابوا غينيا الجديدة
        'pg': {'flag': '🇵🇬', 'code': '+675', 'name': 'Papua New Guinea', 'name_ar': 'بابوا غينيا الجديدة'},
        # باراغواي
        'py': {'flag': '🇵🇾', 'code': '+595', 'name': 'Paraguay', 'name_ar': 'باراغواي'},
        # بيرو
        'pe': {'flag': '🇵🇪', 'code': '+51', 'name': 'Peru', 'name_ar': 'بيرو'},
        # الفلبين
        'ph': {'flag': '🇵🇭', 'code': '+63', 'name': 'Philippines', 'name_ar': 'الفلبين'},
        # بولندا
        'pl': {'flag': '🇵🇱', 'code': '+48', 'name': 'Poland', 'name_ar': 'بولندا'},
        # البرتغال
        'pt': {'flag': '🇵🇹', 'code': '+351', 'name': 'Portugal', 'name_ar': 'البرتغال'},
        # قطر
        'qa': {'flag': '🇶🇦', 'code': '+974', 'name': 'Qatar', 'name_ar': 'قطر'},
        # رومانيا
        'ro': {'flag': '🇷🇴', 'code': '+40', 'name': 'Romania', 'name_ar': 'رومانيا'},
        # روسيا
        'ru': {'flag': '🇷🇺', 'code': '+7', 'name': 'Russia', 'name_ar': 'روسيا'},
        # رواندا
        'rw': {'flag': '🇷🇼', 'code': '+250', 'name': 'Rwanda', 'name_ar': 'رواندا'},
        # سانت كيتس ونيفيس
        'kn': {'flag': '🇰🇳', 'code': '+1869', 'name': 'Saint Kitts and Nevis', 'name_ar': 'سانت كيتس ونيفيس'},
        # سانت لوسيا
        'lc': {'flag': '🇱🇨', 'code': '+1758', 'name': 'Saint Lucia', 'name_ar': 'سانت لوسيا'},
        # سانت فنسنت والغرينادين
        'vc': {'flag': '🇻🇨', 'code': '+1784', 'name': 'Saint Vincent and the Grenadines', 'name_ar': 'سانت فنسنت والغرينادين'},
        # ساموا
        'ws': {'flag': '🇼🇸', 'code': '+685', 'name': 'Samoa', 'name_ar': 'ساموا'},
        # سان مارينو
        'sm': {'flag': '🇸🇲', 'code': '+378', 'name': 'San Marino', 'name_ar': 'سان مارينو'},
        # ساو تومي وبرينسيب
        'st': {'flag': '🇸🇹', 'code': '+239', 'name': 'Sao Tome and Principe', 'name_ar': 'ساو تومي وبرينسيب'},
        # السعودية
        'sa': {'flag': '🇸🇦', 'code': '+966', 'name': 'Saudi Arabia', 'name_ar': 'السعودية'},
        # السنغال
        'sn': {'flag': '🇸🇳', 'code': '+221', 'name': 'Senegal', 'name_ar': 'السنغال'},
        # صربيا
        'rs': {'flag': '🇷🇸', 'code': '+381', 'name': 'Serbia', 'name_ar': 'صربيا'},
        # سيشل
        'sc': {'flag': '🇸🇨', 'code': '+248', 'name': 'Seychelles', 'name_ar': 'سيشل'},
        # سيراليون
        'sl': {'flag': '🇸🇱', 'code': '+232', 'name': 'Sierra Leone', 'name_ar': 'سيراليون'},
        # سنغافورة
        'sg': {'flag': '🇸🇬', 'code': '+65', 'name': 'Singapore', 'name_ar': 'سنغافورة'},
        # سلوفاكيا
        'sk': {'flag': '🇸🇰', 'code': '+421', 'name': 'Slovakia', 'name_ar': 'سلوفاكيا'},
        # سلوفينيا
        'si': {'flag': '🇸🇮', 'code': '+386', 'name': 'Slovenia', 'name_ar': 'سلوفينيا'},
        # جزر سليمان
        'sb': {'flag': '🇸🇧', 'code': '+677', 'name': 'Solomon Islands', 'name_ar': 'جزر سليمان'},
        # الصومال
        'so': {'flag': '🇸🇴', 'code': '+252', 'name': 'Somalia', 'name_ar': 'الصومال'},
        # جنوب أفريقيا
        'za': {'flag': '🇿🇦', 'code': '+27', 'name': 'South Africa', 'name_ar': 'جنوب أفريقيا'},
        # جنوب السودان
        'ss': {'flag': '🇸🇸', 'code': '+211', 'name': 'South Sudan', 'name_ar': 'جنوب السودان'},
        # إسبانيا
        'es': {'flag': '🇪🇸', 'code': '+34', 'name': 'Spain', 'name_ar': 'إسبانيا'},
        # سريلانكا
        'lk': {'flag': '🇱🇰', 'code': '+94', 'name': 'Sri Lanka', 'name_ar': 'سريلانكا'},
        # السودان
        'sd': {'flag': '🇸🇩', 'code': '+249', 'name': 'Sudan', 'name_ar': 'السودان'},
        # سورينام
        'sr': {'flag': '🇸🇷', 'code': '+597', 'name': 'Suriname', 'name_ar': 'سورينام'},
        # السويد
        'se': {'flag': '🇸🇪', 'code': '+46', 'name': 'Sweden', 'name_ar': 'السويد'},
        # سويسرا
        'ch': {'flag': '🇨🇭', 'code': '+41', 'name': 'Switzerland', 'name_ar': 'سويسرا'},
        # سوريا
        'sy': {'flag': '🇸🇾', 'code': '+963', 'name': 'Syria', 'name_ar': 'سوريا'},
        # تايوان
        'tw': {'flag': '🇹🇼', 'code': '+886', 'name': 'Taiwan', 'name_ar': 'تايوان'},
        # طاجيكستان
        'tj': {'flag': '🇹🇯', 'code': '+992', 'name': 'Tajikistan', 'name_ar': 'طاجيكستان'},
        # تنزانيا
        'tz': {'flag': '🇹🇿', 'code': '+255', 'name': 'Tanzania', 'name_ar': 'تنزانيا'},
        # تايلاند
        'th': {'flag': '🇹🇭', 'code': '+66', 'name': 'Thailand', 'name_ar': 'تايلاند'},
        # تيمور الشرقية
        'tl': {'flag': '🇹🇱', 'code': '+670', 'name': 'Timor-Leste', 'name_ar': 'تيمور الشرقية'},
        # توغو
        'tg': {'flag': '🇹🇬', 'code': '+228', 'name': 'Togo', 'name_ar': 'توغو'},
        # تونغا
        'to': {'flag': '🇹🇴', 'code': '+676', 'name': 'Tonga', 'name_ar': 'تونغا'},
        # ترينيداد وتوباغو
        'tt': {'flag': '🇹🇹', 'code': '+1868', 'name': 'Trinidad and Tobago', 'name_ar': 'ترينيداد وتوباغو'},
        # تونس
        'tn': {'flag': '🇹🇳', 'code': '+216', 'name': 'Tunisia', 'name_ar': 'تونس'},
        # تركيا
        'tr': {'flag': '🇹🇷', 'code': '+90', 'name': 'Turkey', 'name_ar': 'تركيا'},
        # تركمانستان
        'tm': {'flag': '🇹🇲', 'code': '+993', 'name': 'Turkmenistan', 'name_ar': 'تركمانستان'},
        # توفالو
        'tv': {'flag': '🇹🇻', 'code': '+688', 'name': 'Tuvalu', 'name_ar': 'توفالو'},
        # أوغندا
        'ug': {'flag': '🇺🇬', 'code': '+256', 'name': 'Uganda', 'name_ar': 'أوغندا'},
        # أوكرانيا
        'ua': {'flag': '🇺🇦', 'code': '+380', 'name': 'Ukraine', 'name_ar': 'أوكرانيا'},
        # الإمارات العربية المتحدة
        'ae': {'flag': '🇦🇪', 'code': '+971', 'name': 'UAE', 'name_ar': 'الإمارات'},
        # المملكة المتحدة
        'gb': {'flag': '🇬🇧', 'code': '+44', 'name': 'United Kingdom', 'name_ar': 'المملكة المتحدة'},
        # الولايات المتحدة
        'us': {'flag': '🇺🇸', 'code': '+1', 'name': 'United States', 'name_ar': 'الولايات المتحدة'},
        # أوروغواي
        'uy': {'flag': '🇺🇾', 'code': '+598', 'name': 'Uruguay', 'name_ar': 'أوروغواي'},
        # أوزبكستان
        'uz': {'flag': '🇺🇿', 'code': '+998', 'name': 'Uzbekistan', 'name_ar': 'أوزبكستان'},
        # فانواتو
        'vu': {'flag': '🇻🇺', 'code': '+678', 'name': 'Vanuatu', 'name_ar': 'فانواتو'},
        # الفاتيكان
        'va': {'flag': '🇻🇦', 'code': '+379', 'name': 'Vatican City', 'name_ar': 'الفاتيكان'},
        # فنزويلا
        've': {'flag': '🇻🇪', 'code': '+58', 'name': 'Venezuela', 'name_ar': 'فنزويلا'},
        # فيتنام
        'vn': {'flag': '🇻🇳', 'code': '+84', 'name': 'Vietnam', 'name_ar': 'فيتنام'},
        # اليمن
        'ye': {'flag': '🇾🇪', 'code': '+967', 'name': 'Yemen', 'name_ar': 'اليمن'},
        # زامبيا
        'zm': {'flag': '🇿🇲', 'code': '+260', 'name': 'Zambia', 'name_ar': 'زامبيا'},
        # زيمبابوي
        'zw': {'flag': '🇿🇼', 'code': '+263', 'name': 'Zimbabwe', 'name_ar': 'زيمبابوي'},
        # كوسوفو
        'xk': {'flag': '🇽🇰', 'code': '+383', 'name': 'Kosovo', 'name_ar': 'كوسوفو'},
        # الصحراء الغربية
        'eh': {'flag': '🇪🇭', 'code': '+212', 'name': 'Western Sahara', 'name_ar': 'الصحراء الغربية'},
        # أرض الصومال
        'somaliland': {'flag': '🇸🇴', 'code': '+252', 'name': 'Somaliland', 'name_ar': 'أرض الصومال'},
        # هونغ كونغ
        'hk': {'flag': '🇭🇰', 'code': '+852', 'name': 'Hong Kong', 'name_ar': 'هونغ كونغ'},
        # ماكاو
        'mo': {'flag': '🇲🇴', 'code': '+853', 'name': 'Macau', 'name_ar': 'ماكاو'},
        # بورتوريكو
        'pr': {'flag': '🇵🇷', 'code': '+1787', 'name': 'Puerto Rico', 'name_ar': 'بورتوريكو'},
        # غوام
        'gu': {'flag': '🇬🇺', 'code': '+1671', 'name': 'Guam', 'name_ar': 'غوام'},
        # برمودا
        'bm': {'flag': '🇧🇲', 'code': '+1441', 'name': 'Bermuda', 'name_ar': 'برمودا'},
        # جزر كايمان
        'ky': {'flag': '🇰🇾', 'code': '+1345', 'name': 'Cayman Islands', 'name_ar': 'جزر كايمان'},
        # جزر فيرجن البريطانية
        'vg': {'flag': '🇻🇬', 'code': '+1284', 'name': 'British Virgin Islands', 'name_ar': 'جزر فيرجن البريطانية'},
        # جزر فيرجن الأمريكية
        'vi': {'flag': '🇻🇮', 'code': '+1340', 'name': 'US Virgin Islands', 'name_ar': 'جزر فيرجن الأمريكية'},
        # جبل طارق
        'gi': {'flag': '🇬🇮', 'code': '+350', 'name': 'Gibraltar', 'name_ar': 'جبل طارق'},
        # جزر فارو
        'fo': {'flag': '🇫🇴', 'code': '+298', 'name': 'Faroe Islands', 'name_ar': 'جزر فارو'},
        # جرينلاند
        'gl': {'flag': '🇬🇱', 'code': '+299', 'name': 'Greenland', 'name_ar': 'جرينلاند'},
        # أروبا
        'aw': {'flag': '🇦🇼', 'code': '+297', 'name': 'Aruba', 'name_ar': 'أروبا'},
        # كوراساو
        'cw': {'flag': '🇨🇼', 'code': '+599', 'name': 'Curacao', 'name_ar': 'كوراساو'},
        # سانت مارتن
        'sx': {'flag': '🇸🇽', 'code': '+1721', 'name': 'Sint Maarten', 'name_ar': 'سانت مارتن'},
        # بونير
        'bq': {'flag': '🇧🇶', 'code': '+599', 'name': 'Bonaire', 'name_ar': 'بونير'},
        # أنغويلا
        'ai': {'flag': '🇦🇮', 'code': '+1264', 'name': 'Anguilla', 'name_ar': 'أنغويلا'},
        # مونتسيرات
        'ms': {'flag': '🇲🇸', 'code': '+1664', 'name': 'Montserrat', 'name_ar': 'مونتسيرات'},
        # جزر توركس وكايكوس
        'tc': {'flag': '🇹🇨', 'code': '+1649', 'name': 'Turks and Caicos', 'name_ar': 'جزر توركس وكايكوس'},
        # سانت بيير وميكلون
        'pm': {'flag': '🇵🇲', 'code': '+508', 'name': 'Saint Pierre and Miquelon', 'name_ar': 'سانت بيير وميكلون'},
        # جزر فوكلاند
        'fk': {'flag': '🇫🇰', 'code': '+500', 'name': 'Falkland Islands', 'name_ar': 'جزر فوكلاند'},
        # بولينيزيا الفرنسية
        'pf': {'flag': '🇵🇫', 'code': '+689', 'name': 'French Polynesia', 'name_ar': 'بولينيزيا الفرنسية'},
        # كاليدونيا الجديدة
        'nc': {'flag': '🇳🇨', 'code': '+687', 'name': 'New Caledonia', 'name_ar': 'كاليدونيا الجديدة'},
        # واليس وفوتونا
        'wf': {'flag': '🇼🇫', 'code': '+681', 'name': 'Wallis and Futuna', 'name_ar': 'واليس وفوتونا'},
        # جزر كوك
        'ck': {'flag': '🇨🇰', 'code': '+682', 'name': 'Cook Islands', 'name_ar': 'جزر كوك'},
        # نييوي
        'nu': {'flag': '🇳🇺', 'code': '+683', 'name': 'Niue', 'name_ar': 'نييوي'},
        # توكيلاو
        'tk': {'flag': '🇹🇰', 'code': '+690', 'name': 'Tokelau', 'name_ar': 'توكيلاو'},
        # جزيرة نورفولك
        'nf': {'flag': '🇳🇫', 'code': '+672', 'name': 'Norfolk Island', 'name_ar': 'جزيرة نورفولك'},
        # جزيرة كريسماس
        'cx': {'flag': '🇨🇽', 'code': '+61', 'name': 'Christmas Island', 'name_ar': 'جزيرة كريسماس'},
        # جزر كوكوس
        'cc': {'flag': '🇨🇨', 'code': '+61', 'name': 'Cocos Islands', 'name_ar': 'جزر كوكوس'},
    }
    
    def extract_country_info(text):
        import re
        text_lower = text.lower()
        
        hashtag_match = re.search(r'#([A-Za-z]{2,3})\b', text)
        if hashtag_match:
            try:
                code = hashtag_match.group(1).lower()
                if code in COUNTRIES_DB:
                    return COUNTRIES_DB[code]['flag'], COUNTRIES_DB[code]['code'], COUNTRIES_DB[code]['name']
            except:
                pass
        
        for key, data in COUNTRIES_DB.items():
            if data['name'].lower() in text_lower or data['name_ar'] in text:
                return data['flag'], data['code'], data['name']
        
        code_match = re.search(r'\+(\d{1,3})\b', text)
        if code_match:
            try:
                dial_code = '+' + code_match.group(1)
                for key, data in COUNTRIES_DB.items():
                    if data['code'] == dial_code:
                        return data['flag'], data['code'], data['name']
            except:
                pass
        
        for key, data in COUNTRIES_DB.items():
            if data['flag'] in text:
                return data['flag'], data['code'], data['name']
        
        return '🌍', '', 'Unknown'
    
    def extract_phone_number(text):
        import re
        
        if not text:
            return '—'
        
        patterns = [
            r'([A-Za-z]?\d{8,15})',
            r'(\+\d{1,3}[\s.-]?\d{8,15})',
            r'(\d{2,3}[•*]{2,}\d{3,5})',
            r'\b(\d{8,15})\b',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    number = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                except:
                    number = match.group(0)
                
                if '•' in number or '*' in number:
                    return number
                
                number = re.sub(r'[\s.\-]', '', number)
                number = re.sub(r'^[A-Za-z]+', '', number)
                
                if len(number) < 8:
                    continue
                
                if len(number) > 8:
                    return number[:4] + '••••' + number[-4:]
                elif len(number) > 4:
                    return number[:2] + '••' + number[-2:]
                else:
                    return '••••'
        
        return '—'
    
    def extract_cli_info(text):
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
            'binance': '₿ Binance',
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
        import re
        clean = text
        
        if flag != '🌍':
            clean = clean.replace(flag, '')
        
        clean = re.sub(r'#[A-Za-z]{2,3}\s*', '', clean)
        clean = re.sub(r'\+\d{1,3}\s*', '', clean)
        clean = re.sub(r'\b\d{8,15}\b', '', clean)
        clean = re.sub(r'\d{2,3}[•*]{2,}\d{3,5}', '', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        code = extract_otp_from_message(text)
        if code:
            if len(clean) > 50:
                return f'{clean[:50]}... <span style="background: #9d4edd; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.7rem; margin-right: 5px;">🔐 {code}</span>'
            else:
                return f'{clean} <span style="background: #9d4edd; color: white; padding: 2px 8px; border-radius: 12px; font-size: 0.7rem; margin-right: 5px;">🔐 {code}</span>'
        
        return clean[:80] + '...' if len(clean) > 80 else clean
    
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
        body {{ background: #f8f9fc; }}
        .records-container {{ max-width: 100% !important; width: 100% !important; padding: 15px 20px !important; margin: 0 !important; }}
        .page-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 15px; }}
        .page-header h1 {{ margin: 0; font-size: 1.8rem; display: flex; align-items: center; gap: 15px; color: #4a1d6e; }}
        .total-badge {{ background: #f0e8fa; padding: 6px 15px; border-radius: 30px; font-size: 0.9rem; color: #5a189a; border: 1px solid #d9c2f0; }}
        .table-wrapper {{ overflow-x: auto; border-radius: 16px; background: #ffffff; border: 1px solid #e8e0f0; box-shadow: 0 4px 12px rgba(0,0,0,0.04); margin-bottom: 20px; }}
        .records-table {{ width: 100%; border-collapse: collapse; min-width: 1100px; font-size: 0.9rem; }}
        .records-table th {{ background: #f8f5ff; padding: 14px 12px; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; letter-spacing: 0.5px; border-bottom: 2px solid #d9c2f0; white-space: nowrap; color: #5a189a; }}
        .records-table td {{ padding: 12px; border-bottom: 1px solid #f0e8fa; vertical-align: middle; color: #1a1a2e; }}
        .records-table tr:hover td {{ background: #fdfbff; }}
        .cli-badge {{ display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; background: #f0e8fa; color: #5a189a; white-space: nowrap; }}
        .table-footer {{ display: flex; justify-content: space-between; align-items: center; margin-top: 15px; flex-wrap: wrap; gap: 15px; }}
        .total-info {{ background: #e8faf1; padding: 10px 20px; border-radius: 30px; border: 1px solid #2cc185; color: #1a1a2e; }}
        .total-info strong {{ color: #2cc185; font-size: 1.3rem; margin: 0 10px; }}
        .pagination {{ display: flex; gap: 5px; }}
        .pagination button {{ padding: 8px 15px; background: #ffffff; border: 1px solid #d9c2f0; border-radius: 8px; color: #4a1d6e; cursor: pointer; font-weight: 500; transition: all 0.2s; }}
        .pagination button:hover {{ background: #9d4edd; color: white; border-color: #9d4edd; }}
        .action-bar {{ display: flex; gap: 10px; }}
        .btn-success {{ background: #2cc185; box-shadow: 0 4px 10px rgba(44, 193, 133, 0.2); }}
        .btn-success:hover {{ background: #25a86f; }}
        .records-table th:nth-child(1) {{ width: 160px; }}
        .records-table th:nth-child(2) {{ width: 180px; }}
        .records-table th:nth-child(3) {{ width: 140px; }}
        .records-table th:nth-child(4) {{ width: 110px; }}
        .records-table th:nth-child(6) {{ width: 100px; }}
        .header {{ background: #ffffff; border-bottom: 1px solid #e8e0f0; box-shadow: 0 2px 8px rgba(0,0,0,0.02); }}
        .back-btn {{ background: #f8f5ff; color: #5a189a; border: 1px solid #d9c2f0; }}
        @media (max-width: 768px) {{ .records-container {{ padding: 10px !important; }} .page-header {{ flex-direction: column; align-items: flex-start; }} }}
    </style>
</head>
<body>
    <div class="header">
        <div style="display: flex; align-items: center; gap: 15px;">
            <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
            <span id="syncStatus"></span>
            <span class="total-badge"><i class="far fa-clock"></i> {last_sync_time}</span>
        </div>
    </div>
    
    <div class="container records-container">
        <div class="page-header">
            <h1><i class="fas fa-table" style="color: #9d4edd;"></i> Show Records</h1>
            <div class="action-bar">
                <button class="btn btn-success" onclick="syncMessages()" id="syncBtn"><i class="fas fa-cloud-download-alt"></i> Sync</button>
                <button class="btn" onclick="location.reload()"><i class="fas fa-redo-alt"></i> Refresh</button>
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
                <tbody>{table_body}</tbody>
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
            fetch('/api/sync').then(r => r.json()).then(d => {{ if (d.success && d.new_messages > 0) location.reload(); }});
        }}, 30000);
    </script>
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
        <div class="card"><h2>{t['added_files']}</h2></div>
        {files_html}
    </div>
</body>
</html>
'''

@app.route('/user/delete-file', methods=['GET', 'POST'])
@login_required
def user_delete_file():
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    if request.method == 'POST':
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
            <form method="POST">
                <label>{t['file']}:</label>
                <input type="text" name="file_name" placeholder="{t['enter_file_name']}" required>
                <button type="submit" class="btn btn-danger" onclick="return confirm('{t['confirm_delete']}')">🗑️ {t['delete']}</button>
            </form>
        </div>
    </div>
</body>
</html>
'''

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

@app.route('/owner/delete-file')
@owner_required
def owner_delete_file_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id, display_name FROM number_files ORDER BY id DESC')
    files = cursor.fetchall()
    
    options = ''.join([f'<option value="{f[0]}">{f[1]}</option>' for f in files])
    
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

@app.route('/owner/increase-limit')
@owner_required
def owner_increase_limit_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id, username, number_limit FROM users WHERE username != ?', (OWNER_USERNAME,))
    users = cursor.fetchall()
    
    options = ''.join([f'<option value="{u[0]}">{u[1]} ({t["current_limit"]}: {u[2] if u[2] else 150})</option>' for u in users])
    
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

@app.route('/owner/results')
@owner_required
def owner_results_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT u.id, u.username, u.whatsapp, u.is_blocked, u.number_limit,
               (SELECT COUNT(*) FROM user_numbers WHERE user_id = u.id) as numbers_count,
               u.role
        FROM users u
        WHERE u.username != ?
        ORDER BY u.id DESC
    ''', (OWNER_USERNAME,))
    users = cursor.fetchall()
    
    rows = ''
    for u in users:
        user_id, username, whatsapp, is_blocked, limit_num, count, role = u
        blocked_text = t['active'] if not is_blocked else t['blocked']
        block_btn = f'<a href="/owner/block/{user_id}" class="btn btn-sm btn-warning">🚫 {t["block"]}</a>' if not is_blocked else f'<a href="/owner/unblock/{user_id}" class="btn btn-sm btn-success">✅ {t["unblock"]}</a>'
        role_badge = {'admin': '👑', 'test': '🧪', 'user': '👤'}.get(role, '👤')
        rows += f'''
            <tr>
                <td>{role_badge} {username}</td>
                <td>{whatsapp or t['unknown']}</td>
                <td><span class="badge {'badge-danger' if is_blocked else 'badge-success'}">{blocked_text}</span></td>
                <td>{count}/{limit_num if limit_num else 150}</td>
                <td>{block_btn} <a href="/owner/increase-limit?user_id={user_id}" class="btn btn-sm" style="padding:5px 10px;">⬆️ {t['increase_limit']}</a></td>
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
                    <tr><th>{t['user']}</th><th>{t['whatsapp']}</th><th>{t['status']}</th><th>{t['numbers']}</th><th>{t['actions']}</th></tr>
                </thead>
                <tbody>{rows if rows else f'<tr><td colspan="5" style="text-align:center;">{t["no_messages"]}</td></tr>'}</tbody>
            </table>
        </div>
    </div>
</body>
</html>
'''

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
@app.route('/owner/create-admin')
@owner_required
def owner_create_admin_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Create Admin - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>👑 Create Admin</h1>
        <div></div>
    </div>
    <div class="container">
        <div class="card">
            <h2><i class="fas fa-crown"></i> إنشاء حساب أدمن</h2>
            <p style="margin-bottom: 20px; color: #fdb44b;">
                <i class="fas fa-info-circle"></i> حساب الأدمن له نفس صلاحيات المالك (إضافة ملفات، بث، إنشاء حسابات، زيادة الحد...)
            </p>
            <form action="/owner/create-admin" method="POST">
                <label>👤 {t['username']}:</label>
                <input type="text" name="username" placeholder="Username" required>
                <label>🔐 {t['password']}:</label>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit" class="btn btn-success">👑 Create Admin</button>
            </form>
        </div>
        <div class="card">
            <h2><i class="fas fa-list"></i> الأدمنز الحاليين</h2>
            <table><thead><tr><th>{t['username']}</th><th>{t['date']}</th></tr></thead>
            <tbody id="adminsList"><tr><td colspan="2" style="text-align:center;">جاري التحميل...</td></tr></tbody>
            </table>
        </div>
    </div>
    <script>
        async function loadAdmins() {{
            try {{
                const r = await fetch('/api/admins/list');
                const d = await r.json();
                const tbody = document.getElementById('adminsList');
                if (d.admins && d.admins.length > 0) {{
                    tbody.innerHTML = d.admins.map(a => `<tr><td><i class="fas fa-crown" style="color: #fdb44b;"></i> ${{a.username}}</td><td>${{a.created_at ? a.created_at.slice(0, 16) : ''}}</td></tr>`).join('');
                }} else {{
                    tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;">لا يوجد أدمنز</td></tr>';
                }}
            }} catch(e) {{ document.getElementById('adminsList').innerHTML = '<tr><td colspan="2" style="text-align:center;">خطأ في التحميل</td></tr>'; }}
        }}
        loadAdmins();
    </script>
</body>
</html>
'''

@app.route('/owner/create-admin', methods=['POST'])
@owner_required
def owner_create_admin():
    username = request.form.get('username')
    password = request.form.get('password')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    if cursor.fetchone():
        return redirect('/owner/create-admin')
    
    cursor.execute('''
        INSERT INTO users (username, password, role, number_limit, created_at)
        VALUES (?, ?, 'admin', 999999, ?)
    ''', (username, hash_password(password), datetime.now().isoformat()))
    db_conn.commit()
    
    log_activity(session['user_id'], 'create_admin', f'Created admin: {username}')
    add_notification(session['user_id'], "👑 تم إنشاء أدمن", f"تم إنشاء حساب الأدمن: {username}", "success")
    return redirect('/owner/create-admin')

@app.route('/owner/create-test')
@owner_required
def owner_create_test_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Create Test - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>🧪 Create Test</h1>
        <div></div>
    </div>
    <div class="container">
        <div class="card">
            <h2><i class="fas fa-flask"></i> إنشاء حساب Test</h2>
            <p style="margin-bottom: 20px; color: #2cc185;">
                <i class="fas fa-info-circle"></i> حساب Test يظهر له فقط: Test Numbers و Public SMS
            </p>
            <form action="/owner/create-test" method="POST">
                <label>👤 {t['username']}:</label>
                <input type="text" name="username" placeholder="Username" required>
                <label>🔐 {t['password']}:</label>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit" class="btn btn-success">🧪 Create Test</button>
            </form>
        </div>
        <div class="card">
            <h2><i class="fas fa-list"></i> حسابات Test الحالية</h2>
            <table><thead><tr><th>{t['username']}</th><th>{t['date']}</th></tr></thead>
            <tbody id="testList"><tr><td colspan="2" style="text-align:center;">جاري التحميل...</td></tr></tbody>
            </table>
        </div>
    </div>
    <script>
        async function loadTests() {{
            try {{
                const r = await fetch('/api/tests/list');
                const d = await r.json();
                const tbody = document.getElementById('testList');
                if (d.tests && d.tests.length > 0) {{
                    tbody.innerHTML = d.tests.map(t => `<tr><td><i class="fas fa-flask" style="color: #2cc185;"></i> ${{t.username}}</td><td>${{t.created_at ? t.created_at.slice(0, 16) : ''}}</td></tr>`).join('');
                }} else {{
                    tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;">لا يوجد حسابات Test</td></tr>';
                }}
            }} catch(e) {{ document.getElementById('testList').innerHTML = '<tr><td colspan="2" style="text-align:center;">خطأ في التحميل</td></tr>'; }}
        }}
        loadTests();
    </script>
</body>
</html>
'''

@app.route('/owner/create-test', methods=['POST'])
@owner_required
def owner_create_test():
    username = request.form.get('username')
    password = request.form.get('password')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    if cursor.fetchone():
        return redirect('/owner/create-test')
    
    cursor.execute('''
        INSERT INTO users (username, password, role, created_at)
        VALUES (?, ?, 'test', ?)
    ''', (username, hash_password(password), datetime.now().isoformat()))
    db_conn.commit()
    
    log_activity(session['user_id'], 'create_test', f'Created test account: {username}')
    add_notification(session['user_id'], "🧪 تم إنشاء حساب Test", f"تم إنشاء حساب Test: {username}", "success")
    return redirect('/owner/create-test')
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
    <div class="container">{notif_html}</div>
</body>
</html>
'''

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
        cursor.execute('UPDATE users SET whatsapp = ?, email = ?, language = ?, theme = ? WHERE id = ?',
                      (whatsapp, email, language, theme, user_id))
        db_conn.commit()
    except:
        pass
    
    session['lang'] = language
    session['theme'] = theme
    log_activity(user_id, 'update_profile', 'Updated profile')
    return redirect('/profile')

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
    
    rows = ''.join([f'<tr><td>{l[3]}</td><td>{l[0]}</td><td>{l[1]}</td><td>{l[2][:16]}</td></tr>' for l in logs])
    
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
                <thead><tr><th>{t['user']}</th><th>{t['activity']}</th><th>{t['details']}</th><th>{t['date']}</th></tr></thead>
                <tbody>{rows if rows else f'<tr><td colspan="4" style="text-align:center;">{t["no_messages"]}</td></tr>'}</tbody>
            </table>
        </div>
    </div>
</body>
</html>
'''
# ============================================================
#                      صفحة إنشاء عميل (Client)
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
                <td><i class="fas fa-user"></i> {c[1]}</td>
                <td><span class="badge badge-success">{count}</span></td>
                <td>{c[2][:16] if c[2] else ''}</td>
                <td>
                    <a href="/user/client/delete/{c[0]}" class="btn btn-sm btn-danger" onclick="return confirm('{t['confirm_delete']}')">🗑️</a>
                </td>
            </tr>
        '''
    
    if not clients_html:
        clients_html = f'<tr><td colspan="4" style="text-align:center;">{t["no_messages"]}</td></tr>'
    
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
            <h2><i class="fas fa-user-plus"></i> {t['create_client']}</h2>
            <form action="/user/client/create" method="POST">
                <label><i class="fas fa-user"></i> {t['client_username']}:</label>
                <input type="text" name="username" placeholder="{t['username']}" required>
                <label><i class="fas fa-lock"></i> {t['client_password']}:</label>
                <input type="password" name="password" placeholder="{t['password']}" required>
                <button type="submit" class="btn btn-success">✅ {t['create_client']}</button>
            </form>
        </div>
        
        <div class="card">
            <h2><i class="fas fa-users"></i> {t['current_clients']}</h2>
            <table>
                <thead>
                    <tr>
                        <th>{t['username']}</th>
                        <th>{t['numbers']}</th>
                        <th>{t['date']}</th>
                        <th>{t['actions']}</th>
                    </tr>
                </thead>
                <tbody>{clients_html}</tbody>
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
    add_notification(parent_id, "👤 تم إنشاء عميل", f"تم إنشاء حساب العميل: {username}", "success")
    
    return redirect('/user/client')

@app.route('/user/client/delete/<int:client_id>')
@login_required
def delete_client(client_id):
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    user_id = session['user_id']
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id FROM users WHERE id = ? AND parent_id = ?', (client_id, user_id))
    if cursor.fetchone():
        cursor.execute('DELETE FROM users WHERE id = ?', (client_id,))
        cursor.execute('DELETE FROM client_numbers WHERE client_id = ?', (client_id,))
        cursor.execute('DELETE FROM user_codes WHERE user_id = ?', (client_id,))
        db_conn.commit()
        log_activity(user_id, 'delete_client', f'Deleted client ID: {client_id}')
    
    return redirect('/user/client')
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
                    <p style="text-align:center; padding: 40px;">
                        <i class="fas fa-users" style="font-size: 3rem; color: #d9c2f0; margin-bottom: 15px; display: block;"></i>
                        لا يوجد عملاء. قم بإنشاء عميل أولاً من صفحة Client
                    </p>
                    <div style="text-align: center;">
                        <a href="/user/client" class="btn btn-success">👤 إنشاء عميل</a>
                    </div>
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
    
    number_options = [50, 100, 150, 200, 500, 1000, 3000, 5000, 10000]
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
    <style>
        .info-banner {{
            background: linear-gradient(135deg, #2cc185, #1a9e6a);
            color: white;
            padding: 20px;
            border-radius: 20px;
            margin-bottom: 25px;
        }}
        .info-banner h3 {{ color: white; margin-bottom: 10px; }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>📱 {t['add_number_client']}</h1>
        <div></div>
    </div>
    
    <div class="container" style="max-width: 700px;">
        <div class="info-banner">
            <h3><i class="fas fa-info-circle"></i> إضافة أرقام للعميل</h3>
            <p>يمكنك إضافة أرقام من الملفات المتاحة إلى حساب العميل. لا يوجد حد أقصى لعدد الأرقام التي يمكن للعميل استقبالها.</p>
        </div>
        
        <div class="card">
            <h2><i class="fas fa-exchange-alt"></i> {t['add_number_client']}</h2>
            <form action="/user/add-number-client" method="POST">
                <label><i class="fas fa-user"></i> {t['select_client']}:</label>
                <select name="client_id" required>
                    <option value="">{t['select_client']}</option>
                    {clients_options}
                </select>
                
                <label><i class="fas fa-folder"></i> {t['select_file']}:</label>
                <select name="file_id" required>
                    <option value="">{t['select_file']}</option>
                    {files_options}
                </select>
                
                <label><i class="fas fa-calculator"></i> {t['select_number_total']}:</label>
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
        add_notification(user_id, "✅ تمت الإضافة", f"تمت إضافة {added} رقم للعميل", "success")
    
    return redirect('/user/client')
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
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h3 style="margin: 0 0 8px 0;">🧪 {f[1]}</h3>
                        <p style="margin: 0; opacity: 0.8;"><i class="fas fa-database"></i> {t['numbers_count']}: <strong>{f[2]}</strong></p>
                        <p style="margin: 5px 0 0 0; opacity: 0.6; font-size: 0.9rem;"><i class="far fa-calendar"></i> {f[3][:16] if f[3] else ''}</p>
                    </div>
                    <div>
                        <a href="/user/test-number/view/{f[0]}" class="btn btn-success">👀 عرض الأرقام</a>
                        <a href="/user/test-number/download/{f[0]}" class="btn" style="background: #fdb44b;">📥 تحميل</a>
                    </div>
                </div>
            </div>
        '''
    
    if not files_html:
        files_html = f'<div class="card"><p style="text-align:center; padding: 40px;"><i class="fas fa-flask" style="font-size: 3rem; color: #d9c2f0; margin-bottom: 15px; display: block;"></i>{t["no_messages"]}</p></div>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{t['test_number']} - {t['app_name']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
    <style>
        .header {{ background: #ffffff; border-bottom: 1px solid #e8e0f0; }}
        .stats-card {{
            background: linear-gradient(135deg, #fdb44b, #e67e22);
            color: white;
            padding: 20px;
            border-radius: 20px;
            margin-bottom: 25px;
        }}
        .stats-card h3 {{ color: white; margin-bottom: 10px; }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1 style="color: #5a189a;">🧪 {t['test_number']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="stats-card">
            <h3><i class="fas fa-flask"></i> أرقام الاختبار المتاحة</h3>
            <p>يمكنك عرض وتحميل أرقام الاختبار من مختلف الدول</p>
            <p style="margin-top: 10px; font-size: 1.2rem;">عدد الملفات: <strong>{len(files)}</strong></p>
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
    for i, num in enumerate(numbers[:200], 1):
        rows += f'<tr><td>{i}</td><td style="direction: ltr; font-family: monospace;">{num}</td></tr>'
    
    return f'''
<!DOCTYPE html>
<html dir="{'rtl' if lang == 'ar' else 'ltr'}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{country_name} - {t['test_number']}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    {get_base_style(theme)}
    <style>
        .header {{ background: #ffffff; border-bottom: 1px solid #e8e0f0; }}
        .table-wrapper {{ max-height: 600px; overflow-y: auto; }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/user/test-number" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1 style="color: #5a189a;">🧪 {country_name}</h1>
        <a href="/user/test-number/download/{file_id}" class="btn" style="background: #fdb44b;">📥 تحميل الكل</a>
    </div>
    
    <div class="container">
        <div class="card">
            <h2><i class="fas fa-flag"></i> {country_name} - {len(numbers)} {t['numbers']}</h2>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr><th>#</th><th>{t['phone']}</th></tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
            {f'<p style="margin-top:15px; text-align:center; color:#9d4edd;"><i class="fas fa-ellipsis-h"></i> و {len(numbers)-200} رقم آخر...</p>' if len(numbers) > 200 else ''}
        </div>
    </div>
</body>
</html>
'''

@app.route('/user/test-number/download/<int:file_id>')
@login_required
def download_test_numbers(file_id):
    if is_client(session['user_id']):
        return redirect('/dashboard')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT country_name, numbers FROM test_number_files WHERE id = ?', (file_id,))
    result = cursor.fetchone()
    
    if result:
        country_name = result[0]
        numbers = json.loads(result[1])
        content = '\n'.join(numbers)
        response = make_response(content)
        response.headers['Content-Type'] = 'text/plain'
        response.headers['Content-Disposition'] = f'attachment; filename={country_name}_numbers.txt'
        
        log_activity(session['user_id'], 'download_test_numbers', f'Downloaded test numbers: {country_name}')
        return response
    
    return redirect('/user/test-number')
@app.route('/owner/add-number-test')
@owner_required
def owner_add_number_test_page():
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    
    cursor = db_conn.cursor()
    cursor.execute('SELECT id, country_name, numbers_count, created_at FROM test_number_files ORDER BY id DESC')
    files = cursor.fetchall()
    
    files_html = ''
    for f in files:
        files_html += f'''
            <tr>
                <td>{f[1]}</td>
                <td>{f[2]}</td>
                <td>{f[3][:16] if f[3] else ''}</td>
                <td>
                    <a href="/owner/delete-test-number/{f[0]}" class="btn btn-sm btn-danger" onclick="return confirm('{t['confirm_delete']}')">🗑️</a>
                </td>
            </tr>
        '''
    
    if not files_html:
        files_html = f'<tr><td colspan="4" style="text-align:center;">لا يوجد ملفات</td></tr>'
    
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
            <h2><i class="fas fa-upload"></i> {t['upload']} {t['test_number']}</h2>
            <form action="/owner/add-number-test" method="POST" enctype="multipart/form-data">
                <label><i class="fas fa-file"></i> {t['select_file']} (TXT/CSV):</label>
                <input type="file" name="file" accept=".txt,.csv" required>
                
                <label><i class="fas fa-flag"></i> {t['country_name']}:</label>
                <input type="text" name="country_name" placeholder="{t['example']}: Qatar" required>
                
                <label><i class="fas fa-calculator"></i> {t['numbers_count']}:</label>
                <input type="number" name="numbers_count" placeholder="{t['example']}: 1000" required>
                
                <button type="submit" class="btn btn-success">📤 {t['upload']}</button>
            </form>
        </div>
        
        <div class="card">
            <h2><i class="fas fa-list"></i> الملفات الحالية</h2>
            <table>
                <thead>
                    <tr>
                        <th>{t['country_name']}</th>
                        <th>{t['numbers_count']}</th>
                        <th>{t['date']}</th>
                        <th>{t['actions']}</th>
                    </tr>
                </thead>
                <tbody>{files_html}</tbody>
            </table>
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
        add_notification(session['user_id'], "🧪 تمت الإضافة", f"تمت إضافة {len(numbers)} رقم اختبار لـ {country_name}", "success")
    
    return redirect('/owner/add-number-test')

@app.route('/owner/delete-test-number/<int:file_id>')
@owner_required
def owner_delete_test_number(file_id):
    cursor = db_conn.cursor()
    cursor.execute('DELETE FROM test_number_files WHERE id = ?', (file_id,))
    db_conn.commit()
    
    log_activity(session['user_id'], 'delete_test_numbers', f'Deleted test numbers file ID: {file_id}')
    return redirect('/owner/add-number-test')
@app.route('/user/my-number')
@login_required
def user_my_number_page():
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = 'light'
    
    filter_file = request.args.get('file', 'all')
    
    if is_client(user_id):
        cursor = db_conn.cursor()
        if filter_file != 'all':
            cursor.execute('''
                SELECT cn.number, nf.display_name, cn.added_at, cn.file_id
                FROM client_numbers cn
                LEFT JOIN number_files nf ON cn.file_id = nf.id
                WHERE cn.client_id = ? AND nf.display_name = ?
                ORDER BY cn.added_at DESC
            ''', (user_id, filter_file))
        else:
            cursor.execute('''
                SELECT cn.number, nf.display_name, cn.added_at, cn.file_id
                FROM client_numbers cn
                LEFT JOIN number_files nf ON cn.file_id = nf.id
                WHERE cn.client_id = ?
                ORDER BY cn.added_at DESC
            ''', (user_id,))
        numbers = cursor.fetchall()
        
        cursor.execute('''
            SELECT DISTINCT nf.display_name
            FROM client_numbers cn
            JOIN number_files nf ON cn.file_id = nf.id
            WHERE cn.client_id = ?
            ORDER BY nf.display_name
        ''', (user_id,))
        available_files = [row[0] for row in cursor.fetchall()]
    else:
        cursor = db_conn.cursor()
        if filter_file != 'all':
            cursor.execute('''
                SELECT un.number, nf.display_name, un.added_at, un.file_id
                FROM user_numbers un
                LEFT JOIN number_files nf ON un.file_id = nf.id
                WHERE un.user_id = ? AND nf.display_name = ?
                ORDER BY un.added_at DESC
            ''', (user_id, filter_file))
        else:
            cursor.execute('''
                SELECT un.number, nf.display_name, un.added_at, un.file_id
                FROM user_numbers un
                LEFT JOIN number_files nf ON un.file_id = nf.id
                WHERE un.user_id = ?
                ORDER BY un.added_at DESC
            ''', (user_id,))
        numbers = cursor.fetchall()
        
        cursor.execute('''
            SELECT DISTINCT nf.display_name
            FROM user_numbers un
            JOIN number_files nf ON un.file_id = nf.id
            WHERE un.user_id = ?
            ORDER BY nf.display_name
        ''', (user_id,))
        available_files = [row[0] for row in cursor.fetchall()]
    
    numbers_count = len(numbers)
    
    if is_client(user_id):
        cursor.execute('''
            SELECT nf.display_name, COUNT(*) as count, cn.file_id
            FROM client_numbers cn
            LEFT JOIN number_files nf ON cn.file_id = nf.id
            WHERE cn.client_id = ?
            GROUP BY nf.display_name, cn.file_id
        ''', (user_id,))
    else:
        cursor.execute('''
            SELECT nf.display_name, COUNT(*) as count, un.file_id
            FROM user_numbers un
            LEFT JOIN number_files nf ON un.file_id = nf.id
            WHERE un.user_id = ?
            GROUP BY nf.display_name, un.file_id
        ''', (user_id,))
    file_stats_data = cursor.fetchall()
    
    file_stats = {}
    total_all_numbers = 0
    for row in file_stats_data:
        file_name = row[0] or t['unknown']
        count = row[1]
        file_id = row[2]
        file_stats[file_name] = {'count': count, 'file_id': file_id}
        total_all_numbers += count
    
    rows = ''
    for n in numbers:
        rows += f'''
            <tr>
                <td style="direction: ltr; font-family: monospace; font-size: 1.1rem;">{n[0]}</td>
                <td><span style="display: flex; align-items: center; gap: 5px;"><i class="fas fa-folder" style="color: #9d4edd;"></i>{n[1] or t['unknown']}</span></td>
                <td style="white-space: nowrap;">{n[2][:16] if n[2] else ''}</td>
            </tr>
        '''
    
    files_summary = ''
    for file_name, stats in file_stats.items():
        files_summary += f'''
            <div class="stat-card" style="text-align: center; cursor: pointer;" onclick="window.location.href='/user/my-number?file={file_name}'">
                <i class="fas fa-folder" style="font-size: 1.5rem; color: #9d4edd; margin-bottom: 8px;"></i>
                <h4 style="margin: 5px 0;">{file_name}</h4>
                <div class="number" style="font-size: 1.5rem;">{stats['count']}</div>
                <small>رقم</small>
                <div style="margin-top: 5px;"><span class="badge badge-success">{stats['count']}</span></div>
            </div>
        '''
    
    filter_options = '<option value="all">📋 جميع الملفات</option>'
    for file_name in available_files:
        selected = 'selected' if file_name == filter_file else ''
        filter_options += f'<option value="{file_name}" {selected}>📁 {file_name}</option>'
    
    page_title = f'أرقام ملف: {filter_file}' if filter_file != 'all' else 'جميع الأرقام'
    
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
        .header {{ background: #ffffff; border-bottom: 1px solid #e8e0f0; }}
        .main-stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 25px; }}
        .main-stat-card {{ background: linear-gradient(135deg, #9d4edd, #7b2cbf); color: white; padding: 20px; border-radius: 20px; text-align: center; }}
        .main-stat-card h3 {{ color: white; margin-bottom: 10px; font-size: 1rem; }}
        .main-stat-card .number {{ font-size: 2.5rem; font-weight: bold; }}
        .files-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 15px; margin: 20px 0; }}
        .table-wrapper {{ overflow-x: auto; border-radius: 16px; background: #ffffff; border: 1px solid #e8e0f0; max-height: 600px; overflow-y: auto; }}
        .numbers-table {{ width: 100%; border-collapse: collapse; min-width: 600px; }}
        .numbers-table th {{ background: #f8f5ff; padding: 14px 15px; font-weight: 600; color: #5a189a; border-bottom: 2px solid #d9c2f0; position: sticky; top: 0; z-index: 10; }}
        .numbers-table td {{ padding: 12px 15px; border-bottom: 1px solid #f0e8fa; }}
        .numbers-table tr:hover td {{ background: #fdfbff; }}
        .action-buttons {{ display: flex; gap: 10px; justify-content: center; margin-top: 20px; flex-wrap: wrap; }}
        .filter-section {{ display: flex; align-items: center; gap: 15px; margin-bottom: 20px; flex-wrap: wrap; }}
        .filter-select {{ padding: 10px 15px; border: 1px solid #d9c2f0; border-radius: 10px; background: #ffffff; color: #4a1d6e; font-size: 1rem; cursor: pointer; min-width: 250px; }}
        .filter-select:focus {{ outline: none; border-color: #9d4edd; }}
        .filter-badge {{ background: #9d4edd; color: white; padding: 8px 15px; border-radius: 10px; font-size: 0.9rem; }}
        .reset-filter {{ background: #f0e8fa; color: #5a189a; padding: 8px 15px; border-radius: 10px; text-decoration: none; font-size: 0.9rem; border: 1px solid #d9c2f0; }}
        .reset-filter:hover {{ background: #9d4edd; color: white; }}
        .stat-card:hover {{ transform: translateY(-3px); box-shadow: 0 8px 20px rgba(157, 78, 221, 0.15); transition: all 0.2s; }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1 style="color: #5a189a;">📱 {t['my_number']}</h1>
        <div></div>
    </div>
    
    <div class="container" style="max-width: 1400px;">
        <div class="main-stats">
            <div class="main-stat-card">
                <h3><i class="fas fa-database"></i> إجمالي الأرقام</h3>
                <div class="number">{total_all_numbers}</div>
            </div>
            <div class="main-stat-card" style="background: linear-gradient(135deg, #2cc185, #1a9e6a);">
                <h3><i class="fas fa-folder-open"></i> عدد الملفات</h3>
                <div class="number">{len(file_stats)}</div>
            </div>
        </div>
        
        <div class="card">
            <div class="filter-section">
                <i class="fas fa-filter" style="color: #9d4edd; font-size: 1.2rem;"></i>
                <span style="font-weight: 500;">فلترة حسب الملف:</span>
                <select class="filter-select" id="fileFilter" onchange="filterNumbers()">
                    {filter_options}
                </select>
                {f'<span class="filter-badge"><i class="fas fa-folder"></i> {filter_file}</span>' if filter_file != 'all' else ''}
                {f'<a href="/user/my-number" class="reset-filter"><i class="fas fa-times"></i> إلغاء الفلتر</a>' if filter_file != 'all' else ''}
            </div>
        </div>
        
        <div class="card">
            <h2 style="display: flex; align-items: center; gap: 10px;">
                <i class="fas fa-chart-pie"></i> توزيع الأرقام حسب الملفات
                <span style="font-size: 0.9rem; opacity: 0.7; margin-right: 10px;">(اضغط على أي ملف للفلترة)</span>
            </h2>
            <div class="files-grid">
                {files_summary if files_summary else f'<p>{t["no_files"]}</p>'}
            </div>
        </div>
        
        <div class="card" style="padding: 0; overflow: hidden;">
            <div style="padding: 20px; border-bottom: 1px solid #e8e0f0; display: flex; justify-content: space-between; align-items: center;">
                <h2 style="display: flex; align-items: center; gap: 10px; margin: 0;">
                    <i class="fas fa-list"></i>
                    {page_title} ({numbers_count})
                </h2>
                {f'<span style="color: #9d4edd;"><i class="fas fa-filter"></i> تمت الفلترة</span>' if filter_file != 'all' else ''}
            </div>
            
            <div class="table-wrapper" style="border: none; border-radius: 0;">
                <table class="numbers-table">
                    <thead>
                        <tr>
                            <th><i class="fas fa-phone"></i> {t['phone']}</th>
                            <th><i class="fas fa-folder"></i> {t['file']}</th>
                            <th><i class="far fa-calendar"></i> {t['date']}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows if rows else f'''
                        <tr>
                            <td colspan="3" style="text-align: center; padding: 50px;">
                                <i class="fas fa-phone-slash" style="font-size: 3rem; color: #d9c2f0; margin-bottom: 15px; display: block;"></i>
                                <p style="color: #8b6baf;">{t["no_numbers"]}</p>
                            </td>
                        </tr>
                        '''}
                    </tbody>
                </table>
            </div>
        </div>
        
        {f'''<div class="action-buttons">
            <a href="/user/add-number" class="btn btn-success"><i class="fas fa-plus"></i> {t['add_number']}</a>
        </div>''' if not is_client(user_id) else ''}
    </div>
    
    <script>
        function filterNumbers() {{
            const select = document.getElementById('fileFilter');
            const selectedFile = select.value;
            if (selectedFile === 'all') {{
                window.location.href = '/user/my-number';
            }} else {{
                window.location.href = '/user/my-number?file=' + encodeURIComponent(selectedFile);
            }}
        }}
    </script>
</body>
</html>
'''
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
    <style>
        .info-card {{
            background: linear-gradient(135deg, #0088cc, #006699);
            color: white;
            padding: 20px;
            border-radius: 20px;
            margin-bottom: 25px;
        }}
        .info-card h3 {{ color: white; margin-bottom: 10px; }}
        .queue-info {{
            background: #fdb44b;
            color: #1a1a2e;
            padding: 10px 15px;
            border-radius: 10px;
            display: inline-block;
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>🔗 {t['linking_channels']}</h1>
        <div></div>
    </div>
    
    <div class="container">
        <div class="info-card">
            <h3><i class="fab fa-telegram"></i> {t['link_channel']}</h3>
            <p>{t['forwarding_info']}</p>
            <span class="queue-info">
                <i class="fas fa-clock"></i> {t['queue_status']}: {queue_size} {t['messages_in_queue']}
            </span>
        </div>
        
        <div class="card">
            <h2><i class="fas fa-link"></i> {t['link_channel']}</h2>
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
                <tbody>{channels_html}</tbody>
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
@app.route('/support')
@login_required
def support_page():
    user_id = session['user_id']
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    theme = session.get('theme', 'dark')
    is_owner_or_admin = session.get('role') in ['owner', 'admin']
    
    cursor = db_conn.cursor()
    
    if is_owner_or_admin:
        cursor.execute('''
            SELECT DISTINCT u.id, u.username, u.role
            FROM users u
            WHERE u.id != ?
            ORDER BY u.username ASC
        ''', (user_id,))
        users = cursor.fetchall()
        
        users_html = ''
        for u in users:
            unread = get_unread_messages_count(u[0])
            badge = f' <span class="notification-badge">{unread}</span>' if unread > 0 else ''
            
            role_icon = {'owner': '👑', 'admin': '👑', 'test': '🧪', 'user': '👤'}.get(u[2], '👤')
            
            users_html += f'''
                <a href="/support/chat/{u[0]}" class="sidebar-item">
                    {role_icon} {u[1]}{badge}
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
</head>
<body>
    <div class="header">
        <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <h1>💬 {t['support']}</h1>
        <div></div>
    </div>
    
    <div class="container">
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
<html>
<head><title>{t['support']}</title>{get_base_style(theme)}</head>
<body>
    <div class="container"><div class="card"><p>{t['error']}</p></div></div>
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
    
    cursor.execute('SELECT username, role FROM users WHERE id = ?', (other_id,))
    other = cursor.fetchone()
    
    if other:
        role_icon = {'owner': '👑', 'admin': '👑', 'test': '🧪', 'user': '👤'}.get(other[1], '👤')
        other_name = f"{role_icon} {other[0]}"
    else:
        other_name = 'Unknown'
    
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
        messages_html += f'''
            <div style="
                max-width: 70%;
                margin: 10px 0;
                padding: 12px 16px;
                border-radius: 20px;
                background: {'#9d4edd' if is_sent else '#f0e8fa'};
                color: {'white' if is_sent else '#1a1a2e'};
                {'margin-right: auto;' if is_sent else 'margin-left: auto;'}
            ">
                <small style="opacity: 0.7; display: block; margin-bottom: 5px;">
                    <i class="fas fa-user"></i> {m[3]}
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
        .chat-header {{ display: flex; align-items: center; gap: 10px; }}
        .messages-area {{ display: flex; flex-direction: column; }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/support" class="back-btn"><i class="fas fa-arrow-right"></i> {t['back']}</a>
        <div class="chat-header">
            <h1>💬 {other_name}</h1>
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
#                      Server-Sent Events (SSE)
# ============================================================

sse_clients = {}

@app.route('/api/sse/connect/<int:user_id>')
@login_required
def sse_connect(user_id):
    """اتصال SSE للمستخدم"""
    def event_stream():
        q = queue.Queue()
        sse_clients[user_id] = q
        print(f'🔗 مستخدم {user_id} متصل بـ SSE')
        
        try:
            yield f"data: {json.dumps({'type': 'connected', 'message': 'تم الاتصال'})}\n\n"
            
            while True:
                try:
                    message = q.get(timeout=30)
                    yield f"data: {json.dumps(message)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            if user_id in sse_clients:
                del sse_clients[user_id]
                print(f'🔌 مستخدم {user_id} قطع اتصال SSE')
    
    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )

def notify_user_new_sms(user_id, data):
    """إرسال إشعار فوري للمستخدم عن طريق SSE"""
    if user_id in sse_clients:
        try:
            sse_clients[user_id].put({
                'type': 'new_sms',
                'data': data
            })
            print(f'📤 تم إرسال إشعار SSE للمستخدم {user_id}')
        except:
            pass
 # ============================================================
#                      API Routes
# ============================================================

@app.route('/api/sync')
def api_sync():
    """مزامنة الرسائل من تيليجرام"""
    global loop
    try:
        result = loop.run_until_complete(fetch_and_save_messages())
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/queue/status')
def api_queue_status():
    """حالة قائمة الانتظار"""
    return jsonify({'queue_size': len(message_queue)})

@app.route('/api/linked-channels/count')
def api_linked_channels_count():
    """عدد القنوات المرتبطة"""
    channels = get_all_active_linked_channels()
    return jsonify({'count': len(channels)})

@app.route('/api/admins/list')
@owner_required
def api_admins_list():
    """قائمة الأدمنز"""
    cursor = db_conn.cursor()
    cursor.execute('SELECT username, created_at FROM users WHERE role = "admin" ORDER BY id DESC')
    admins = [{'username': row[0], 'created_at': row[1]} for row in cursor.fetchall()]
    return jsonify({'admins': admins})

@app.route('/api/tests/list')
@owner_required
def api_tests_list():
    """قائمة حسابات Test"""
    cursor = db_conn.cursor()
    cursor.execute('SELECT username, created_at FROM users WHERE role = "test" ORDER BY id DESC')
    tests = [{'username': row[0], 'created_at': row[1]} for row in cursor.fetchall()]
    return jsonify({'tests': tests})

@app.route('/api/users/list')
@owner_required
def api_users_list():
    """قائمة جميع المستخدمين"""
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT id, username, whatsapp, is_blocked, number_limit, role, created_at
        FROM users 
        WHERE username != ?
        ORDER BY id DESC
    ''', (OWNER_USERNAME,))
    users = []
    for row in cursor.fetchall():
        cursor.execute('SELECT COUNT(*) FROM user_numbers WHERE user_id = ?', (row[0],))
        numbers_count = cursor.fetchone()[0]
        users.append({
            'id': row[0],
            'username': row[1],
            'whatsapp': row[2],
            'is_blocked': row[3],
            'number_limit': row[4],
            'role': row[5],
            'created_at': row[6],
            'numbers_count': numbers_count
        })
    return jsonify({'users': users})

@app.route('/api/stats')
@login_required
def api_stats():
    """إحصائيات النظام"""
    cursor = db_conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM messages')
    total_messages = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM user_numbers')
    total_numbers = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM linked_channels WHERE is_active = 1')
    active_channels = cursor.fetchone()[0]
    
    cursor.execute("SELECT value FROM stats WHERE key = 'last_sync'")
    last_sync = cursor.fetchone()
    last_sync_time = last_sync[0] if last_sync else None
    
    return jsonify({
        'total_users': total_users,
        'total_messages': total_messages,
        'total_numbers': total_numbers,
        'active_channels': active_channels,
        'queue_size': len(message_queue),
        'last_sync': last_sync_time
    })

@app.route('/api/notifications/unread')
@login_required
def api_unread_notifications():
    """عدد الإشعارات غير المقروءة"""
    user_id = session['user_id']
    count = get_unread_notifications_count(user_id)
    messages_count = get_unread_messages_count(user_id)
    return jsonify({
        'notifications': count,
        'messages': messages_count,
        'total': count + messages_count
    })

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def api_mark_notifications_read():
    """تحديد الإشعارات كمقروءة"""
    user_id = session['user_id']
    cursor = db_conn.cursor()
    cursor.execute('UPDATE notifications SET is_read = 1 WHERE user_id = ?', (user_id,))
    db_conn.commit()
    return jsonify({'success': True})

@app.route('/api/search/numbers')
@login_required
def api_search_numbers():
    """البحث عن رقم"""
    query = request.args.get('q', '')
    user_id = session['user_id']
    
    cursor = db_conn.cursor()
    
    if is_client(user_id):
        cursor.execute('''
            SELECT number FROM client_numbers 
            WHERE client_id = ? AND number LIKE ?
            LIMIT 50
        ''', (user_id, f'%{query}%'))
    else:
        cursor.execute('''
            SELECT number FROM user_numbers 
            WHERE user_id = ? AND number LIKE ?
            LIMIT 50
        ''', (user_id, f'%{query}%'))
    
    numbers = [row[0] for row in cursor.fetchall()]
    return jsonify({'numbers': numbers})

@app.route('/health')
def health():
    """فحص صحة النظام"""
    cursor = db_conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM messages')
    msg_count = cursor.fetchone()[0]
    channels_count = len(get_all_active_linked_channels())
    
    # فحص اتصال تيليجرام
    telegram_status = 'connected' if user_client and user_client.is_connected() else 'disconnected'
    bot_status = 'connected' if bot_client and bot_client.is_connected() else 'disconnected'
    
    return jsonify({
        'status': 'ok',
        'messages': msg_count,
        'linked_channels': channels_count,
        'queue_size': len(message_queue),
        'telegram': telegram_status,
        'bot': bot_status
    })

# ============================================================
#                      المسارات الأساسية
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
            
            if len(user) > 14 and user[14]:
                session['role'] = user[14]
            elif user[1] == OWNER_USERNAME:
                session['role'] = 'owner'
            else:
                session['role'] = 'user'
            
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
#                      معالجة الأخطاء
# ============================================================

@app.errorhandler(404)
def page_not_found(e):
    lang = session.get('lang', 'ar')
    t = LANGUAGES[lang]
    return f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>404 - {t['app_name']}</title>
    {get_base_style('light')}
</head>
<body>
    <div class="container" style="text-align: center; padding: 100px 20px;">
        <i class="fas fa-map-signs" style="font-size: 5rem; color: #d9c2f0; margin-bottom: 20px;"></i>
        <h1 style="font-size: 3rem; color: #5a189a;">404</h1>
        <p style="font-size: 1.2rem; margin-bottom: 30px;">الصفحة غير موجودة</p>
        <a href="/dashboard" class="btn">العودة للوحة التحكم</a>
    </div>
</body>
</html>
'''

@app.errorhandler(500)
def internal_error(e):
    return f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>500 - خطأ في السيرفر</title>
    {get_base_style('light')}
</head>
<body>
    <div class="container" style="text-align: center; padding: 100px 20px;">
        <i class="fas fa-exclamation-triangle" style="font-size: 5rem; color: #ff5e5e; margin-bottom: 20px;"></i>
        <h1 style="font-size: 3rem; color: #5a189a;">500</h1>
        <p style="font-size: 1.2rem; margin-bottom: 30px;">حدث خطأ في السيرفر</p>
        <a href="/dashboard" class="btn">العودة للوحة التحكم</a>
    </div>
</body>
</html>
'''

# ============================================================
#                      التشغيل
# ============================================================

def print_banner():
    print('=' * 60)
    print('   SELVA & OTP - Complete Advanced System')
    print('   النسخة النهائية مع Queue للإرسال السريع')
    print('   نظام الأدوار: Owner, Admin, Test, User, Client')
    print('=' * 60)

def cleanup():
    """تنظيف الموارد عند الخروج"""
    global db_conn, loop, user_client, bot_client
    
    print('\n🔄 جاري إغلاق الاتصالات...')
    
    if db_conn:
        db_conn.close()
        print('✅ تم إغلاق قاعدة البيانات')
    
    if loop:
        if user_client:
            loop.run_until_complete(user_client.disconnect())
        if bot_client:
            loop.run_until_complete(bot_client.disconnect())
        loop.close()
        print('✅ تم إغلاق اتصالات تيليجرام')

import signal

def signal_handler(sig, frame):
    print('\n👋 تم استلام إشارة إيقاف...')
    cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == '__main__':
    print_banner()
    
    # تهيئة تيليجرام
    try:
        init_telegram()
        print('✅ تم الاتصال بتليجرام')
        print('🔔 مراقبة الرسائل الجديدة وإعادة التوجيه مفعلة')
        print('🔄 نظام Queue يعمل في الخلفية')
        
        print('📥 جاري مزامنة الرسائل القديمة...')
        result = loop.run_until_complete(fetch_and_save_messages())
        if result['success']:
            print(f'✅ تمت المزامنة الأولية: {result["new_messages"]} رسالة')
        else:
            print(f'⚠️ فشلت المزامنة الأولية: {result.get("error", "خطأ غير معروف")}')
    except Exception as e:
        print(f'⚠️ تيليجرام غير متاح: {e}')
        print('📱 النظام سيعمل بدون مزامنة تيليجرام')
    
    # إحصائيات قاعدة البيانات
    cursor = db_conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    users_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM messages')
    messages_count = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM number_files')
    files_count = cursor.fetchone()[0]
    
    print('=' * 60)
    print('📊 إحصائيات النظام:')
    print(f'   👥 عدد المستخدمين: {users_count}')
    print(f'   💬 عدد الرسائل: {messages_count}')
    print(f'   📁 عدد الملفات: {files_count}')
    print('=' * 60)
    
    # تشغيل السيرفر
    try:
        port = 5000
        print(f'\n🌐 السيرفر يعمل على:')
        print(f'   🚀 http://127.0.0.1:{port}')
        print(f'   🚀 http://localhost:{port}')
        print(f'\n👑 بيانات المالك:')
        print(f'   👤 المستخدم: {OWNER_USERNAME}')
        print(f'   🔐 كلمة المرور: {OWNER_PASSWORD}')
        print(f'\n🤖 بيانات البوت:')
        print(f'   🤖 Token: {BOT_TOKEN[:20]}...')
        print('\n' + '=' * 60)
        print('اضغط CTRL+C لإيقاف السيرفر')
        print('=' * 60 + '\n')
        
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'\n❌ خطأ في تشغيل السيرفر: {e}')
    finally:
        cleanup()
        print('\n👋 تم إيقاف السيرفر بنجاح')
        sys.exit(0)
