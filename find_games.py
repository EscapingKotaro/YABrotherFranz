#!/usr/bin/env python3
"""
Скрипт проходит по ВСЕМ страницам каталога CNDK и ищет игры по названию,
НО показывает ТОЛЬКО те, которые реально готовы к публикации (есть цена и publish=True).
"""
import requests
import json

LOCAL_API_URL = "http://127.0.0.1:8090/api/sync/cndk-slots"
CHANNEL_ID = 15

SEARCH_TERMS = ["gta", "grand theft", "fifa", "ea sports fc", "fc 24", "fc 25", "fc 26", "fc 27"]
BAD_INTENTS = ["filtered_out", "no_price", "variant_disabled", "variant_hidden", "product_disabled", "not_publishable", "delisted_confirmed"]

def search_all_slots():
    cursor = None
    page = 0
    found_games = []
    total_scanned = 0
    
    while True:
        page += 1
        if page>=340:
            break
        params = {"channel_id": CHANNEL_ID, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        
        print(f"[Страница {page}] Запрашиваю слоты...", end=" ", flush=True)
        
        try:
            response = requests.get(LOCAL_API_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"\n❌ Ошибка запроса к локальному API: {e}")
            break
        
        if not data.get("success"):
            print(f"\n❌ API вернул ошибку: {data}")
            break
            
        slots = data.get("slots", [])
        total_scanned += len(slots)
        
        for slot in slots:
            name = slot.get("product_name", "").lower()
            variant_name = slot.get("product_variant_name", "").lower()
            
            # 1. Проверяем название
            if not any(term in name or term in variant_name for term in SEARCH_TERMS):
                continue
                
            # 2. 🔥 ЖЕСТКАЯ ФИЛЬТРАЦИЯ: Готов ли товар к продаже?
            if not slot.get("publish"):
                continue
            if not slot.get("target"): # Нет цены
                continue
            if slot.get("intent_reason") in BAD_INTENTS:
                continue
                
            # Если дошли сюда — товар годный!
            found_games.append({
                "sellable_position_id": slot.get("sellable_position_id"),
                "product_name": slot.get("product_name"),
                "variant_name": slot.get("product_variant_name"),
                "platform": slot.get("axis_values", {}).get("platform"),
                "tier": slot.get("axis_values", {}).get("tier"),
                "publish": slot.get("publish"),
                "intent_reason": slot.get("intent_reason"),
                "target": slot.get("target"),
            })
        
        print(f"Просмотрено {len(slots)} слотов. Найдено ГОТОВЫХ: {len(found_games)}")
        
        next_cursor = data.get("next_cursor")
        if not next_cursor:
            print(f"\n✅ Достигли конца каталога. Всего просмотрено: {total_scanned} слотов")
            break
        
        cursor = next_cursor
    
    return found_games

if __name__ == "__main__":
    print(f"🔍 Ищу игры: {SEARCH_TERMS}")
    print(f"⚠️ Показываю ТОЛЬКО те, где publish=True и есть цена (target)\n")
    
    results = search_all_slots()
    
    print(f"\n{'='*80}")
    print(f"🎯 НАЙДЕНО ГОТОВЫХ К ПРОДАЖЕ ИГР: {len(results)}")
    print(f"{'='*80}\n")
    
    if not results:
        print("😔 К сожалению, среди запрошенных игр сейчас нет ни одной с проставленной ценой и флагом publish=True.")
        print("💡 Совет: Попробуй поискать по другому названию или попроси админа CNDK проставить цены.")
    else:
        for game in results:
            print(f"✅ ГОТОВ К ЗАЛИВУ:")
            print(f"   📦 ID: {game['sellable_position_id']}")
            print(f"   🎮 Название: {game['product_name']} ({game['variant_name']})")
            print(f"   🎯 Платформа: {game['platform']} | Тир: {game['tier']}")
            print(f"   💰 Цена: {game['target']['amount']} {game['target']['currency']}")
            print("-" * 80)