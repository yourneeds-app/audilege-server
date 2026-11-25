import { loadCtcModel, resolveCtcRun } from "@storyteller-platform/ghost-story";
import { ctcAlign } from "@storyteller-platform/align";

if (typeof ctcAlign !== "function") throw new Error("STAlign konnte nicht geladen werden.");
const run = resolveCtcRun({ device: "cpu", model: "quartznet15x5", language: "de" });
const model = await loadCtcModel(run, { autoInstall: true, printOutput: false });
try {
    const output = await model.compute([new Float32Array(Math.max(16000, model.minSamples))]);
    if (output.length !== 1) throw new Error("Das Sprachmodell liefert keine Ausgabe.");
} finally {
    await model[Symbol.asyncDispose]();
}
