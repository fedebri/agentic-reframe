const form = document.getElementById("exercise-form");
const choose = document.getElementById("choose-exercise");
const notice = document.getElementById("navigation-status");
let dirty = false;
let submitting = false;
let leaving = false;

for (const event of ["input", "change"]) {
    form.addEventListener(event, () => {
        dirty = true;
        const saved = document.getElementById("draft-saved-status");
        if (saved) saved.hidden = true;
    });
}
form.addEventListener("submit", () => { submitting = true; });
document.getElementById("exercise-select").addEventListener("change", () => {
    form.requestSubmit(choose);
});
choose.hidden = true;
const overview = document.getElementById("exercise-overview");
if (window.location.hash === "#exercise-overview") overview.open = true;
for (const link of document.querySelectorAll('a[href="#exercise-overview"]')) {
    link.addEventListener("click", () => { overview.open = true; });
}

// Save before leaving through the project selector, upload form, or a page link.
async function saveBeforeLeaving(continueNavigation) {
    if (leaving) return;
    leaving = true;
    const data = new FormData(form);
    const controls = [...form.elements].filter(control => !control.disabled);
    controls.forEach(control => { control.disabled = true; });
    notice.textContent = "Saving draft…";
    try {
        const response = await fetch(form.querySelector('button[formaction$="/draft"]').formAction, {
            method: "POST", body: data, headers: {Accept: "application/json"}
        });
        if (!response.ok) {
            notice.textContent = response.status === 409
                ? "This draft changed on another page or machine. Your edits remain here. Copy them before reloading to resolve the conflict."
                : "The draft could not be saved. Your edits remain here; retry Save draft before leaving.";
            leaving = false;
            return;
        }
        const saved = await response.json();
        document.getElementById("draft-version").value = saved.version;
        dirty = false;
        submitting = true;
        notice.textContent = "Draft saved.";
        continueNavigation();
    } catch {
        notice.textContent = "The draft could not be saved. Your edits remain here; check the connection and retry.";
        leaving = false;
    } finally {
        controls.forEach(control => { control.disabled = false; });
    }
}

for (const other of document.forms) {
    if (other === form) continue;
    other.addEventListener("submit", event => {
        if (!dirty || submitting) return;
        event.preventDefault();
        saveBeforeLeaving(() => other.requestSubmit(event.submitter));
    });
}
for (const link of document.querySelectorAll("a[href]")) {
    link.addEventListener("click", event => {
        if (!dirty || submitting || link.getAttribute("href").startsWith("#")
            || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        saveBeforeLeaving(() => window.location.assign(link.href));
    });
}
window.addEventListener("beforeunload", event => {
    if (dirty && !submitting) {
        event.preventDefault();
        event.returnValue = "";
    }
});
