const tg = window.Telegram.WebApp;

tg.ready();
tg.expand();

const API_URL = "https://insmart-mini-app-production.up.railway.app/api/offers";

async function loadOffers() {
    const container = document.querySelector(".container");

    try {
        const response = await fetch(API_URL);

        if (!response.ok) {
            throw new Error("Ошибка загрузки офферов");
        }

        const data = await response.json();

        document.querySelectorAll(".offer").forEach(element => {
            element.remove();
        });

        data.offers.forEach(offer => {
            const card = document.createElement("div");
            card.className = "offer";

            card.innerHTML = `
                <h2>${offer.name || "Предложение"}</h2>

                <div class="info">
                    <p>💵 Сумма:
                        <b>${formatAmount(offer.amountFrom)} – ${formatAmount(offer.amountTo)} ₽</b>
                    </p>

                    <p>📅 Срок:
                        <b>${offer.termFrom} – ${offer.termTo} дней</b>
                    </p>

                    <p>📈 Ставка:
                        <b>${offer.interestRate ?? "уточняется"}</b>
                    </p>
                </div>

                <button onclick="openOffer('${escapeHtml(offer.link || "")}')">
                    Оформить
                </button>
            `;

            container.appendChild(card);
        });

    } catch (error) {
        console.error(error);

        const errorMessage = document.createElement("p");
        errorMessage.textContent = "Не удалось загрузить предложения.";
        container.appendChild(errorMessage);
    }
}

function formatAmount(value) {
    if (value === null || value === undefined) {
        return "—";
    }

    return Number(value).toLocaleString("ru-RU");
}

function escapeHtml(value) {
    return String(value)
        .replace(/'/g, "\\'")
        .replace(/"/g, "&quot;");
}

function openOffer(link) {
    if (!link) {
        tg.showAlert("Ссылка на предложение недоступна.");
        return;
    }

    window.open(link, "_blank");
}

loadOffers();