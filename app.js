const tg = window.Telegram.WebApp;

tg.ready();

tg.expand();


function showOffer(name) {

    tg.showPopup({
        title: name,
        message: "Здесь будут подробные условия предложения.",
        buttons: [
            {
                id: "close",
                type: "close",
                text: "Закрыть"
            }
        ]
    });

}