import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
from googletrans import SyncTranslator
import translators as ts

# --- НАСТРОЙКИ ---
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "ВАШ_URL_ВЕБХУКА_ЗДЕСЬ").strip()
NEWS_URL = "https://www.wherewindsmeetgame.com/news/"
STATE_FILE = "sent_news.json"

translator = SyncTranslator()

def load_sent_news():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_sent_news(sent_set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(sent_set), f, ensure_ascii=False, indent=2)

def translate_text(text):
    if not text or not text.strip():
        return ""
    if len(text) > 4500:
        text = text[:4500] + "..."
        
    try:
        result = translator.translate(text, dest='ru')
        time.sleep(1)
        return result.text
    except Exception as e:
        print(f"⚠️ Google не смог перевести: {e}. Пробуем Bing...")
        
    try:
        result = ts.translate_text(text, translator='bing', from_language='en', to_language='ru')
        time.sleep(1)
        return result
    except Exception as e:
        print(f"❌ Bing тоже не смог перевести: {e}. Оставляем оригинал.")
        return text

def fetch_news_list():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(NEWS_URL, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        news_items = []
        for item in soup.select(".news_list li"):
            link_tag = item.find("a", class_="news")
            if not link_tag:
                continue
            
            title = link_tag.get("title") or link_tag.find("p", class_="news_tit").get_text(strip=True)
            url = link_tag.get("href")
            if url and url.startswith("/"):
                url = "https://www.wherewindsmeetgame.com" + url
            
            if url: # Защита: добавляем только если ссылка существует
                news_items.append({"id": url, "title": title, "url": url})
        return news_items
    except Exception as e:
        print(f"❌ Ошибка при получении списка новостей: {e}")
        return []

def fetch_article_details(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        content_div = soup.find("div", class_=re.compile(r"(article|content|detail|news_content|artText|news-detail|main-content)", re.I))
        
        if not content_div:
            content_div = soup.body
            if content_div:
                for script in content_div(["script", "style", "nav", "header", "footer"]):
                    script.decompose()

        image_url = None
        description_text = ""
        
        if content_div:
            for img_tag in content_div.find_all("img"):
                src = img_tag.get("src")
                if not src:
                    continue

                if src.startswith("//"):
                    src = "https:" + src
                elif src.startswith("/"):
                    src = "https://www.wherewindsmeetgame.com" + src
                elif not src.startswith("http"):
                    continue

                src_lower = src.lower()
                bad_words = ['icon', 'logo', 'share', 'btn', 'line', 'divider', 'arrow', 'sprite', 'bg_', 'avatar', 'social']
                if any(bad_word in src_lower for bad_word in bad_words):
                    continue

                width = img_tag.get("width")
                height = img_tag.get("height")
                
                if width and str(width).isdigit() and int(width) < 250:
                    continue
                if height and str(height).isdigit() and int(height) < 150:
                    continue

                image_url = src
                break 
            
            paragraphs = content_div.find_all("p")
            text_pieces = []
            
            if paragraphs:
                current_length = 0
                for p in paragraphs:
                    text = p.get_text(strip=True)
                    if text and len(text) > 15:
                        text_pieces.append(text)
                        current_length += len(text)
                    if current_length > 3500:
                        break
            else:
                raw_text = content_div.get_text(separator='\n', strip=True)
                lines = [line for line in raw_text.split('\n') if len(line) > 20]
                text_pieces = lines[:15]
            
            if text_pieces:
                description_text = "\n\n".join(text_pieces)
        
        return {"description": description_text, "image": image_url}
        
    except Exception as e:
        print(f"Ошибка при парсинге статьи {url}: {e}")
        return {"description": "", "image": None}

def send_to_discord(news_item, details):
    print(f"Перевод заголовка: {news_item['title']}")
    rus_title = translate_text(news_item["title"]).upper()
    
    if details["description"]:
        print("Перевод описания...")
        rus_desc = translate_text(details["description"])
    else:
        rus_desc = "Подробное описание доступно по ссылке ниже."
    
    if len(rus_desc) > 3800:
        rus_desc = rus_desc[:3800] + "\n\n**(Текст сокращен из-за лимитов Discord. Полная версия по ссылке ниже)**"
        
    rus_desc += f"\n\n**>> Подробнее (ENG):**\n{news_item['url']}"

    embed = {
        "title": rus_title,
        "description": rus_desc,
        "color": 0x2b2d31, 
    }

    if details.get("image"):
        embed["image"] = {"url": details["image"]}

    payload = {
        "username": "Where Winds Meet [RU]",
        "embeds": [embed]
    }
    
    # Отправляем сообщение по каждой ссылке из списка (поддержка нескольких вебхуков)
    if isinstance(WEBHOOK_URL, str) and ',' in WEBHOOK_URL:
        urls = [u.strip() for u in WEBHOOK_URL.split(',') if u.strip()]
    else:
        urls = [WEBHOOK_URL]

    for url in urls:
        try:
            response = requests.post(url, json=payload, timeout=15)
            if response.status_code == 429:
                retry_after = response.json().get("retry_after", 1)
                time.sleep(retry_after)
                response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
            print(f"✅ Успешно отправлено в канал: {url[:30]}...")
        except Exception as e:
            print(f"❌ Ошибка при отправке в канал {url[:30]}...: {e}")
        
        time.sleep(1)

def main():
    sent_ids = load_sent_news()
    news_list = fetch_news_list()
    
    # ЗАЩИТА: Если новостей не найдено (сайт заблокировал), НЕ перезаписываем файл
    if not news_list:
        print("⚠️ ВНИМАНИЕ: Не удалось получить новости с сайта (возможно, блокировка).")
        print("⚠️ Скрипт завершает работу, чтобы не стереть историю отправленных новостей.")
        return
        
    print(f"Найдено новостей на сайте: {len(news_list)}")
    print(f"Уже было отправлено ранее: {len(sent_ids)}")
    
    sent_anything = False
    for news in reversed(news_list):
        if news["id"] not in sent_ids:
            print(f"\n--- Новая новость: {news['title']} ---")
            details = fetch_article_details(news["url"])
            
            try:
                send_to_discord(news, details)
                sent_ids.add(news["id"])
                sent_anything = True
                time.sleep(3)
            except Exception as e:
                print(f"❌ Ошибка при отправке «{news['title']}»: {e}")
    
    # Сохраняем файл только если были отправлены новые новости или если список изменился
    if sent_anything:
        save_sent_news(sent_ids)
        print(f"\n💾 Файл sent_news.json обновлен. Всего в памяти: {len(sent_ids)} новостей.")
    else:
        print("\nℹ️ Новых новостей не найдено. Файл sent_news.json не изменен.")

if __name__ == "__main__":
    main()
