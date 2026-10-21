const exerciseSelect = document.getElementById("exercise-select");
const exerciseInstructions = document.getElementById("exercise-instructions");
const interpretationFields = document.getElementById("interpretation-fields");
const drafts = new Map(Object.entries(JSON.parse(
    document.getElementById("saved-drafts").content.textContent
)));
const draftVersion = document.getElementById("draft-version");
const savedNotice = document.getElementById("draft-saved-status");
let currentExercise = exerciseSelect.value;

if (savedNotice) {
    interpretationFields.addEventListener("input", () => { savedNotice.hidden = true; });
}

exerciseSelect.addEventListener("change", () => {
    if (savedNotice) savedNotice.hidden = true;
    // Keep answers attached to their exercise when the questions change.
    const answers = Object.fromEntries(
        [...interpretationFields.querySelectorAll("textarea")].map(
            field => [field.name, field.value]
        )
    );
    answers.evidence = [...document.querySelectorAll('input[name="evidence"]:checked')].map(field => field.value);
    answers.context = [...document.querySelectorAll('input[name="context"]:checked')].map(field => field.value);
    answers.critic = document.querySelector('input[name="critic"]').checked;
    drafts.set(currentExercise, {data: answers, version: Number(draftVersion.value)});
    currentExercise = exerciseSelect.value;
    const content = document.getElementById(`instructions-${exerciseSelect.value}`);
    exerciseInstructions.querySelector("pre").textContent = content.content.textContent;
    exerciseInstructions.open = true;
    const prompts = document.getElementById(`interpretation-${currentExercise}`);
    interpretationFields.replaceChildren(prompts.content.cloneNode(true));
    if (drafts.has(currentExercise)) {
        for (const field of interpretationFields.querySelectorAll("textarea")) {
            field.value = drafts.get(currentExercise).data[field.name];
        }
        for (const name of ["evidence", "context"]) {
            for (const field of document.querySelectorAll(`input[name="${name}"]`)) {
                field.checked = drafts.get(currentExercise).data[name].includes(field.value);
            }
        }
        document.querySelector('input[name="critic"]').checked = drafts.get(currentExercise).data.critic;
    }
    draftVersion.value = drafts.get(currentExercise)?.version ?? 0;
    const title = currentExercise.replaceAll("_", " ");
    document.getElementById("interpretation-exercise").textContent = (
        title.charAt(0).toUpperCase() + title.slice(1)
    );
    for (const field of document.querySelectorAll('input[type="hidden"][name="exercise"]')) {
        field.value = currentExercise;
    }

    const url = new URL(window.location.href);
    url.searchParams.set("exercise", exerciseSelect.value);
    url.searchParams.delete("saved");
    url.hash = "exercise";
    window.history.replaceState(null, "", url);
});

document.getElementById("choose-exercise").hidden = true;
document.getElementById("exercise-draft-note").hidden = false;
