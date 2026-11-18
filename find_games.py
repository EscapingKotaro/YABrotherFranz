#!/usr/bin/env python3
"""
Скрипт проходит по ВСЕМ страницам каталога через наш локальный API
и ищет игры по названию (GTA, FIFA и т.д.).
"""
import requests
import json

# Используем наш локальный API, который уже настроен на работу с CNDK
LOCAL_API_URL = "http://127.0.0.1:8090/api/sync/cndk-slots"
CHANNEL_ID = 15

# Что ищем (регистронезависимо)
SEARCH_TERMS = ["gta", "grand theft", "fifa", "ea sports fc", "fc 24", "fc 25", "fc 26"]

def search_all_slots():
    cursor = None
    page = 0
    found_games = []
    total_scanned = 0

    while True:
        page += 1
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
        abu=0

        # Ищем нужные игры
        for slot in slots:
            name = slot.get("product_name", "").lower()
            if abu==0:
                print(f"first name {name}")
                abu=1
            variant_name = slot.get("product_variant_name", "").lower()

            if any(term in name or term in variant_name for term in SEARCH_TERMS):
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

        print(f"Просмотрено {len(slots)} слотов. Всего найдено: {len(found_games)}")
        print(f"nex_cursor {data.get("next_cursor")}")

        # Проверяем, есть ли следующая страница
        next_cursor = data.get("next_cursor")
        if not next_cursor:
            print(f"\n✅ Достигли конца каталога. Всего просмотрено: {total_scanned} слотов")
            break

        cursor = next_cursor

    return found_games

if __name__ == "__main__":
    print(f"🔍 Ищу игры: {SEARCH_TERMS}")
    print(f"📡 Источник: {LOCAL_API_URL} (channel_id={CHANNEL_ID})\n")

    results = search_all_slots()

    print(f"\n{'='*80}")
    print(f"🎯 НАЙДЕНО ИГР: {len(results)}")
    print(f"{'='*80}\n")

    for game in results:
        print(f"📦 ID: {game['sellable_position_id']}")
        print(f"   Название: {game['product_name']}")
        print(f"   Вариант: {game['variant_name']}")
        print(f"   Платформа: {game['platform']} | Тир: {game['tier']}")
        print(f"   Publish: {game['publish']} | Intent: {game['intent_reason']}")
        print(f"   Цена (target): {game['target']}")
        print("-" * 80)
