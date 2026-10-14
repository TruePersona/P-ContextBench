# Step 4B — Dynamic Filler

Step 4B creates controlled app-log variants by regenerating only
`messenger.filler_sessions[*].messages[*].text`.

It is intended for A/B testing filler quality without changing the benchmark's
fact-bearing evidence.

For `surprise` runs, `generator.py` owns the news-event flow. It derives
persona-relevant search strategy from Step 2 profile context and Step 3
social-circle topics, fetches sourced events from the app-log window, writes
them to `data_samples/input/{persona}_news_events.json`, then weaves short
references into filler.

By default, this strategy comes from a GPT-generated news brief cached at
`data_samples/input/{persona}_news_brief.json`. The brief contains GDELT
queries and relevance guidance only; GPT does not invent news events. GDELT
still supplies the real sourced events. If no brief is available or it is
invalid, the generator falls back to generic anchors from location, occupation,
preference text, and social-circle recent topics. It does not hardcode
persona-specific searches. GDELT responses are cached under
`data_samples/input/.gdelt_cache/` to reduce repeat API calls.

## Invariants

The generator preserves these fields exactly:

- `messenger.meaningful_sessions`
- `calendar.events`
- `hidden_facts`
- `cross_app_index`
- `persona_name`
- `log_window`
- every filler `session_id`, `date`, `contact`, message `time`, and `sender`

Only these app-log fields change:

- filler message `text`
- `token_stats.filler_token_count`
- `token_stats.approximate_tokens`
- `token_stats.ratio_filler_to_meaningful`
- `surprises_woven`

## Variants

- `baseline` — GPT/Codex-regenerated mundane filler with no news or surprises.
- `surprise` — GPT/Codex-regenerated filler with short references to supplied
  or auto-discovered news/dynamic events.

By default, `surprise` targets 50% of filler sessions as news-oriented
sessions. Each selected filler session gets one shallow event reference while
preserving the original session structure. Override with `--surprise-rate`,
for example `--surprise-rate 0.25` or `--surprise-rate 0.75`.

The generator targets 20 sourced events and requires at least 12 by default.
If GDELT returns too few usable events, the run fails before expensive filler
generation. This prevents thousands of filler messages from repeating the same
small handful of stories.

Terminology:

- `news_events` are the input events.
- `surprises_woven` are the actual filler-session references to those events.
- `dynamic filler` is the experiment name.

## Commands

Baseline:

```powershell
python step4b_dynamic_filler/generator.py `
  --persona alicia_gonzalez `
  --variant baseline `
  --backend codex `
  --model gpt-5.5 `
  --output step4b_dynamic_filler/data_samples/output
```

Surprise:

```powershell
python step4b_dynamic_filler/generator.py `
  --persona alicia_gonzalez `
  --variant surprise `
  --backend codex `
  --model gpt-5.5 `
  --output step4b_dynamic_filler/data_samples/output
```

The surprise command auto-creates:

```text
step4b_dynamic_filler/data_samples/input/alicia_gonzalez_news_brief.json
step4b_dynamic_filler/data_samples/input/alicia_gonzalez_news_events.json
```

To refresh the sourced events:

```powershell
python step4b_dynamic_filler/generator.py `
  --persona alicia_gonzalez `
  --variant surprise `
  --refresh-news-brief `
  --refresh-news-events `
  --generate-news-only
```

GDELT knobs:

```powershell
python step4b_dynamic_filler/generator.py `
  --persona alicia_gonzalez `
  --variant surprise `
  --refresh-news-events `
  --generate-news-only `
  --gdelt-max-queries 12 `
  --gdelt-max-records 6 `
  --gdelt-delay-seconds 1.5
```

Dry run:

```powershell
python step4b_dynamic_filler/generator.py `
  --persona alicia_gonzalez `
  --variant baseline `
  --dry-run
```

## Reusing For Other Personas

Swap only `--persona`. The generator resolves:

- app logs from `step4b_dynamic_filler/data_samples/input/{persona}_app_logs.json`
  or `step4_app_log_synthesizer/data_samples/output/{persona}*_app_logs.json`
- profile from `step2_interview/data_samples/output/{persona}_verification.json`
- social circle from
  `step3_social_circle/data_samples/output/{persona}_social_circle_verification.json`
- news events from `step4b_dynamic_filler/data_samples/input/{persona}_news_events.json`

You can still pass `--app-logs`, `--profile`, `--social-circle`, or
`--news-events` explicitly for nonstandard paths.
