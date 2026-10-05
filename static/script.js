document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
        if (!window.confirm(form.dataset.confirm)) {
            event.preventDefault();
        }
    });
});

document.querySelectorAll(".password-toggle").forEach(function (button) {
    button.addEventListener("click", function () {
        const passwordInput = document.getElementById(button.getAttribute("aria-controls"));
        if (!passwordInput) {
            return;
        }

        const isVisible = passwordInput.type === "text";
        passwordInput.type = isVisible ? "password" : "text";
        button.textContent = isVisible ? "Show" : "Hide";
        button.setAttribute("aria-pressed", String(!isVisible));
        button.setAttribute(
            "aria-label",
            isVisible ? "Show password" : "Hide password"
        );
    });
});
