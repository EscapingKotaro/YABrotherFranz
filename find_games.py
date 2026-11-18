#!/usr/bin/env python3
"""
Скрипт проходит по ВСЕМ страницам каталога CNDK и ищет игры по названию.
"""
import requests
import json
import sys

API_URL = "https://auto-posting.cyndykshop.su/api/v1/channels/15/positions"
API_KEY = "apm_6MO6lji_SfLwg8VqafXq07Zor2P2WzSkk-gcCwU-TLU"

# Что ищем (регистронезависимо)
SEARCH_TERMS = ["gta", "grand theft", "fifa", "ea sports fc", "fc 24", "fc 25", "fc 26"]

def search_all_slots():
    cursor = None
    page = 0
    found_games = []
    total_scanned = 0

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    while True:
        page += 1
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor

        print(f"[Страница {page}] Запрашиваю слоты...", end=" ", flush=True)

        try:
            response = requests.get(API_URL, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"\n❌ Ошибка запроса: {e}")
            break

        slots = data.get("slots", [])
        total_scanned += len(slots)

        # Ищем нужные игры
        for slot in slots:
            name = slot.get("product_name", "").lower()
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

        print(f"Просмотрено {len(slots)} слотов. Найдено совпадений: {len(found_games)}")

        # Проверяем, есть ли следующая страница
        next_cursor = data.get("next_cursor")
        if not next_cursor:
            print(f"\n✅ Достигли конца каталога. Всего просмотрено: {total_scanned} слотов")
            break

        cursor = next_cursor

    return found_games


if __name__ == "__main__":
    print(f"🔍 Ищу игры: {SEARCH_TERMS}")
    print(f"📡 API: {API_URL}\n")

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
