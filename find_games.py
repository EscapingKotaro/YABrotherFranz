#!/usr/bin/env python3
"""
Скрипт для проверки каталога CNDK перед заливом в Яндекс.

Режимы:
  1. Поиск:  python3 find_games.py search "gta"
  2. Детали: python3 find_games.py detail <sellable_position_id>
"""
import requests
import json
import sys

LOCAL_API_URL = "http://127.0.0.1:8090/api/sync/cndk-slots"
CHANNEL_ID = 15

BAD_INTENTS = [
    "filtered_out", "no_price", "variant_disabled", "variant_hidden",
    "product_disabled", "not_publishable", "delisted_confirmed"
]

# ============================================================================
# РЕЖИМ 1: ПОИСК С ПРОВЕРКОЙ "СУЕТЫ"
# ============================================================================
def search_mode(query: str):
    cursor = None
    page = 0
    found_games = []
    total_scanned = 0
    search_terms = [q.lower() for q in query.split(",")]
    
    print(f"🔍 Ищу: {search_terms}")
    print(f"📡 Канал: {CHANNEL_ID}\n")
    
    while True:
        page += 1
        params = {"channel_id": CHANNEL_ID, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        
        print(f"[Стр. {page}] ...", end=" ", flush=True)
        
        try:
            resp = requests.get(LOCAL_API_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"\n❌ Ошибка: {e}")
            break
        
        if not data.get("success"):
            print(f"\n❌ API ошибка: {data}")
            break
        
        slots = data.get("slots", [])
        total_scanned += len(slots)
        
        for slot in slots:
            name = slot.get("product_name", "").lower()
            variant = slot.get("product_variant_name", "").lower()
            
            if not any(t in name or t in variant for t in search_terms):
                continue
            
            # Проверяем "готовность"
            publish = slot.get("publish", False)
            target = slot.get("target")
            intent = slot.get("intent_reason")
            
            # Проверяем "суету" (контент)
            presentation = slot.get("presentation") or {}
            title = presentation.get("title", "")
            text = presentation.get("text", "")
            gallery = presentation.get("gallery", [])
            
            # Считаем картинки
            img_count = len(gallery)
            has_cover = any("cover" in (img.get("type", "") or "").lower() for img in gallery)
            has_screenshot = any("screenshot" in (img.get("type", "") or "").lower() for img in gallery)
            
            # Статус проверки
            review_status = slot.get("product_variant_review_status", "unknown")
            consoles = slot.get("product_variant_consoles", [])
            axis = slot.get("axis_values", {})
            
            # Оценка готовности
            issues = []
            if not publish:
                issues.append("❌ publish=False")
            if not target:
                issues.append("❌ нет цены")
            if intent in BAD_INTENTS:
                issues.append(f"❌ intent={intent}")
            if not title:
                issues.append("⚠️ нет title")
            if not text:
                issues.append("⚠️ нет описания")
            if img_count == 0:
                issues.append("🔥 НЕТ КАРТИНОК")
            elif img_count < 3:
                issues.append(f"⚠️ мало картинок ({img_count})")
            if review_status != "confirmed":
                issues.append(f"⚠️ review={review_status}")
            
            found_games.append({
                "id": slot.get("sellable_position_id"),
                "name": slot.get("product_name"),
                "variant": slot.get("product_variant_name"),
                "platform": axis.get("platform"),
                "tier": axis.get("tier"),
                "delivery": axis.get("delivery_type"),
                "price": f"{target['amount']} {target['currency']}" if target else None,
                "publish": publish,
                "intent": intent,
                "title": title[:50] + "..." if len(title) > 50 else title,
                "text_len": len(text),
                "img_count": img_count,
                "has_cover": has_cover,
                "has_screenshot": has_screenshot,
                "review": review_status,
                "consoles": consoles,
                "issues": issues,
            })
        
        print(f"скан: {len(slots)}, найдено: {len(found_games)}")
        
        next_cursor = data.get("next_cursor")
        if not next_cursor:
            print(f"\n✅ Конец каталога. Просмотрено: {total_scanned}")
            break
        cursor = next_cursor
    
    # === ВЫВОД РЕЗУЛЬТАТОВ ===
    print(f"\n{'='*90}")
    print(f"🎯 НАЙДЕНО: {len(found_games)}")
    print(f"{'='*90}\n")
    
    if not found_games:
        print("😔 Ничего не найдено. Попробуй другой запрос.")
        return
    
    # Сортируем: сначала готовые (без критических проблем), потом остальные
    def sort_key(g):
        critical = sum(1 for i in g["issues"] if i.startswith("❌") or "НЕТ КАРТИНОК" in i)
        return (critical, -g["img_count"])
    
    found_games.sort(key=sort_key)
    
    for g in found_games:
        # Цветовая индикация
        critical_issues = [i for i in g["issues"] if i.startswith("❌") or "НЕТ КАРТИНОК" in i]
        if not critical_issues:
            status = "✅ ГОТОВ К ЗАЛИВУ"
        elif len(critical_issues) <= 2:
            status = "⚠️  Частично готов"
        else:
            status = "❌ Не готов"
        
        print(f"{status}")
        print(f"  📦 ID: {g['id']}")
        print(f"  🎮 {g['name']}")
        print(f"  📝 Вариант: {g['variant']}")
        print(f"  🎯 {g['platform']} | {g['tier']} | {g['delivery']}")
        print(f"  💰 Цена: {g['price'] or 'НЕТ'}")
        print(f"  🖼  Картинки: {g['img_count']} (cover={g['has_cover']}, screens={g['has_screenshot']})")
        print(f"  📄 Title: '{g['title']}'")
        print(f"  📄 Описание: {g['text_len']} симв.")
        print(f"  🔍 Review: {g['review']} | Consoles: {g['consoles']}")
        if g["issues"]:
            print(f"  ⚡ Проблемы: {', '.join(g['issues'])}")
        print("-" * 90)
    
    # Итоговая статистика
    ready = sum(1 for g in found_games if not any(i.startswith("❌") or "НЕТ КАРТИНОК" in i for i in g["issues"]))
    print(f"\n📊 Итого: {ready} из {len(found_games)} готовы к заливке")
    print(f"💡 Для залива нужен: publish=True + цена + title + >=1 картинка")


# ============================================================================
# РЕЖИМ 2: ДЕТАЛИ ПО КОНКРЕТНОМУ ID
# ============================================================================
def detail_mode(sellable_position_id: str):
    print(f"🔍 Ищу детали для sellable_position_id={sellable_position_id}\n")
    
    cursor = None
    while True:
        params = {"channel_id": CHANNEL_ID, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        
        try:
            resp = requests.get(LOCAL_API_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return
        
        for slot in data.get("slots", []):
            if str(slot.get("sellable_position_id")) == str(sellable_position_id):
                print(json.dumps(slot, indent=2, ensure_ascii=False))
                return
        
        next_cursor = data.get("next_cursor")
        if not next_cursor:
            print(f"❌ ID {sellable_position_id} не найден в канале {CHANNEL_ID}")
            return
        cursor = next_cursor


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python3 find_games.py search <запрос>       # поиск (например: gta,ea sports fc)")
        print("  python3 find_games.py detail <ID>           # детали по sellable_position_id")
        sys.exit(1)
    
    mode = sys.argv[1].lower()
    
    if mode == "search":
        if len(sys.argv) < 3:
            print("❌ Укажи запрос: python3 find_games.py search gta")
            sys.exit(1)
        search_mode(sys.argv[2])
    elif mode == "detail":
        if len(sys.argv) < 3:
            print("❌ Укажи ID: python3 find_games.py detail 14303")
            sys.exit(1)
        detail_mode(sys.argv[2])
    else:
        print(f"❌ Неизвестный режим: {mode}")
        sys.exit(1)