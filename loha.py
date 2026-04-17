#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SELVA & OTP - Telegram Message Viewer with Permanent Archive
جميع الرسائل تبقى محفوظة حتى لو حذفت من القناة
"""

import sys
import asyncio
import sqlite3
import json
from datetime import datetime
from flask import Flask, jsonify, request, make_response
from telethon import TelegramClient, errors, events

# ============================================================
#                  الإعدادات - استبدل ببياناتك
# ============================================================

API_ID = 33437938  # ← استبدل بالـ api_id الخاص بك
API_HASH = '4aa02cced89e0eb1c509ac1f5336d5b7' 
CHANNEL_ID = -1003850394406  # ← تأكد من الإيدي الصحيح
AUTH_TYPE = 'user'  # ← 'user' أو 'bot'
BOT_TOKEN = ''  # ← ضع توكن البوت إذا اخترت 'bot'

# ============================================================
#                      قاعدة البيانات
# ============================================================

def init_database():
    """تهيئة قاعدة البيانات لتخزين الرسائل بشكل دائم"""
    conn = sqlite3.connect('messages_archive.db', check_same_thread=False)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            message_id INTEGER UNIQUE,
            text TEXT,
            date TEXT,
            saved_at TEXT,
            is_deleted INTEGER DEFAULT 0
        )
    ''')
    
    # جدول للإحصائيات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    conn.commit()
    return conn

db_conn = init_database()

def save_message_to_db(msg_id, text, date):
    """حفظ رسالة في قاعدة البيانات"""
    try:
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO messages (message_id, text, date, saved_at, is_deleted)
            VALUES (?, ?, ?, ?, 0)
        ''', (msg_id, text, date, datetime.now().isoformat()))
        db_conn.commit()
        return True
    except Exception as e:
        print(f"خطأ في حفظ الرسالة: {e}")
        return False

def mark_message_deleted(msg_id):
    """تحديد رسالة كمحذوفة (لكن تبقى في الأرشيف)"""
    try:
        cursor = db_conn.cursor()
        cursor.execute('''
            UPDATE messages SET is_deleted = 1 
            WHERE message_id = ?
        ''', (msg_id,))
        db_conn.commit()
        return True
    except:
        return False

def get_all_messages(limit=100):
    """جلب جميع الرسائل من الأرشيف"""
    cursor = db_conn.cursor()
    cursor.execute('''
        SELECT message_id, text, date, is_deleted 
        FROM messages 
        ORDER BY message_id DESC 
        LIMIT ?
    ''', (limit,))
    
    messages = []
    for row in cursor.fetchall():
        messages.append({
            'id': row[0],
            'text': row[1],
            'date': row[2],
            'deleted': bool(row[3])
        })
    return messages

def get_message_count():
    """عدد الرسائل في الأرشيف"""
    cursor = db_conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM messages')
    return cursor.fetchone()[0]

def sync_messages_from_telegram(messages):
    """مزامنة الرسائل من تيليجرام إلى قاعدة البيانات"""
    for msg in messages:
        if msg.message:
            save_message_to_db(msg.id, msg.message, msg.date.isoformat())
    
    # تحديث الإحصائية
    cursor = db_conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO stats (key, value) 
        VALUES ('last_sync', ?)
    ''', (datetime.now().isoformat(),))
    db_conn.commit()

# ============================================================
#                      النصوص متعددة اللغات
# ============================================================

TEXTS = {
    'ar': {
        'select_language': 'من فضلك اختار اللغة ✨🪐',
        'arabic': 'العربية',
        'english': 'English',
        'welcome': 'Please log in to the channels ✨👋',
        'main_channel': 'MAIN CHANNEL ✨🪐',
        'selva_otp': 'Selva & Otp ✨🪐',
        'check': 'Check ✅',
        'verified': 'تم التحقق ✓',
        'open_channels_first': 'يرجى فتح القناتين أولاً',
        'refresh': 'تحديث',
        'auto_refresh': 'تحديث تلقائي',
        'messages': 'رسالة',
        'copy': 'نسخ',
        'copied': 'تم النسخ!',
        'no_messages': 'لا توجد رسائل في الأرشيف',
        'loading': 'جاري تحميل الأرشيف...',
        'error': 'فشل الاتصال بالسيرفر',
        'footer': 'SELVA SYSTEM | الأرشيف الدائم',
        'archived': '📦 مؤرشفة',
        'deleted': '🗑️ محذوفة من القناة',
        'total_archived': 'إجمالي الرسائل المؤرشفة',
        'sync_now': 'مزامنة الآن'
    },
    'en': {
        'select_language': 'Please select a language ✨🪐',
        'arabic': 'العربية',
        'english': 'English',
        'welcome': 'Please log in to the channels ✨👋',
        'main_channel': 'MAIN CHANNEL ✨🪐',
        'selva_otp': 'Selva & Otp ✨🪐',
        'check': 'Check ✅',
        'verified': 'Verified ✓',
        'open_channels_first': 'Please open both channels first',
        'refresh': 'Refresh',
        'auto_refresh': 'Auto Refresh',
        'messages': 'Messages',
        'copy': 'Copy',
        'copied': 'Copied!',
        'no_messages': 'No messages in archive',
        'loading': 'Loading archive...',
        'error': 'Failed to connect',
        'footer': 'SELVA SYSTEM | Permanent Archive',
        'archived': '📦 Archived',
        'deleted': '🗑️ Deleted from channel',
        'total_archived': 'Total Archived Messages',
        'sync_now': 'Sync Now'
    }
}

# ============================================================
#                      الصفحات HTML
# ============================================================

def get_language_page():
    """صفحة اختيار اللغة"""
    return '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SELVA & OTP - Archive</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            background: linear-gradient(135deg, #0a0a1a 0%, #0d0d2b 50%, #050510 100%);
            font-family: 'Segoe UI', 'Cairo', sans-serif;
            color: #e0e0ff;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }

        .header { text-align: center; margin-bottom: 50px; }

        h1 {
            font-size: clamp(2.5rem, 10vw, 5rem);
            font-weight: 800;
            letter-spacing: 8px;
            text-transform: uppercase;
            text-shadow: 0 0 10px #9d4edd, 0 0 20px #7b2cbf, 0 0 40px #5a189a, 0 0 80px #3c096c;
            animation: flicker 3s infinite alternate;
        }

        @keyframes flicker {
            0%, 18%, 22%, 25%, 53%, 57%, 100% { text-shadow: 0 0 10px #9d4edd, 0 0 20px #7b2cbf, 0 0 40px #5a189a, 0 0 80px #3c096c; }
            20%, 24%, 55% { text-shadow: 0 0 5px #7b2cbf, 0 0 10px #5a189a; }
        }

        .subtitle {
            color: #c77dff;
            font-size: 1.5rem;
            margin-top: 20px;
            text-shadow: 0 0 10px #9d4edd;
        }

        .badge {
            background: rgba(157, 78, 221, 0.3);
            border: 1px solid #9d4edd;
            border-radius: 30px;
            padding: 5px 20px;
            margin-top: 15px;
            display: inline-block;
            font-size: 1rem;
        }

        .language-container {
            display: flex;
            gap: 30px;
            justify-content: center;
            flex-wrap: wrap;
            margin: 40px 0;
        }

        .lang-btn {
            background: rgba(20, 10, 40, 0.6);
            border: 3px solid #9d4edd;
            color: #e0aaff;
            padding: 25px 60px;
            font-size: 2rem;
            border-radius: 60px;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 0 30px #9d4edd66;
            font-weight: bold;
            backdrop-filter: blur(8px);
            text-decoration: none;
            display: inline-block;
        }

        .lang-btn:hover {
            background: #9d4edd;
            color: #0d0d1a;
            box-shadow: 0 0 50px #c77dff;
            transform: scale(1.1);
        }

        .footer {
            margin-top: 60px;
            color: #5a189a;
            text-shadow: 0 0 5px #3c096c;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>SELVA & OTP</h1>
        <div class="subtitle">من فضلك اختار اللغة ✨🪐<br>Please select a language ✨🪐</div>
        <div class="badge">
            <i class="fas fa-database"></i> الأرشيف الدائم | Permanent Archive
        </div>
    </div>

    <div class="language-container">
        <a href="/set-language/ar" class="lang-btn">العربية</a>
        <a href="/set-language/en" class="lang-btn">English</a>
    </div>

    <div class="footer">
        <i class="fas fa-bolt"></i> SELVA SYSTEM <i class="fas fa-bolt"></i>
    </div>
</body>
</html>
'''

def get_channels_page(lang='ar'):
    """صفحة القنوات"""
    t = TEXTS[lang]
    dir_attr = 'rtl' if lang == 'ar' else 'ltr'
    
    return f'''
<!DOCTYPE html>
<html lang="{lang}" dir="{dir_attr}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SELVA & OTP - Channels</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            background: linear-gradient(135deg, #0a0a1a 0%, #0d0d2b 50%, #050510 100%);
            font-family: 'Segoe UI', 'Cairo', sans-serif;
            color: #e0e0ff;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }}

        .header {{ text-align: center; margin-bottom: 30px; }}

        h1 {{
            font-size: clamp(2.5rem, 10vw, 4.5rem);
            font-weight: 800;
            letter-spacing: 8px;
            text-transform: uppercase;
            text-shadow: 0 0 10px #9d4edd, 0 0 20px #7b2cbf, 0 0 40px #5a189a, 0 0 80px #3c096c;
            animation: flicker 3s infinite alternate;
        }}

        @keyframes flicker {{
            0%, 18%, 22%, 25%, 53%, 57%, 100% {{ text-shadow: 0 0 10px #9d4edd, 0 0 20px #7b2cbf, 0 0 40px #5a189a, 0 0 80px #3c096c; }}
            20%, 24%, 55% {{ text-shadow: 0 0 5px #7b2cbf, 0 0 10px #5a189a; }}
        }}

        .welcome-text {{
            color: #c77dff;
            font-size: 1.8rem;
            margin: 30px 0;
            text-shadow: 0 0 15px #9d4edd;
        }}

        .channels-container {{
            display: flex;
            flex-direction: column;
            gap: 20px;
            margin: 30px 0;
            width: 90%;
            max-width: 500px;
        }}

        .channel-btn {{
            background: rgba(20, 10, 40, 0.7);
            border: 2px solid #9d4edd;
            color: #e0aaff;
            padding: 20px 30px;
            font-size: 1.4rem;
            border-radius: 50px;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 0 20px #9d4edd66;
            font-weight: bold;
            backdrop-filter: blur(8px);
            text-decoration: none;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 15px;
        }}

        .channel-btn:hover {{
            background: #9d4edd;
            color: #0d0d1a;
            box-shadow: 0 0 40px #c77dff;
            transform: scale(1.02);
        }}

        .channel-btn.clicked {{
            background: #9d4edd;
            color: #0d0d1a;
        }}

        .check-btn {{
            background: rgba(123, 44, 191, 0.8);
            border: 3px solid #c77dff;
            color: white;
            padding: 18px 40px;
            font-size: 1.6rem;
            border-radius: 50px;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 0 30px #9d4edd;
            font-weight: bold;
            backdrop-filter: blur(8px);
            margin-top: 20px;
        }}

        .check-btn:hover {{
            background: #c77dff;
            color: #0d0d1a;
            box-shadow: 0 0 50px #e0aaff;
            transform: scale(1.05);
        }}

        .verified-message {{
            background: rgba(0, 180, 100, 0.3);
            border: 2px solid #00ff88;
            color: #00ff88;
            padding: 15px 30px;
            border-radius: 40px;
            font-size: 1.3rem;
            margin: 20px 0;
            text-align: center;
            backdrop-filter: blur(8px);
        }}

        .footer {{
            margin-top: 50px;
            color: #5a189a;
            text-shadow: 0 0 5px #3c096c;
        }}

        .language-switch {{
            position: fixed;
            top: 20px;
            right: 20px;
        }}

        .lang-link {{
            color: #9d4edd;
            text-decoration: none;
            font-size: 1.1rem;
            padding: 10px 20px;
            border: 1px solid #9d4edd;
            border-radius: 30px;
            transition: all 0.3s;
            background: rgba(10, 5, 20, 0.6);
            backdrop-filter: blur(5px);
        }}

        .lang-link:hover {{
            background: #9d4edd;
            color: white;
        }}
    </style>
</head>
<body>
    <div class="language-switch">
        <a href="/set-language/{'en' if lang == 'ar' else 'ar'}" class="lang-link">
            <i class="fas fa-globe"></i> {'English' if lang == 'ar' else 'العربية'}
        </a>
    </div>

    <div class="header">
        <h1>SELVA & OTP</h1>
    </div>

    <div class="welcome-text">
        {t['welcome']}
    </div>

    <div class="channels-container">
        <a href="https://t.me/selva_card" target="_blank" class="channel-btn" id="channel1" onclick="markClicked(this)">
            <i class="fab fa-telegram"></i> {t['main_channel']}
        </a>
        <a href="https://t.me/otp_selva" target="_blank" class="channel-btn" id="channel2" onclick="markClicked(this)">
            <i class="fab fa-telegram"></i> {t['selva_otp']}
        </a>
    </div>

    <button class="check-btn" onclick="verifyChannels()">
        {t['check']}
    </button>
    
    <div id="verify-message"></div>

    <div class="footer">
        <i class="fas fa-bolt"></i> SELVA SYSTEM | الأرشيف الدائم <i class="fas fa-bolt"></i>
    </div>

    <script>
        let channel1Clicked = false;
        let channel2Clicked = false;
        
        function markClicked(el) {{
            el.classList.add('clicked');
            if (el.id === 'channel1') channel1Clicked = true;
            if (el.id === 'channel2') channel2Clicked = true;
        }}
        
        function verifyChannels() {{
            const msgDiv = document.getElementById('verify-message');
            
            if (channel1Clicked && channel2Clicked) {{
                document.cookie = "channels_verified=true; path=/; max-age=86400";
                
                msgDiv.className = 'verified-message';
                msgDiv.innerHTML = '<i class="fas fa-check-circle"></i> {t["verified"]}';
                
                setTimeout(() => {{
                    window.location.href = '/messages';
                }}, 1000);
            }} else {{
                alert('{t["open_channels_first"]}');
            }}
        }}
    </script>
</body>
</html>
'''

def get_messages_page(lang='ar'):
    """صفحة عرض الرسائل من الأرشيف"""
    t = TEXTS[lang]
    dir_attr = 'rtl' if lang == 'ar' else 'ltr'
    
    return f'''
<!DOCTYPE html>
<html lang="{lang}" dir="{dir_attr}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SELVA & OTP - Archive</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        * {{ box-sizing: border-box; }}
        
        body {{
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, #0a0a1a 0%, #0d0d2b 50%, #050510 100%);
            font-family: 'Segoe UI', 'Cairo', sans-serif;
            color: #e0e0ff;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}

        .header {{
            width: 100%;
            text-align: center;
            padding: 25px 0 15px;
            border-bottom: 1px solid #2a0a4a;
            box-shadow: 0 0 30px rgba(138, 43, 226, 0.3);
            background: rgba(10, 5, 20, 0.8);
            backdrop-filter: blur(5px);
            position: sticky;
            top: 0;
            z-index: 100;
        }}

        h1 {{
            font-size: clamp(2rem, 8vw, 3.5rem);
            font-weight: 800;
            letter-spacing: 5px;
            margin: 0;
            text-transform: uppercase;
            text-shadow: 0 0 10px #9d4edd, 0 0 20px #7b2cbf, 0 0 40px #5a189a;
            animation: flicker 3s infinite alternate;
        }}

        @keyframes flicker {{
            0%, 18%, 22%, 25%, 53%, 57%, 100% {{ text-shadow: 0 0 10px #9d4edd, 0 0 20px #7b2cbf, 0 0 40px #5a189a; }}
            20%, 24%, 55% {{ text-shadow: 0 0 5px #7b2cbf, 0 0 10px #5a189a; }}
        }}

        .archive-badge {{
            display: inline-block;
            background: rgba(0, 180, 100, 0.2);
            border: 1px solid #00ff88;
            color: #00ff88;
            padding: 4px 15px;
            border-radius: 20px;
            font-size: 0.8rem;
            margin-top: 5px;
        }}

        .language-switch {{
            position: fixed;
            top: 15px;
            right: 15px;
            z-index: 101;
        }}

        .lang-link {{
            color: #9d4edd;
            text-decoration: none;
            font-size: 0.9rem;
            padding: 6px 12px;
            border: 1px solid #9d4edd;
            border-radius: 30px;
            background: rgba(10, 5, 20, 0.6);
            backdrop-filter: blur(5px);
        }}

        .lang-link:hover {{
            background: #9d4edd;
            color: white;
        }}

        .status-bar {{
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 15px;
            margin: 15px 0;
            flex-wrap: wrap;
        }}

        .container {{
            width: 90%;
            max-width: 900px;
            margin: 10px 0 50px;
        }}

        .refresh-btn, .sync-btn {{
            background: rgba(20, 10, 40, 0.6);
            border: 2px solid #9d4edd;
            color: #e0aaff;
            padding: 10px 20px;
            font-size: 1rem;
            border-radius: 50px;
            cursor: pointer;
            box-shadow: 0 0 20px #9d4edd66;
            font-weight: bold;
            backdrop-filter: blur(8px);
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }}

        .sync-btn {{
            border-color: #00b894;
            box-shadow: 0 0 20px #00b89466;
        }}

        .refresh-btn:hover {{
            background: #9d4edd;
            color: #0d0d1a;
            box-shadow: 0 0 40px #c77dff;
        }}

        .sync-btn:hover {{
            background: #00b894;
            color: #0d0d1a;
            box-shadow: 0 0 40px #00ffaa;
        }}

        .auto-refresh {{
            display: flex;
            align-items: center;
            gap: 10px;
            color: #9d4edd;
        }}

        .auto-refresh input[type="checkbox"] {{
            accent-color: #9d4edd;
            width: 18px;
            height: 18px;
        }}

        .stats-bar {{
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }}

        .stat-item {{
            background: rgba(15, 8, 30, 0.7);
            padding: 8px 20px;
            border-radius: 30px;
            border: 1px solid #5a189a;
            backdrop-filter: blur(5px);
        }}

        .loading {{
            text-align: center;
            color: #9d4edd;
            font-size: 1.3rem;
            padding: 40px;
            animation: pulse 1.5s infinite;
        }}

        @keyframes pulse {{
            0% {{ opacity: 0.5; }}
            50% {{ opacity: 1; text-shadow: 0 0 20px #c77dff; }}
            100% {{ opacity: 0.5; }}
        }}

        .message-card {{
            background: rgba(15, 8, 30, 0.75);
            backdrop-filter: blur(10px);
            border-{'right' if lang == 'ar' else 'left'}: 4px solid #9d4edd;
            margin-bottom: 15px;
            padding: 15px 20px;
            border-radius: 12px;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.8);
            transition: all 0.25s;
            border: 1px solid #7b2cbf;
            animation: slideIn 0.3s ease-out;
            position: relative;
        }}

        .message-card.deleted {{
            border-{'right' if lang == 'ar' else 'left'}-color: #ff6b6b;
            opacity: 0.85;
        }}

        .message-card.deleted::after {{
            content: "{t['deleted']}";
            position: absolute;
            top: 10px;
            {'left' if lang == 'ar' else 'right'}: 10px;
            background: rgba(255, 50, 50, 0.3);
            color: #ff9999;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.7rem;
            border: 1px solid #ff4444;
        }}

        .message-card.archived::before {{
            content: "{t['archived']}";
            position: absolute;
            top: 10px;
            {'right' if lang == 'ar' else 'left'}: 10px;
            background: rgba(0, 180, 100, 0.2);
            color: #00ff88;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.7rem;
            border: 1px solid #00b894;
        }}

        .message-card:hover {{
            transform: translateX({'-5px' if lang == 'ar' else '5px'});
            box-shadow: 0 8px 25px #3c096c;
        }}

        @keyframes slideIn {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        .msg-header {{
            display: flex;
            justify-content: space-between;
            color: #c77dff;
            font-size: 0.8rem;
            margin: 25px 0 10px 0;
            padding-bottom: 8px;
            border-bottom: 1px dashed #5a189a;
            flex-wrap: wrap;
        }}

        .msg-text {{
            font-size: 1.1rem;
            line-height: 1.6;
            color: #f8f0ff;
            white-space: pre-wrap;
            word-break: break-word;
        }}

        .msg-actions {{
            display: flex;
            justify-content: flex-end;
            margin-top: 12px;
        }}

        .copy-btn {{
            background: rgba(123, 44, 191, 0.2);
            border: 1.5px solid #7b2cbf;
            color: #e0aaff;
            padding: 6px 16px;
            border-radius: 30px;
            cursor: pointer;
            font-size: 0.85rem;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            backdrop-filter: blur(5px);
        }}

        .copy-btn:hover {{
            background: #7b2cbf;
            color: white;
            box-shadow: 0 0 15px #9d4edd;
        }}

        .error-message {{
            background: rgba(255, 50, 50, 0.15);
            border-{'right' if lang == 'ar' else 'left'}: 4px solid #ff4444;
            color: #ff9999;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
        }}

        .footer {{
            margin-top: auto;
            padding: 20px;
            color: #5a189a;
            text-align: center;
            width: 100%;
            background: rgba(10, 5, 20, 0.5);
            backdrop-filter: blur(5px);
            border-top: 1px solid #2a0a4a;
        }}

        ::-webkit-scrollbar {{ width: 6px; }}
        ::-webkit-scrollbar-track {{ background: #0a0a1a; }}
        ::-webkit-scrollbar-thumb {{ background: #5a189a; border-radius: 3px; }}
    </style>
</head>
<body>
    <div class="language-switch">
        <a href="/set-language/{'en' if lang == 'ar' else 'ar'}" class="lang-link">
            <i class="fas fa-globe"></i> {'English' if lang == 'ar' else 'العربية'}
        </a>
    </div>

    <div class="header">
        <h1>SELVA & OTP</h1>
        <span class="archive-badge">
            <i class="fas fa-archive"></i> الأرشيف الدائم | Permanent Archive
        </span>
    </div>

    <div class="status-bar">
        <button class="refresh-btn" onclick="loadArchive()">
            <i class="fas fa-sync-alt"></i> {t['refresh']}
        </button>
        <button class="sync-btn" onclick="syncNow()">
            <i class="fas fa-cloud-download-alt"></i> {t['sync_now']}
        </button>
        <div class="auto-refresh">
            <label>
                <input type="checkbox" id="autoRefresh" onchange="toggleAutoRefresh()"> 
                <span>{t['auto_refresh']}</span>
            </label>
        </div>
    </div>

    <div class="stats-bar">
        <div class="stat-item" id="totalCount">
            <i class="fas fa-database"></i> <span id="msgCount">0</span> {t['messages']}
        </div>
        <div class="stat-item" id="syncStatus">
            <i class="fas fa-clock"></i> <span id="lastSync">--:--:--</span>
        </div>
    </div>

    <div class="container">
        <div id="content-area">
            <div class="loading">
                <i class="fas fa-spinner fa-pulse"></i> {t['loading']}
            </div>
        </div>
    </div>

    <div class="footer">
        <div>{t['footer']}</div>
        <div style="font-size:0.8rem; margin-top:10px;">
            <i class="fas fa-shield-alt"></i> الرسائل تبقى محفوظة حتى لو حذفت من القناة
        </div>
    </div>

    <script>
        let autoRefreshInterval = null;
        let messagesData = [];

        async function loadArchive() {{
            const area = document.getElementById('content-area');
            const refreshBtn = document.querySelector('.refresh-btn i');
            const originalIcon = refreshBtn.className;
            
            refreshBtn.className = 'fas fa-spinner fa-pulse';
            
            try {{
                const response = await fetch('/api/archive');
                const data = await response.json();
                
                messagesData = data.messages;
                document.getElementById('msgCount').textContent = data.total;
                document.getElementById('lastSync').textContent = data.last_sync || '--:--:--';
                
                if (messagesData.length === 0) {{
                    area.innerHTML = `<div class="error-message"><i class="fas fa-inbox"></i> {t['no_messages']}</div>`;
                    return;
                }}

                let html = '';
                messagesData.forEach(msg => {{
                    const date = new Date(msg.date);
                    const formattedDate = date.toLocaleString('{lang}-EG', {{
                        year: 'numeric', month: '2-digit', day: '2-digit',
                        hour: '2-digit', minute: '2-digit', second: '2-digit'
                    }});
                    
                    const cardClass = msg.deleted ? 'message-card deleted' : 'message-card archived';
                    
                    html += `<div class="${{cardClass}}" data-id="${{msg.id}}">
                        <div class="msg-header">
                            <span><i class="far fa-calendar-alt"></i> ${{formattedDate}}</span>
                            <span><i class="fas fa-hashtag"></i> ${{msg.id}}</span>
                        </div>
                        <div class="msg-text">${{escapeHtml(msg.text)}}</div>
                        <div class="msg-actions">
                            <button class="copy-btn" onclick="copyMessage(${{msg.id}})">
                                <i class="far fa-copy"></i> {t['copy']}
                            </button>
                        </div>
                    </div>`;
                }});
                
                area.innerHTML = html;
            }} catch (error) {{
                area.innerHTML = `<div class="error-message"><i class="fas fa-exclamation-triangle"></i> {t['error']}</div>`;
            }} finally {{
                refreshBtn.className = originalIcon;
            }}
        }}

        async function syncNow() {{
            const syncBtn = document.querySelector('.sync-btn i');
            const originalIcon = syncBtn.className;
            syncBtn.className = 'fas fa-spinner fa-pulse';
            
            try {{
                const response = await fetch('/api/sync');
                const data = await response.json();
                
                if (data.success) {{
                    loadArchive();
                }}
            }} catch (error) {{
                alert('فشل المزامنة');
            }} finally {{
                syncBtn.className = originalIcon;
            }}
        }}

        function escapeHtml(unsafe) {{
            if (!unsafe) return '';
            return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        }}

        function copyMessage(id) {{
            const message = messagesData.find(m => m.id === id);
            if (message) {{
                navigator.clipboard.writeText(message.text).then(() => {{
                    const btn = event.target.closest('.copy-btn');
                    const originalText = btn.innerHTML;
                    btn.innerHTML = '<i class="fas fa-check"></i> {t["copied"]}';
                    btn.style.background = '#00b894';
                    setTimeout(() => {{ btn.innerHTML = originalText; btn.style.background = ''; }}, 1500);
                }});
            }}
        }}

        function toggleAutoRefresh() {{
            const checkbox = document.getElementById('autoRefresh');
            if (checkbox.checked) {{
                autoRefreshInterval = setInterval(loadArchive, 5000);
            }} else {{
                if (autoRefreshInterval) clearInterval(autoRefreshInterval);
            }}
        }}

        window.onload = () => {{
            loadArchive();
            document.getElementById('autoRefresh').checked = true;
            toggleAutoRefresh();
        }};

        window.addEventListener('beforeunload', () => {{
            if (autoRefreshInterval) clearInterval(autoRefreshInterval);
        }});
    </script>
</body>
</html>
'''

# ============================================================
#                           تهيئة التطبيق
# ============================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = 'selva_otp_neon_secret_key'

client = None
loop = None

def get_language():
    lang = request.cookies.get('language', 'ar')
    return lang if lang in ['ar', 'en'] else 'ar'

async def login_user():
    global client
    print('\033[93m📱 جاري تسجيل الدخول...\033[0m')
    await client.start()
    me = await client.get_me()
    print(f'\033[92m✅ تم تسجيل الدخول كـ: {me.first_name}\033[0m')

async def login_bot():
    global client
    print('\033[93m🤖 جاري تسجيل الدخول كبوت...\033[0m')
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    print(f'\033[92m✅ تم تسجيل الدخول كبوت: @{me.username}\033[0m')

def init_telegram():
    global client, loop
    if client is None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        session_name = 'selva_user_session' if AUTH_TYPE == 'user' else 'selva_bot_session'
        client = TelegramClient(session_name, API_ID, API_HASH, loop=loop)
        if AUTH_TYPE == 'user':
            loop.run_until_complete(login_user())
        else:
            loop.run_until_complete(login_bot())

async def fetch_and_save_messages():
    """جلب الرسائل من تيليجرام وحفظها في الأرشيف"""
    global client
    try:
        entity = await client.get_entity(CHANNEL_ID)
        messages = await client.get_messages(entity, limit=100)
        
        count = 0
        for msg in messages:
            if msg.message:
                if save_message_to_db(msg.id, msg.message, msg.date.isoformat()):
                    count += 1
        
        # تحديث وقت آخر مزامنة
        cursor = db_conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO stats (key, value) 
            VALUES ('last_sync', ?)
        ''', (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
        db_conn.commit()
        
        return {'success': True, 'new_messages': count}
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ============================================================
#                           المسارات
# ============================================================

@app.route('/')
def index():
    if request.cookies.get('language'):
        return get_channels_page(get_language())
    return get_language_page()

@app.route('/set-language/<lang>')
def set_language(lang):
    if lang not in ['ar', 'en']:
        lang = 'ar'
    
    response = make_response('')
    response.set_cookie('language', lang, max_age=365*24*60*60)
    response.headers['Location'] = '/channels'
    response.status_code = 302
    return response

@app.route('/channels')
def channels():
    return get_channels_page(get_language())

@app.route('/messages')
def messages():
    lang = get_language()
    verified = request.cookies.get('channels_verified', 'false') == 'true'
    
    if not verified:
        response = make_response('')
        response.headers['Location'] = '/channels'
        response.status_code = 302
        return response
    
    return get_messages_page(lang)

@app.route('/api/archive')
def api_archive():
    """API لجلب الرسائل من الأرشيف"""
    try:
        messages = get_all_messages(100)
        
        cursor = db_conn.cursor()
        cursor.execute("SELECT value FROM stats WHERE key = 'last_sync'")
        last_sync = cursor.fetchone()
        
        return jsonify({
            'messages': messages,
            'total': len(messages),
            'last_sync': last_sync[0] if last_sync else None
        })
    except Exception as e:
        return jsonify({'messages': [], 'total': 0, 'error': str(e)})

@app.route('/api/sync')
def api_sync():
    """API لمزامنة الرسائل الجديدة من تيليجرام"""
    global loop
    try:
        result = loop.run_until_complete(fetch_and_save_messages())
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def print_banner():
    print('\033[95m╔══════════════════════════════════════════════════════════╗\033[0m')
    print('\033[95m║     SELVA & OTP - Permanent Archive System               ║\033[0m')
    print('\033[95m║         جميع الرسائل تبقى محفوظة للأبد 🗄️                 ║\033[0m')
    print('\033[95m╚══════════════════════════════════════════════════════════╝\033[0m')
    print('\033[96m  🚀 http://127.0.0.1:5000\033[0m')
    print('\033[92m  📦 قاعدة البيانات: messages_archive.db\033[0m')

if __name__ == '__main__':
    if API_ID == 12345678:
        print('\033[91m❌ خطأ: قم بتعيين api_id و api_hash من my.telegram.org\033[0m')
        sys.exit(1)
    
    init_telegram()
    print_banner()
    
    # مزامنة أولية عند التشغيل
    print('\033[93m📥 جاري مزامنة الرسائل الأولية...\033[0m')
    loop.run_until_complete(fetch_and_save_messages())
    print('\033[92m✅ تمت المزامنة الأولية!\033[0m')
    
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        print('\n\033[91m👋 تم إيقاف السيرفر\033[0m')
        db_conn.close()
        if loop:
            loop.close()
        sys.exit(0)