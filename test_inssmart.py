import requests


URL = "https://api.inssmart.ru/v1/product-finance/offers"

TOKEN = input("Вставь Bearer token и нажми Enter: ")

headers = {
    "Authorization": TOKEN,
    "Accept": "application/json",
    "Origin": "https://partners.inssmart.ru",
    "Referer": "https://partners.inssmart.ru/",
}

params = {
    "startAt": 0,
    "maxResults": 25,
    "sortNulls": "true",
    "types[]": 3,
    "status": 1,
    "useRetention": "true",
}

response = requests.get(
    URL,
    params=params,
    headers=headers,
    timeout=20,
)

print("HTTP:", response.status_code)

if response.status_code != 200:
    print(response.text[:1000])
    raise SystemExit

data = response.json()

print("Всего офферов:", data.get("total"))
print("Получено:", len(data.get("items", [])))

print("\nПервые предложения:\n")

for offer in data.get("items", []):
    company = offer.get("company", {}).get(
        "name",
        offer.get("name", "Без названия")
    )

    product = offer.get("productInfo") or {}

    print(
        f"- {company} | "
        f"{product.get('amountFrom')}–{product.get('amountTo')} ₽ | "
        f"{product.get('creditTermFrom')}–{product.get('creditTermTo')} дней"
    )