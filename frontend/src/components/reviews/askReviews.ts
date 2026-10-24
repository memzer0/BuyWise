import type { ReviewAspect, ReviewItem, Reviews } from "../../types/api";

/** "Ask the reviews": answers come only from the review data BuyWise already has – counts from the aspect analysis and
 *  verbatim sentences from real reviews. Nothing is generated, so nothing can be invented; when the reviews don't
 *  cover a question the answer says so. */

export interface Excerpt { review: ReviewItem; text: string; aspect: string | null; tone: "positive" | "negative" | "mixed" | "neutral" }
export interface ReviewAnswer {
  status: "answered" | "insufficient";
  lines: string[];
  caveat: string | null;
  excerpts: Excerpt[];
  aspects: string[];
}

const STOP = new Set(("a an and are as at be but by can do does did for from has have how i if in is it its me my of on or " +
  "so that the this to was what when which who why will with you your any about after all also am been being could " +
  "get got many much more most other people should than them then there these they those would really very just " +
  "phone product device buy buying worth good bad").split(" "));
const COMPLAINT_RE = /\b(complain\w*|problems?|issues?|cons|negatives?|downsides?|drawbacks?|faults?|wrong|hate|dislike)\b/i;
const PRAISE_RE = /\b(pros|positives?|praise\w*|like|love|best thing|strengths?)\b/i;
const USE_CASE_RE: [RegExp, string][] = [
  [/\b(gam(e|es|ing|er)|pubg|bgmi|fps)\b/i, "gaming"],
  [/\b(photo\w*|picture|camera work|shoot\w*|vlog\w*)\b/i, "photography"],
  [/\b(cod(e|ing|er)|programm\w*|developer|ide|compil\w*)\b/i, "coding"],
  [/\b(office|work|meetings?|calls?|zoom|excel|business)\b/i, "office"],
  [/\b(everyday|daily|day to day|normal use|regular use)\b/i, "everyday"],
];

const SENT_SPLIT = /(?<=[.!?])\s+|\n+/;
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const stem = (w: string) => w.replace(/(ing|ers|er|es|s)$/, "");

function hasKeyword(text: string, keys: string[]): boolean {
  const low = ` ${text.toLowerCase()} `;
  return keys.some((k) => new RegExp(`(?<![a-z])${esc(k.toLowerCase())}(?![a-z])`).test(low));
}

export function detectAspects(q: string, r: Reviews): string[] {
  const kw = r.aspect_keywords ?? {};
  return Object.keys(kw).filter((a) => hasKeyword(q, [a, ...kw[a]]));
}

export function detectUseCase(q: string): string | null {
  return USE_CASE_RE.find(([re]) => re.test(q))?.[1] ?? null;
}

function sentences(rv: ReviewItem): string[] {
  return [rv.title, rv.text].filter(Boolean).join(". ").split(SENT_SPLIT).map((s) => s.trim()).filter((s) => s.length >= 8);
}

function aspectLine(a: ReviewAspect | undefined, name: string, n: number): string {
  if (!a || a.mentions === 0) return `${name}: none of the ${n} reviews mention it.`;
  const parts = [`${a.positive} positive`, `${a.negative} negative`];
  if (a.mixed) parts.push(`${a.mixed} mixed`);
  const conf = a.confidence === "low" ? " – low confidence, too few reviews to call it a trend" : "";
  return `${name}: ${a.mentions} of ${n} reviews mention it (${parts.join(", ")})${conf}.`;
}

