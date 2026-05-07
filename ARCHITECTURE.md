# Architecture

There are six steps, one per `step{N}_*/` directory. Each step's prompt
template is in `step{N}/prompt.txt`.

## How a step runs

A bash script opens a fresh `claude -p --tools "" --model <version>` shell
for each LLM call. With `--tools ""` the model can only emit text (no file,
shell, or network access). The script fills the prompt from
`step{N}/prompt.txt`, pipes it on stdin, and writes the response to
`step{N}/data_samples/output/`.

## Step ordering

`bash run_pipeline.sh <persona>` walks the six steps in order. Step n only
starts after step n-1 exits successfully. `bash run_step.sh <step> <persona>`
runs one step against the prior step's output.

## Models

Set model versions in `run_pipeline.sh`. Use exact version strings
(`claude-opus-4-7`), not aliases (`opus`). Aliases are rejected at parse
time.

## Reproducing a model's score

The dataset committed to `main` is the canonical artifact. To check a model
against it, run step 6 only:

```
bash run_step.sh 6 <persona>
```

Output lands in `step6_benchmark_runner/data_samples/output/`. Run three
times for a variance estimate.
