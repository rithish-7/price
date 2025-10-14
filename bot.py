# bot.py
import os
import requests
import json
import re
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from supabase import create_client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Telegram & Supabase setup ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")  # Use service role for RLS bypass

# Initialize Supabase client lazily
def get_supabase_client():
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return client
    except Exception as e:
        print(f"Error initializing Supabase client: {e}")
        return None

# --- Scraper Function ---
def get_flipkart_product_details(product_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(product_url, headers=headers)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        name_tag = soup.find("span", class_="VU-ZEz")
        product_name = name_tag.text.strip() if name_tag else "Name not found"

        price_tag = soup.find("div", class_="Nx9bqj CxhGGd")
        price = price_tag.text.strip() if price_tag else "Price not found"

        image_tag = soup.find("img", class_="DByuf4 IZexXJ jLEJ7H")
        if not image_tag:
            image_tag = soup.find("img", class_="DByuf4 R9zj5d _3pEy2q") or soup.find("img", class_="_396cs4 _2amPTt _3qGmMb")
        image_url = image_tag['src'] if image_tag and image_tag.has_attr('src') else None

        return {"product": product_name, "price": price, "image": image_url}
    except Exception as e:
        return {"error": str(e)}

# --- Affiliate Link Function ---
def get_affiliate_link(product_url):
    api_url = "https://ekaro-api.affiliaters.in/api/converter/public"
    payload = json.dumps({
        "deal": product_url,
        "convert_option": "convert_only"
    })
    headers = {
        'Authorization': f'Bearer {os.getenv("AFFILIATE_API_TOKEN")}',
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(api_url, headers=headers, data=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("data") or product_url
    except Exception as e:
        print(f"Affiliate link error: {e}")
        return product_url  # fallback

# --- Telegram Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a Flipkart product link to start tracking!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()
    user_id = update.message.from_user.id

    # Extract Flipkart URL
    match = re.search(r'(https?://(?:www\.)?(?:dl\.)?flipkart\.com[^\s]+)', message_text)
    if not match:
        await update.message.reply_text("Please send a valid Flipkart product URL.")
        return
    
    url = match.group(1)
    url = url.replace("://dl.", "://")
    await update.message.reply_text("Fetching product details...")

    # Scrape product info
    data = get_flipkart_product_details(url)
    if "error" in data:
        await update.message.reply_text(f"Error: {data['error']}")
        return

    # Convert to affiliate link
    affiliate_url = get_affiliate_link(url)

    # Save to Supabase (two-table design)
    try:
        supabase_client = get_supabase_client()
        if supabase_client:
            # Upsert product info into 'products' table
            supabase_client.table("products").upsert({
                "product_url": url,
                "affiliate_url": affiliate_url,
                "product_name": data["product"],
                "last_price": data["price"],
                "image_url": data["image"]
            }).execute()

            # Upsert user tracking into 'user_tracking' table
            supabase_client.table("user_tracking").upsert({
                "user_id": user_id,
                "product_url": url
            }).execute()

            print(f"Product '{data['product']}' tracked for user {user_id}")
        else:
            print("Database not available - product not saved")
    except Exception as e:
        print(f"Database error: {str(e)} - continuing without saving")

    # Send confirmation to user with affiliate link
    text = f"Added to tracking!\n\n*{data['product']}*\n\n*{data['price']}*\n[View Product]({affiliate_url})"
    if data["image"]:
        await update.message.reply_photo(photo=data["image"], caption=text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")

# --- Main Bot ---
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Bot is running...")
app.run_polling()