export function askReviews(question: string, r: Reviews, useCaseKey?: string | null): ReviewAnswer {
  const all = (r.reviews ?? []).filter((x) => x.counted !== false);
  const n = all.length;
  const q = question.trim();
  const byAspect = new Map((r.aspects ?? []).map((a) => [a.aspect, a]));
  const caveat = r.coverage && r.coverage.level !== "high" ? r.coverage.note : null;
  if (!q || n === 0) {
    return { status: "insufficient", lines: ["There are no written reviews to search for this product."], caveat: null, excerpts: [], aspects: [] };
  }

  const ucKey = detectUseCase(q) ?? (/\b(suit\w*|good for|use it for)\b/i.test(q) ? useCaseKey ?? null : null);
  const uc = ucKey ? r.use_cases?.find((u) => u.key === ucKey) : undefined;
  let aspects = detectAspects(q, r);
  if (uc && aspects.length === 0) aspects = uc.aspects.map((x) => x.aspect);
  const wantsNeg = COMPLAINT_RE.test(q);
  const wantsPos = !wantsNeg && PRAISE_RE.test(q);

  const lines: string[] = [];
  if (aspects.length) {
    if (uc) lines.push(`For ${uc.label.toLowerCase()}, the aspects that matter most are ${uc.aspects.map((x) => x.aspect.toLowerCase()).join(", ")}.`);
    aspects.slice(0, 5).forEach((a) => lines.push(aspectLine(byAspect.get(a), a, n)));
  } else if (wantsNeg || wantsPos) {
    const want = wantsNeg ? "complaint" : "praised";
    const hits = (r.aspects ?? []).filter((a) => a.stance === want);
    if (hits.length) {
      lines.push(wantsNeg ? `Recurring complaints in the ${n} reviews:` : `What reviewers praise most in the ${n} reviews:`);
      hits.slice(0, 4).forEach((a) => lines.push(aspectLine(a, a.aspect, n)));
      aspects = hits.map((a) => a.aspect);
    } else {
      lines.push(wantsNeg ? `No complaint comes up in more than one of the ${n} reviews.` : `No aspect is praised in more than one of the ${n} reviews.`);
    }
  }

  // Retrieve supporting sentences: aspect keywords first, then the question's own words.
  const terms = [...new Set(q.toLowerCase().match(/[a-z0-9]+/g) ?? [])].filter((w) => w.length >= 3 && !STOP.has(w)).map(stem);
  const kw = r.aspect_keywords ?? {};
  const scored: (Excerpt & { score: number })[] = [];
  for (const rv of all) {
    for (const s of sentences(rv)) {
      const hitAspect = aspects.find((a) => hasKeyword(s, [a, ...(kw[a] ?? [])])) ?? null;
      const words = new Set((s.toLowerCase().match(/[a-z0-9]+/g) ?? []).map(stem));
      const overlap = terms.filter((t) => words.has(t)).length;
      const score = (hitAspect ? 3 : 0) + overlap;
      if (score === 0) continue;
      const tone = hitAspect ? rv.aspect_sentiment?.[hitAspect] ?? "neutral" : rv.sentiment > 0 ? "positive" : rv.sentiment < 0 ? "negative" : "neutral";
      if (wantsNeg && tone !== "negative" && tone !== "mixed") continue;
      if (wantsPos && tone !== "positive" && tone !== "mixed") continue;
      scored.push({ review: rv, text: s, aspect: hitAspect, tone, score });
    }
  }
  scored.sort((a, b) => b.score - a.score);
  const excerpts: Excerpt[] = [];
  const seen = new Set<number>();
  for (const e of scored) {
    if (seen.has(e.review.id)) continue;          // one excerpt per review
    seen.add(e.review.id);
    excerpts.push({ review: e.review, text: e.text, aspect: e.aspect, tone: e.tone });
    if (excerpts.length === 5) break;
  }

  if (!lines.length) {
    if (!excerpts.length) {
      return { status: "insufficient", caveat: null, excerpts: [], aspects: [],
        lines: [`None of the ${n} available reviews mention this, so BuyWise can't answer it from reviews.`] };
    }
    lines.push(`${seen.size} of ${n} reviews mention this. Here is what they say:`);
  }
  const mentioned = aspects.some((a) => (byAspect.get(a)?.mentions ?? 0) > 0);
  const status = aspects.length && !mentioned && !excerpts.length ? "insufficient" : "answered";
  return { status, lines, caveat, excerpts, aspects };
}
