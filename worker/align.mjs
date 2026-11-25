import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { processAudiobook, emit, upgradeEpub, markup, ctcAlign } from "@storyteller-platform/align";

const [directory, language] = process.argv.slice(2);
const locale = new Intl.Locale(language);
const file = name => join(directory, name);
for (const name of ["processed", "emissions"]) await mkdir(file(name), {recursive: true});
console.log("Ton vorbereiten");
await processAudiobook(file("audio"), file("processed"), {parallelism: 1});
console.log("Sprachmodell auf der CPU ausführen");
await emit(file("processed"), file("emissions"), {engine: "ctc-local", device: "cpu", model: "quartznet15x5", language: locale, concurrency: 1});
console.log("Wörter markieren");
await upgradeEpub(file("source.epub"), file("upgraded.epub"), {removeNcx: false});
await markup(file("upgraded.epub"), file("marked.epub"), {granularity: "word", primaryLocale: locale});
console.log("Text und Ton zusammenführen");
await ctcAlign(file("marked.epub"), file("result.epub"), file("emissions"), file("processed"), {
    granularity: "word", primaryLocale: locale, textRef: "id-fragment", outFormat: "epub", autoExclude: true
});
