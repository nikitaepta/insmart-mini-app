import os

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


INSSMART_URL = "https://api.inssmart.ru/v1/product-finance/offers"

INSSMART_TOKEN = os.getenv("INSSMART_TOKEN")


@app.get("/api/offers")
def get_offers():
    if not INSSMART_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="INSSMART_TOKEN не задан"
        )

    headers = {
        "Authorization": INSSMART_TOKEN,
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
        INSSMART_URL,
        params=params,
        headers=headers,
        timeout=20,
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail="Ошибка запроса к Inssmart"
        )

    data = response.json()

    offers = []

    for offer in data.get("items", []):
        product = offer.get("productInfo") or {}
        company = offer.get("company") or {}

        logo = None

        for attachment in offer.get("attachments", []):
            if attachment.get("type") == "mini":
                logo = attachment.get("link")
                break

        offers.append({
            "id": offer.get("id"),
            "name": company.get("name") or offer.get("name"),
            "amountFrom": product.get("amountFrom"),
            "amountTo": product.get("amountTo"),
            "termFrom": product.get("creditTermFrom"),
            "termTo": product.get("creditTermTo"),
            "interestRate": product.get("interestRate"),
            "description": offer.get("clientDescription"),
            "disclaimer": offer.get("disclaimer"),
            "conditions": offer.get("conditions"),
            "logo": logo,
            "link": offer.get("link"),
        })

    return {
        "total": data.get("total", 0),
        "offers": offers,
    }
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000
    )