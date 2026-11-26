// Offsets refer to the original text. Audio timing can add boundaries inside a sentence.
function audilegePhraseBounds(text, start, end, offset, pauses = []) {
    const cuts = pauses.filter(at => at > start && at < end);
    const punctuation = /(?:[,;:]|[–—])(?:[»”"’)]*)\s+(?=\S)/gu;
    for (const match of text.slice(start, end).matchAll(punctuation)) {
        cuts.push(start + match.index + match[0].length);
    }
    let from = start, to = end;
    for (const cut of cuts) {
        if (cut <= offset) from = Math.max(from, cut);
        else to = Math.min(to, cut);
    }
    while (from < offset && /\s/u.test(text[from])) from++;
    while (to > offset + 1 && /\s/u.test(text[to - 1])) to--;
    return [from, to];
}
