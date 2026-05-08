#!/usr/bin/env python3
"""Build alicia_gonzalez_app_logs_news_dynamic_v1.json by adding ripple traces.

Reads:
  step4_app_log_synthesizer/data_samples/output_news_v1/alicia_gonzalez_app_logs_news_v1.json
  step4_app_log_synthesizer/data_samples/input/alicia_gonzalez_news_events_dynamic_v1.json

Writes:
  step4_app_log_synthesizer/data_samples/output_news_dynamic_v1/alicia_gonzalez_app_logs_news_dynamic_v1.json
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta

ROOT = "/Users/anmoltadikonda/PersonaBench"
SRC = f"{ROOT}/step4_app_log_synthesizer/data_samples/output_news_v1/alicia_gonzalez_app_logs_news_v1.json"
NEWS = f"{ROOT}/step4_app_log_synthesizer/data_samples/input/alicia_gonzalez_news_events_dynamic_v1.json"
OUT = f"{ROOT}/step4_app_log_synthesizer/data_samples/output_news_dynamic_v1/alicia_gonzalez_app_logs_news_dynamic_v1.json"


def tok(text_block: str) -> int:
    return math.ceil(len(text_block) / 4)


def serialize_filler(filler_sessions):
    parts = []
    for s in filler_sessions:
        for m in s["messages"]:
            parts.append(m["text"])
    return "\n".join(parts)


def serialize_meaningful(meaningful_sessions):
    parts = []
    for s in meaningful_sessions:
        for m in s["messages"]:
            parts.append(m["text"])
    return "\n".join(parts)


def main():
    with open(SRC) as f:
        log = json.load(f)
        # snapshot original filler text + token stats for delta-based recompute
    with open(SRC) as f:
        original = json.load(f)
    with open(NEWS) as f:
        news = json.load(f)

    log_window_end = log["log_window"]["end_date"]

    fs = log["messenger"]["filler_sessions"]
    news_touched_ids = {s["referenced_in_session_id"] for s in log["surprises_woven"]}

    by_date = defaultdict(list)
    for s in fs:
        by_date[s["date"]].append(s)

    def find_candidate(event_date_str, contacts, days_after=range(1, 8), used=set()):
        d = datetime.strptime(event_date_str, "%Y-%m-%d")
        for delta in days_after:
            cd = (d + timedelta(days=delta)).strftime("%Y-%m-%d")
            if cd > log_window_end:
                continue
            for s in by_date.get(cd, []):
                if s["session_id"] in news_touched_ids or s["session_id"] in used:
                    continue
                if s["contact"] in contacts:
                    return s
        return None

    used_ids = set()
    new_surprises = []

    def msgs(*tuples):
        return [{"time": t, "sender": s, "text": txt} for (t, s, txt) in tuples]

    plans = []

    plans.append(dict(
        nid="N-001", date="2026-03-03", contacts=["Priya Raman"],
        topic="Mistral Small 4 follow-up benchmarks", style="follow_up",
        build=lambda other: msgs(
            ("10:14", "Alicia", "ok ran Mistral Small 4 against our narrative eval set"),
            ("10:16", other,    "and?"),
            ("10:18", "Alicia", "decent on coherence, weaker on long-arc consistency vs the gpt baseline"),
            ("10:21", other,    "matches what their card claimed honestly"),
            ("10:23", "Alicia", "not dropping the backbone over it but worth a row in the table"),
        ),
    ))

    plans.append(dict(
        nid="N-002", date="2026-03-04", contacts=["Sofia Delgado"],
        topic="post-burn AQI recheck before run", style="logistics",
        build=lambda other: msgs(
            ("07:42", "Alicia", "AQI in upper park is back to 38 this morning"),
            ("07:45", other,    "ok green light then?"),
            ("07:47", "Alicia", "yeah I'll do the loop, bringing the inhaler in the running belt anyway"),
            ("07:50", other,    "smart. text me when you're back at the car"),
            ("07:52", "Alicia", "will do"),
        ),
    ))

    plans.append(dict(
        nid="N-003", date="2026-03-05", contacts=["Priya Raman"],
        topic="GPT-5.4 1M-context ripple on eval plan", style="follow_up",
        build=lambda other: msgs(
            ("13:11", "Alicia", "thinking about whether the 1M context changes our long-doc baseline at all"),
            ("13:14", other,    "you'd basically be retiring the chunked-retrieval comparison"),
            ("13:16", "Alicia", "not retiring, just adding a column. don't want to redo all the prompts"),
            ("13:19", other,    "fair. one column, one footnote"),
            ("13:21", "Alicia", "exactly. lazy science good science"),
        ),
    ))

    plans.append(dict(
        nid="N-004", date="2026-03-07", contacts=["Sofia Delgado"],
        topic="post-race trail conditions", style="logistics",
        build=lambda other: msgs(
            ("09:02", "Alicia", "ran the lower park loop and there's still a bunch of cones up by the finish line"),
            ("09:05", other,    "they're slow about pulling those, give it til Tuesday"),
            ("09:08", "Alicia", "I'll just go around. legs are fine, calves are not"),
            ("09:11", other,    "post-race calves are humbling"),
            ("09:13", "Alicia", "lol yes"),
        ),
    ))

    plans.append(dict(
        nid="N-005", date="2026-03-08", contacts=["Elena Gonzalez", "Valentina Restrepo"],
        topic="Colombia primary follow-up after results", style="follow_up",
        build=lambda other: msgs(
            ("19:08", "Alicia", "viste los resultados del primary?"),
            ("19:11", other,    "si, mas o menos lo que esperabamos"),
            ("19:13", "Alicia", "abuela esta tranquila? no quiero que se ponga ansiosa"),
            ("19:16", other,    "ella esta bien, mas preocupada por la tos del gato del vecino jaja"),
            ("19:18", "Alicia", "clasico abuela"),
        ),
    ))

    plans.append(dict(
        nid="N-006", date="2026-03-11", contacts=["Mateo Gonzalez"],
        topic="Kings elimination bet payout ripple", style="follow_up",
        build=lambda other: msgs(
            ("21:04", other,    "venmo me my $20 already"),
            ("21:06", "Alicia", "I sent it. with the saddest emoji I could find"),
            ("21:08", other,    "I will frame this transaction"),
            ("21:10", "Alicia", "bet's off the books. next year I'm taking the under day one"),
            ("21:13", other,    "wise"),
        ),
    ))

    plans.append(dict(
        nid="N-007", date="2026-03-12", contacts=["Sofia Delgado"],
        topic="trail reopen check after second-wave burn", style="logistics",
        build=lambda other: msgs(
            ("16:33", "Alicia", "any word on whether the upper trails reopen by Saturday?"),
            ("16:36", other,    "rangers said Friday afternoon if winds cooperate"),
            ("16:38", "Alicia", "ok keeping Table Mtn as plan B then"),
            ("16:41", other,    "yes. I'll text by Friday 5pm with the call"),
            ("16:43", "Alicia", "perfect"),
        ),
    ))

    plans.append(dict(
        nid="N-008", date="2026-03-15", contacts=["Sofia Delgado"],
        topic="purifier filter swap after heat/wind", style="follow_up",
        build=lambda other: msgs(
            ("11:21", "Alicia", "ordered a replacement HEPA for the Coway, the old one was crunchy"),
            ("11:24", other,    "good call. mine was last changed during the Park fire era"),
            ("11:26", "Alicia", "yikes. I'll bring a spare to your place too"),
            ("11:28", other,    "you're a saint"),
            ("11:30", "Alicia", "I am medium-saint, I want trail mix in return"),
        ),
    ))

    plans.append(dict(
        nid="N-009", date="2026-03-17", contacts=["Priya Raman"],
        topic="nano cost ripple for prototype loop", style="follow_up",
        build=lambda other: msgs(
            ("15:02", "Alicia", "swapped nano in for the inner-loop scoring step, cost dropped like 80%"),
            ("15:05", other,    "quality?"),
            ("15:07", "Alicia", "indistinguishable on the small eval. need to run on the real eval set tonight"),
            ("15:09", other,    "exciting. do it"),
            ("15:11", "Alicia", "queueing now"),
        ),
    ))

    plans.append(dict(
        nid="N-010", date="2026-03-20", contacts=["Priya Raman"],
        topic="Maker Radio recap to Priya", style="screenshot",
        build=lambda other: msgs(
            ("18:44", "Alicia", "[photo] this kid had a Pi-zero theremin you could detune with a foot pedal"),
            ("18:47", other,    "okay that's sick. did you talk to them"),
            ("18:50", "Alicia", "got their IG, they want to do an arts walk demo in May"),
            ("18:52", other,    "you collect makers like pokemon"),
            ("18:54", "Alicia", "gotta catch em all"),
        ),
    ))

    plans.append(dict(
        nid="N-011", date="2026-03-22", contacts=["Elena Gonzalez", "Valentina Restrepo"],
        topic="Medellin trip safety follow-up", style="follow_up",
        build=lambda other: msgs(
            ("20:11", "Alicia", "estuve pensando en el itinerario de Medellin"),
            ("20:14", other,    "que estabas pensando?"),
            ("20:16", "Alicia", "nada de salir sola por la noche, Uber siempre, y le mando a alguien la ubicacion"),
            ("20:19", other,    "eso es lo basico mija. yo te mando los nombres de los barrios que tu prima dijo que evites"),
            ("20:21", "Alicia", "gracias mama"),
        ),
    ))

    plans.append(dict(
        nid="N-012", date="2026-03-22", contacts=["Sofia Delgado"],
        topic="Table Mountain wildflower follow-up parking", style="logistics",
        build=lambda other: msgs(
            ("08:14", "Alicia", "btw the Table Mtn lot was full by 9 last weekend per Reddit"),
            ("08:17", other,    "we should leave Chico by 7:45 then"),
            ("08:19", "Alicia", "ugh ok. I'll prep coffee the night before"),
            ("08:21", other,    "I'll bring the bagels"),
            ("08:23", "Alicia", "deal"),
        ),
    ))

    plans.append(dict(
        nid="N-013", date="2026-03-24", contacts=["Priya Raman"],
        topic="Chico State AI MS lunch debate", style="follow_up",
        build=lambda other: msgs(
            ("12:32", "Alicia", "lunch table today was 80% the new MS thing"),
            ("12:35", other,    "predictable. who's pro, who's con"),
            ("12:37", "Alicia", "tenure-tracks pro, lecturers nervous, the dean smiling at nothing in particular"),
            ("12:40", other,    "lol classic dean energy"),
            ("12:42", "Alicia", "I just want to know who's teaching the methods sequence"),
        ),
    ))

    plans.append(dict(
        nid="N-014", date="2026-03-27", contacts=["Priya Raman"],
        topic="Sunday call on OpenAI deal pushback", style="follow_up",
        build=lambda other: msgs(
            ("17:01", other,    "still on for the Sunday call?"),
            ("17:03", "Alicia", "yes. I want to hear if your dept is signing anything"),
            ("17:06", other,    "we got a draft MOU last week, nobody loves it"),
            ("17:08", "Alicia", "ours too. the indemnity language is wild"),
            ("17:11", other,    "Sunday 4pm my time?"),
            ("17:13", "Alicia", "perfect"),
        ),
    ))

    plans.append(dict(
        nid="N-015", date="2026-03-28", contacts=["Sofia Delgado", "Elena Gonzalez"],
        topic="post-storm trail mud assessment", style="logistics",
        build=lambda other: msgs(
            ("10:18", "Alicia", "trails gonna be a swamp through midweek"),
            ("10:21", other,    "yep. I rerouted Saturday to lower park paved"),
            ("10:23", "Alicia", "good. boots are still drying from last time"),
            ("10:25", other,    "lay them in the sun, stuff with newspaper"),
            ("10:27", "Alicia", "old school. I love it"),
        ),
    ))

    plans.append(dict(
        nid="N-016", date="2026-03-28", contacts=["Sofia Delgado"],
        topic="Charliefest donation receipt", style="logistics",
        build=lambda other: msgs(
            ("09:33", "Alicia", "donation receipt came thru, I forwarded it"),
            ("09:36", other,    "got it, thanks. I'll match what you put in"),
            ("09:38", "Alicia", "you don't have to"),
            ("09:41", other,    "I want to. it was a great night"),
            ("09:43", "Alicia", "ok ok. thank you"),
        ),
    ))

    plans.append(dict(
        nid="N-017", date="2026-03-28", contacts=["Sofia Delgado"],
        topic="Hot Buttered Rum post-show photo", style="screenshot",
        build=lambda other: msgs(
            ("23:51", "Alicia", "[photo] Ben got pulled on stage for the encore"),
            ("23:54", other,    "STOP that's amazing"),
            ("23:56", "Alicia", "he's grinning like a kid. I'm dying"),
            ("23:58", other,    "frame this. seriously"),
            ("00:01", "Alicia", "already did mentally"),
        ),
    ))

    plans.append(dict(
        nid="N-018", date="2026-03-30", contacts=["Mateo Gonzalez"],
        topic="Elite Eight bracket update", style="follow_up",
        build=lambda other: msgs(
            ("19:22", other,    "well Texas killed my bracket"),
            ("19:25", "Alicia", "told you not to take Michigan past elite 8"),
            ("19:27", other,    "I take notes from a chaos algorithm"),
            ("19:29", "Alicia", "explains a lot about your portfolio"),
            ("19:31", other,    "ok ok"),
        ),
    ))

    plans.append(dict(
        nid="N-019", date="2026-04-01", contacts=["Sofia Delgado"],
        topic="Magnolia Place post-show debrief", style="follow_up",
        build=lambda other: msgs(
            ("22:44", "Alicia", "the second act was the whole show honestly"),
            ("22:47", other,    "the porch scene? unreal"),
            ("22:49", "Alicia", "exactly. I want to send the playwright a note"),
            ("22:51", other,    "do it. they read those"),
            ("22:53", "Alicia", "ok composing in my head"),
        ),
    ))

    plans.append(dict(
        nid="N-020", date="2026-04-04", contacts=["Sofia Delgado"],
        topic="post wildflower walk plant ID", style="screenshot",
        build=lambda other: msgs(
            ("14:18", "Alicia", "[photo] is this lupine or lacepod?"),
            ("14:21", other,    "lupine, the leaves give it away"),
            ("14:23", "Alicia", "ok I'm 0 for 3 on plant IDs today"),
            ("14:25", other,    "you're better at painting them than naming them"),
            ("14:27", "Alicia", "fair"),
        ),
    ))

    plans.append(dict(
        nid="N-021", date="2026-04-07", contacts=["Priya Raman", "Sofia Delgado"],
        topic="print shop conversation after exhibition", style="follow_up",
        build=lambda other: msgs(
            ("16:42", "Alicia", "I want to take a relief printing class this summer"),
            ("16:44", other,    "the Janet Turner studio one?"),
            ("16:47", "Alicia", "yeah. saw the brochure at the show"),
            ("16:49", other,    "do it. you'd love carving blocks"),
            ("16:51", "Alicia", "adding to the budget tracker tonight"),
        ),
    ))

    plans.append(dict(
        nid="N-022", date="2026-04-11", contacts=["Sofia Delgado"],
        topic="post second wildflower walk meadowfoam pic", style="screenshot",
        build=lambda other: msgs(
            ("11:02", "Alicia", "[photo] meadowfoam is unreal at noon light"),
            ("11:05", other,    "that's a print"),
            ("11:07", "Alicia", "yeah I might actually try to translate it"),
            ("11:09", other,    "do the gouache study first"),
            ("11:11", "Alicia", "always"),
        ),
    ))

    plans.append(dict(
        nid="N-023", date="2026-04-15", contacts=["Valentina Restrepo", "Elena Gonzalez"],
        topic="Colombia itinerary cost ripple", style="follow_up",
        build=lambda other: msgs(
            ("21:18", "Alicia", "moving the Cali side trip off the itinerary"),
            ("21:21", other,    "buena decision por ahora"),
            ("21:23", "Alicia", "added two more days en Medellin con abuela en su lugar"),
            ("21:26", other,    "ella se va a poner feliz"),
            ("21:28", "Alicia", "es lo unico que importa"),
        ),
    ))

    for plan in plans:
        cand = find_candidate(plan["date"], plan["contacts"], used=used_ids)
        if cand is None:
            print(f"WARN: no candidate for {plan['nid']} {plan['date']} {plan['contacts']}")
            continue
        used_ids.add(cand["session_id"])
        contact_first = cand["contact"].split()[0]
        cand["messages"] = plan["build"](contact_first)
        new_surprises.append({
            "news_event_date": plan["date"],
            "referenced_in_session_id": cand["session_id"],
            "news_event_id": plan["nid"],
            "contact": cand["contact"],
            "topic": plan["topic"],
            "reference_style": plan["style"],
            "dynamic_role": "ripple",
        })

    cal = log["calendar"]["events"]
    tweak_made = False
    for ev in cal:
        if ev.get("source_fact_ids"):
            continue
        d = ev.get("date") or ev.get("start") or ""
        if not isinstance(d, str):
            continue
        date_only = d[:10]
        if "2026-03-23" <= date_only <= "2026-03-29":
            title = ev.get("title", "")
            if any(k in title.lower() for k in ["hike", "run", "trail", "park", "bidwell"]):
                if "Table" not in title:
                    ev["title"] = title + " (switch to Table Mountain — wildflower bloom)"
                notes = ev.get("notes", "")
                ev["notes"] = (notes + " | AQI check before run, Table Mtn route per N-012 ripple").strip(" |")
                new_surprises.append({
                    "news_event_date": "2026-03-22",
                    "referenced_in_session_id": ev.get("event_id", "E-???"),
                    "news_event_id": "N-012",
                    "contact": "calendar",
                    "topic": "Table Mountain wildflower route swap",
                    "reference_style": "logistics",
                    "dynamic_role": "ripple",
                })
                tweak_made = True
                break

    log["surprises_woven"] = log["surprises_woven"] + new_surprises

    # Token stats: keep meaningful identical (we did not mutate meaningful content),
    # recompute filler as original + ceil(delta_chars/4) using text-only serialization.
    orig_filler_text = serialize_filler(original["messenger"]["filler_sessions"])
    new_filler_text = serialize_filler(log["messenger"]["filler_sessions"])
    delta_chars = len(new_filler_text) - len(orig_filler_text)
    if delta_chars >= 0:
        delta_tokens = math.ceil(delta_chars / 4)
    else:
        delta_tokens = -math.ceil(-delta_chars / 4)
    meaningful_tokens = original["token_stats"]["meaningful_token_count"]
    filler_tokens = original["token_stats"]["filler_token_count"] + delta_tokens
    ratio = filler_tokens / meaningful_tokens if meaningful_tokens else 0
    log["token_stats"] = {
        "approximate_tokens": meaningful_tokens + filler_tokens,
        "meaningful_token_count": meaningful_tokens,
        "filler_token_count": filler_tokens,
        "ratio_filler_to_meaningful": f"{ratio:.2f}:1 (target 3:1)",
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)

    print("WROTE", OUT)
    print("ripple count:", len([s for s in log["surprises_woven"] if s["dynamic_role"] == "ripple"]))
    print("first_wave count:", len([s for s in log["surprises_woven"] if s["dynamic_role"] == "first_wave"]))
    print("token_stats:", log["token_stats"])
    print("calendar tweak:", tweak_made)


if __name__ == "__main__":
    main()
